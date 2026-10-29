"""Gate : un run DCE interrompu ne laisse pas le doc en « downloading » (incident du 29/10/2026 :
run 1049534 bloque apres « Clic Valider », annule au delai du job ; le bouton DCE de MP restait
en sablier et refusait la relance).
Lancer : python -m unittest test.test_dce_interrompu  (venv veille)"""
import re
import unittest
from pathlib import Path

from src import dce_download as d
from src.dce_to_blob import maj_si_interrompu, MOTIF_INTERROMPU

YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "download-dce.yml"


def _etapes(texte):
    """Decoupe le workflow en etapes {nom: texte du bloc} (sans dependance yaml)."""
    blocs = re.split(r"\n      - name: ", texte)
    return {b.split("\n", 1)[0].strip(): b for b in blocs[1:]}


def _minutes(bloc):
    return int(re.search(r"timeout-minutes:\s*(\d+)", bloc).group(1))


class TestMajSiInterrompu(unittest.TestCase):
    def test_en_cours_devient_echec_nomme(self):
        for st in ("downloading", "queued"):
            self.assertEqual(maj_si_interrompu({"dce_status": st}),
                             {"dce_status": "failed", "dce_error": MOTIF_INTERROMPU})

    def test_rien_ne_s_ecrase(self):
        self.assertIsNone(maj_si_interrompu({"dce_status": "ready", "dce_url": "https://x"}))
        self.assertIsNone(maj_si_interrompu({"dce_status": "failed", "dce_error": "TimeoutError: ..."}))
        self.assertIsNone(maj_si_interrompu({}))
        self.assertIsNone(maj_si_interrompu(None))


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        texte = YML.read_text(encoding="utf-8")
        self.job_minutes = _minutes(texte.split("steps:")[0])
        self.etapes = _etapes(texte)
        self.princ = _minutes(self.etapes["Download DCE + upload Blob + update Cosmos"])

    def test_etape_de_secours_sur_echec_et_annulation(self):
        s = self.etapes["Nommer un run interrompu"]
        self.assertRegex(s, r"if: failure\(\) \|\| cancelled\(\)")
        self.assertIn("-m src.dce_to_blob --interrompu", s)
        self.assertIn("COSMOS_KEY: ${{ secrets.COSMOS_KEY }}", s)

    def test_l_etape_principale_s_arrete_avant_le_job(self):
        # l'etape principale a son propre delai, plus court que le job, et laisse au moins
        # 2 min a l'etape de secours
        installation = 3  # checkout + venv + playwright, mesure < 1 min sur ce PC
        self.assertLessEqual(installation + self.princ + 2, self.job_minutes)

    def test_l_etape_principale_a_le_temps_de_ses_trois_tentatives(self):
        pire = (d.DCE_RETRY_ATTEMPTS * d.DCE_TENTATIVE_MAX_S
                + sum(b + d.DCE_RETRY_ALEA_S for b in d.DCE_RETRY_DELAYS) + 60)  # + upload/mail
        self.assertLess(pire, self.princ * 60)


if __name__ == "__main__":
    unittest.main()
