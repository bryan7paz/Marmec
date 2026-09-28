"""Tests for processor/prompt_builder.py."""

from __future__ import annotations

from processor.prompt_builder import build_prompt


class TestBuildPrompt:
    def test_returns_tuple(self):
        result = build_prompt("test document")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_contains_marmec(self):
        system, _ = build_prompt("doc")
        assert "Marmec" in system

    def test_system_contains_assunto_legend(self):
        system, _ = build_prompt("doc")
        assert "Legenda de Assunto" in system
        assert "SEG:" in system
        assert "IMO:" in system

    def test_system_contains_aplicacao_legend(self):
        system, _ = build_prompt("doc")
        assert "Legenda de Aplicação" in system
        assert "NP:" in system

    def test_system_contains_pertinence_rule(self):
        system, _ = build_prompt("doc")
        assert "REGRA DE PERTINÊNCIA" in system

    def test_user_contains_document(self):
        _, user = build_prompt("meu documento aqui")
        assert "meu documento aqui" in user

    def test_prompt_uses_config(self):
        system, _ = build_prompt("x")
        # Should contain the 9 assunto codes
        for code in ("SEG", "INC", "COM", "NAV", "CON", "TRI", "AMB", "NAU", "IMO"):
            assert code in system
