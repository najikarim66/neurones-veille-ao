# neurones-veille-ao

## ⚙ RÈGLE D'AUTONOMIE (décision Karim, 26/10/2026 — règle de méthode, gravée hors gel de doctrine)

1. **Pas de demande de GO.** La session enchaîne seule : branche → gates → push → runs → fast-forward →
   smoke → relecture. Une op de données : dry-run, puis apply automatique si le dry-run correspond à
   l'attendu annoncé, avec archive + audit + relecture. Le compte rendu vient après, pas avant.
2. **Arrêt et attente de Karim UNIQUEMENT pour :**
   - le régime argent (paie, cumul, net convenu, coût MO, STC, déplacements, soldes de congés,
     clôture) : mise en prod d'un changement de calcul ;
   - toute suppression de données de prod sans archive, ou irréversible ;
   - secrets, identités et sécurité d'infrastructure (rotation de secret, httpsOnly, sauvegarde
     Cosmos, rôles Entra, pare-feu) ;
   - tout envoi vers l'extérieur (mail, message, notification à des personnes autres que Karim,
     document au maître d'ouvrage) ;
   - un dry-run qui ne donne pas l'attendu, un run rouge inexpliqué, un conflit de propriété entre
     sessions ;
   - une décision métier écrite nulle part (règle, norme, droit d'accès nouveau).
   Dans ces cas : UNE question courte, fermée, la recommandation en premier (« Je fais X ; si non,
   dis Y »). Jamais deux questions, jamais une question dont la réponse est dans la consigne.
3. **Sans réponse sous 30 minutes** à une question hors de la liste du point 2 : la session prend sa
   recommandation et continue, et le note dans le rapport.
4. **Permissions Claude Code** : `.claude/settings.json` (commité, sans secret) porte la liste
   « allow » et la liste « deny » de cette règle ; ce qui n'est dans aucune des deux continue de
   demander. Limites de la syntaxe (préfixes) : `git reset --hard` est en « ask » pour toute branche
   (la branche main ne se distingue pas), `rm -rf` est refusé partout (un worktree se retire par
   `git worktree remove`), `gh api` ne peut pas exclure un `-X POST` placé après le chemin.
