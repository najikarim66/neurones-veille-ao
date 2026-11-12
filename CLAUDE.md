# Repo : neurones-veille-ao (robot de veille des appels d'offres publics)

- Chemin sur le PC du DG : `C:\dev\neurones-veille-ao` — remote `origin`, branche `main`. Python 3 + Playwright (Chromium), sans front.
- Rôle : lire les consultations de marchespublics.gov.ma (postbacks PRADO, cartes `div.generalBox`), les scorer (`config.json` > scoring,
  seuil 35, VERT ≥ 60 / JAUNE 35–59), les dédupliquer dans Cosmos et envoyer la synthèse au DG. `src/` : `pipeline` (orchestration, 4 phases),
  `search` (portail), `score`, `cosmos_client`, `send_email` (Microsoft Graph), `alerte_veille` + `alerte_echec` (alertes d'exploitation),
  `dce_download` / `dce_to_blob` / `etude_tick` (DCE à la demande et étude d'AO), `purge`, `coffre_alerte`.

## Chaîne d'exploitation (heures exprimées en UTC — décision DG 11/11/2026, « Casablanca est à UTC »)
1. Tâche planifiée Windows « Veille AO - Trigger » sur le PC `neurones-maroc-pc1`, compte `naji`, lun–ven **08:00 et 14:00 UTC**.
   La tâche stocke le mot de passe de session : toute modification exige sa saisie par le DG dans l'invite Windows (sans elle, même en
   élévation, Windows répond « mot de passe incorrect »). Le mot de passe n'est jamais journalisé ni manipulé par une session.
2. `C:\actions-runner\trigger-veille.ps1` → `gh workflow run veille-ao.yml --ref main` (journal `C:\actions-runner\_trigger-veille.log`).
3. GitHub Actions « Veille AO » (`.github/workflows/veille-ao.yml`, `workflow_dispatch` seul — plus de cron GitHub, imprécis) sur le runner
   self-hosted `[self-hosted, maroc]`, venv `C:\actions-runner\veille-venv`, `timeout-minutes: 45` : gates unitaires → `python -m src.pipeline`
   → en cas d'échec, étape « Alerte DG — le passage a echoue ».
4. Cosmos `mp_veille_ao` (base `btp-pointage`, secrets GitHub `COSMOS_KEY`, `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET`).
5. Écran **Veille AO** de MP Manager (https://mp.neurones.ma, `GET /api/data/mp_veille_ao`) : libellés « 8h / 14h UTC » ; chaque AO
   y porte sa date et son heure limite. Le bouton « Relancer » de cet écran déclenche le même workflow.

## Commandes
- Passage à la main : `gh workflow run veille-ao.yml --ref main` puis `gh run list --workflow veille-ao.yml --limit 5` et
  `gh run watch <id> --exit-status`. Durée normale : 10 à 15 min (~30 s par page de 50).
- Journaux : `gh run view <id> --log | grep -E "\[(MAIN|PHASE|STEP2|PORTAIL|CAT-)"` (bilan « BILAN PIPELINE » en fin de log : AO scrapés,
  retenus, nouveautés, rappels) ; passage rouge : `gh run view <id> --log-failed`, **lire d'abord la ligne `[PORTAIL]`**. Captures et HTML des
  échecs portail : `C:\Users\NAJI\Documents\veille_ao\logs\`.
- En local (venv ci-dessus, secrets par variables d'environnement, jamais en ligne de commande) : `python -m src.pipeline --dry-run`
  (ni Cosmos ni mail), `--no-cosmos`, `--no-email`. Un passage local complet écrit en prod : réservé au rattrapage décidé.
- Tests : `python -m unittest discover -s test -t .` — 63 tests, sans réseau ni base (`test_pages_portail` joue un faux portail,
  `test_taille_page`, `test_alerte_veille`, `test_parse_cartes`, `test_search_retry`, `test_dce_*`, `test_etude_tick`, `test_purge`,
  `test_coffre_alerte`). Joués en CI avant chaque passage.

## Alertes d'exploitation (décision DG 10/11/2026 ; destinataire = DG, `config.json` > `email.to_addresses`)
- Passage en échec : étape `if: failure()` → `python -m src.alerte_echec --run-url <run>` → mail « [Veille AO] ECHEC du passage — <cause> »
  (cause écrite par le pipeline dans `veille-echec.txt`, gitignoré).
- Silence : si un passage ne crée aucun AO et que la dernière `date_premiere_decouverte` en Cosmos date de plus de 24 h ouvrées
  (lun–ven, `src/alerte_veille.heures_ouvrees`) → mail « [Veille AO] Aucun nouvel AO depuis 24 h ouvrees ».
- Ces mails automatiques vers le DG sont les seuls permis ; aucun mail automatique vers l'extérieur (voir règle d'autonomie §2).

## Panne du 09/11/2026 (diagnostic du 10/11, lecture seule maillon par maillon)
- Constat : 16 passages rouges muets, dernier document Cosmos du 02/11 16:41, écran MP figé.
- Cause 1 : portail en HTTP 503 (arrêt annoncé par la TGR) du **02/11 14:00 UTC au 10/11**. Cause 2, à la réouverture : le sélecteur
  « résultats par page » n'offre plus que 10/20/50 alors que le robot demandait 500 (`select_option` en délai). **Aucun secret en cause.**
- Correctif `fac99a3` : `choisir_taille_page` (plus grande taille offerte), `_ouvrir_page` (rejoue une page vide et la nomme dans le bilan
  au lieu de planter), alertes ci-dessus, gates unitaires en CI, timeout 45 min ; `download-dce.yml` réparé (fichier invalide depuis le
  01/11, bouton « Demander DCE » sans effet). Rattrapage du 10/11 : 732 AO lus, 55 retenus, 10 créés, 45 mis à jour.
- Horaire : passage du matin 06:00 → **08:00 UTC** le 11/11 (le portail n'est pas servi plus tôt).

## Livraison et interdits
- Branche par session → tests locaux → push → fast-forward `git push origin <branche>:main`. Aucun workflow ne tourne sur `push` :
  un changement de code se prouve par un passage manuel VERT après le fast-forward, puis contrôle sur l'écran MP (date et heure limite
  affichées). Commit par pathspec (`git commit --only <chemins>`). Fenêtre interdite : 23h15–23h45 heure du Maroc.
- Retrait d'un worktree : toujours `node C:/dev/btp-pointage/api/scripts/nettoyer-node-modules.js <worktree> --apply` puis
  `git worktree remove`, jamais à la main (arbitrage DG 12/11).
- Secrets : aucune rotation, aucun affichage, aucune copie ; un secret périmé se NOMME avec la marche à suivre, sans rien modifier.
  Pas de rôle Azure, aucun `az delete`. Aucun nom de personne dans les commits. Un test n'écrit jamais en production.
- Doctrine : ce dépôt ne porte pas de copie ; appliquer `C:\dev\mp-neurones\.claude\skills\doctrines-neurones\SKILL.md` (§1 rien ne se
  devine, §5 fraîcheur, §6 secrets, §12 tests sans écriture en prod, §13 pied de rapport sur tout compte rendu de lot).
- Extensions au niveau du projet (`.claude/settings.json` > `enabledPlugins`) : skill-creator, claude-md-management ; skill
  `.claude/skills/webapp-testing` (copie du dossier officiel anthropics/skills). security-guidance refusé le 12/11 ; aucune autre.

## ⚙ RÈGLE D'AUTONOMIE (décision DG, 26/10/2026 — règle de méthode, gravée hors gel de doctrine ; copie identique dans mp-neurones)

1. **Pas de demande de GO.** La session enchaîne seule : branche → gates → push → runs → fast-forward →
   smoke → relecture. Une op de données : dry-run, puis apply automatique si le dry-run correspond à
   l'attendu annoncé, avec archive + audit + relecture. Le compte rendu vient après, pas avant.
2. **Arrêt et attente du DG UNIQUEMENT pour :**
   - le régime argent (paie, cumul, net convenu, coût MO, STC, déplacements, soldes de congés,
     clôture) : mise en prod d'un changement de calcul ;
   - toute suppression de données de prod sans archive, ou irréversible ;
   - secrets, identités et sécurité d'infrastructure (rotation de secret, httpsOnly, sauvegarde
     Cosmos, rôles Entra, pare-feu) ;
   - tout envoi vers l'extérieur : clients, fournisseurs, maîtres d'ouvrage, toute personne autre que le DG
     (mail, message, notification, document). **Seuls sont permis sans question les mails automatiques
     d'exploitation adressés au DG** : échec d'un passage de la veille AO, aucun AO collecté pendant
     24 h ouvrées, échec d'un déploiement (arbitrage DG 12/11/2026). Aucun mail automatique vers l'extérieur ;
   - un dry-run qui ne donne pas l'attendu, un run rouge inexpliqué, un conflit de propriété entre
     sessions ;
   - une décision métier écrite nulle part (règle, norme, droit d'accès nouveau).
   Dans ces cas : UNE question courte, fermée, la recommandation en premier (« Je fais X ; si non,
   dis Y »). Jamais deux questions, jamais une question dont la réponse est dans la consigne.
3. **Sans réponse sous 30 minutes** à une question hors de la liste du point 2 : la session prend sa
   recommandation et continue, et le note dans le rapport.
4. **Permissions Claude Code** : `.claude/settings.json` (commité, sans secret) porte la liste « allow », la liste « deny » de cette règle
   et la clé `enabledPlugins` ; ce qui n'est dans aucune liste continue de demander. Limites de la syntaxe (préfixes) : `git reset --hard`
   est en « ask » pour toute branche (la branche main ne se distingue pas), `rm -rf` est refusé partout (un worktree se retire par
   nettoyer-node-modules puis `git worktree remove`, voir « Livraison »), `gh api` ne peut pas exclure un `-X POST` placé après le chemin.
