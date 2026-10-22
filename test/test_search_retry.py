"""Gate : goto_avec_retry rejoue page.goto sur erreur reseau transitoire.
Lancer : python -m unittest test.test_search_retry  (venv veille)"""
import unittest
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PWTimeout

from src.search import goto_avec_retry


class FakePage:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = []

    def goto(self, url, wait_until=None):
        self.calls.append(url)
        if self.failures:
            raise self.failures.pop(0)


class TestGotoAvecRetry(unittest.TestCase):
    def test_reset_puis_succes_a_la_3e(self):
        page = FakePage([PlaywrightError("Page.goto: net::ERR_CONNECTION_RESET"), PWTimeout("Timeout")])
        slept = []
        goto_avec_retry(page, "https://x", sleep=slept.append)
        self.assertEqual(len(page.calls), 3)
        self.assertEqual(slept, [8, 15])

    def test_echec_definitif_apres_3(self):
        page = FakePage([PlaywrightError("reset")] * 3)
        with self.assertRaises(PlaywrightError):
            goto_avec_retry(page, "https://x", sleep=lambda s: None)
        self.assertEqual(len(page.calls), 3)

    def test_bug_non_reseau_propage_sans_retry(self):
        page = FakePage([KeyError("bug")])
        with self.assertRaises(KeyError):
            goto_avec_retry(page, "https://x", sleep=lambda s: None)
        self.assertEqual(len(page.calls), 1)


if __name__ == "__main__":
    unittest.main()


from src.search import detecter_indisponibilite, PortailIndisponible  # noqa: E402


class TestDetecterIndisponibilite(unittest.TestCase):
    PAGE_TGR = ("! Site temporairement indisponible Par mesure de precaution, ce site est "
                "temporairement suspendu a la suite de l'annonce de vulnerabilites critiques affectant PHP.")

    def test_503_page_tgr(self):
        m = detecter_indisponibilite(503, self.PAGE_TGR)
        self.assertIn("HTTP 503", m)
        self.assertIn("temporairement indisponible", m)

    def test_200_mais_page_maintenance(self):
        self.assertIsNotNone(detecter_indisponibilite(200, "Maintenance en cours, revenez plus tard"))

    def test_200_page_normale(self):
        self.assertIsNone(detecter_indisponibilite(200, "Resultats de la recherche : 500 consultations"))

    def test_statut_inconnu_page_normale(self):
        self.assertIsNone(detecter_indisponibilite(None, "Resultats"))

    def test_exception_nommee(self):
        self.assertTrue(issubclass(PortailIndisponible, Exception))
