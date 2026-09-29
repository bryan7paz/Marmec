"""Tests for process_queue.py — queue processing."""

from __future__ import annotations

import contextlib
import json
from unittest.mock import MagicMock, patch

from process_queue import _compact_queue, process_queue
from processor.pipeline import DocumentoIgnoradoError


class TestCompactQueue:
    def test_removes_processed(self, tmp_path):
        q = tmp_path / "queue.jsonl"
        q.write_text(
            json.dumps({"sha256": "aaa", "title": "doc1"})
            + "\n"
            + json.dumps({"sha256": "bbb", "title": "doc2"})
            + "\n"
            + json.dumps({"sha256": "ccc", "title": "doc3"})
            + "\n"
        )
        with patch("process_queue.QUEUE_PATH", q):
            _compact_queue(["aaa", "ccc"])
            lines = q.read_text().strip().split("\n")
            assert len(lines) == 1
            assert json.loads(lines[0])["sha256"] == "bbb"

    def test_empty_processed(self, tmp_path):
        q = tmp_path / "queue.jsonl"
        q.write_text(json.dumps({"sha256": "aaa"}) + "\n")
        with patch("process_queue.QUEUE_PATH", q):
            _compact_queue([])
            lines = q.read_text().strip().split("\n")
            assert len(lines) == 1

    def test_no_file(self, tmp_path):
        q = tmp_path / "nonexistent.jsonl"
        with patch("process_queue.QUEUE_PATH", q), contextlib.suppress(FileNotFoundError):
            _compact_queue(["aaa"])


class TestDocumentoIgnorado:
    """Documento de qualidade ruim sai da fila; erro transitório fica."""

    @staticmethod
    def _mock_db():
        db = MagicMock()
        db.execute.return_value.all.return_value = []
        return db

    def test_junk_removed_from_queue(self, tmp_path):
        q = tmp_path / "queue.jsonl"
        q.write_text(json.dumps({"sha256": "junk", "title": "pagina 404"}) + "\n")
        db = self._mock_db()

        with (
            patch("process_queue.QUEUE_PATH", q),
            patch("process_queue.Base"),
            patch("process_queue.SessionLocal", return_value=db),
            patch("process_queue.pipeline.read_queue") as mock_read,
            patch(
                "process_queue.pipeline.process_record",
                side_effect=DocumentoIgnoradoError("sem norma"),
            ),
        ):
            mock_read.return_value = [{"sha256": "junk", "title": "pagina 404"}]
            saved = process_queue()

        assert saved == 0
        assert q.read_text().strip() == ""  # descartado da fila

    def test_transient_error_stays_in_queue(self, tmp_path):
        q = tmp_path / "queue.jsonl"
        q.write_text(json.dumps({"sha256": "tmp", "title": "doc"}) + "\n")
        db = self._mock_db()

        with (
            patch("process_queue.QUEUE_PATH", q),
            patch("process_queue.Base"),
            patch("process_queue.SessionLocal", return_value=db),
            patch("process_queue.pipeline.read_queue") as mock_read,
            patch(
                "process_queue.pipeline.process_record",
                side_effect=RuntimeError("cota excedida"),
            ),
        ):
            mock_read.return_value = [{"sha256": "tmp", "title": "doc"}]
            saved = process_queue()

        assert saved == 0
        assert "tmp" in q.read_text()  # mantido para retry
