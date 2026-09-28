#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Marmec Regulatory Pipeline — Iniciando..."
echo "═══════════════════════════════════════════════════"
echo ""

# 1. Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "[ERRO] Python3 nao encontrado. Instale Python 3.12+"
    exit 1
fi

# 2. Primeira execucao? Roda o setup automaticamente
if [ ! -d ".venv" ]; then
    echo "[INFO] Primeira execucao detectada - rodando setup automatico..."
    echo ""
    ./setup.sh
fi

# 3. Ativar virtualenv
if [ ! -f ".venv/bin/activate" ]; then
    echo "[ERRO] Virtualenv nao encontrado. Execute setup.sh manualmente."
    exit 1
fi
source .venv/bin/activate

# 4. Agendar abertura do navegador apos o servidor subir
( sleep 3 && (xdg-open http://127.0.0.1:8000 || open http://127.0.0.1:8000 || true) ) &

echo "═══════════════════════════════════════════════════"
echo "  Servidor iniciando em http://127.0.0.1:8000"
echo "  (navegador abre automaticamente em ~3s)"
echo "  Encerrar: Ctrl+C"
echo "═══════════════════════════════════════════════════"
echo ""

python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
