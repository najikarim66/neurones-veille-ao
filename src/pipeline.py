"""
Orchestrator principal de la veille AO.

Workflow :
  1. Charge config.json
  2. Scrape marchespublics.gov.ma avec la chaine de mots-cles
  3. Calcule scores
  4. Filtre par seuil
  5. Push Cosmos DB avec dedup intelligente (cf. cosmos_client)
  6. Envoie email Resend (nouveautes + rappels VERTS actifs)

Usage :
  python -m src.pipeline                  (mode normal, lit config.json a la racine)
  python -m src.pipeline --no-cosmos      (skip Cosmos, utile en dev local)
  python -m src.pipeline --no-email       (skip email, utile en dev local)
  python -m src.pipeline --dry-run        (skip Cosmos ET email, juste log)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Imports relatifs au package src/
from src.search import scraper_aos, log
from src.score import calculer_score, filtrer_par_seuil
from src.cosmos_client import CosmosVeilleClient
from src.send_email import envoyer_email


def charger_config(path: str = "config.json") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config.json introuvable a {p.resolve()}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Pipeline veille AO")
    parser.add_argument("--config", default="config.json", help="Chemin vers config.json")
    parser.add_argument("--no-cosmos", action="store_true", help="Ne pas pusher vers Cosmos")
    parser.add_argument("--no-email", action="store_true", help="Ne pas envoyer d'email")
    parser.add_argument("--dry-run", action="store_true", help="Skip Cosmos ET email")
    args = parser.parse_args()

    if args.dry_run:
        args.no_cosmos = True
        args.no_email = True

    log("MAIN", "=== Pipeline veille AO ===")
    log("MAIN", f"Config : {args.config}")
    cfg = charger_config(args.config)

    keywords = cfg["search"]["keywords"]
    log("MAIN", f"Mots-cles : {keywords}")

    # ========== PHASE 1 : SCRAPE ==========
    log("PHASE", ">>> Phase 1/4 : Scrape")
    aos = scraper_aos(
        keyword=keywords,
        page_size=cfg["search"]["page_size"],
        playwright_cfg=cfg["playwright"],
    )
    log("PHASE", f"<<< {len(aos)} AO scrapes")

    if not aos:
        log("MAIN", "Aucun AO scrape, arret du pipeline")
        sys.exit(0)

    # ========== PHASE 2 : SCORING ==========
    log("PHASE", ">>> Phase 2/4 : Scoring")
    scoring_cfg = cfg["scoring"]
    for ao in aos:
        ao.update(calculer_score(ao, scoring_cfg))
    aos.sort(key=lambda r: r["score"], reverse=True)

    seuil = scoring_cfg["seuil_inclusion"]
    aos_retenus = filtrer_par_seuil(aos, seuil)
    nb_filtres = len(aos) - len(aos_retenus)
    nb_verts = sum(1 for a in aos_retenus if a["score"] >= 60)
    nb_jaunes = sum(1 for a in aos_retenus if seuil <= a["score"] < 60)
    log("PHASE", f"<<< Retenus : {len(aos_retenus)}/{len(aos)} (filtres : {nb_filtres})")
    log("PHASE", f"    VERT (>=60) : {nb_verts} | JAUNE ({seuil}-59) : {nb_jaunes}")

    # ========== PHASE 3 : COSMOS ==========
    nouveautes = []
    if args.no_cosmos:
        log("PHASE", ">>> Phase 3/4 : Cosmos SKIP (no-cosmos)")
        # En mode local sans Cosmos, on considere TOUT comme nouveaute pour test email
        nouveautes = aos_retenus
        rappels = []
    else:
        log("PHASE", ">>> Phase 3/4 : Push Cosmos avec dedup")
        cosmos = CosmosVeilleClient(
            endpoint=cfg["cosmos"]["endpoint"],
            database=cfg["cosmos"]["database"],
            container=cfg["cosmos"]["container"],
            source_id=cfg["cosmos"]["source_id"],
        )
        nb_created = 0
        nb_updated = 0
        for ao in aos_retenus:
            try:
                res = cosmos.upsert_ao(ao)
                if res["action"] == "created":
                    nb_created += 1
                    nouveautes.append(res["doc"])
                else:
                    nb_updated += 1
            except Exception as e:
                log("COSMOS", f"  ERROR upsert ref={ao.get('ref_consultation')}: {e}")
        log("PHASE", f"<<< Cosmos : {nb_created} crees | {nb_updated} mis a jour")

        # Recuperer les VERTS actifs pour rappel
        rappel_cfg = cfg["email"]["rappel_verts_actifs"]
        if rappel_cfg.get("actif", True):
            rappels_all = cosmos.list_verts_actifs(
                score_min=rappel_cfg["score_min"],
                deadline_jours_max=rappel_cfg["deadline_jours_max"],
            )
            # Exclure ceux qui sont deja dans "nouveautes" (eviter doublon visuel)
            ids_nouveaux = {n["id"] for n in nouveautes}
            rappels = [r for r in rappels_all if r["id"] not in ids_nouveaux]
            log("PHASE", f"    Rappels VERTS actifs (hors nouveautes) : {len(rappels)}")
        else:
            rappels = []

    # ========== PHASE 4 : EMAIL ==========
    if args.no_email:
        log("PHASE", ">>> Phase 4/4 : Email SKIP (no-email)")
    else:
        log("PHASE", ">>> Phase 4/4 : Envoi email Resend")
        run_id = datetime.now().strftime("%Y%m%d_%H%M")
        result = envoyer_email(
            config_email=cfg["email"],
            nouveautes=nouveautes,
            rappels=rappels,
            run_id=run_id,
        )
        if result["sent"]:
            log("PHASE", f"<<< Email envoye : id={result['message_id']}")
        else:
            log("PHASE", f"<<< Email NON envoye : {result['reason']}")

    # ========== BILAN ==========
    print()
    print("=" * 60)
    print("BILAN PIPELINE")
    print("=" * 60)
    print(f"  AO scrapes     : {len(aos)}")
    print(f"  AO retenus     : {len(aos_retenus)}")
    print(f"  VERTS (>=60)   : {nb_verts}")
    print(f"  Nouveautes     : {len(nouveautes)}")
    if not args.no_cosmos:
        print(f"  Rappels actifs : {len(rappels)}")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
