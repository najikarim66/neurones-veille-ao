"""
Releve de l'etude d'AO de MP apres un telechargement de DCE (lot « Etude d'AO », 01/11/2026).

La pre-etude automatique et l'analyse vivent dans MP (la cle de l'API Claude n'est QUE la-bas) ;
ce runner sert d'horloge : il appelle GET https://mp.neurones.ma/api/etudes-tick (route sans
entree, sans secret, qui avance seulement ce qui est deja eligible), puis le rappelle chaque
minute tant qu'une etude est en cours, au plus `duree_max_s`. Un echec reseau n'est jamais
bloquant : MP releve aussi a chaque ouverture d'ecran.

Lancer seul : python -m src.etude_tick
"""
import json
import time
import urllib.request

URL = "https://mp.neurones.ma/api/etudes-tick"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] [ETUDE] {msg}", flush=True)


def appeler(url=URL, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "veille-ao-runner"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def relever(appel=appeler, sleep=time.sleep, duree_max_s=20 * 60, pas_s=60):
    """Rappelle le tick tant qu'il reste une etude en cours. Renvoie le dernier bilan (ou None)."""
    debut, dernier, n = time.monotonic(), None, 0
    while True:
        n += 1
        try:
            b = appel()
        except Exception as e:
            log(f"tick {n} : MP injoignable ({type(e).__name__}) — releve laissee a MP")
            return dernier
        if b.get("saute"):
            log(f"tick {n} : {b['saute']}")
        else:
            dernier = b
            pre = ", ".join(f"{p.get('ref')} ({p.get('statut')})" for p in b.get("pre_lancees") or []) or "aucune"
            log(f"tick {n} : {b.get('en_cours', 0)} etude(s) en cours · {b.get('terminees', 0)} terminee(s) · pre-etude lancee : {pre}")
            ecartees = b.get("pre_ecartees") or []
            if ecartees and n == 1:
                log("  pre-etudes ecartees : " + " ; ".join(f"{x.get('ref')} : {x.get('motif')}" for x in ecartees[:10]))
            if not b.get("en_cours") and not b.get("pre_lancees"):
                return dernier
        if time.monotonic() - debut + pas_s > duree_max_s:
            log(f"arret apres {n} tick(s) : etude encore en cours, MP la relevera")
            return dernier
        sleep(pas_s)


if __name__ == "__main__":
    relever()
