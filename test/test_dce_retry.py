"""Gate : reprises du telechargement DCE etalees (incident du 29/10/2026 : six DCE en 3 minutes,
quatre en echec, reprises a 8 s / 15 s retombant ensemble sur un portail sature).
Lancer : python -m unittest test.test_dce_retry  (venv veille)"""
import re
import unittest
from pathlib import Path
from playwright.sync_api import TimeoutError as PWTimeout

from src import dce_download as d


class TestRepriseEtalee(unittest.TestCase):
    def test_deux_echecs_puis_succes(self):
        essais, attentes = [], []

        def une_fois(ref, org, cfg):
            essais.append(ref)
            if len(essais) < 3:
                raise PWTimeout("Timeout 90000ms exceeded while waiting for event \"download\"")
            return {"zip_path": "x.zip"}

        r = d.telecharger_dce("1", "o", {}, sleep=attentes.append, alea=lambda a, b: 12, _une_fois=une_fois)
        self.assertEqual(r, {"zip_path": "x.zip"})
        self.assertEqual(attentes, [57, 102])

    def test_echec_definitif_apres_3(self):
        def une_fois(ref, org, cfg):
            raise PWTimeout("Page.goto: Timeout 30000ms exceeded.")
        attentes = []
        with self.assertRaises(PWTimeout):
            d.telecharger_dce("1", "o", {}, sleep=attentes.append, alea=lambda a, b: 0, _une_fois=une_fois)
        self.assertEqual(len(attentes), 2)

    def test_deux_runs_lances_ensemble_ne_reprennent_pas_ensemble(self):
        self.assertNotEqual(d.delai_reprise(1, alea=lambda a, b: 3), d.delai_reprise(1, alea=lambda a, b: 27))
        for _ in range(200):
            self.assertTrue(45 <= d.delai_reprise(1) <= 75)
            self.assertTrue(90 <= d.delai_reprise(2) <= 120)

    def test_le_job_a_le_temps_de_ses_trois_tentatives(self):
        # incident : un run tue a 8 min par timeout-minutes, en pleine 3e tentative
        yml = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "download-dce.yml"
        minutes = int(re.search(r"timeout-minutes:\s*(\d+)", yml.read_text(encoding="utf-8")).group(1))
        installation_s = 180  # checkout + pip + playwright install --with-deps (mesure ~1,5 min)
        pire = (installation_s + d.DCE_RETRY_ATTEMPTS * d.DCE_TENTATIVE_MAX_S
                + sum(b + d.DCE_RETRY_ALEA_S for b in d.DCE_RETRY_DELAYS))
        self.assertLess(pire, minutes * 60)


if __name__ == "__main__":
    unittest.main()
