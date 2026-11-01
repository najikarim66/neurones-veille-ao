"""Gate : alerte e-mail des documents de la societe (coffre MP) qui expirent sous 15 jours.
Fixture piegee : version courante = la derniere, sans validite = pas d'alerte, un seul e-mail
par version (journal), echec d'envoi = journal intact, aucun fichier du coffre lu.
Lancer : python -m unittest test.test_coffre_alerte  (venv veille)"""
import unittest
from datetime import date

from src.coffre_alerte import alertes, a_envoyer, verifier, DESTINATAIRES_DEFAUT

AUJ = date(2026, 11, 1)


def doc(i, *validites, **kw):
    d = {"id": i, "type": kw.get("type", "cnss"), "versions": [{"v": n + 1, "date_validite": v} for n, v in enumerate(validites)]}
    d.update({k: v for k, v in kw.items() if k != "type"})
    return d


class FakeContainer:
    def __init__(self, docs=None, items=None):
        self.docs, self.items, self.upserts = docs or [], dict(items or {}), []

    def query_items(self, q, enable_cross_partition_query=True):
        return list(self.docs)

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise KeyError(item)
        return self.items[item]

    def upsert_item(self, body):
        self.upserts.append(body)
        self.items[body["id"]] = body


class FakeDb:
    def __init__(self, docs, cfg=None):
        self.c = {"mp_coffre_docs": FakeContainer(docs), "mp_config": FakeContainer(items=cfg)}

    def get_container_client(self, nom):
        return self.c[nom]


class TestAlertes(unittest.TestCase):
    def test_regle(self):
        docs = [doc("a", "2026-12-31", "2026-11-10"), doc("b", "2026-11-10", "2027-06-30"), doc("c", "2026-10-20"),
                {"id": "d", "type": "statuts", "versions": [{"v": 1}]}, doc("e", "2026-11-16"), doc("f", "2026-11-17"),
                doc("g", "2026-11-05", archive=True)]
        r = alertes(docs, AUJ)
        self.assertEqual([x["id"] for x in r], ["c", "a", "e"])  # tries par date ; f hors fenetre ; b renouvele ; d sans date ; g archive
        self.assertTrue(r[0]["expire"])
        self.assertEqual(r[1]["cle"], "a:v2")

    def test_une_fois_par_version(self):
        r = alertes([doc("a", "2026-11-10")], AUJ)
        self.assertEqual(a_envoyer(r, {"envoyes": {"a:v1": "2026-10-28"}}), [])
        self.assertEqual(len(a_envoyer(r, {"envoyes": {"a:v0": "x"}})), 1)


class TestVerifier(unittest.TestCase):
    def test_envoi_puis_journal(self):
        envois = []
        db = FakeDb([doc("a", "2026-11-10", type="attestation_fiscale")])
        b = verifier(db, lambda to, s, h: envois.append((to, s, h)) or {"sent": True}, aujourdhui=AUJ)
        self.assertEqual(b["envoyes"], 1)
        self.assertEqual(envois[0][0], DESTINATAIRES_DEFAUT)
        self.assertIn("Attestation fiscale", envois[0][2])
        self.assertIn("10/11/2026", envois[0][2])
        self.assertEqual(db.c["mp_config"].items["coffre_alerte_journal"]["envoyes"], {"a:v1": "2026-11-01"})
        b2 = verifier(db, lambda *a: envois.append(a) or {"sent": True}, aujourdhui=AUJ)
        self.assertEqual(b2["envoyes"], 0)
        self.assertEqual(len(envois), 1)

    def test_echec_envoi_journal_intact(self):
        db = FakeDb([doc("a", "2026-11-10")])
        b = verifier(db, lambda *a: {"sent": False, "reason": "graph"}, aujourdhui=AUJ)
        self.assertEqual(b["envoyes"], 0)
        self.assertEqual(db.c["mp_config"].upserts, [])

    def test_destinataires_configures_et_dry_run(self):
        envois = []
        db = FakeDb([doc("a", "2026-11-10")], cfg={"coffre_alerte": {"id": "coffre_alerte", "destinataires": ["x@neurones.ma", " "]}})
        verifier(db, lambda to, s, h: envois.append(to) or {"sent": True}, aujourdhui=AUJ, appliquer=False)
        self.assertEqual(envois, [])
        verifier(db, lambda to, s, h: envois.append(to) or {"sent": True}, aujourdhui=AUJ)
        self.assertEqual(envois, [["x@neurones.ma"]])


if __name__ == "__main__":
    unittest.main()
