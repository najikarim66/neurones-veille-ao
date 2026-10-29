"""
Suppression automatique des AO de veille echus (decision Karim, 29/10/2026 :
« des que la date limite est depassee on supprime »).

Regle (celle validee pour le nettoyage du 29/10, 324 fiches) : un AO est supprime quand
l'instant limite de remise (date_limite + heure_limite, heure de Casablanca ; sans heure,
fin de journee) est passe ET qu'il n'a jamais ete traite :
  - statut « a_etudier » (ou absent) ou « no_go » ;
  - aucun DCE telecharge (dce_status ready ou dce_url) ;
  - aucune fiche AO de MP liee (ao_id_lie).
Tout le reste est GARDE avec son motif nomme (go, en analyse, soumissionne, gagne, DCE,
fiche AO, date non lue). Aucune archive de ce qui est supprime (decision Karim,
29/10/2026) : le journal du run n'en garde que les comptes.

Lancer seul : python -m src.purge --dry-run   (lecture seule, liste ce qui partirait)
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CASABLANCA = ZoneInfo("Africa/Casablanca")
STATUTS_NON_TRAITES = ("a_etudier", "no_go")


def log(step, msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{step}] {msg}", flush=True)


def instant_limite(doc):
    """Instant limite de remise en UTC, ou None si la date n'est pas lisible."""
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})", doc.get("date_limite") or "")
    if not m:
        return None
    j, mo, a = (int(x) for x in m.groups())
    h = re.match(r"^\s*(\d{1,2}):(\d{2})", doc.get("heure_limite") or "")
    hh, mm = (int(h.group(1)), int(h.group(2))) if h else (23, 59)
    try:
        return datetime(a, mo, j, hh, mm, tzinfo=CASABLANCA).astimezone(timezone.utc)
    except ValueError:
        return None


def motif_garde(doc, maintenant):
    """None = a supprimer ; sinon le motif nomme pour lequel le doc est garde."""
    limite = instant_limite(doc)
    if limite is None:
        return "date limite non lue"
    if limite > maintenant:
        return "encore ouvert"
    statut = doc.get("statut") or "a_etudier"
    if statut not in STATUTS_NON_TRAITES:
        return f"statut {statut}"
    if doc.get("dce_status") == "ready" or doc.get("dce_url"):
        return "DCE telecharge"
    if doc.get("ao_id_lie"):
        return "fiche AO liee"
    return None


def selectionner(docs, maintenant):
    """-> (a_supprimer, gardes_par_motif). Le doc de config n'est jamais vu comme un AO."""
    a_supprimer, gardes = [], {}
    for d in docs:
        if d.get("type") == "config" or d.get("id") == "veille_config":
            continue
        motif = motif_garde(d, maintenant)
        if motif is None:
            a_supprimer.append(d)
        else:
            gardes[motif] = gardes.get(motif, 0) + 1
    return a_supprimer, gardes


def purger(container, source_id, maintenant=None, appliquer=True):
    maintenant = maintenant or datetime.now(timezone.utc)
    docs = list(container.query_items(
        query="SELECT * FROM c WHERE c.source = @src",
        parameters=[{"name": "@src", "value": source_id}],
        partition_key=source_id,
    ))
    sel, gardes = selectionner(docs, maintenant)
    vus = len(docs) - sum(1 for d in docs if d.get("type") == "config" or d.get("id") == "veille_config")
    detail = ", ".join(f"{n} {m}" for m, n in sorted(gardes.items())) or "aucun"
    log("PURGE", f"{vus} vus · {len(sel)} echus non traites a supprimer · {vus - len(sel)} gardes ({detail})")
    if not sel or not appliquer:
        for d in sel:
            log("PURGE", f"  {'a supprimer' if not appliquer else ''} {d.get('reference_ao') or d.get('ref_consultation')} "
                         f"(limite {d.get('date_limite')} {d.get('heure_limite') or ''}, {d.get('statut') or 'a_etudier'})")
        return {"vus": vus, "supprimes": 0, "a_supprimer": len(sel), "gardes": gardes}

    supprimes, echecs = 0, []
    for d in sel:
        try:
            container.delete_item(item=d["id"], partition_key=source_id)
            supprimes += 1
        except Exception as e:
            echecs.append(f"{d.get('reference_ao') or d.get('ref_consultation')} ({type(e).__name__})")
    log("PURGE", f"<<< {supprimes} supprimes · {len(echecs)} echec(s)" + (f" : {', '.join(echecs)}" if echecs else ""))
    return {"vus": vus, "supprimes": supprimes, "echecs": echecs, "gardes": gardes}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    from src.cosmos_client import CosmosVeilleClient
    c = CosmosVeilleClient(endpoint=cfg["cosmos"]["endpoint"], database=cfg["cosmos"]["database"],
                           container=cfg["cosmos"]["container"], source_id=cfg["cosmos"]["source_id"])
    purger(c.container, cfg["cosmos"]["source_id"], appliquer=not args.dry_run)


if __name__ == "__main__":
    main()
