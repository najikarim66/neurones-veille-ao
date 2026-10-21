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
