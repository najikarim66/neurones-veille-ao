"""Gate : alertes de la veille (DG 10/11/2026) — heures ouvrees, verdict « aucun nouvel AO depuis
24 h ouvrees », cause nommee d'un echec et mail d'echec (envoi injecte, aucun reseau).
Lancer : python -m unittest test.test_alerte_veille  (venv veille)"""
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from src.alerte_veille import heures_ouvrees, verdict_silence, lire_iso, ecrire_cause, lire_cause, corps_echec, corps_silence
from src import alerte_echec

UTC = timezone.utc


class TestHeuresOuvrees(unittest.TestCase):
    def test_un_jour_ouvre_complet(self):
        # mardi 03/11/2026 10:00 -> mercredi 04/11 10:00 (Maroc = UTC+1 en novembre) : 24 h
        self.assertAlmostEqual(heures_ouvrees(datetime(2026, 11, 3, 9, tzinfo=UTC), datetime(2026, 11, 4, 9, tzinfo=UTC)), 24.0, places=3)

    def test_le_week_end_ne_compte_pas(self):
        # vendredi 06/11 16:00 Maroc -> lundi 09/11 10:00 Maroc : 8 h (vendredi) + 10 h (lundi) = 18 h
        self.assertAlmostEqual(heures_ouvrees(datetime(2026, 11, 6, 15, tzinfo=UTC), datetime(2026, 11, 9, 9, tzinfo=UTC)), 18.0, places=3)

    def test_fin_avant_debut(self):
        self.assertEqual(heures_ouvrees(datetime(2026, 11, 9, 9, tzinfo=UTC), datetime(2026, 11, 8, 9, tzinfo=UTC)), 0.0)

    def test_panne_du_02_au_10_11(self):
        # dernier AO decouvert lundi 02/11 16:41 UTC ; passage mardi 10/11 06:00 UTC : 5 jours ouvres + ...
        h = heures_ouvrees(lire_iso("2026-11-02T16:41:57Z"), datetime(2026, 11, 10, 6, tzinfo=UTC))
        self.assertGreater(h, 24 * 5)
        self.assertLess(h, 24 * 6)


class TestVerdictSilence(unittest.TestCase):
    def test_silence_de_8_jours_alerte(self):
        v = verdict_silence(lire_iso("2026-11-02T16:41:57Z"), datetime(2026, 11, 10, 6, tzinfo=UTC))
        self.assertTrue(v["alerter"])
        self.assertIn("02/11/2026", v["motif"])

    def test_decouverte_du_matin_meme_n_alerte_pas(self):
        v = verdict_silence(datetime(2026, 11, 10, 6, tzinfo=UTC), datetime(2026, 11, 10, 14, tzinfo=UTC))
        self.assertFalse(v["alerter"])

    def test_vendredi_soir_a_lundi_matin_n_alerte_pas(self):
        v = verdict_silence(datetime(2026, 11, 6, 13, tzinfo=UTC), datetime(2026, 11, 9, 6, tzinfo=UTC))
        self.assertFalse(v["alerter"])

    def test_base_vide_alerte(self):
        self.assertTrue(verdict_silence(None, datetime(2026, 11, 10, 6, tzinfo=UTC))["alerter"])

    def test_date_illisible_ne_conclut_pas(self):
        self.assertIsNone(lire_iso("hier"))
        self.assertIsNone(lire_iso(""))

    def test_corps_silence_porte_le_motif(self):
        v = verdict_silence(lire_iso("2026-11-02T16:41:57Z"), datetime(2026, 11, 10, 6, tzinfo=UTC))
        self.assertIn(v["motif"], corps_silence(v, "https://x/run/1"))


class TestAlerteEchec(unittest.TestCase):
    def test_cause_ecrite_puis_lue(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "veille-echec.txt"
            ecrire_cause("portail marchespublics.gov.ma indisponible (HTTP 503) : suspension", f)
            self.assertEqual(lire_cause(f), "portail marchespublics.gov.ma indisponible (HTTP 503) : suspension")
            self.assertEqual(lire_cause(Path(d) / "absent.txt"), "")

    def test_mail_d_echec_part_aux_destinataires_de_la_config_avec_la_cause(self):
        envois = []
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text('{"email": {"to_addresses": ["dg@exemple.ma"]}}', encoding="utf-8")
            cause = Path(d) / "veille-echec.txt"
            cause.write_text("TimeoutError: Page.select_option: Timeout 30000ms exceeded.\n", encoding="utf-8")
            import src.alerte_veille as av
            ancien = av.FICHIER_CAUSE
            av.FICHIER_CAUSE = cause
            try:
                alerte_echec.lire_cause.__defaults__ = (cause,)
                alerte_echec.main(["--run-url", "https://x/run/2", "--config", str(cfg)], envoyer=lambda to, s, h: envois.append((to, s, h)) or {"sent": True})
            finally:
                av.FICHIER_CAUSE = ancien
                alerte_echec.lire_cause.__defaults__ = (ancien,)
        self.assertEqual(len(envois), 1)
        to, sujet, html = envois[0]
        self.assertEqual(to, ["dg@exemple.ma"])
        self.assertTrue(sujet.startswith("[Veille AO] ECHEC du passage"))
        self.assertIn("Page.select_option", html)
        self.assertIn("https://x/run/2", html)

    def test_sans_destinataire_rien_ne_part(self):
        envois = []
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text('{"email": {}}', encoding="utf-8")
            alerte_echec.main(["--config", str(cfg)], envoyer=lambda *a: envois.append(a) or {"sent": True})
        self.assertEqual(envois, [])

    def test_corps_echec_sans_cause_le_dit(self):
        self.assertIn("cause non nommee", corps_echec("", ""))


if __name__ == "__main__":
    unittest.main()
