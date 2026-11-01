"""
Alerte « documents de la societe » (coffre de MP, conteneur mp_coffre_docs) : un document dont
la validite expire dans les 15 jours, ou deja expire, declenche un e-mail (lot « Etude d'AO »,
01/11/2026). Meme regle que MP (public/etude-calc.js, alertesCoffre) : version COURANTE = la
derniere deposee ; sans date de validite, pas d'alerte. La rubrique « a traiter » de MP montre
la meme liste a l'ecran.

Un e-mail par document et par version, une seule fois : le journal vit dans mp_config
(document « coffre_alerte_journal »). Destinataires : mp_config « coffre_alerte »
(champ destinataires), sinon Karim seul. Aucun fichier du coffre n'est lu ni joint : seulement
le type, le libelle et la date de validite.

Lancer seul : python -m src.coffre_alerte --dry-run   (lecture seule : liste ce qui partirait)
"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JOURS = 15
DESTINATAIRES_DEFAUT = ["naji@neurones.ma"]
LIBELLES = {
    "attestation_fiscale": "Attestation fiscale", "cnss": "Attestation CNSS", "registre_commerce": "Registre de commerce (modele 7)",
    "statuts": "Statuts", "pouvoirs": "Pouvoirs du signataire", "qualification": "Qualification et classification",
    "certificat": "Certificat", "attestation_reference": "Attestation de bonne execution", "rib": "RIB", "autre": "Autre document",
}


def log(step, msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)


def version_courante(doc):
    v = (doc or {}).get("versions") or []
    return v[-1] if v else None


def alertes(docs, aujourdhui, jours=JOURS):
    """[{id, cle, libelle, validite, expire}] des documents qui expirent sous `jours` jours ou sont expires."""
    limite = aujourdhui + timedelta(days=jours)
    out = []
    for d in docs or []:
        v = version_courante(d)
        if not v or d.get("archive") or not v.get("date_validite"):
            continue
        try:
            val = date.fromisoformat(str(v["date_validite"])[:10])
        except ValueError:
            continue
        if val > limite:
            continue
        out.append({"id": d["id"], "cle": f"{d['id']}:v{v.get('v')}", "validite": val, "expire": val < aujourdhui,
                    "libelle": d.get("libelle") or LIBELLES.get(d.get("type"), "Document")})
    out.sort(key=lambda a: a["validite"])
    return out


def a_envoyer(liste, journal):
    """Ceux qui n'ont pas encore eu leur e-mail pour cette version."""
    deja = (journal or {}).get("envoyes") or {}
    return [a for a in liste if a["cle"] not in deja]


def corps_html(liste):
    from html import escape
    lignes = "".join(
        f"<tr><td style='padding:6px 10px;border:1px solid #ddd'>{escape(a['libelle'])}</td>"
        f"<td style='padding:6px 10px;border:1px solid #ddd;color:{'#b3261e' if a['expire'] else '#9a5b00'}'>"
        f"{'Expiré le' if a['expire'] else 'Expire le'} {a['validite'].strftime('%d/%m/%Y')}</td></tr>"
        for a in liste)
    return ("<div style='font-family:Arial,Helvetica,sans-serif;max-width:640px;color:#222'>"
            "<h2 style='color:#1F4E78'>Documents de la societe a renouveler</h2>"
            f"<p>{len(liste)} document(s) expire(nt) dans les {JOURS} jours ou sont deja expires. "
            "Deposer la nouvelle version dans MP Manager, page « Documents de la societe ».</p>"
            f"<table style='border-collapse:collapse;font-size:14px'>{lignes}</table>"
            "<p style='color:#777;font-size:12px'>E-mail automatique (une fois par version de document).</p></div>")


def verifier(db, envoyer, aujourdhui=None, appliquer=True):
    """db = client base Cosmos (get_container_client). envoyer(to, sujet, html) -> {'sent': bool}."""
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    try:
        docs = list(db.get_container_client("mp_coffre_docs").query_items("SELECT * FROM c", enable_cross_partition_query=True))
    except Exception as e:
        log("COFFRE", f"  coffre illisible ({type(e).__name__}) : alerte non verifiee")
        return {"lus": 0, "alertes": 0, "envoyes": 0}
    cfg = db.get_container_client("mp_config")
    def lire(doc_id):
        try:
            return cfg.read_item(item=doc_id, partition_key=doc_id)
        except Exception:
            return None
    journal = lire("coffre_alerte_journal") or {"id": "coffre_alerte_journal", "envoyes": {}}
    dest = [x for x in ((lire("coffre_alerte") or {}).get("destinataires") or []) if str(x).strip()] or list(DESTINATAIRES_DEFAUT)
    toutes = alertes(docs, aujourdhui)
    nouvelles = a_envoyer(toutes, journal)
    log("COFFRE", f"  {len(docs)} document(s) lus · {len(toutes)} a renouveler sous {JOURS} jours · {len(nouvelles)} sans e-mail encore")
    if not nouvelles or not appliquer:
        return {"lus": len(docs), "alertes": len(toutes), "envoyes": 0}
    r = envoyer(dest, f"MP : {len(nouvelles)} document(s) de la societe a renouveler", corps_html(nouvelles))
    if not r.get("sent"):
        log("COFFRE", f"  e-mail NON envoye : {r.get('reason')}")
        return {"lus": len(docs), "alertes": len(toutes), "envoyes": 0}
    for a in nouvelles:
        journal.setdefault("envoyes", {})[a["cle"]] = aujourdhui.isoformat()
    cfg.upsert_item(journal)
    log("COFFRE", f"  e-mail envoye a {len(dest)} destinataire(s) pour {len(nouvelles)} document(s)")
    return {"lus": len(docs), "alertes": len(toutes), "envoyes": len(nouvelles)}


def main():
    import os
    from azure.cosmos import CosmosClient
    from src.send_email import envoyer_graph_simple
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))
    db = CosmosClient(cfg["cosmos"]["endpoint"], credential=os.environ["COSMOS_KEY"]).get_database_client(cfg["cosmos"]["database"])
    verifier(db, lambda to, s, h: envoyer_graph_simple(to, s, h), appliquer=not a.dry_run)


if __name__ == "__main__":
    main()
