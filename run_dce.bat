@echo off
chcp 65001 >nul
title Veille AO - DCE Manuel

if "%~2"=="" (
    echo Usage: run_dce.bat ^<refConsultation^> ^<orgAcronyme^>
    echo Exemple: run_dce.bat 994600 q9t
    echo.
    echo Ces 2 valeurs s'extraient des emails de veille ou de la fiche AO du portail :
    echo https://www.marchespublics.gov.ma/index.php?page=...^&refConsultation=XXXX^&orgAcronyme=YYY
    pause
    exit /b 1
)

echo ============================================================
echo   VEILLE AO - TELECHARGEMENT DCE MANUEL
echo ============================================================
echo   refConsultation : %1
echo   orgAcronyme     : %2
echo.

python -m src.dce_download %1 %2

echo.
echo ============================================================
echo   FIN
echo ============================================================
pause
