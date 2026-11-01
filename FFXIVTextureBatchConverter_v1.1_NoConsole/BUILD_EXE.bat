@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo   FFXIV Texture Batch Converter - v1.2
echo   One-click EXE build
echo ================================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY=python"
    ) else (
        echo [ERROR] Python was not found.
        echo Install Python 3.10+ and enable Add Python to PATH.
        pause
        exit /b 1
    )
)

echo [1/4] Checking Python...
%PY% --version
if errorlevel 1 goto :fail

echo.
echo [2/4] Installing PyInstaller...
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail

echo.
echo [3/4] Preparing Microsoft DirectXTex texconv...
%PY% prepare_texconv.py
if errorlevel 1 goto :fail

echo.
echo [4/4] Building single-file EXE...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
%PY% -m PyInstaller --noconfirm --clean FFXIVTextureBatchConverter.spec
if errorlevel 1 goto :fail

if not exist "dist\FFXIVTextureBatchConverter.exe" (
    echo [ERROR] PyInstaller did not create the expected EXE.
    goto :fail
)

echo.
echo Renaming the final EXE...
%PY% rename_output.py
if errorlevel 1 goto :fail

echo.
echo ================================================
echo   BUILD SUCCESS
echo ================================================
echo.
echo The final EXE is inside the dist folder.
echo.
pause
exit /b 0

:fail
echo.
echo ================================================
echo   BUILD FAILED
echo ================================================
echo Check the error messages above.
echo ================================================
pause
exit /b 1
