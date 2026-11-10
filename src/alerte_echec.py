"""
Alerte « le passage a echoue » — lancee par l'etape `if: failure()` du workflow Veille AO
(decision DG 10/11/2026 : la panne du portail du 02 au 10/11 a laisse 16 passages rouges sans
qu'un mail ne parte). Lit la cause nommee par le pipeline (veille-echec.txt) et le lien du
passage, puis mail au DG (destinataires de config.json > email.to_addresses) via l'app Graph
deja en place. Ne leve jamais : une alerte qui plante ne doit pas masquer l'echec d'origine.

Usage : python -m src.alerte_echec [--run-url <url>] [--config config.json]
"""
import argparse
import json
import sys
from pathlib import Path

from src.alerte_veille import corps_echec, lire_cause
from src.send_email import envoyer_graph_simple


def destinataires(config_path: str) -> list:
    try:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        to = cfg.get("email", {}).get("to_addresses") or []
        return [str(a) for a in to if str(a).strip()]
    except (OSError, ValueError):
        return []


def construire(cause: str, run_url: str) -> tuple:
    sujet = "[Veille AO] ECHEC du passage — " + (cause.splitlines()[0][:90] if cause else "cause non nommee")
    return sujet, corps_echec(cause, run_url)


def main(argv=None, envoyer=envoyer_graph_simple):
    p = argparse.ArgumentParser()
    p.add_argument("--run-url", default="")
    p.add_argument("--config", default="config.json")
    a = p.parse_args(argv)
    to = destinataires(a.config)
    if not to:
        print("[ALERTE] aucun destinataire (config.json > email.to_addresses) : mail non envoye")
        return 0
    sujet, html = construire(lire_cause(), a.run_url)
    r = envoyer(to, sujet, html)
    print(f"[ALERTE] mail « {sujet} » -> {', '.join(to)} : {'envoye' if r.get('sent') else 'NON envoye (' + str(r.get('reason')) + ')'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
