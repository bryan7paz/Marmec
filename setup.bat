@echo off
chcp 65001 >nul
echo.
echo ═══════════════════════════════════════════════════
echo   Marmec Regulatory Pipeline — Setup
echo ═══════════════════════════════════════════════════
echo.

:: 1. Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.12+ em https://python.org
    pause
    exit /b 1
)
echo [OK] Python encontrado:
python --version

:: 2. Criar virtualenv
if not exist ".venv" (
    echo.
    echo [1/5] Criando virtualenv...
    python -m venv .venv
) else (
    echo.
    echo [1/5] Virtualenv ja existe, pulando...
)

:: 3. Ativar virtualenv
echo [2/5] Ativando virtualenv...
call .venv\Scripts\activate.bat

:: 4. Instalar dependencias
echo [3/5] Instalando dependencias...
pip install -r requirements.txt --quiet

:: 5. Instalar Chromium do Playwright
echo [4/5] Instalando Chromium (Playwright)...
playwright install chromium

:: 6. Configurar credenciais
if not exist "config\secrets.env" (
    echo [5/5] Criando config\secrets.env a partir do exemplo...
    copy config\secrets.env.example config\secrets.env >nul
    echo       >>> EDITE config\secrets.env com suas credenciais <<<
) else (
    echo [5/5] config\secrets.env ja existe, pulando...
)

echo.
echo ═══════════════════════════════════════════════════
echo   Setup completo!
echo ═══════════════════════════════════════════════════
echo.
echo   Para rodar:
echo     .venv\Scripts\activate
echo     python -m uvicorn api.main:app --port 8000
echo     Abrir http://127.0.0.1:8000
echo.
echo   Para testar:
echo     python -m pytest tests/ -v
echo.
if "%~1"=="/auto" exit /b 0
pause
