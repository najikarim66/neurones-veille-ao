"""
Wrapper Cosmos DB pour la veille AO.

Container : mp_veille_ao
Partition key : /source

Schema d'un document :
{
    "id": "veille_<source>_<ref_consultation>",   # cle deterministe
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
    "matches_positifs": "...",
    "matches_negatifs": "",
    "lien_fiche": "https://...",

    "statut": "a_etudier",        # a_etudier | en_analyse | go | no_go | soumissionne | gagne
    "decision_par": null,
    "decision_le": null,
    "notes": "",
    "marche_id_lie": null,

    "date_premiere_decouverte": "2026-05-02T07:00:00Z",
    "date_derniere_mise_a_jour": "2026-05-02T07:00:00Z"
}
"""
import os
from datetime import datetime, timezone

from azure.cosmos import CosmosClient, exceptions


# Champs qu'on UPDATE si l'AO est deja connu (le portail peut corriger l'objet,
# le score peut evoluer si scoring change, etc.)
CHAMPS_VOLATILES = {
    "score",
    "matches_positifs",
    "matches_negatifs",
    "objet",
    "categorie",
    "type_procedure",
    "reference_ao",
    "acheteur",
    "lieu_execution",
    "date_publication",
    "date_limite",
    "heure_limite",
    "lien_fiche",
}

# Champs PRESERVES absolument (ne jamais ecraser sur un re-scrape)
CHAMPS_PRESERVES = {
    "statut",
    "decision_par",
    "decision_le",
    "notes",
    "marche_id_lie",
    "date_premiere_decouverte",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CosmosVeilleClient:
    def __init__(self, endpoint: str, database: str, container: str, source_id: str):
        key = os.environ.get("COSMOS_KEY")
        if not key:
            raise RuntimeError(
                "Variable d'environnement COSMOS_KEY non definie. "
                "Sur GitHub Actions : ajouter dans repo > Settings > Secrets. "
                "En local Windows : "
                "[System.Environment]::SetEnvironmentVariable('COSMOS_KEY', '...', 'User')"
            )
        self.client = CosmosClient(endpoint, credential=key)
        self.db = self.client.get_database_client(database)
        self.container = self.db.get_container_client(container)
        self.source_id = source_id

    def _doc_id(self, ref_consultation: str) -> str:
        return f"veille_{self.source_id}_{ref_consultation}"

    def upsert_ao(self, ao: dict) -> dict:
        """
        Upsert un AO avec dedup intelligente.

        Retourne {'action': 'created'|'updated', 'doc': <doc final>}.

        Si l'AO existe deja :
        - update CHAMPS_VOLATILES (score, objet, date_limite, etc.)
        - preserve CHAMPS_PRESERVES (statut, decision, notes...)

        Si nouveau :
        - insert avec statut='a_etudier' et date_premiere_decouverte=now
        """
        ref = ao.get("ref_consultation")
        if not ref:
            raise ValueError("AO sans ref_consultation, impossible de upsert")

        doc_id = self._doc_id(ref)
        now = _utcnow_iso()

        try:
            existing = self.container.read_item(item=doc_id, partition_key=self.source_id)
            # Existe : merge
            for champ in CHAMPS_VOLATILES:
                if champ in ao:
                    existing[champ] = ao[champ]
            existing["date_derniere_mise_a_jour"] = now
            # On reset les champs preserves seulement s'ils manquent (defensive)
            existing.setdefault("statut", "a_etudier")
            existing.setdefault("decision_par", None)
            existing.setdefault("decision_le", None)
            existing.setdefault("notes", "")
            existing.setdefault("marche_id_lie", None)
            existing.setdefault("date_premiere_decouverte", now)

            self.container.replace_item(item=doc_id, body=existing)
            return {"action": "updated", "doc": existing}

        except exceptions.CosmosResourceNotFoundError:
            # Nouveau
            doc = {
                "id": doc_id,
                "source": self.source_id,
                "ref_consultation": ref,
                "org_acronyme": ao.get("org_acronyme", ""),
                "type_procedure": ao.get("type_procedure", ""),
                "categorie": ao.get("categorie", ""),
                "reference_ao": ao.get("reference_ao", ""),
                "objet": ao.get("objet", ""),
                "acheteur": ao.get("acheteur", ""),
                "lieu_execution": ao.get("lieu_execution", ""),
                "date_publication": ao.get("date_publication", ""),
                "date_limite": ao.get("date_limite", ""),
                "heure_limite": ao.get("heure_limite", ""),
                "score": ao.get("score", 0),
                "matches_positifs": ao.get("matches_positifs", ""),
                "matches_negatifs": ao.get("matches_negatifs", ""),
                "lien_fiche": ao.get("lien_fiche", ""),
                "statut": "a_etudier",
                "decision_par": None,
                "decision_le": None,
                "notes": "",
                "marche_id_lie": None,
                "date_premiere_decouverte": now,
                "date_derniere_mise_a_jour": now,
            }
            self.container.create_item(body=doc)
            return {"action": "created", "doc": doc}

    def list_verts_actifs(self, score_min: int, deadline_jours_max: int) -> list:
        """
        Retourne les AO :
        - score >= score_min
        - statut = 'a_etudier'
        - date_limite dans le futur ET dans (now + deadline_jours_max)

        IMPORTANT : la date_limite Cosmos est au format "DD/MM/YYYY" (string),
        donc le filtre est fait cote Python apres recuperation.
        """
        query = (
            "SELECT * FROM c "
            "WHERE c.source = @src AND c.score >= @score AND c.statut = 'a_etudier'"
        )
        params = [
            {"name": "@src", "value": self.source_id},
            {"name": "@score", "value": score_min},
        ]
        results = list(self.container.query_items(
            query=query,
            parameters=params,
            partition_key=self.source_id,
        ))

        # Filtre par date_limite cote Python
        from datetime import date, timedelta
        today = date.today()
        deadline_max = today + timedelta(days=deadline_jours_max)

        actifs = []
        for r in results:
            dl_str = r.get("date_limite", "")
            try:
                d, m, y = dl_str.split("/")
                dl = date(int(y), int(m), int(d))
                if today <= dl <= deadline_max:
                    actifs.append(r)
            except Exception:
                continue

        actifs.sort(key=lambda x: x.get("score", 0), reverse=True)
        return actifs
