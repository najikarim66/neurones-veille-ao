"""
Scoring d'un AO selon mots-cles, categorie, combos.

Le scoring est entierement pilote par config.json (section "scoring") :
- positifs : termes a points positifs
- negatifs : termes a points negatifs
- combos : bonus si terme + categorie compatibles
- bonus_categorie : bonus selon Travaux/Services/Fournitures/Etudes
- acronymes_word_boundary : termes courts matches en mot entier (\\bX\\b)
- seuil_inclusion : score minimal pour qu'un AO soit considere

Score cap : 0-100.
"""
import re
import unicodedata


def normalize(text: str) -> str:
    """Minuscules + sans accents + espaces normalises."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text)
    return text


def match_terme(haystack: str, needle: str, acronymes_wb: set) -> bool:
    """Match d'un terme avec word boundary pour acronymes courts."""
    if needle in acronymes_wb or (len(needle) <= 4 and " " not in needle):
        pattern = r"\b" + re.escape(needle) + r"\b"
        return re.search(pattern, haystack) is not None
    return needle in haystack


def calculer_score(ao: dict, scoring_config: dict) -> dict:
    """Retourne {score, matches_positifs, matches_negatifs}."""
    objet_norm = normalize(ao.get("objet", ""))
    categorie_norm = normalize(ao.get("categorie", ""))

    acronymes_wb = set(scoring_config.get("acronymes_word_boundary", []))
    positifs = scoring_config.get("positifs", {})
    negatifs = scoring_config.get("negatifs", {})
    combos = scoring_config.get("combos", [])
    bonus_cat = scoring_config.get("bonus_categorie", {})

    score = 0
    matches_pos = []
    matches_neg = []

    # Termes positifs
    for terme, points in positifs.items():
        if match_terme(objet_norm, terme, acronymes_wb):
            score += points
            matches_pos.append(f"{terme}(+{points})")

    # Termes negatifs (substring direct, on veut max de detection)
    for terme, points in negatifs.items():
        if terme in objet_norm:
            score += points  # negatif
            matches_neg.append(f"{terme}({points})")

    # Bonus categorie
    for cat_key, bonus in bonus_cat.items():
        if cat_key in categorie_norm:
            score += bonus
            break

    # Bonus combos
    for combo in combos:
        terme = combo.get("terme", "")
        cats = set(combo.get("categories", []))
        bonus = combo.get("bonus", 0)
        if not terme or not cats:
            continue
        if match_terme(objet_norm, terme, acronymes_wb):
            for cat_key in cats:
                if cat_key in categorie_norm:
                    score += bonus
                    matches_pos.append(f"combo[{terme}+{cat_key}](+{bonus})")
                    break

    score = max(0, min(100, score))

    return {
        "score": score,
        "matches_positifs": ", ".join(matches_pos),
        "matches_negatifs": ", ".join(matches_neg),
    }


def filtrer_par_seuil(resultats: list, seuil: int) -> list:
    """Garde uniquement les AO dont le score est >= seuil."""
    return [r for r in resultats if r.get("score", 0) >= seuil]
