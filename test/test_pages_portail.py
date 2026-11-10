"""Gate : une page de resultats que le portail rend VIDE est rejouee une fois, puis NOMMEE et sautee —
jamais un plantage du passage entier (dry-run du 10/11/2026 : page 12 vide, Locator.inner_text en delai,
passage perdu). Faux portail en memoire, aucun reseau.
Lancer : python -m unittest test.test_pages_portail  (venv veille)"""
import unittest

from src import search


class FauxLocator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    def count(self):
        return self.page.cartes

    def inner_text(self, timeout=None):
        if self.page.cartes == 0:
            raise search.PWTimeout("Locator.inner_text: Timeout")
        return "REF-" + str(self.page.num)


class FauxPortail:
    """Chaque postback vers une page consomme un scenario : nombre de cartes rendues."""
    def __init__(self, scenario):
        self.scenario = list(scenario)
        self.cartes, self.num, self.postbacks = 50, "1", []

    def locator(self, sel):
        return FauxLocator(self, sel)

    def fill(self, sel, v):
        self.saisie = v

    def press(self, sel, k):
        self.postbacks.append(self.saisie)
        self.num = self.saisie
        self.cartes = self.scenario.pop(0) if self.scenario else 50

    def evaluate(self, js, args):
        return [self.cartes, self.num, "REF-" + self.num if self.cartes else ""]

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, *a, **k):
        pass


class TestOuvrirPage(unittest.TestCase):
    def setUp(self):
        self.journal = []
        self._log = search.log
        search.log = lambda etape, msg: self.journal.append(msg)

    def tearDown(self):
        search.log = self._log

    def test_page_vide_une_fois_puis_pleine(self):
        p = FauxPortail([0, 50])
        self.assertTrue(search._ouvrir_page(p, 2, 50, "T", essais=2, delai_s=0.01))
        self.assertEqual(p.postbacks, ["2", "2"])
        self.assertTrue(any("essai 1/2" in m for m in self.journal))

    def test_page_vide_deux_fois_est_nommee_et_sautee(self):
        p = FauxPortail([0, 0])
        self.assertFalse(search._ouvrir_page(p, 3, 50, "T", essais=2, delai_s=0.01))
        self.assertEqual(p.postbacks, ["3", "3"])

    def test_page_pleine_du_premier_coup(self):
        p = FauxPortail([50])
        self.assertTrue(search._ouvrir_page(p, 2, 50, "T", delai_s=0.01))
        self.assertEqual(p.postbacks, ["2"])


if __name__ == "__main__":
    unittest.main()
