"""Gate : releve de l'etude d'AO par le runner apres un DCE (horloge de MP).
Rappel chaque minute tant qu'une etude est en cours, arret quand rien n'est en cours, arret
borne dans le temps, MP injoignable non bloquant.
Lancer : python -m unittest test.test_etude_tick  (venv veille)"""
import unittest

from src.etude_tick import relever


def suite(*reponses):
    it = iter(reponses)
    def appel():
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    return appel


class TestRelever(unittest.TestCase):
    def test_rappelle_tant_que_en_cours(self):
        dodos = []
        b = relever(suite({"en_cours": 0, "pre_lancees": [{"ref": "1/T", "statut": "analyse_en_cours"}]}, {"en_cours": 1}, {"saute": "tick recent"},
                          {"en_cours": 0, "terminees": 1}), sleep=dodos.append, duree_max_s=3600, pas_s=60)
        self.assertEqual(b, {"en_cours": 0, "terminees": 1})
        self.assertEqual(dodos, [60, 60, 60])

    def test_rien_en_cours_un_seul_appel(self):
        dodos = []
        relever(suite({"en_cours": 0, "pre_lancees": []}), sleep=dodos.append)
        self.assertEqual(dodos, [])

    def test_borne(self):
        dodos = []
        relever(suite(*[{"en_cours": 1}] * 50), sleep=dodos.append, duree_max_s=0, pas_s=60)
        self.assertEqual(dodos, [])

    def test_mp_injoignable(self):
        self.assertIsNone(relever(suite(OSError("reseau")), sleep=lambda s: None))


if __name__ == "__main__":
    unittest.main()
