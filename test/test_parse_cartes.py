"""Gate : lecture des resultats du portail en CARTES (mise en page constatee le 28/10/2026).
Fixture synthetique : meme structure HTML que le portail, references inventees.
Lancer : python -m unittest test.test_parse_cartes  (venv veille)"""
import unittest

from src.search import parse_resultats, attribuer_categories, date_carte


def carte(ref_cons, org, ref_ao, objet, acheteur, date, heure, lieu, estimation=""):
    est = f'<span class="estim-mad" id="ctl0_x_estimationLabel">{estimation}</span>'
    return f'''
<div class="hidden-xs col-xs-10 generalBox watched">
 <div class="rightColumn rightColumn-green">
  <span class="verticalText hotTender"><span title="Appel d'offres ouvert"> AOO </span></span>
 </div>
 <div class="contentColumn without-logo">
  <div class="status p-card"><div><span> Référence : <span id="ctl0_r_ctl0_referencem">{ref_ao}</span>
   <span style="display:none">...</span></span></div></div>
  <div class="info p-card"><div class="p-objet"><strong> Objet : </strong> {objet} </div></div>
  <div style="display:none;"><div class="num p-card"><div><strong> Estimation TTC (en DH) : </strong>{est}</div></div></div>
  <div class="title p-card" role="heading"><div class="a-card"><div><strong> Acheteur public : </strong> {acheteur} </div></div></div>
 </div>
 <div class="leftColumn leftColumn-green">
  <div class="limita p-card"><div><span> Date limite de remise des plis </span></div></div>
  <div class="limita p-card"><strong><div><span> {date} </span></div></strong><strong><div><span> {heure} </span></div></strong></div>
  <div id="ctl0_r_ctl0_panelBlocLieuxExec">
   <div class="limita p-card"><div> Lieu d'exécution </div></div>
   <div class="limita p-card"><strong><div> {lieu[:12]}<br/>
    <div class="bloc-info-bulle"><a class="info-suite"> ... </a>
     <div class="info-bulle" id="ctl0_r_ctl0_ctl19_infosLieuExecution"><div> {lieu} </div></div></div></div></strong></div>
  </div>
 </div>
 <div class="share"><ul>
  <li title="Ajouter au panier"><a href="index.php?page=entreprise.EntrepriseHome&amp;goto=x">+</a></li>
  <li title="Téléchargement"><a href="https://www.marchespublics.gov.ma/?page=entreprise.EntrepriseDetailsConsultation&amp;refConsultation={ref_cons}&amp;orgAcronyme={org}&amp;retraits">DCE</a></li>
 </ul></div>
</div>'''


PAGE = "<html><body><div id='ctl0_CONTENU_PAGE_panelResult'>" + "".join([
    carte("9000001", "zz1", "99/TEST/2026", "Travaux d'électricité et courant faible du bâtiment X, en 2 lots.",
          "AGENCE TEST DES EAUX", "Mar 08 Dec 2026", "10:00", "RABAT-SALE-KENITRA LONG", "1 234 567,89"),
    carte("9000002", "zz2", "12/ESSAI/2026", "Fourniture de matériel informatique.",
          "COMMUNE D'ESSAI", "Jeu 26 Nov 2026", "09:30", "CASABLANCA"),
]) + "</div></body></html>"


class TestParseCartes(unittest.TestCase):
    def setUp(self):
        self.aos = parse_resultats(PAGE)

    def test_deux_cartes_lues(self):
        self.assertEqual([a["ref_consultation"] for a in self.aos], ["9000001", "9000002"])

    def test_champs_de_la_carte(self):
        a = self.aos[0]
        self.assertEqual(a["org_acronyme"], "zz1")
        self.assertEqual(a["reference_ao"], "99/TEST/2026")
        self.assertEqual(a["type_procedure"], "AOO")
        self.assertEqual(a["objet"], "Travaux d'électricité et courant faible du bâtiment X, en 2 lots.")
        self.assertEqual(a["acheteur"], "AGENCE TEST DES EAUX")
        self.assertEqual(a["date_limite"], "08/12/2026")
        self.assertEqual(a["heure_limite"], "10:00")
        self.assertEqual(a["lieu_execution"], "RABAT-SALE-KENITRA LONG")  # texte complet de la bulle, pas l'abrege
        self.assertEqual(a["estimation_ttc"], "1 234 567,89")
        self.assertIn("refConsultation=9000001&orgAcronyme=zz1", a["lien_fiche"])

    def test_sans_estimation_pas_de_cle(self):
        self.assertNotIn("estimation_ttc", self.aos[1])

    def test_categorie_jamais_posee_par_le_parseur(self):
        # une cle absente n'ecrase pas la categorie deja connue en Cosmos
        for a in self.aos:
            self.assertNotIn("categorie", a)
            self.assertNotIn("date_publication", a)

    def test_page_ancienne_mise_en_page_ne_lit_rien(self):
        self.assertEqual(parse_resultats("<table><tr><td>rien</td></tr></table>"), [])


class TestDateCarte(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(date_carte(" Mar 08 Dec 2026 "), "08/12/2026")
        self.assertEqual(date_carte("Lun 2 Févr. 2027"), "02/02/2027")
        self.assertEqual(date_carte("Ven 01 May 2026"), "01/05/2026")
        self.assertEqual(date_carte("27/11/2026 10:30"), "27/11/2026")
        self.assertEqual(date_carte("Date limite de remise des plis"), "")


class TestAttribuerCategories(unittest.TestCase):
    def test_bilan_nomme(self):
        aos = [{"ref_consultation": r, "categorie": "ancienne"} for r in ("1", "2", "3")]
        bilan = attribuer_categories(aos, {"Travaux": {"1", "3"}, "Fournitures": {"3"}, "Services": set()})
        self.assertEqual([a.get("categorie") for a in aos], ["Travaux", None, "Travaux"])
        self.assertEqual(bilan, {"avec": 2, "sans": ["2"], "multiples": ["3"]})

    def test_categorie_non_relue_ne_compte_pas(self):
        aos = [{"ref_consultation": "1"}]
        bilan = attribuer_categories(aos, {"Fournitures": {"1"}})
        self.assertEqual(aos[0]["categorie"], "Fournitures")
        self.assertEqual(bilan["sans"], [])


if __name__ == "__main__":
    unittest.main()
