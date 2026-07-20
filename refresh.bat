@echo off
chcp 65001 >nul
title Eco Go Dashboard - Refresh

cd /d "%~dp0"

echo.
echo  ===============================================================
echo   ECO GO DASHBOARD - Refresh de datos
echo  ===============================================================
echo.

REM Buscar Python (primero "python", despues "py")
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYCMD=python
    goto :run
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYCMD=py
    goto :run
)

echo  ERROR: No se encontro Python en el sistema.
echo  Instalalo desde https://www.python.org/downloads/
echo  (durante la instalacion marca "Add Python to PATH")
echo.
pause
exit /b 1

:run
echo  Usando Python: %PYCMD%
echo.

REM Asegurar que openpyxl este instalado
%PYCMD% -c "import openpyxl" 2>nul
if %errorlevel% neq 0 (
    echo  Instalando dependencia 'openpyxl'...
    %PYCMD% -m pip install openpyxl --quiet
    if %errorlevel% neq 0 (
        echo  ERROR: No se pudo instalar openpyxl.
        pause
        exit /b 1
    )
)

REM Ejecutar el script
%PYCMD% "%~dp0refresh.py"
set EXITCODE=%errorlevel%

echo.
echo  ===============================================================
if %EXITCODE% equ 0 (
    echo   LISTO. Recarga el dashboard en el navegador.
) else (
    echo   Hubo problemas. Revisa los mensajes de arriba.
)
echo  ===============================================================
echo.
pause
exit /b %EXITCODE%
