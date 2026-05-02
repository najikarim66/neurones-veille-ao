# Neurones Veille AO

Pipeline automatique de veille sur les marchés publics marocains (marchespublics.gov.ma).

**Workflow** : scrape → scoring → push Cosmos DB → email HTML quotidien.

**Fonctionnement** :
- 7h00 et 15h00 (heure Casablanca), GitHub Actions execute le pipeline
- Les nouveaux AO pertinents (score >= 35) sont stockes en Cosmos avec deduplication
- Un email recapitulatif est envoye via Resend a `naji@neurones.ma`
- Le DL DCE se fait **a la demande** depuis ton PC local

---

## Architecture

```
GITHUB ACTIONS (cron 6h+14h UTC)
       │
       └─> python -m src.pipeline
              │
              ├── scrape marchespublics.gov.ma  (Playwright + BeautifulSoup)
              ├── scoring (positifs/negatifs/combos/categorie)
              ├── filtre seuil (35)
              ├── push Cosmos (dedup intelligente, preserve statut go/no-go)
              └── email Resend (HTML colore : nouveautes + rappels VERTS)


TON PC (usage manuel) :
  run_search.bat       → test pipeline complet local
  run_dce.bat REF ORG  → DL DCE d'un AO precis
```

---

## Setup initial (a faire une seule fois)

### 1. Creer un repo GitHub prive

1. Va sur https://github.com/new
2. Nom : `neurones-veille-ao`
3. Visibilite : **Private**
4. Coche : "Initialize this repository with README" → **NON** (on a deja un README)
5. **Create repository**

### 2. Cloner ce dossier dans ton repo

Sur ton PC, dans le dossier `neurones-veille-ao` :

```powershell
cd C:\Users\NAJI\veille_ao
git init
git add .
git commit -m "Initial commit - veille AO pipeline"
git branch -M main
git remote add origin https://github.com/najikarim66/neurones-veille-ao.git
git push -u origin main
```

### 3. Ajouter les Secrets GitHub

Sur la page du repo : **Settings → Secrets and variables → Actions → New repository secret**

Ajoute 2 secrets :

**Secret 1 :**
- Name : `COSMOS_KEY`
- Value : la primary key du compte Cosmos `btp-pointage-db` (sans guillemets)

Pour la recuperer :
```powershell
az cosmosdb keys list --name btp-pointage-db --resource-group btp-pointage-rg --query primaryMasterKey -o tsv
```

**Secret 2 :**
- Name : `RESEND_API_KEY`
- Value : la cle Resend (commence par `re_xxxxxxxx`)

### 4. Tester le 1er run manuel sur GitHub

Sur la page du repo : **Actions → Veille AO → Run workflow → Run workflow** (bouton vert)

Le run prend 2-3 minutes. Suis l'execution en temps reel dans le tab Actions.

A la fin :
- Tu dois recevoir un email a `naji@neurones.ma` (verifie aussi le dossier Spam)
- Le container Cosmos `mp_veille_ao` doit etre rempli

### 5. (Optionnel) Setup local pour DL DCE manuel

Sur ton PC :

```powershell
cd C:\Users\NAJI\veille_ao
pip install -r requirements.txt
playwright install chromium
```

---

## Modifier les horaires de scrape

Edite `.github/workflows/veille-ao.yml` lignes `cron: ...`.

Format cron : `minute heure jour mois jour-semaine`. Format **UTC** (Casablanca = UTC+1).

Exemples :
- `"0 6 * * 1-5"` → 7h00 Casablanca, lundi-vendredi
- `"0 14 * * *"` → 15h00 Casablanca, tous les jours
- `"30 5 * * *"` → 6h30 Casablanca, tous les jours

Apres modification, commit + push : le nouveau cron est actif a partir du prochain creneau.

---

## Modifier les mots-cles ou le scoring

Edite `config.json` (section `search.keywords` ou `scoring.*`), commit + push.

Le prochain run utilisera les nouvelles regles.

---

## Modifier les destinataires email

Edite `config.json` section `email.to_addresses`. Tu peux mettre plusieurs adresses :

```json
"to_addresses": ["naji@neurones.ma", "commercial@neurones.ma"]
```

---

## Telecharger un DCE specifique

Quand tu vois un AO interessant dans l'email (par ex. ref `971226` org `p1v`) :

```powershell
cd C:\Users\NAJI\veille_ao
run_dce.bat 971226 p1v
```

Le ZIP est sauvegarde dans `C:\Users\NAJI\Documents\veille_ao\DCE\test\<ref>_<org>\`.

---

## Tester le pipeline en local sans pousser en Cosmos

Pratique pour debugger ou ajuster le scoring :

```powershell
python -m src.pipeline --dry-run
```

→ Scrape + scoring + log, mais pas de Cosmos ni email.

Pour tester l'email sans Cosmos :

```powershell
python -m src.pipeline --no-cosmos
```

---

## Structure des fichiers

```
neurones-veille-ao/
├── .github/workflows/
│   └── veille-ao.yml          # Cron GitHub Actions
├── src/
│   ├── search.py              # Scrape + parsing HTML
│   ├── score.py               # Scoring (positifs/negatifs/combos)
│   ├── cosmos_client.py       # Wrapper Cosmos avec dedup
│   ├── send_email.py          # Resend + template HTML
│   ├── pipeline.py            # Orchestrator (entry point)
│   └── dce_download.py        # DL DCE manuel (local only)
├── config.json                # TOUTE la configuration editable
├── requirements.txt           # Deps Python
├── run_search.bat             # Test pipeline local
├── run_dce.bat                # DL DCE local
├── .gitignore
└── README.md
```

---

## Cosmos DB - schema des documents

Container : `mp_veille_ao`, partition key : `/source`.

Chaque AO scrape devient un document :

```json
{
  "id": "veille_marchespublics_gov_ma_971226",
  "source": "marchespublics_gov_ma",
  "ref_consultation": "971226",
  "org_acronyme": "p1v",
  "type_procedure": "AOO",
  "categorie": "Travaux",
  "reference_ao": "04/2026/CBJ",
  "objet": "...",
  "acheteur": "...",
  "lieu_execution": "EL JADIDA",
  "date_publication": "15/04/2026",
  "date_limite": "25/05/2026",
  "heure_limite": "11:00",
  "score": 70,
  "matches_positifs": "eclairage public(+25), basse tension(+20), ...",
  "matches_negatifs": "",
  "lien_fiche": "https://...",
  "statut": "a_etudier",
  "decision_par": null,
  "decision_le": null,
  "notes": "",
  "marche_id_lie": null,
  "date_premiere_decouverte": "2026-05-02T07:00:00Z",
  "date_derniere_mise_a_jour": "2026-05-02T15:00:00Z"
}
```

Les **CHAMPS_VOLATILES** (score, objet, date_limite...) sont mis a jour a chaque scrape.

Les **CHAMPS_PRESERVES** (statut, decision, notes...) ne sont jamais ecrases. Quand tu changeras le statut a `go` ou `no_go` depuis MP Manager (futur onglet Veille AO), il sera preserve sur les re-scrapes.

---

## Roadmap

- [x] Pipeline scrape + scoring + Excel local (POC)
- [x] DL DCE manuel local
- [x] Cosmos DB integration
- [x] Resend email HTML
- [x] GitHub Actions cron
- [ ] Onglet "Veille AO" dans MP Manager v12 (decision go/no-go web)
- [ ] Verification domaine `neurones.ma` chez Resend (envoi from `veille-ao@neurones.ma`)
- [ ] Sources additionnelles : ONEE, OCP, ADM, regies (RADEEMA, Lydec)
- [ ] Analyse predictive : suggestion go/no-go base sur historique de marches gagnes

---

## Troubleshooting

### Le run GitHub Actions echoue avec "COSMOS_KEY non defini"
→ Verifie Settings → Secrets : le secret doit s'appeler **exactement** `COSMOS_KEY` (majuscules).

### Le run Actions reussit mais aucun email
→ Verifie Settings → Secrets : `RESEND_API_KEY` doit etre defini.
→ Verifie le dossier Spam de naji@neurones.ma.
→ Regarde les logs du run dans Actions, cherche "Email NON envoye".

### Le scrape rapporte 0 AO
→ Le portail a peut-etre evolue (selecteurs PRADO changes). Regarde les logs Actions du run, cherche les warnings "select pageSize introuvable" ou "nb resultats inchange".
→ Tu peux relancer en local avec `--dry-run` pour debugger.

### DL DCE echoue
→ Regarde dans `C:\Users\NAJI\Documents\veille_ao\logs\` : screenshots et HTMLs sauvegardes pour chaque echec.
