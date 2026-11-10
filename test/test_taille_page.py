"""Gate : la taille de page se CHOISIT parmi celles que le portail offre (panne du 09-10/11/2026 :
le portail rouvert n'offre plus que 10/20/50, demander 500 attendait une option absente jusqu'au delai).
Lancer : python -m unittest test.test_taille_page  (venv veille)"""
import unittest

from src.search import choisir_taille_page


class TestChoisirTaillePage(unittest.TestCase):
    def test_portail_rouvert_offre_10_20_50_on_prend_50(self):
        self.assertEqual(choisir_taille_page(["10", "20", "50"], 500), 50)

    def test_taille_voulue_offerte_on_la_prend(self):
        self.assertEqual(choisir_taille_page(["10", "20", "50", "500"], 500), 500)

    def test_plus_grande_sous_la_voulue(self):
        self.assertEqual(choisir_taille_page(["10", "20", "50", "100", "500"], 200), 100)

    def test_toutes_au_dessus_on_prend_la_plus_grande(self):
        self.assertEqual(choisir_taille_page(["100", "200"], 50), 200)

    def test_aucune_option_rend_none(self):
        self.assertIsNone(choisir_taille_page([], 500))
        self.assertIsNone(choisir_taille_page(None, 500))
        self.assertIsNone(choisir_taille_page(["", "abc"], 500))

    def test_valeurs_bruitees(self):
        self.assertEqual(choisir_taille_page([" 10 ", "20 résultats", "50"], 500), 50)


if __name__ == "__main__":
    unittest.main()
