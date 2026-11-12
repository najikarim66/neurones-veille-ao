"""Gate : garde des passages (DG 12/11/2026) — creneau a verifier, verdict non lance / en attente du runner / ok,
mail envoye seulement quand un passage prevu n'a pas eu lieu (envoi et lecture des runs injectes, aucun reseau).
Lancer : python -m unittest test.test_garde_passage"""
import unittest
from datetime import datetime, timezone

from src import garde_passage as g

UTC = timezone.utc
CRENEAUX = g.analyser_creneaux("08:00,14:00")


def run(cree, status="completed", conclusion="success"):
    return {"created_at": cree, "status": status, "conclusion": conclusion, "html_url": "https://github.com/x/y/actions/runs/1"}


class TestCreneau(unittest.TestCase):
    def test_avant_echeance_rien(self):
        # jeudi 12/11/2026 09:00 UTC : le creneau 08:00 n'est echu qu'a 09:30
        self.assertIsNone(g.creneau_a_verifier(datetime(2026, 11, 12, 9, 0, tzinfo=UTC), CRENEAUX))

    def test_apres_echeance_le_plus_recent(self):
        self.assertEqual(g.creneau_a_verifier(datetime(2026, 11, 12, 9, 40, tzinfo=UTC), CRENEAUX), datetime(2026, 11, 12, 8, 0, tzinfo=UTC))
        self.assertEqual(g.creneau_a_verifier(datetime(2026, 11, 12, 15, 40, tzinfo=UTC), CRENEAUX), datetime(2026, 11, 12, 14, 0, tzinfo=UTC))
        # cron en retard de plusieurs heures : on verifie quand meme le creneau le plus recent echu
        self.assertEqual(g.creneau_a_verifier(datetime(2026, 11, 12, 13, 0, tzinfo=UTC), CRENEAUX), datetime(2026, 11, 12, 8, 0, tzinfo=UTC))

    def test_week_end_rien(self):
        self.assertIsNone(g.creneau_a_verifier(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), CRENEAUX))  # samedi
        self.assertIsNone(g.creneau_a_verifier(datetime(2026, 11, 15, 12, 0, tzinfo=UTC), CRENEAUX))  # dimanche

    def test_analyse(self):
        self.assertEqual(g.analyser_creneaux("14:00, 08:00"), [(8, 0), (14, 0)])


class TestVerdict(unittest.TestCase):
    C = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    M = datetime(2026, 11, 12, 9, 40, tzinfo=UTC)

    def test_aucun_run_non_lance(self):
        v = g.verdict_passage(self.C, self.M, [run("2026-11-11T14:00:04Z")])  # seul le passage de la veille
        self.assertEqual(v["etat"], "non_lance")
        self.assertEqual(v["retard_min"], 100)

    def test_run_du_creneau_ok(self):
        v = g.verdict_passage(self.C, self.M, [run("2026-11-12T08:00:05Z", "in_progress", None)])
        self.assertEqual(v["etat"], "ok")
        self.assertEqual(v["retard_min"], 0)

    def test_rattrapage_apres_demarrage_ok_avec_retard(self):
        v = g.verdict_passage(self.C, self.M, [run("2026-11-12T08:52:00Z")])
        self.assertEqual(v["etat"], "ok")
        self.assertEqual(v["retard_min"], 52)

    def test_queued_trop_longtemps_en_attente_runner(self):
        v = g.verdict_passage(self.C, self.M, [run("2026-11-12T08:00:05Z", "queued", None)])
        self.assertEqual(v["etat"], "en_attente_runner")
        self.assertGreaterEqual(v["attente_min"], 99)

    def test_queued_recent_reste_ok(self):
        v = g.verdict_passage(self.C, datetime(2026, 11, 12, 8, 10, tzinfo=UTC), [run("2026-11-12T08:00:05Z", "queued", None)])
        self.assertEqual(v["etat"], "ok")

    def test_run_rouge_est_ok_pour_la_garde(self):
        # l'echec est couvert par l'alerte « le passage a echoue » ; la garde ne doublonne pas
        v = g.verdict_passage(self.C, self.M, [run("2026-11-12T08:00:05Z", "completed", "failure")])
        self.assertEqual(v["etat"], "ok")

    def test_run_juste_avant_l_heure_compte(self):
        v = g.verdict_passage(self.C, self.M, [run("2026-11-12T07:59:30Z")])
        self.assertEqual(v["etat"], "ok")


class TestMain(unittest.TestCase):
    def _lancer(self, runs, maintenant="2026-11-12T09:40:00Z", config="config.json"):
        envois = []
        r = g.main(["--maintenant", maintenant, "--config", config], envoyer=lambda to, s, h: envois.append((to, s, h)) or {"sent": True},
                   lister=lambda repo, token, depuis: runs)
        return r, envois

    def test_passage_present_aucun_mail(self):
        r, envois = self._lancer([run("2026-11-12T08:00:04Z")])
        self.assertEqual(r, 0)
        self.assertEqual(envois, [])

    def test_passage_absent_mail_au_dg(self):
        r, envois = self._lancer([run("2026-11-11T14:00:04Z")])
        self.assertEqual(r, 0)
        self.assertEqual(len(envois), 1)
        to, sujet, html = envois[0]
        self.assertTrue(to)
        self.assertIn("NON LANCE", sujet)
        self.assertIn("12/11/2026 08:00 UTC", sujet)
        self.assertIn("Relancer", html)

    def test_runner_muet_mail_au_dg(self):
        r, envois = self._lancer([run("2026-11-12T08:00:04Z", "queued", None)])
        self.assertEqual(len(envois), 1)
        self.assertIn("EN ATTENTE du runner", envois[0][1])

    def test_week_end_aucun_appel(self):
        r, envois = self._lancer([], maintenant="2026-11-14T09:40:00Z")
        self.assertEqual(envois, [])

    def test_lecture_impossible_ne_leve_pas(self):
        def casse(repo, token, depuis):
            raise OSError("reseau")
        envois = []
        r = g.main(["--maintenant", "2026-11-12T09:40:00Z"], envoyer=lambda *a: envois.append(a), lister=casse)
        self.assertEqual(r, 0)
        self.assertEqual(envois, [])


if __name__ == "__main__":
    unittest.main()
