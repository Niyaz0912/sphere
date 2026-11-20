@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Сфера - сброс пароля мастера
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% reset_admin_password.py
if errorlevel 1 (
    echo.
    echo Не удалось сбросить пароль.
    echo Проверьте, что Python и зависимости установлены:
    echo   python -m pip install -r requirements.txt
)

echo.
pause
