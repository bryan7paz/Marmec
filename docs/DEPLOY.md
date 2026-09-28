# Guia de Deploy

## Pré-requisitos

- Python 3.12+
- pip
- Git
- (Opcional) PostgreSQL 16
- (Opcional) Docker + Docker Compose

## Setup Local (Desenvolvimento)

### 1. Clonar e configurar

```bash
git clone <repo-url>
cd regulatory-pipeline
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
playwright install chromium
```

### 2. Configurar credenciais

```bash
cp config/secrets.env.example config/secrets.env
```

Editar `config/secrets.env`:

```env
# Banco de dados (SQLite local)
DATABASE_URL=sqlite:///./data/regulatory.db

# LLM (preencha ao menos um)
GOOGLE_API_KEY=sua_chave_aqui
NVIDIA_API_KEY=nvapi-sua_chave_aqui

# IMODOCS (opcional)
IMODOCS_USER=seu_login
IMODOCS_PASSWORD=sua_senha
```

### 3. Rodar

```bash
# Dashboard (port 8000)
python -m uvicorn api.main:app --port 8000 --reload

# Pipeline completo (crawl + process)
python run_pipeline.py

# Processar fila apenas
python process_queue.py
```

Acessar: http://127.0.0.1:8000

---

## Deploy com Docker

### 1. Configurar

```bash
cp config/secrets.env.example config/secrets.env
# Editar secrets.env com suas credenciais
```

### 2. Subir com Docker Compose

```bash
docker compose up -d
```

Isso sobe:
- App na porta 8000
- PostgreSQL 16 na porta 5432

### 3. Verificar

```bash
docker compose logs -f app
```

---

## Deploy Manual (Produção)

### 1. Servidor

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install python3.12 python3.12-venv postgresql

# Criar usuário e banco
sudo -u postgres psql
CREATE USER regulatory WITH PASSWORD 'sua_senha';
CREATE DATABASE regulatory OWNER regulatory;
\q
```

### 2. Aplicação

```bash
cd /opt
git clone <repo-url> regulatory-pipeline
cd regulatory-pipeline

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 3. Configurar

```bash
cp config/secrets.env.example config/secrets.env
nano config/secrets.env
```

```env
DATABASE_URL=postgresql+psycopg2://regulatory:sua_senha@localhost:5432/regulatory
GOOGLE_API_KEY=sua_chave
```

### 4. Database

```bash
python -c "from api.database import Base, engine; Base.metadata.create_all(bind=engine)"
```

### 5. Serviço Systemd

```bash
sudo nano /etc/systemd/system/regulatory.service
```

```ini
[Unit]
Description=Regulatory Pipeline
After=network.target postgresql.service

[Service]
Type=simple
User=regulatory
WorkingDirectory=/opt/regulatory-pipeline
Environment=PATH=/opt/regulatory-pipeline/.venv/bin
ExecStart=/opt/regulatory-pipeline/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable regulatory
sudo systemctl start regulatory
```

### 6. Nginx (Reverse Proxy)

```bash
sudo nano /etc/nginx/sites-available/regulatory
```

```nginx
server {
    listen 80;
    server_name regul.marmec.com.br;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /pipeline/stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Cache-Control no-cache;
        proxy_buffering off;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/regulatory /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 7. SSL (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d regul.marmec.com.br
```

---

## Cron Job (Crawl Diário)

```bash
crontab -e
```

```cron
# Crawl diário às 06:00
0 6 * * * cd /opt/regulatory-pipeline && .venv/bin/python run_pipeline.py >> /var/log/regulatory.log 2>&1
```

---

## Monitoramento

### Health Check

```bash
curl http://localhost:8000/health
# {"status":"ok","db":"connected"}
```

### Logs

```bash
# Docker
docker compose logs -f app

# Systemd
journalctl -u regulatory -f

# Arquivo
tail -f /var/log/regulatory.log
```

### Notificações

Notificações são salvas em `data/logs/notifications.jsonl`:

```bash
tail -f data/logs/notifications.jsonl
```

---

## Troubleshooting

### PostgreSQL indisponível
O sistema faz fallback para SQLite automaticamente. Verifique:
```bash
pg_isready -h localhost -p 5432
```

### Playwright erro
```bash
playwright install chromium
playwright install-deps
```

### LLM quota excedida
O sistema faz fallback automático para o próximo provedor. Verifique `config/llm.yaml`.

### IMODOCS login falha
1. Verifique credenciais em `config/secrets.env`
2. Teste manualmente no navegador
3. Verifique seletores em `config/sources.yaml`
