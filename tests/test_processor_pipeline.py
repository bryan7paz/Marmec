"""Tests for processor/pipeline.py — processing pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from processor.pipeline import DocumentoIgnoradoError, process_all, process_record

LONG_TEXT = "texto de documento regulatório " * 20  # > MIN_TEXT_CHARS


class TestProcessRecord:
    @patch("processor.pipeline.extract_from_file")
    @patch("processor.pipeline.build_prompt")
    @patch("processor.pipeline.generate_structured")
    @patch("processor.pipeline.normalize")
    def test_success(self, mock_normalize, mock_generate, mock_build, mock_extract):
        mock_extract.return_value = LONG_TEXT
        mock_build.return_value = ("system", "user")
        mock_generate.return_value = {"norma": "MSC.1"}
        analysis = MagicMock()
        analysis.norma = "MSC.1"
        analysis.model_dump.return_value = {"norma": "MSC.1"}
        mock_normalize.return_value = analysis

        record = {"url": "http://example.com/doc.pdf", "local_path": "/tmp/doc.pdf"}
        process_record(record)

        mock_extract.assert_called_once()
        mock_build.assert_called_once_with(LONG_TEXT)
        mock_generate.assert_called_once_with("system", "user")
        mock_normalize.assert_called_once()

    @patch("processor.pipeline.extract_from_file", side_effect=Exception("error"))
    def test_extract_error(self, mock_extract):
        record = {"url": "http://example.com/doc.pdf", "local_path": "/tmp/doc.pdf"}
        try:
            process_record(record)
            raise AssertionError()
        except Exception as e:
            assert "error" in str(e)

    @patch("processor.pipeline.normalize")
    @patch("processor.pipeline.generate_structured")
    @patch("processor.pipeline.build_prompt")
    @patch("processor.pipeline.extract_from_file")
    def test_short_text_discarded_before_llm(self, mock_extract, mock_build, mock_gen, mock_norm):
        """Texto curto (página de navegação/404) é descartado sem chamar o LLM."""
        mock_extract.return_value = "Ir para a Busca 4"

        record = {"url": "http://example.com/x", "local_path": "/tmp/x"}
        try:
            process_record(record)
            raise AssertionError("deveria lançar DocumentoIgnoradoError")
        except DocumentoIgnoradoError as exc:
            assert "curto" in str(exc)

        mock_gen.assert_not_called()
        mock_norm.assert_not_called()

    @patch("processor.pipeline.extract_from_file")
    @patch("processor.pipeline.build_prompt")
    @patch("processor.pipeline.generate_structured")
    @patch("processor.pipeline.normalize")
    def test_null_norma_discarded(self, mock_normalize, mock_generate, mock_build, mock_extract):
        """LLM sem norma identificada é descartado — não persiste registro vazio."""
        mock_extract.return_value = LONG_TEXT
        mock_build.return_value = ("system", "user")
        mock_generate.return_value = {}
        analysis = MagicMock()
        analysis.norma = ""
        mock_normalize.return_value = analysis

        record = {"url": "http://example.com/x", "local_path": "/tmp/x"}
        try:
            process_record(record)
            raise AssertionError("deveria lançar DocumentoIgnoradoError")
        except DocumentoIgnoradoError as exc:
            assert "norma" in str(exc)


class TestProcessAll:
    @patch("processor.pipeline.process_record")
    @patch("processor.pipeline.read_queue")
    def test_calls_process_record(self, mock_read, mock_process):
        mock_read.return_value = [
            {"url": "http://a.com/1.pdf", "sha256": "aaa"},
            {"url": "http://a.com/2.pdf", "sha256": "bbb"},
        ]
        mock_process.return_value = {"norma": "MSC.1"}
        results = process_all()
        assert len(results) == 2
        assert mock_process.call_count == 2

    @patch("processor.pipeline.process_record", side_effect=Exception("err"))
    @patch("processor.pipeline.read_queue")
    def test_error_skipped(self, mock_read, mock_process):
        mock_read.return_value = [{"url": "http://a.com/1.pdf", "sha256": "aaa"}]
        results = process_all()
        assert len(results) == 0
