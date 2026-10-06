"""Pasta de downloads: nome legível, migração do layout antigo e limpeza."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from api.database import SessionLocal, get_db
from api.main import app
from api.middleware import api_key_auth
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    async def override_auth():
        return None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[api_key_auth] = override_auth
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestSanitizeFilename:
    def test_remove_invalidos(self):
        from crawler.storage import sanitize_filename

        nome = sanitize_filename('Portaria 45/2024: "v2"? <ok>|x', "", ".html")
        for ch in '\\/:*?"<>|':
            assert ch not in nome
        assert nome.endswith(".html")

    def test_fallback_url(self):
        from crawler.storage import sanitize_filename

        assert (
            sanitize_filename("", "https://x.org/docs/norma-123.pdf?dl=1", ".pdf")
            == "norma-123.pdf"
        )

    def test_fallback_documento(self):
        from crawler.storage import sanitize_filename

        assert sanitize_filename("", "", ".html") == "documento.html"
        assert sanitize_filename("   ...   ", "", ".html") == "documento.html"

    def test_limite_comprimento(self):
        from crawler.storage import sanitize_filename

        nome = sanitize_filename("a" * 300, "", ".pdf")
        assert len(nome) <= 80 + len(".pdf")


class TestEnqueueNomeLegivel:
    def test_grava_em_downloads_com_titulo(self, tmp_path, monkeypatch):
        from crawler import storage

        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        item = {
            "title": "Code of Practice for Pipeline Laying",
            "url": "https://x.org/a.pdf",
            "source_id": "iacs.test",
        }
        record = storage.enqueue(item, b"%PDF-1.4 fake")
        path = Path(record["local_path"])
        assert path.parent == tmp_path / "downloads" / "iacs.test"
        assert path.name.startswith("Code of Practice for Pipeline Laying [")
        assert path.suffix == ".pdf"
        assert path.exists()


class TestMigrate:
    def _data_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "iacs").mkdir()
        (tmp_path / "iacs" / f"{'a' * 16}.pdf").write_bytes(b"pdf")
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "n.jsonl").write_text("{}\n", encoding="utf-8")
        (tmp_path / "backup_registros.json").write_text("[]", encoding="utf-8")
        conn = sqlite3.connect(str(tmp_path / "regulatory.db"))
        conn.execute("CREATE TABLE regulatory_analysis (documento_hash VARCHAR, norma VARCHAR)")
        conn.execute(
            "INSERT INTO regulatory_analysis VALUES (?, ?)",
            ("a" * 64, "CP 2024: Norma X?"),
        )
        conn.commit()
        conn.close()
        return tmp_path

    def test_move_e_renomeia(self, tmp_path, monkeypatch):
        from crawler import migrate

        monkeypatch.setattr(migrate, "DATA_DIR", self._data_dir(tmp_path))
        stats = migrate.migrate_downloads()
        assert stats["moved"] == 1
        assert stats["renamed"] == 1
        alvo = list((tmp_path / "downloads" / "iacs").iterdir())
        assert len(alvo) == 1
        assert alvo[0].name.startswith("CP 2024 Norma X [")
        assert not (tmp_path / "iacs").exists()
        # backups e logs intactos
        assert (tmp_path / "backup_registros.json").exists()
        assert (tmp_path / "logs" / "n.jsonl").exists()

    def test_idempotente(self, tmp_path, monkeypatch):
        from crawler import migrate

        monkeypatch.setattr(migrate, "DATA_DIR", self._data_dir(tmp_path))
        migrate.migrate_downloads()
        stats2 = migrate.migrate_downloads()
        assert stats2["moved"] == 0
        assert len(list((tmp_path / "downloads" / "iacs").iterdir())) == 1

    def test_atualiza_local_path_da_fila(self, tmp_path, monkeypatch):
        import json

        from crawler import migrate

        data = self._data_dir(tmp_path)
        antigo = str(tmp_path / "iacs" / f"{'a' * 16}.pdf")
        entrada = json.dumps(
            {"url": "https://x.org/a.pdf", "local_path": antigo}, ensure_ascii=False
        )
        (tmp_path / "queue.jsonl").write_text(entrada + "\n", encoding="utf-8")
        monkeypatch.setattr(migrate, "DATA_DIR", data)
        migrate.migrate_downloads()
        linha = (tmp_path / "queue.jsonl").read_text(encoding="utf-8")
        assert antigo not in linha
        assert "downloads" in linha


class TestDownloadsAPI:
    def test_info_vazio(self, client, tmp_path, monkeypatch):
        from crawler import storage

        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        resp = client.get("/pipeline/downloads")
        assert resp.status_code == 200
        assert resp.json() == {"arquivos": 0, "bytes": 0}

    def test_info_conta_arquivos(self, client, tmp_path, monkeypatch):
        from crawler import storage

        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        pasta = tmp_path / "downloads" / "fonte"
        pasta.mkdir(parents=True)
        (pasta / "doc [ab12].pdf").write_bytes(b"12345")
        (pasta / "outro [cd34].html").write_bytes(b"12")
        resp = client.get("/pipeline/downloads")
        assert resp.json() == {"arquivos": 2, "bytes": 7}

    def test_clear_bloqueado_com_fila(self, client, tmp_path, monkeypatch):
        from crawler import storage

        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        (tmp_path / "queue.jsonl").write_text('{"sha256": "abc"}\n', encoding="utf-8")
        resp = client.post("/pipeline/clear-downloads")
        body = resp.json()
        assert body["ok"] is False
        assert "fila" in body["error"]
        assert (tmp_path / "queue.jsonl").exists()

    def test_clear_apaga_downloads(self, client, tmp_path, monkeypatch):
        from crawler import storage

        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        pasta = tmp_path / "downloads" / "fonte"
        pasta.mkdir(parents=True)
        (pasta / "doc [ab12].pdf").write_bytes(b"12345")
        resp = client.post("/pipeline/clear-downloads")
        body = resp.json()
        assert body["ok"] is True
        assert body["arquivos"] == 1
        assert body["bytes"] == 5
        assert not (tmp_path / "downloads").exists()
