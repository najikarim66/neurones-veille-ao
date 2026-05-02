"""
Telechargement DCE manuel - usage LOCAL uniquement (pas dans GitHub Actions).

Utilise les selecteurs PRADO valides via les HARs et debug iteratif.
Cf. mp_v11 et la session de mise au point du 02/05/2026.

Usage :
  python -m src.dce_download <refConsultation> <orgAcronyme>

Exemple :
  python -m src.dce_download 994600 q9t
"""
import sys
import zipfile
import json
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://www.marchespublics.gov.ma"

SEL = {
    "nom":              '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$nom"]',
    "prenom":           '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$prenom"]',
    "email":            '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$email"]',
    "raison_sociale":   '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$raisonSocial"]',
    "ice":              '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$ICE"]',
    "pays":             '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$pays"]',
    "accepter":         '[name="ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$accepterConditions"]',
    "valider":          '[name="ctl0$CONTENU_PAGE$validateButton"]',
    "radio_maroc":      '#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_france',
    "radio_dl_complet": '#ctl0_CONTENU_PAGE_EntrepriseFormulaireDemande_choixTelechargement',
    "complete_dl":      'a[href*="EntrepriseDownloadDce_completeDownload"]',
}


def log(step, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{step}] {msg}", flush=True)


def telecharger_dce(ref: str, org: str, config: dict) -> Path:
    identite = config["dce_identite"]
    racine = Path(config["stockage_local"]["racine_dce"])
    debug_dir = Path(config["stockage_local"]["racine_logs"])
    pw_cfg = config["playwright"]

    dest_dir = racine / f"{ref}_{org}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    url_demande = (
        f"{BASE_URL}/index.php?page=entreprise.EntrepriseDemandeTelechargementDce"
        f"&refConsultation={ref}&orgAcronyme={org}"
    )

    def _save_debug(page, prefix: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            page.screenshot(path=str(debug_dir / f"dce_{prefix}_{ref}_{ts}.png"), full_page=True)
        except Exception:
            pass
        try:
            (debug_dir / f"dce_{prefix}_{ref}_{ts}.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass

    with sync_playwright() as pw:
        log("INIT", f"Lancement Chromium (headless={pw_cfg['headless']})")
        browser = pw.chromium.launch(
            headless=pw_cfg["headless"],
            slow_mo=pw_cfg.get("slow_mo_ms", 0),
        )
        context = browser.new_context(
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/143.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(pw_cfg.get("timeout_default_ms", 30000))

        try:
            log("STEP1", f"GET formulaire identite")
            page.goto(url_demande, wait_until="domcontentloaded")
            try:
                page.wait_for_selector(SEL["nom"], timeout=15000)
            except PWTimeout:
                _save_debug(page, "step1_no_form")
                raise RuntimeError("Page formulaire introuvable. Voir logs/dce_step1_*.")

            log("STEP2", "Remplissage formulaire identite")
            page.fill(SEL["nom"], identite["nom"])
            page.fill(SEL["prenom"], identite["prenom"])
            page.fill(SEL["email"], identite["email"])
            page.fill(SEL["raison_sociale"], identite["raison_sociale"])
            page.fill(SEL["ice"], identite["ice"])
            try:
                page.select_option(SEL["pays"], value=identite["pays_index"])
            except Exception:
                pass
            try:
                page.check(SEL["radio_maroc"], force=True)
            except Exception as e:
                log("STEP2", f"  WARN radio Maroc: {e}")
            try:
                page.check(SEL["radio_dl_complet"], force=True)
            except Exception as e:
                log("STEP2", f"  WARN radio DL complet: {e}")
            page.check(SEL["accepter"])

            log("STEP3", "Clic Valider")
            page.click(SEL["valider"])
            try:
                page.wait_for_selector(SEL["complete_dl"], timeout=15000)
            except PWTimeout:
                _save_debug(page, "step3_no_complete_btn")
                raise RuntimeError("Bouton 'Telecharger DCE' introuvable. Voir logs/dce_step3_*.")

            log("STEP4", "Clic 'Telecharger Dossier de consultation'")
            with page.expect_download(timeout=pw_cfg.get("timeout_download_ms", 90000)) as dl_info:
                page.click(SEL["complete_dl"])
            download = dl_info.value
            suggested = download.suggested_filename or f"DCE_{ref}.zip"
            local_path = dest_dir / suggested
            download.save_as(str(local_path))
            log("STEP4", f"DCE sauvegarde : {local_path}")

            log("STEP5", "Validation ZIP")
            size = local_path.stat().st_size
            if size == 0:
                raise RuntimeError("ZIP vide !")
            log("STEP5", f"Taille : {size:,} bytes")
            with zipfile.ZipFile(local_path) as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"ZIP corrompu : {bad}")
                nb = len(zf.namelist())
                log("STEP5", f"ZIP valide, {nb} fichier(s)")

            return local_path

        except Exception:
            try:
                _save_debug(page, "uncaught")
            except Exception:
                pass
            raise
        finally:
            context.close()
            browser.close()


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m src.dce_download <refConsultation> <orgAcronyme>")
        sys.exit(1)

    ref, org = sys.argv[1], sys.argv[2]

    config_path = Path("config.json")
    if not config_path.exists():
        print(f"config.json introuvable a {config_path.resolve()}")
        sys.exit(1)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    log("MAIN", f"DCE download ref={ref} org={org}")
    try:
        path = telecharger_dce(ref, org, config)
        log("MAIN", f"SUCCESS -> {path}")
        sys.exit(0)
    except Exception as e:
        log("MAIN", f"FAILURE -> {type(e).__name__}: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
