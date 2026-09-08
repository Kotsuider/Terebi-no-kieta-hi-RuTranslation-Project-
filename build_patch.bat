@echo off
chcp 65001 >nul
setlocal

echo ========================================
echo   ASB Import and Arc Packing Tool
echo ========================================

cd /d "%~dp0ScriptEditing"

if not exist "new_tv.xlsx" (
    echo [!] File new_tv.xlsx not found in ScriptEditing!
    pause
    exit /b 1
)

echo [*] Importing translation from new_tv.xlsx...
py -3.12 asb_tool.py import ./script ./new_tv.xlsx ./script_patched

if errorlevel 1 (
    echo [!] Error during script import!
    pause
    exit /b 1
)

echo [!] Packing script.arc...
py -3.12 arc_pack.py ./script_patched ../script.arc ../system.arc ../script_original.arc

if errorlevel 1 (
    echo [!] Error packing script.arc!
    pause
    exit /b 1
)

echo ========================================
echo [+] SUCCESS! script.arc updated in game root!
echo ========================================
pause
