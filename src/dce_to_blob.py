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
from src.send_email import envoyer_graph_simple

# Destinataires par defaut si la config Cosmos (veille_config) est absente/vide
DCE_EMAIL_FALLBACK = ["imane@neurones.ma"]


def _read_dce_recipients(cosmos_endpoint, cosmos_db, cosmos_container, source):
    """Lit le doc veille_config -> (to, cc). Filtre les vides ; fallback si 'to' vide.
    Editable depuis MP Manager (page Veille AO)."""
    key = os.environ.get("COSMOS_KEY")
    to, cc = [], []
    if key:
        try:
            client = CosmosClient(cosmos_endpoint, credential=key)
            container = client.get_database_client(cosmos_db).get_container_client(cosmos_container)
            cfg = container.read_item(item="veille_config", partition_key=source)
            to = [str(e).strip() for e in (cfg.get("dce_email_to") or []) if str(e).strip()]
            cc = [str(e).strip() for e in (cfg.get("dce_email_cc") or []) if str(e).strip()]
        except Exception as e:
            log("EMAIL", f"  config destinataires illisible ({e}) - fallback")
    if not to:
        to = list(DCE_EMAIL_FALLBACK)
    return to, cc


def _fmt_mad(n):
    """Montant -> 'xxx xxx,xx MAD' (format FR) ; None -> 'non precise'."""
    if n is None:
        return "non precise"
    try:
        s = "{:,.2f}".format(float(n))
    except (ValueError, TypeError):
        return "non precise"
    return s.replace(",", " ").replace(".", ",") + " MAD"


def _build_email_html(doc, sas_url):
    """Corps HTML de l'email secretaire (recap + bouton telechargement SAS)."""
    from html import escape

    def row(k, v):
        return ('<tr><td style="padding:6px 10px;border:1px solid #ddd;background:#f5f5f5;'
                'font-weight:bold">' + k + '</td>'
                '<td style="padding:6px 10px;border:1px solid #ddd">' + v + '</td></tr>')

    ref = escape(str(doc.get("reference_ao") or doc.get("ref_consultation") or "-"))
    objet = escape(str(doc.get("objet") or "-"))
    moa = escape(str(doc.get("acheteur") or "-"))
    dl = escape(str(doc.get("date_limite") or "-"))
    est = _fmt_mad(doc.get("estimation_mo"))
    cau = _fmt_mad(doc.get("caution_provisoire"))
    href = escape(sas_url or "#")
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;color:#222">'
        '<h2 style="color:#1F4E78">Nouvel appel d\'offres a preparer</h2>'
        '<table style="border-collapse:collapse;width:100%;font-size:14px">'
        + row("Reference", ref) + row("Objet", objet) + row("Maitre d'ouvrage", moa)
        + row("Estimation (MO)", est) + row("Caution provisoire", cau) + row("Date limite", dl)
        + '</table>'
        '<p style="margin:20px 0">'
        '<a href="' + href + '" style="background:#107C41;color:#fff;padding:10px 18px;'
        'text-decoration:none;border-radius:4px;font-weight:bold">Telecharger le dossier (DCE)</a>'
        '</p>'
        '<p style="color:#777;font-size:12px">Lien de telechargement valable 35 jours. '
        'Email automatique - Veille AO Neurones.</p>'
        '</div>'
    )


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
            dce = telecharger_dce(args.ref, args.org, local_config)
            zip_path = dce["zip_path"]
            log("STEP1", f"DCE telecharge : {zip_path} ({zip_path.stat().st_size:,} bytes)")
            log("STEP1", f"  estimation={dce['estimation_mo']} caution={dce['caution_provisoire']}")

            # ----- 2. Upload Blob -----
            account = os.environ["AZURE_STORAGE_ACCOUNT"]
            account_key = os.environ["AZURE_STORAGE_KEY"]
            container_name = os.environ["AZURE_STORAGE_CONTAINER"]

            blob_name, public_url, size = upload_blob_with_sas(
                zip_path, args.ref, args.org,
                account, account_key, container_name
            )

        # ----- 3. Update Cosmos avec succes (+ enrichissement estimation/caution) -----
        doc = update_cosmos_doc(
            cosmos_cfg["endpoint"], cosmos_cfg["database"], cosmos_cfg["container"],
            args.doc_id, source_id,
            {
                "dce_status": "ready",
                "dce_url": public_url,
                "dce_blob_name": blob_name,
                "dce_size_bytes": size,
                "dce_uploaded_at": utcnow_iso(),
                "dce_error": None,
                "estimation_mo": dce["estimation_mo"],
                "caution_provisoire": dce["caution_provisoire"],
            }
        )
        log("STEP3", "Cosmos mis a jour : ready")

        # ----- 4. Email secretaire (BEST-EFFORT ; une seule fois ; jamais si failed) -----
        try:
            if doc is not None and not doc.get("dce_email_sent"):
                ref_aff = doc.get("reference_ao") or doc.get("ref_consultation") or args.ref
                moa = doc.get("acheteur") or "-"
                subject = f"Nouvel AO a preparer : {ref_aff} - {moa}"
                html = _build_email_html(doc, public_url)
                to, cc = _read_dce_recipients(
                    cosmos_cfg["endpoint"], cosmos_cfg["database"], cosmos_cfg["container"], source_id
                )
                res_mail = envoyer_graph_simple(to, subject, html, cc_addresses=cc)
                if res_mail.get("sent"):
                    update_cosmos_doc(
                        cosmos_cfg["endpoint"], cosmos_cfg["database"], cosmos_cfg["container"],
                        args.doc_id, source_id,
                        {"dce_email_sent": True, "dce_email_at": utcnow_iso()}
                    )
                    log("EMAIL", f"Email envoye a {', '.join(to)}" + (f" (cc {', '.join(cc)})" if cc else ""))
                else:
                    log("EMAIL", f"WARN email non envoye : {res_mail.get('reason')}")
            else:
                log("EMAIL", "Email deja envoye (dce_email_sent) - skip")
        except Exception as e:
            log("EMAIL", f"WARN email echoue (best-effort) : {e}")

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
