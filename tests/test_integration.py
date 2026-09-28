"""Integration tests — end-to-end pipeline flow."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Test data ────────────────────────────────────────────────────────

SAMPLE_LLM_RESPONSE = {
    "data_publicacao": "2024-06-15",
    "entrada_em_vigor": "2025-01-01",
    "requisito": "Certificação de equipamentos de segurança",
    "norma": "MSC.1/Circ.1234",
    "assunto": "SEG",
    "aplicacao": "D",
    "status": "R",
    "item": "1.2.3",
    "itens_modificados": "Anexo I, Seção 3",
    "acao_sugerida": "Atualizar equipamentos de salva-vida até 01/2025",
}


# ── 1. Spider registry ──────────────────────────────────────────────


class TestSpiderRegistry:
    def test_get_spider_returns_html_list(self):
        from crawler.spiders.registry import get_spider

        source = {"id": "test", "type": "html_list", "url": "https://example.com"}
        spider = get_spider(source)
        assert type(spider).__name__ == "HtmlListSpider"

    def test_get_spider_returns_login(self):
        from crawler.spiders.registry import get_spider

        source = {"id": "imodocs", "type": "login", "url": "https://docs.imo.org"}
        spider = get_spider(source)
        assert type(spider).__name__ == "ImodocsAdapter"

    def test_adapter_overrides_type(self):
        from crawler.spiders.registry import get_spider

        source = {"id": "imodocs", "type": "html_list", "url": "https://docs.imo.org"}
        spider = get_spider(source)
        assert type(spider).__name__ == "ImodocsAdapter"

    def test_unknown_type_falls_back_to_html_list(self):
        from crawler.spiders.registry import get_spider

        source = {"id": "unknown", "type": "nonexistent", "url": "https://example.com"}
        spider = get_spider(source)
        assert type(spider).__name__ == "HtmlListSpider"


# ── 2. Storage ──────────────────────────────────────────────────────


class TestStorage:
    def test_enqueue_and_read(self, tmp_path, monkeypatch):
        import time

        from crawler import storage

        # Evita poluir data/queue.jsonl real com entradas de teste
        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

        item = {
            "title": f"Test Doc {time.time()}",
            "url": f"https://example.com/test_{int(time.time())}.pdf",
            "source_id": f"test_storage_{int(time.time())}",
        }
        content = f"test pdf content {time.time()}".encode()

        record = storage.enqueue(item, content)
        assert record is not None
        assert "local_path" in record

    def test_dedup_same_content(self, tmp_path, monkeypatch):
        from crawler import storage

        # Evita poluir data/queue.jsonl real com entradas de teste
        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

        item = {
            "title": "Test Dedup",
            "url": "https://example.com/dedup.pdf",
            "source_id": "test_dedup",
        }
        content = b"dedup content"

        r1 = storage.enqueue(item, content)
        r2 = storage.enqueue(item, content)
        assert r1 is not None
        assert r2 == {}  # skipped as duplicate

    def test_item_hash_is_stable(self):
        from crawler.storage import item_hash

        item = {"source_id": "a", "title": "Test", "url": "http://x.com"}
        h1 = item_hash(item)
        h2 = item_hash(item)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex


# ── 3. Text extraction ──────────────────────────────────────────────


class TestExtraction:
    def test_extract_html(self):
        from processor.extract import extract_text

        html = b"<html><body><h1>Regulation</h1><p>Text content</p></body></html>"
        text = extract_text(html, "html")
        assert "Regulation" in text
        assert "Text content" in text
        assert "<h1>" not in text  # tags removed


# ── 4. Normalizer ───────────────────────────────────────────────────


class TestNormalizer:
    def test_normalize_valid(self):
        from processor.normalizer import normalize

        result = normalize(SAMPLE_LLM_RESPONSE)
        assert result.assunto == "SEG"
        assert result.aplicacao == "D"
        assert result.status == "R"

    def test_normalize_np_preserves_action(self):
        from processor.normalizer import normalize

        data = {**SAMPLE_LLM_RESPONSE, "aplicacao": "NP"}
        result = normalize(data)
        assert result.aplicacao == "NP"
        # NP preserves the action (it's up to the validator to decide)
        assert result.acao_sugerida is not None


# ── 5. Prompt builder ───────────────────────────────────────────────


class TestPromptBuilder:
    def test_build_prompt_returns_tuple(self):
        from processor.prompt_builder import build_prompt

        system, user = build_prompt("test document text")
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert len(system) > 100
        assert "test document text" in user


# ── 6. Pipeline state ───────────────────────────────────────────────


class TestPipelineState:
    def test_singleton(self):
        from core.pipeline_state import PipelineState

        s1 = PipelineState()
        s2 = PipelineState()
        assert s1 is s2

    def test_start_finish(self):
        from core.pipeline_state import PipelineState

        state = PipelineState()
        state.start()
        assert state.running is True

        state.finish(ok=True)
        assert state.running is False
        assert state.last_run_ok is True

    def test_snapshot(self):
        from core.pipeline_state import PipelineState

        state = PipelineState()
        snap = state.snapshot()
        assert "running" in snap
        assert "step" in snap
        assert "errors" in snap


# ── 7. LLM providers ────────────────────────────────────────────────


class TestLLMProviders:
    def test_list_providers(self):
        from core.llm_providers import list_providers

        providers = list_providers()
        assert isinstance(providers, list)
        assert len(providers) > 0

    def test_active_provider(self):
        from core.llm_providers import list_providers

        providers = list_providers()
        active = [p for p in providers if p.get("active")]
        assert len(active) == 1


# ── 8. Config ────────────────────────────────────────────────────────


class TestConfig:
    def test_load_sources(self):
        from core.config import load_sources

        sources = load_sources()
        assert len(sources) == 6
        ids = {s["id"] for s in sources}
        assert "imodocs" in ids
        assert "iacs" in ids

    def test_load_llm_config(self):
        import yaml
        from core.config import CONFIG_DIR

        llm_path = CONFIG_DIR / "llm.yaml"
        assert llm_path.exists()
        with open(llm_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert "active" in cfg
        assert "providers" in cfg
