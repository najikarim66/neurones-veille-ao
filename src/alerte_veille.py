"""
Alertes de la veille AO (decision DG 10/11/2026, apres la panne du 02 au 10/11 restee muette) :
  · un passage qui ECHOUE -> mail au DG (src/alerte_echec.py, etape « if: failure() » du workflow,
    qui lit la cause nommee ecrite ici par le pipeline) ;
  · AUCUN nouvel AO collecte depuis 24 h OUVREES -> mail au DG, decide ici a chaque passage vert.

Tout est PUR et teste (test/test_alerte_veille.py) ; l'envoi est injecte. Heure du Maroc
(Africa/Casablanca). Les heures ouvrees : lundi a vendredi, 24 h par jour ouvre (un week-end
entier ne compte pas) — « 24 h ouvrees » = un jour ouvre complet sans decouverte.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FUSEAU = ZoneInfo("Africa/Casablanca")
SEUIL_SILENCE_H = 24
FICHIER_CAUSE = Path("veille-echec.txt")


def heures_ouvrees(debut: datetime, fin: datetime) -> float:
    """Heures ecoulees de `debut` a `fin` en ne comptant que les jours ouvres (lun-ven), heure
    du Maroc. Un instant sans fuseau est pris pour de l'UTC (c'est ainsi que Cosmos les ecrit)."""
    debut = _au_maroc(debut)
    fin = _au_maroc(fin)
    if fin <= debut:
        return 0.0
    total = 0.0
    curseur = debut
    while curseur < fin:
        minuit_suivant = (curseur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        borne = min(minuit_suivant, fin)
        if curseur.weekday() < 5:
            total += (borne - curseur).total_seconds() / 3600.0
        curseur = borne
    return total


def _au_maroc(d: datetime) -> datetime:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(FUSEAU)


def lire_iso(texte):
    """'2026-11-02T16:41:57Z' -> datetime UTC ; None si vide ou illisible (une date illisible ne
    conclut jamais, doctrine #35)."""
    if not texte:
        return None
    try:
        t = str(texte).strip().replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def verdict_silence(derniere_decouverte, maintenant, seuil_h: float = SEUIL_SILENCE_H) -> dict:
    """Decide l'alerte « aucun nouvel AO » : {alerter, heures, motif}.
    derniere_decouverte : datetime ou None (aucun AO en base -> on alerte : rien n'a jamais ete collecte)."""
    if derniere_decouverte is None:
        return {"alerter": True, "heures": None, "motif": "aucune date de premiere decouverte en base"}
    h = heures_ouvrees(derniere_decouverte, maintenant)
    if h >= seuil_h:
        return {"alerter": True, "heures": round(h, 1),
                "motif": f"dernier AO decouvert le {_au_maroc(derniere_decouverte):%d/%m/%Y %H:%M} (Maroc), "
                         f"soit {h:.0f} h ouvrees sans nouveaute (seuil {seuil_h:.0f} h)"}
    return {"alerter": False, "heures": round(h, 1), "motif": f"{h:.0f} h ouvrees depuis le dernier AO decouvert"}


def corps_silence(verdict: dict, run_url: str = "") -> str:
    return (
        "<p>La veille AO a tourne, le portail a repondu, mais <b>aucun nouvel appel d'offres</b> n'a ete "
        f"collecte depuis plus de {SEUIL_SILENCE_H} h ouvrees.</p>"
        f"<p>{verdict.get('motif', '')}</p>"
        "<p>A verifier : mots-cles de la veille (ecran Veille AO de MP), mise en page du portail "
        "marchespublics.gov.ma, ou simple creux de publication.</p>"
        + (f"<p>Passage : <a href=\"{run_url}\">{run_url}</a></p>" if run_url else "")
    )


def corps_echec(cause: str, run_url: str = "") -> str:
    return (
        "<p>Le passage de la veille AO a <b>echoue</b> : aucun AO collecte a ce creneau.</p>"
        f"<pre style=\"white-space:pre-wrap\">{cause or 'cause non nommee (voir le journal du passage)'}</pre>"
        + (f"<p>Journal : <a href=\"{run_url}\">{run_url}</a></p>" if run_url else "")
    )


def ecrire_cause(texte: str, fichier: Path = FICHIER_CAUSE) -> None:
    """Le pipeline NOMME sa cause dans un fichier ; l'etape d'alerte du workflow la lit (une cause
    nommee vaut mieux qu'un journal de 300 lignes). Jamais bloquant."""
    try:
        fichier.write_text(str(texte or "").strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def lire_cause(fichier: Path = FICHIER_CAUSE) -> str:
    try:
        return fichier.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
