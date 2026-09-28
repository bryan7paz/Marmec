@echo off
chcp 65001 >nul
title Marmec — Regulatory Pipeline
echo.
echo ═══════════════════════════════════════════════════
echo   Marmec Regulatory Pipeline — Iniciando...
echo ═══════════════════════════════════════════════════
echo.

:: 1. Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.12+ em https://python.org
    pause
    exit /b 1
)

:: 2. Primeira execucao? Roda o setup automaticamente
if not exist ".venv" (
    echo [INFO] Primeira execucao detectada - rodando setup automatico...
    echo.
    call "%~dp0setup.bat" /auto
    if errorlevel 1 (
        echo [ERRO] Setup falhou. Corrija os erros acima e tente novamente.
        pause
        exit /b 1
    )
    echo.
)

:: 3. Ativar virtualenv
if not exist ".venv\Scripts\activate.bat" (
    echo [ERRO] Virtualenv nao encontrado. Execute setup.bat manualmente.
    pause
    exit /b 1
)
call "%~dp0.venv\Scripts\activate.bat"

:: 4. Agendar abertura do navegador apos o servidor subir
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"

echo ═══════════════════════════════════════════════════
echo   Servidor iniciando em http://127.0.0.1:8000
echo   (navegador abre automaticamente em ~3s)
echo   Encerrar: Ctrl+C nesta janela
echo ═══════════════════════════════════════════════════
echo.

python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

echo.
echo Servidor encerrado.
pause
