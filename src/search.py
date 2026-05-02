"""
Scrape de marchespublics.gov.ma : recherche par mots-cles + parsing des resultats.

Pas de scoring ici (c'est dans score.py).
Pas de DCE download (c'est dans dce_download.py).
"""
import re
import urllib.parse
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
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


def parse_resultats(html: str) -> list:
    """Parse le HTML de la page resultats et retourne la liste des AOs."""
    soup = BeautifulSoup(html, "html.parser")
    resultats = []

    inputs_ref = soup.select('input[name$="$refCons"]')
    for inp_ref in inputs_ref:
        tr = inp_ref.find_parent("tr")
        if tr is None:
            continue

        ao = {
            "ref_consultation": "",
            "org_acronyme": "",
            "type_procedure": "",
            "categorie": "",
            "date_publication": "",
            "reference_ao": "",
            "objet": "",
            "acheteur": "",
            "lieu_execution": "",
            "date_limite": "",
            "heure_limite": "",
        }

        try:
            ao["ref_consultation"] = inp_ref.get("value", "").strip()
            inp_org = tr.select_one('input[name$="$orgCons"]')
            ao["org_acronyme"] = inp_org.get("value", "").strip() if inp_org else ""
        except Exception:
            pass

        try:
            td_ref = tr.select_one('td[headers="cons_ref"]')
            if td_ref:
                first_div = td_ref.select_one("div.line-info-bulle")
                if first_div:
                    ao["type_procedure"] = first_div.get_text(" ", strip=True).split("...")[0].strip()
                cat_div = td_ref.select_one('[id$="panelBlocCategorie"]')
                if cat_div:
                    ao["categorie"] = cat_div.get_text(strip=True)
                m = re.search(r"(\d{2}/\d{2}/\d{4})", td_ref.get_text())
                if m:
                    ao["date_publication"] = m.group(1)
        except Exception:
            pass

        try:
            td_int = tr.select_one('td[headers="cons_intitule"]')
            if td_int:
                ref_span = td_int.select_one("span.ref")
                if ref_span:
                    ao["reference_ao"] = ref_span.get_text(strip=True)
                objet_bulle = td_int.select_one('[id$="infosBullesObjet"] div')
                if objet_bulle:
                    ao["objet"] = objet_bulle.get_text(" ", strip=True)
                else:
                    obj_div = td_int.select_one('[id$="panelBlocObjet"]')
                    if obj_div:
                        txt = obj_div.get_text(" ", strip=True)
                        txt = re.sub(r"^Objet\s*:\s*", "", txt)
                        txt = re.sub(r"\.{3,}\s*$", "", txt).strip()
                        ao["objet"] = txt
                ach_div = td_int.select_one('[id$="panelBlocDenomination"]')
                if ach_div:
                    txt = ach_div.get_text(" ", strip=True)
                    txt = re.sub(r"^Acheteur public\s*:\s*", "", txt)
                    ao["acheteur"] = txt
        except Exception:
            pass

        try:
            td_lieu = tr.select_one('td[headers="cons_lieuExe"]')
            if td_lieu:
                lieu_div = td_lieu.select_one('[id$="panelBlocLieuxExec"]')
                if lieu_div:
                    txt = lieu_div.get_text(" ", strip=True)
                    txt = re.sub(r"\s+", " ", txt).strip()
                    ao["lieu_execution"] = txt
        except Exception:
            pass

        try:
            td_end = tr.select_one('td[headers="cons_dateEnd"]')
            if td_end:
                txt = td_end.get_text(" ", strip=True)
                m = re.search(r"(\d{2}/\d{2}/\d{4}).*?(\d{2}:\d{2})", txt)
                if m:
                    ao["date_limite"] = m.group(1)
                    ao["heure_limite"] = m.group(2)
                else:
                    m2 = re.search(r"(\d{2}/\d{2}/\d{4})", txt)
                    if m2:
                        ao["date_limite"] = m2.group(1)
        except Exception:
            pass

        ao["lien_fiche"] = construire_url_fiche(ao["ref_consultation"], ao["org_acronyme"])

        if ao["ref_consultation"]:
            resultats.append(ao)

    return resultats


def scraper_aos(keyword: str, page_size: int, playwright_cfg: dict) -> list:
    """
    Lance la recherche, set pageSize, parse, retourne la liste des AOs.

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
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector('input[name$="$refCons"]', state="attached", timeout=20000)
            log("STEP1", "Page resultats chargee")

            log("STEP2", f"Set pageSize={page_size} (postback PRADO)...")
            nb_avant = page.locator('input[name$="$refCons"]').count()
            log("STEP2", f"  Resultats avant changement : {nb_avant}")

            try:
                page.wait_for_selector('select[name$="$listePageSizeBottom"]', timeout=5000)
            except PWTimeout:
                log("STEP2", "  WARN: select pageSize introuvable, on garde pageSize defaut")
            else:
                try:
                    page.select_option('select[name$="$listePageSizeBottom"]', value=str(page_size))
                    try:
                        page.wait_for_function(
                            """(prev) => {
                                const inputs = document.querySelectorAll('input[name$="$refCons"]');
                                return inputs.length !== prev;
                            }""",
                            arg=nb_avant,
                            timeout=30000,
                        )
                        log("STEP2", "  Postback PRADO detecte (DOM mis a jour)")
                    except PWTimeout:
                        log("STEP2", "  WARN: nb resultats inchange apres select_option")
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception as e:
                    log("STEP2", f"  WARN: {type(e).__name__}: {e}")
                    page.wait_for_timeout(3000)

            page.wait_for_selector('input[name$="$refCons"]', state="attached", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=20000)
            nb = page.locator('input[name$="$refCons"]').count()
            log("STEP2", f"Tableau elargi pret ({nb} resultats detectes)")

            html = page.content()
            log("STEP3", f"HTML recupere : {len(html):,} chars")

            resultats = parse_resultats(html)
            log("STEP3", f"Parsing : {len(resultats)} AO extraits")

            return resultats

        finally:
            context.close()
            browser.close()
