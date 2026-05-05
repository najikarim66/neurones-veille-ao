"""
DL DCE + upload Azure Blob + update Cosmos.

Lance par le workflow .github/workflows/download-dce.yml avec inputs :
  --ref <ref_consultation>
  --org <org_acronyme>
  --doc-id <cosmos_doc_id>

Etapes :
  1. Marque le doc Cosmos en dce_status='downloading'
  2. Lance le DL DCE via Playwright (re-utilise dce_download.telecharger_dce)
  3. Upload le ZIP vers Azure Blob avec nommage <ref>_<org>_<ts>.zip
  4. Genere une URL SAS valide 35 jours
  5. Update doc Cosmos : dce_url, dce_uploaded_at, dce_size_bytes, dce_status='ready'
  6. En cas d'erreur : dce_status='failed' avec dce_error
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
from azure.cosmos import CosmosClient, exceptions as cosmos_exc

from src.dce_download import telecharger_dce


def log(step, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{step}] {msg}", flush=True)


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_cosmos_doc(cosmos_endpoint, cosmos_db, cosmos_container, doc_id, source, updates):
    """Update partiel du doc Cosmos en preservant le reste."""
    key = os.environ.get("COSMOS_KEY")
    if not key:
        raise RuntimeError("COSMOS_KEY non defini")

    client = CosmosClient(cosmos_endpoint, credential=key)
    db = client.get_database_client(cosmos_db)
    container = db.get_container_client(cosmos_container)

    try:
        doc = container.read_item(item=doc_id, partition_key=source)
    except cosmos_exc.CosmosResourceNotFoundError:
        log("COSMOS", f"  Doc {doc_id} introuvable, abort")
        return None

    for k, v in updates.items():
        doc[k] = v
    doc["date_derniere_mise_a_jour"] = utcnow_iso()

    container.replace_item(item=doc_id, body=doc)
    return doc


def upload_blob_with_sas(local_zip_path, ref, org, account, account_key, container_name):
    """Upload le ZIP et retourne (blob_name, public_url_with_sas, size)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    blob_name = f"{ref}_{org}_{timestamp}.zip"

    blob_url = f"https://{account}.blob.core.windows.net"
    blob_service = BlobServiceClient(account_url=blob_url, credential=account_key)
    blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)

    log("BLOB", f"Upload {local_zip_path.name} -> {blob_name}")
    with local_zip_path.open("rb") as f:
        blob_client.upload_blob(f, overwrite=True, content_settings=None)

    size = local_zip_path.stat().st_size
    log("BLOB", f"  Upload OK ({size:,} bytes)")

    # SAS valide 35 jours (>= retention lifecycle 30j + marge)
    sas = generate_blob_sas(
        account_name=account,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(days=35),
        content_disposition=f'attachment; filename="DCE_{ref}_{org}.zip"',
    )

    public_url = f"{blob_url}/{container_name}/{blob_name}?{sas}"
    return blob_name, public_url, size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    parser.add_argument("--org", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    log("MAIN", f"=== DCE on demand : ref={args.ref} org={args.org} ===")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    cosmos_cfg = config["cosmos"]
    source_id = cosmos_cfg["source_id"]

    # ----- 0. Marque downloading -----
    try:
        update_cosmos_doc(
            cosmos_cfg["endpoint"], cosmos_cfg["database"], cosmos_cfg["container"],
            args.doc_id, source_id,
            {"dce_status": "downloading", "dce_started_at": utcnow_iso(), "dce_error": None}
        )
        log("STEP0", "Doc Cosmos marque downloading")
    except Exception as e:
        log("STEP0", f"WARN: update downloading echec : {e}")
        # On continue quand meme

    try:
        # ----- 1. DL DCE (override config pour utiliser tmpdir local du runner) -----
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Override pour le runner (pas de chemins Windows)
            local_config = json.loads(Path(args.config).read_text(encoding="utf-8"))
            local_config["stockage_local"] = {
                "racine_dce": str(tmpdir_path / "dce"),
                "racine_logs": str(tmpdir_path / "logs"),
                "racine_rapports": str(tmpdir_path / "rapports"),
            }
            # Force headless true sur le runner
            local_config["playwright"]["headless"] = True

            log("STEP1", "Lancement DL DCE Playwright")
            zip_path = telecharger_dce(args.ref, args.org, local_config)
            log("STEP1", f"DCE telecharge : {zip_path} ({zip_path.stat().st_size:,} bytes)")

            # ----- 2. Upload Blob -----
            account = os.environ["AZURE_STORAGE_ACCOUNT"]
            account_key = os.environ["AZURE_STORAGE_KEY"]
            container_name = os.environ["AZURE_STORAGE_CONTAINER"]

            blob_name, public_url, size = upload_blob_with_sas(
                zip_path, args.ref, args.org,
                account, account_key, container_name
            )

        # ----- 3. Update Cosmos avec succes -----
        update_cosmos_doc(
            cosmos_cfg["endpoint"], cosmos_cfg["database"], cosmos_cfg["container"],
            args.doc_id, source_id,
            {
                "dce_status": "ready",
                "dce_url": public_url,
                "dce_blob_name": blob_name,
                "dce_size_bytes": size,
                "dce_uploaded_at": utcnow_iso(),
                "dce_error": None,
            }
        )
        log("STEP3", "Cosmos mis a jour : ready")
        log("MAIN", "SUCCESS")
        sys.exit(0)

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        log("MAIN", f"FAILURE : {err_msg}")
        try:
            update_cosmos_doc(
                cosmos_cfg["endpoint"], cosmos_cfg["database"], cosmos_cfg["container"],
                args.doc_id, source_id,
                {"dce_status": "failed", "dce_error": err_msg[:500]}
            )
        except Exception as e2:
            log("MAIN", f"Echec update statut failed : {e2}")
        sys.exit(2)


if __name__ == "__main__":
    main()
