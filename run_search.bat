@echo off
chcp 65001 >nul
title Veille AO - Test Local

echo ============================================================
echo   VEILLE AO - TEST LOCAL (mode complet : Cosmos + Email)
echo ============================================================
echo.
echo   ATTENTION : ce script POUSSE en Cosmos et ENVOIE un email reel.
echo   Si tu veux juste scraper sans cote, utilise --dry-run.
echo.
pause

if not defined COSMOS_KEY (
    echo ERREUR: variable d'environnement COSMOS_KEY non definie
    echo Definir avec : [System.Environment]::SetEnvironmentVariable^("COSMOS_KEY", "...", "User"^)
    pause
    exit /b 1
)
if not defined RESEND_API_KEY (
    echo ERREUR: variable d'environnement RESEND_API_KEY non definie
    pause
    exit /b 1
)

python -m src.pipeline

echo.
echo ============================================================
echo   FIN
echo ============================================================
pause
