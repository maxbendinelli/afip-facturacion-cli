@echo off
title ARCA / AFIP Facturador
echo ========================================================
echo   Iniciando Interfaz Grafica ARCA / AFIP...
echo ========================================================
wsl.exe -d Ubuntu-22.04 -e bash -c "cd /home/max/afip && python3 run_gui.py"
pause
