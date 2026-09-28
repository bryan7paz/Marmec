#!/bin/bash
set -e

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Marmec Regulatory Pipeline — Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# 1. Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "[ERRO] Python3 nao encontrado. Instale Python 3.12+"
    exit 1
fi
echo "[OK] Python encontrado: $(python3 --version)"

# 2. Criar virtualenv
if [ ! -d ".venv" ]; then
    echo ""
    echo "[1/5] Criando virtualenv..."
    python3 -m venv .venv
else
    echo ""
    echo "[1/5] Virtualenv ja existe, pulando..."
fi

# 3. Ativar virtualenv
echo "[2/5] Ativando virtualenv..."
source .venv/bin/activate

# 4. Instalar dependencias
echo "[3/5] Instalando dependencias..."
pip install -r requirements.txt --quiet

# 5. Instalar Chromium do Playwright
echo "[4/5] Instalando Chromium (Playwright)..."
playwright install chromium

# 6. Configurar credenciais
if [ ! -f "config/secrets.env" ]; then
    echo "[5/5] Criando config/secrets.env a partir do exemplo..."
    cp config/secrets.env.example config/secrets.env
    echo "      >>> EDITE config/secrets.env com suas credenciais <<<"
else
    echo "[5/5] config/secrets.env ja existe, pulando..."
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup completo!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Para rodar:"
echo "    source .venv/bin/activate"
echo "    python -m uvicorn api.main:app --port 8000"
echo "    Abrir http://127.0.0.1:8000"
echo ""
echo "  Para testar:"
echo "    python -m pytest tests/ -v"
echo ""
