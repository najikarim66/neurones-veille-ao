"""
Garde des passages de la veille AO — tourne DANS LE CLOUD (runner GitHub, planifie), donc aussi quand le PC
qui porte la tache planifiee et le runner est eteint (decision DG 12/11/2026 : alerter le DG si un passage
PREVU n'a pas eu lieu, pas seulement s'il a echoue).

Chaine surveillee : tache planifiee Windows (lun-ven 08:00 et 14:00 UTC) -> trigger-veille.ps1
-> `gh workflow run veille-ao.yml` -> runner self-hosted (meme PC) -> Cosmos -> ecran MP.

Pour le creneau le plus recent dont l'echeance (creneau + tolerance) est passee, verdict :
  ok                : un passage a ete cree depuis le creneau et a demarre (ou est termine) ;
  en_attente_runner : un passage existe mais reste « queued » depuis plus de ATTENTE_RUNNER_MIN
                      (le declenchement a eu lieu, le runner du PC ne repond pas) ;
  non_lance         : aucun passage cree depuis le creneau (PC eteint, en veille, ou tache non declenchee).
Un echec de passage (run rouge) n'est pas du ressort de cette garde : l'etape « Alerte DG — le passage a
echoue » du workflow Veille AO le couvre deja.

Le rattrapage n'est PAS lance d'ici : la tache Windows (StartWhenAvailable + WakeToRun) rejoue le
declenchement manque au demarrage ou au reveil suivant du PC ; un second dispatch depuis le cloud ferait
un passage en double. Si le PC reste eteint, le DG lance « Relancer » dans l'ecran Veille AO de MP.

Usage : python -m src.garde_passage [--maintenant ISO-UTC] [--creneaux 08:00,14:00] [--tolerance-min 90]
                                    [--attente-runner-min 30] [--sans-mail] [--config config.json]
Env : GITHUB_REPOSITORY, GITHUB_TOKEN (lecture des runs) ; GRAPH_* (mail, voir send_email).
Ne leve jamais vers le workflow : une garde qui plante ne doit pas se confondre avec un passage manque.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape

from src.alerte_echec import destinataires
from src.send_email import envoyer_graph_simple

UTC = timezone.utc
CRENEAUX_DEFAUT = "08:00,14:00"
TOLERANCE_MIN = 90
ATTENTE_RUNNER_MIN = 30
WORKFLOW = "veille-ao.yml"


def lire_iso_utc(texte: str) -> datetime:
    d = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def analyser_creneaux(texte: str) -> list:
    """« 08:00,14:00 » -> [(8, 0), (14, 0)], tries."""
    out = []
    for part in str(texte).split(","):
        part = part.strip()
        if not part:
            continue
        h, m = part.split(":")
        out.append((int(h), int(m)))
    return sorted(out)


def creneaux_du_jour(maintenant: datetime, creneaux: list) -> list:
    """Les creneaux UTC du jour de `maintenant` ; aucun le samedi et le dimanche."""
    if maintenant.weekday() >= 5:
        return []
    return [maintenant.replace(hour=h, minute=m, second=0, microsecond=0) for (h, m) in creneaux]


def creneau_a_verifier(maintenant: datetime, creneaux: list, tolerance_min: int = TOLERANCE_MIN):
    """Le creneau le plus recent du jour dont l'echeance (creneau + tolerance) est passee ; None sinon."""
    echus = [c for c in creneaux_du_jour(maintenant, creneaux) if c + timedelta(minutes=tolerance_min) <= maintenant]
    return max(echus) if echus else None


def verdict_passage(creneau: datetime, maintenant: datetime, runs: list, attente_runner_min: int = ATTENTE_RUNNER_MIN) -> dict:
    """runs : liste de {created_at, status, conclusion, html_url} (API GitHub). Verdict pour un creneau."""
    marge = timedelta(minutes=5)  # une tache lancee quelques secondes avant l'heure reste « du creneau »
    du_creneau = []
    for r in runs:
        try:
            cree = lire_iso_utc(r.get("created_at"))
        except (TypeError, ValueError):
            continue
        if creneau - marge <= cree <= maintenant:
            du_creneau.append((cree, r))
    if not du_creneau:
        return {"etat": "non_lance", "creneau": creneau, "run": None, "retard_min": int((maintenant - creneau).total_seconds() // 60)}
    cree, r = min(du_creneau, key=lambda x: x[0])
    retard = int((cree - creneau).total_seconds() // 60)
    if r.get("status") == "queued" and maintenant - cree >= timedelta(minutes=attente_runner_min):
        return {"etat": "en_attente_runner", "creneau": creneau, "run": r, "retard_min": retard,
                "attente_min": int((maintenant - cree).total_seconds() // 60)}
    return {"etat": "ok", "creneau": creneau, "run": r, "retard_min": retard}


def _fmt(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")


def sujet_garde(v: dict) -> str:
    c = _fmt(v["creneau"])
    if v["etat"] == "non_lance":
        return f"[Veille AO] Passage prevu a {c} NON LANCE — PC eteint ou tache planifiee muette ?"
    if v["etat"] == "en_attente_runner":
        return f"[Veille AO] Passage de {c} EN ATTENTE du runner depuis {v.get('attente_min', 0)} min"
    return f"[Veille AO] Passage de {c} lance (retard {v.get('retard_min', 0)} min)"


def corps_garde(v: dict, maintenant: datetime, runs_url: str = "") -> str:
    c = escape(_fmt(v["creneau"]))
    lien = f'<p><a href="{escape(runs_url)}">Passages de la veille AO (GitHub Actions)</a></p>' if runs_url else ""
    if v["etat"] == "non_lance":
        return (
            f"<p>Aucun passage de la veille AO n'a ete cree depuis le creneau prevu de <b>{c}</b> "
            f"(verifie a {escape(_fmt(maintenant))}, soit {v.get('retard_min', 0)} min apres).</p>"
            "<p>Cause probable : le PC qui porte la tache planifiee « Veille AO - Trigger » et le runner etait "
            "eteint, en veille ou en redemarrage a l'heure prevue, ou la tache ne s'est pas declenchee.</p>"
            "<p>Rattrapage : la tache Windows rejoue le declenchement manque au prochain demarrage ou reveil du PC "
            "(parametres « executer des que possible » et « reveiller l'ordinateur »). Si le PC reste eteint : "
            "bouton « Relancer » de l'ecran Veille AO de MP Manager, ou « Run workflow » sur GitHub.</p>" + lien
        )
    if v["etat"] == "en_attente_runner":
        url = escape((v.get("run") or {}).get("html_url", ""))
        return (
            f"<p>Le passage prevu a <b>{c}</b> a bien ete declenche mais attend le runner depuis "
            f"{v.get('attente_min', 0)} min : le service du runner sur le PC ne repond pas (PC eteint apres le "
            "declenchement, service arrete ou reseau absent).</p>"
            f'<p><a href="{url}">Le passage en attente</a> demarrera de lui-meme des que le runner reviendra ; '
            "GitHub abandonne un passage jamais pris apres 24 h.</p>" + lien
        )
    return f"<p>Le passage prevu a <b>{c}</b> a ete lance.</p>" + lien


def lister_runs(repo: str, token: str, depuis: datetime) -> list:
    """Runs du workflow Veille AO crees depuis `depuis` (API GitHub, lecture seule)."""
    q = urllib.parse.urlencode({"per_page": 50, "created": ">=" + depuis.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs?{q}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "neurones-veille-ao/garde"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [{"created_at": r.get("created_at"), "status": r.get("status"), "conclusion": r.get("conclusion"),
             "html_url": r.get("html_url"), "event": r.get("event")} for r in data.get("workflow_runs", [])]


def main(argv=None, envoyer=envoyer_graph_simple, lister=lister_runs):
    p = argparse.ArgumentParser()
    p.add_argument("--maintenant", default="")
    p.add_argument("--creneaux", default=CRENEAUX_DEFAUT)
    p.add_argument("--tolerance-min", type=int, default=TOLERANCE_MIN)
    p.add_argument("--attente-runner-min", type=int, default=ATTENTE_RUNNER_MIN)
    p.add_argument("--sans-mail", action="store_true")
    p.add_argument("--config", default="config.json")
    a = p.parse_args(argv)
    maintenant = lire_iso_utc(a.maintenant) if a.maintenant else datetime.now(UTC)
    creneau = creneau_a_verifier(maintenant, analyser_creneaux(a.creneaux), a.tolerance_min)
    if creneau is None:
        print(f"[GARDE] {_fmt(maintenant)} : aucun creneau echu a verifier (week-end, ou avant {a.tolerance_min} min apres le premier creneau)")
        return 0
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        runs = lister(repo, token, creneau - timedelta(hours=1))
    except Exception as e:  # noqa: BLE001 — la garde ne doit pas se confondre avec un passage manque
        print(f"[GARDE] lecture des runs impossible ({type(e).__name__}) : verdict non rendu")
        return 0
    v = verdict_passage(creneau, maintenant, runs, a.attente_runner_min)
    print(f"[GARDE] creneau {_fmt(creneau)} verifie a {_fmt(maintenant)} : {v['etat']} (retard {v.get('retard_min')} min, {len(runs)} run(s) lus)")
    if v["etat"] == "ok" or a.sans_mail:
        return 0
    to = destinataires(a.config)
    if not to:
        print("[GARDE] aucun destinataire (config.json > email.to_addresses) : mail non envoye")
        return 0
    runs_url = f"https://github.com/{repo}/actions/workflows/{WORKFLOW}" if repo else ""
    sujet = sujet_garde(v)
    r = envoyer(to, sujet, corps_garde(v, maintenant, runs_url))
    print(f"[GARDE] mail « {sujet} » -> {', '.join(to)} : {'envoye' if r.get('sent') else 'NON envoye (' + str(r.get('reason')) + ')'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
