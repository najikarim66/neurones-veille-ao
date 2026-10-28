"""
Scrape de marchespublics.gov.ma : recherche par mots-cles + parsing des resultats.

Pas de scoring ici (c'est dans score.py).
Pas de DCE download (c'est dans dce_download.py).
"""
import re
import urllib.parse
from datetime import datetime

import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PlaywrightError
from bs4 import BeautifulSoup

BASE_URL = "https://www.marchespublics.gov.ma"


def log(step, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{step}] {msg}", flush=True)


def construire_url_recherche(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return (
        f"{BASE_URL}/index.php?page=entreprise.EntrepriseAdvancedSearch"
        f"&searchAnnCons&keyWord={encoded}"
    )


def construire_url_fiche(ref_cons: str, org: str) -> str:
    return (
        f"{BASE_URL}/index.php?page=entreprise.EntrepriseDetailsConsultation"
        f"&refConsultation={ref_cons}&orgAcronyme={org}"
    )


# Mise en page du portail depuis sa reouverture (constatee le 28/10/2026) : une CARTE
# par consultation (div.generalBox), plus de tableau ni de champs caches $refCons.
# Les identifiants (refConsultation, orgAcronyme) se lisent sur le lien de la fiche.
# La categorie et la date de publication ne figurent plus sur la carte : la categorie
# est relue par trois recherches filtrees (voir scraper_aos), la date de publication
# n'est plus lue. Une cle absente n'ecrase pas la valeur deja connue en Cosmos.

SEL_CARTE = "div.generalBox"
SEL_NOMBRE = "#ctl0_CONTENU_PAGE_resultSearch_nombreElement"
SEL_NUM_PAGE = "#ctl0_CONTENU_PAGE_resultSearch_numPageTop"
SEL_NB_PAGES = "#ctl0_CONTENU_PAGE_resultSearch_nombrePageTop"
SEL_PAGE_SIZE = 'select[name$="$listePageSizeTop"]'
SEL_FORM_MOTS = "#ctl0_CONTENU_PAGE_AdvancedSearch_keywordSearch"
SEL_FORM_CATEGORIE = 'select[name$="AdvancedSearch$categorie"]'
SEL_FORM_LANCER = "#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche"

CATEGORIES = {"1": "Travaux", "2": "Fournitures", "3": "Services"}

MOIS = {
    "jan": 1, "janv": 1, "feb": 2, "fev": 2, "fevr": 2, "mar": 3, "mars": 3, "apr": 4, "avr": 4,
    "may": 5, "mai": 5, "jun": 6, "juin": 6, "jul": 7, "juil": 7, "aug": 8, "aou": 8, "aout": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _sans_accents(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def date_carte(texte: str) -> str:
    """Pur. 'Mar 08 Dec 2026' -> '08/12/2026' ; accepte aussi dd/mm/yyyy. '' si illisible."""
    t = " ".join((texte or "").split())
    m = re.search(r"(\d{2}/\d{2}/\d{4})", t)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})\s+([A-Za-z\u00c0-\u017f]+)\.?\s+(\d{4})", t)
    if not m:
        return ""
    mois = MOIS.get(_sans_accents(m.group(2)).lower().rstrip("."))
    if not mois:
        return ""
    return f"{int(m.group(1)):02d}/{mois:02d}/{m.group(3)}"


def _texte(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el is not None else ""


def parse_resultats(html: str) -> list:
    """Pur. Parse une page de resultats (cartes) et retourne la liste des AO."""
    soup = BeautifulSoup(html, "html.parser")
    resultats = []
    for carte in soup.select(SEL_CARTE):
        lien = carte.select_one('a[href*="EntrepriseDetailsConsultation"][href*="refConsultation="]')
        if lien is None:
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(lien.get("href", "")).query)
        ref_cons = (q.get("refConsultation") or [""])[0].strip()
        org = (q.get("orgAcronyme") or [""])[0].strip()
        if not ref_cons:
            continue

        ao = {"ref_consultation": ref_cons, "org_acronyme": org}
        ao["type_procedure"] = _texte(carte.select_one("span.verticalText"))
        ao["reference_ao"] = _texte(carte.select_one('[id$="_referencem"]'))
        ao["objet"] = re.sub(r"^Objet\s*:\s*", "", _texte(carte.select_one("div.p-objet")), flags=re.I)
        ach = carte.select_one("div.title .a-card") or carte.select_one("div.title")
        ao["acheteur"] = re.sub(r"^Acheteur public\s*:\s*", "", _texte(ach), flags=re.I)

        estim = _texte(carte.select_one("span.estim-mad"))
        if estim:
            ao["estimation_ttc"] = estim

        lieu = ""
        lieu_bloc = carte.select_one('[id$="_panelBlocLieuxExec"]')
        if lieu_bloc is not None:
            bulle = lieu_bloc.select_one('div.info-bulle[id$="infosLieuExecution"] div')
            lieu = _texte(bulle) or re.sub(r"\s*\.\.\.\s*$", "", _texte(lieu_bloc.select_one("strong")))
        ao["lieu_execution"] = lieu

        ao["date_limite"], ao["heure_limite"] = "", ""
        gauche = carte.select_one("div.leftColumn")
        if gauche is not None:
            for bloc in gauche.select("div.limita"):
                t = _texte(bloc)
                d = date_carte(t)
                h = re.search(r"\b(\d{2}:\d{2})\b", t)
                if d and not ao["date_limite"]:
                    ao["date_limite"] = d
                if h and not ao["heure_limite"]:
                    ao["heure_limite"] = h.group(1)

        ao["lien_fiche"] = construire_url_fiche(ref_cons, org)
        resultats.append(ao)
    return resultats


def attribuer_categories(aos: list, refs_par_categorie: dict) -> dict:
    """Pur. Pose ao['categorie'] d'apres {libelle: set(ref_consultation)}.
    Un AO present dans plusieurs categories garde la premiere dans l'ordre Travaux,
    Fournitures, Services et est compte en 'multiples'.
    Un AO sans categorie n'a PAS de cle 'categorie' (la valeur Cosmos deja connue est gardee).
    Retourne le bilan {'avec': n, 'sans': [refs], 'multiples': [refs]}."""
    ordre = [c for c in ("Travaux", "Fournitures", "Services") if c in refs_par_categorie]
    bilan = {"avec": 0, "sans": [], "multiples": []}
    for ao in aos:
        ref = ao["ref_consultation"]
        trouvees = [c for c in ordre if ref in refs_par_categorie[c]]
        if trouvees:
            ao["categorie"] = trouvees[0]
            bilan["avec"] += 1
            if len(trouvees) > 1:
                bilan["multiples"].append(ref)
        else:
            ao.pop("categorie", None)
            bilan["sans"].append(ref)
    return bilan


# Retry de l'ouverture de la page de recherche (echecs transitoires du portail :
# net::ERR_CONNECTION_RESET, timeout). Meme politique que le DCE (d696290).
SEARCH_RETRY_ATTEMPTS = 3
SEARCH_RETRY_DELAYS = [8, 15]  # secondes de backoff entre tentatives


class PortailIndisponible(Exception):
    """Le portail repond mais ne sert pas la recherche (HTTP 5xx ou page de maintenance).
    Cause NOMMEE : ce n'est ni un bug ni un timeout anonyme."""


MARQUEURS_INDISPONIBLE = (
    "temporairement indisponible",
    "temporairement suspendu",
    "site indisponible",
    "service unavailable",
    "maintenance en cours",
)


def detecter_indisponibilite(status, texte_page: str):
    """Pur. Retourne le message nomme si le portail est indisponible, sinon None.
    status : code HTTP de la reponse du goto (None si inconnu) ; texte_page : texte visible."""
    texte = " ".join((texte_page or "").split())
    bas = texte.lower()
    marqueur = next((m for m in MARQUEURS_INDISPONIBLE if m in bas), None)
    if (status is not None and status >= 500) or marqueur:
        http = f"HTTP {status}" if status is not None else "HTTP inconnu"
        extrait = texte[:400] if texte else "page sans texte"
        return f"portail marchespublics.gov.ma indisponible ({http}) : {extrait}"
    return None


def goto_avec_retry(page, url: str, attempts: int = SEARCH_RETRY_ATTEMPTS,
                    delays=SEARCH_RETRY_DELAYS, sleep=time.sleep):
    """page.goto(url) rejoue jusqu'a `attempts` fois sur PWTimeout / PlaywrightError
    (erreurs reseau du portail). Toute autre exception propage sans retry.
    Aucun side-effect avant : le retry est sans risque de doublon."""
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            return page.goto(url, wait_until="domcontentloaded")
        except (PWTimeout, PlaywrightError) as e:
            last_err = e
            log("RETRY", f"tentative {attempt}/{attempts} echouee : {type(e).__name__}: {str(e).splitlines()[0]}")
            if attempt < attempts:
                delay = delays[min(attempt - 1, len(delays) - 1)]
                log("RETRY", f"  nouvelle tentative dans {delay}s")
                sleep(delay)
    log("RETRY", f"echec definitif apres {attempts} tentatives")
    raise last_err


def _texte_visible(page) -> str:
    try:
        return page.inner_text("body", timeout=5000)
    except Exception:
        return ""


def _attendre_resultats(page, status):
    """Attend le compteur de resultats ; nomme l'indisponibilite du portail sinon."""
    try:
        page.wait_for_selector(SEL_NOMBRE, state="attached", timeout=30000)
    except PWTimeout:
        motif = detecter_indisponibilite(status, _texte_visible(page))
        if motif:
            raise PortailIndisponible(motif) from None
        raise


def _repos(page, timeout_ms: int = 10000):
    """Le portail garde des requetes ouvertes : 'networkidle' peut ne jamais venir. Non bloquant."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PWTimeout:
        pass


def _attendre_cartes(page, attendu: int, num: str, minimum: int = 0, ref_avant: str = None,
                     delai_s: float = 120, pas_s: float = 2.0, stable_n: int = 4):
    """Attend la fin du postback PRADO de la page `num` : sortie des que `attendu` cartes
    sont affichees, ou quand le nombre de cartes (> minimum) est stable sur `stable_n`
    lectures avec le bon numero de page. Le portail annonce parfois quelques AO de plus
    qu'il n'en affiche : l'ecart se voit dans le bilan « non lu(s) », il ne bloque pas."""
    fin = time.monotonic() + delai_s
    dernier, stables = -1, 0
    while time.monotonic() < fin:
        try:
            n, v, r = page.evaluate(
                "([sc, sp, sr]) => [document.querySelectorAll(sc).length, "
                "(document.querySelector(sp) || {}).value || '', "
                "((document.querySelector(sr) || {}).innerText || '').trim()]",
                [SEL_CARTE, SEL_NUM_PAGE, '[id$="_referencem"]'])
        except PlaywrightError:
            n, v, r = -1, "", ""  # navigation PRADO en cours
        if ref_avant is not None and r == ref_avant:
            n = -1  # la page affichee est encore l'ancienne
        if v == num and n == attendu:
            break
        if v == num and n > minimum and n == dernier:
            stables += 1
            if stables >= stable_n:
                break
        else:
            stables = 0
        dernier = n
        page.wait_for_timeout(int(pas_s * 1000))
    else:
        log("PAGE", f"  WARN page {num} : delai depasse, {page.locator(SEL_CARTE).count()} carte(s) affichee(s)")
    _repos(page)


def _lire_toutes_les_pages(page, page_size: int, etiquette: str) -> tuple:
    """Page de resultats deja chargee -> (aos de TOUTES les pages, nombre annonce)."""
    annonce = int(re.sub(r"\D", "", page.inner_text(SEL_NOMBRE)) or 0)
    if annonce == 0:
        log(etiquette, "0 resultat annonce")
        return [], 0
    attendu_p1 = min(annonce, page_size)
    avant = page.locator(SEL_CARTE).count()
    if annonce > avant:
        _repos(page)
        page.select_option(SEL_PAGE_SIZE, value=str(page_size))
        _attendre_cartes(page, attendu_p1, "1", minimum=avant)
    nb_pages = -(-annonce // page_size)
    aos, vus = [], set()
    for num in range(1, nb_pages + 1):
        if num > 1:
            ref_avant = page.locator('[id$="_referencem"]').first.inner_text().strip()
            page.fill(SEL_NUM_PAGE, str(num))
            page.press(SEL_NUM_PAGE, "Enter")
            _attendre_cartes(page, min(page_size, annonce - (num - 1) * page_size), str(num), ref_avant=ref_avant)
        lus = parse_resultats(page.content())
        nouveaux = [a for a in lus if a["ref_consultation"] not in vus]
        vus.update(a["ref_consultation"] for a in nouveaux)
        aos.extend(nouveaux)
        log(etiquette, f"  page {num}/{nb_pages} : {len(lus)} carte(s), {len(nouveaux)} nouvelle(s)")
    log(etiquette, f"{annonce} annonce(s) · {len(aos)} lu(s) · {annonce - len(aos)} non lu(s)")
    return aos, annonce


def _recherche_formulaire(page, keyword: str, code_categorie: str):
    goto_avec_retry(page, f"{BASE_URL}/index.php?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons")
    page.fill(SEL_FORM_MOTS, keyword)
    page.select_option(SEL_FORM_CATEGORIE, code_categorie)
    page.click(SEL_FORM_LANCER)
    page.wait_for_selector(SEL_NOMBRE, state="attached", timeout=60000)
    _repos(page)


def scraper_aos(keyword: str, page_size: int, playwright_cfg: dict) -> list:
    """
    Recherche par mots-cles, lit TOUTES les pages de resultats (cartes), puis relit la
    categorie par trois recherches filtrees (Travaux, Fournitures, Services).

    Aucun side-effect (pas de fichiers ecrits, pas de Cosmos, pas d'email).
    """
    url = construire_url_recherche(keyword)

    with sync_playwright() as pw:
        log("INIT", f"Lancement Chromium (headless={playwright_cfg['headless']})")
        browser = pw.chromium.launch(
            headless=playwright_cfg["headless"],
            slow_mo=playwright_cfg.get("slow_mo_ms", 0),
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/143.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(playwright_cfg.get("timeout_default_ms", 30000))

        try:
            log("STEP1", f"GET {url[:120]}...")
            resp = goto_avec_retry(page, url)
            status = resp.status if resp is not None else None
            motif = detecter_indisponibilite(status, _texte_visible(page))
            if motif:
                raise PortailIndisponible(motif)
            _attendre_resultats(page, status)
            log("STEP1", f"Page resultats chargee (HTTP {status})")

            log("STEP2", f"Lecture de toutes les pages (taille {page_size})")
            resultats, _ = _lire_toutes_les_pages(page, page_size, "STEP2")

            log("STEP3", "Categories : trois recherches filtrees")
            refs_par_categorie = {}
            for code, libelle in CATEGORIES.items():
                try:
                    _recherche_formulaire(page, keyword, code)
                    aos_cat, _ = _lire_toutes_les_pages(page, page_size, f"CAT-{libelle}")
                    refs_par_categorie[libelle] = {a["ref_consultation"] for a in aos_cat}
                except Exception as e:
                    log("STEP3", f"  WARN categorie {libelle} non relue : {type(e).__name__}: {str(e).splitlines()[0]}")
            bilan = attribuer_categories(resultats, refs_par_categorie)
            log("STEP3", f"{len(resultats)} AO lus · {bilan['avec']} avec categorie · "
                         f"{len(bilan['sans'])} sans categorie (valeur Cosmos conservee)"
                         + (f" · {len(bilan['multiples'])} dans plusieurs categories" if bilan["multiples"] else ""))
            manquantes = [c for c in CATEGORIES.values() if c not in refs_par_categorie]
            if manquantes:
                log("STEP3", f"  categories non relues : {', '.join(manquantes)}")

            return resultats

        finally:
            context.close()
            browser.close()
