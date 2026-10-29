"""Gate : suppression automatique des AO de veille echus (decision Karim, 29/10/2026).
Fixture piegee : instant limite a la minute pres en heure de Casablanca, AO traites
(go, DCE, fiche AO) jamais supprimes, doc de config jamais touche, dry-run sans effet.
Lancer : python -m unittest test.test_purge  (venv veille)"""
import unittest
from datetime import datetime, timezone

from src.purge import instant_limite, motif_garde, selectionner, purger, CASABLANCA

# 29/10/2026 13:00 a Casablanca ; le decalage UTC vient de tzdata, jamais ecrit en dur
# (tzdata 2026.6 : UTC+0 en octobre 2026, UTC+1 en juin)
MAINTENANT = datetime(2026, 10, 29, 13, 0, tzinfo=CASABLANCA).astimezone(timezone.utc)


def ao(ref, date, heure="10:00", **kw):
    d = {"id": f"veille_t_{ref}", "source": "s", "reference_ao": ref, "date_limite": date, "heure_limite": heure}
    d.update(kw)
    return d


class FakeContainer:
    def __init__(self, docs, refus=()):
        self.docs, self.refus, self.supprimes = docs, set(refus), []

    def query_items(self, query, parameters, partition_key):
        return list(self.docs)

    def delete_item(self, item, partition_key):
        if item in self.refus:
            raise RuntimeError("refus")
        self.supprimes.append(item)


DOCS = [
    ao("ECHU", "28/10/2026", statut="a_etudier"),
    ao("NOGO", "01/06/2026", statut="no_go"),
    ao("SANS-STATUT", "11/05/2026"),
    ao("MIDI-PASSE", "29/10/2026", "12:59"),        # 12:59 Casablanca < 13:00 : echu
    ao("13H01", "29/10/2026", "13:01"),             # pas encore : garde
    ao("SANS-HEURE-AUJ", "29/10/2026", ""),          # fin de journee : garde
    ao("GO", "01/10/2026", statut="go"),
    ao("ANALYSE", "01/10/2026", statut="en_analyse"),
    ao("DCE", "01/10/2026", dce_status="ready", dce_url="https://x"),
    ao("LIE", "01/10/2026", ao_id_lie="ao_1"),
    ao("ILLISIBLE", "date inconnue"),
    {"id": "veille_config", "type": "config", "source": "s"},
]


class TestRegle(unittest.TestCase):
    def test_instant_limite_en_heure_de_casablanca(self):
        self.assertEqual(instant_limite(ao("x", "29/10/2026", "13:00")), MAINTENANT)
        self.assertIsNone(instant_limite(ao("x", "31/02/2026")))
        juin = instant_limite(ao("x", "15/06/2026", "13:00"))
        self.assertEqual(juin, datetime(2026, 6, 15, 13, 0, tzinfo=CASABLANCA).astimezone(timezone.utc))

    def test_selection_et_motifs_nommes(self):
        sel, gardes = selectionner(DOCS, MAINTENANT)
        self.assertEqual(sorted(d["reference_ao"] for d in sel), ["ECHU", "MIDI-PASSE", "NOGO", "SANS-STATUT"])
        self.assertEqual(gardes, {"encore ouvert": 2, "statut go": 1, "statut en_analyse": 1,
                                  "DCE telecharge": 1, "fiche AO liee": 1, "date limite non lue": 1})

    def test_un_ao_traite_n_est_jamais_supprime(self):
        for d in DOCS[6:10]:
            self.assertIsNotNone(motif_garde(d, MAINTENANT), d["reference_ao"])


class TestPurger(unittest.TestCase):
    def test_dry_run_ne_supprime_rien(self):
        c = FakeContainer(DOCS)
        r = purger(c, "s", maintenant=MAINTENANT, appliquer=False)
        self.assertEqual(c.supprimes, [])
        self.assertEqual((r["vus"], r["a_supprimer"]), (11, 4))

    def test_applique_supprime_exactement_la_selection(self):
        c = FakeContainer(DOCS)
        r = purger(c, "s", maintenant=MAINTENANT)
        self.assertEqual(sorted(c.supprimes), ["veille_t_ECHU", "veille_t_MIDI-PASSE", "veille_t_NOGO", "veille_t_SANS-STATUT"])
        self.assertEqual(r["supprimes"], 4)
        self.assertNotIn("veille_config", c.supprimes)

    def test_un_echec_est_nomme(self):
        c = FakeContainer(DOCS, refus={"veille_t_NOGO"})
        r = purger(c, "s", maintenant=MAINTENANT)
        self.assertEqual(r["supprimes"], 3)
        self.assertEqual(r["echecs"], ["NOGO (RuntimeError)"])


if __name__ == "__main__":
    unittest.main()
