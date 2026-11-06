"""Importador do Acompanhamento Normativo Completo (XLSX).

Lê o arquivo produzido pela equipe de conformidade (Consolidado + abas mensais)
e persiste como baseline de referência para QA/acurácia da IA.

O XLSX não é fonte de verdade para o LLM — serve como gabarito histórico:
cada linha vira um registro em ``regulatory_analysis`` com ``source_id="spreadsheet"``,
permitindo comparação posterior (ex.: o que o LLM extraiu vs. o que a equipe
já classificou naquela mesma norma).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from api import models, persistence
from api.database import Base, SessionLocal, engine
from openpyxl import load_workbook

DEFAULT_PATH = Path("data/baseline/Acompanhamento Normativo Completo.xlsx")

# Mapeamento de sinônimos de cabeçalho -> campo do modelo.
HEADER_ALIASES = {
    "mês de envio": "entrada_em_vigor",
    "entrada em vigor": "entrada_em_vigor",
    "data que entra em vigor": "data_publicacao",
    "requisito": "requisito",
    "norma": "norma",
    "direta (d) / indireta (i)": "aplicacao",
    "aplicação": "aplicacao",
    "aplicacao": "aplicacao",
    "status": "status",
    "item": "item",
    "itens modificados": "itens_modificados",
    "itens modificados ou objetivos": "itens_modificados",
    "o que deve ser feito?": "acao_sugerida",
    "ação sugerida": "acao_sugerida",
    "acao sugerida": "acao_sugerida",
    "referencia": "norma",
    "nome da norma": "norma",
}

# Fallback posicional para abas sem cabeçalho reconhecível (layout mensal padrão).
COL_INDEX = {
    "data_publicacao": 1,
    "requisito": 2,
    "norma": 3,
    "aplicacao": 4,
    "status": 5,
    "item": 6,
    "itens_modificados": 7,
    "acao_sugerida": 8,
}

MODEL_FIELDS = (
    "data_publicacao",
    "requisito",
    "norma",
    "aplicacao",
    "status",
    "item",
    "itens_modificados",
    "acao_sugerida",
    "entrada_em_vigor",
)


def _to_iso_date(value: Any) -> str | None:
    """Converte várias representações de data para AAAA-MM-DD ou None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        try:
            return date(y, mo, 1).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{2})$", s)
    if m:
        mo, yy = int(m.group(1)), int(m.group(2))
        y = 2000 + yy if yy < 70 else 1900 + yy
        try:
            return date(y, mo, 1).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _blank(row: tuple) -> bool:
    return all(v is None or str(v).strip() == "" for v in row)


def _header_map(headers: list[Any]) -> dict[int, str]:
    """Mapeia índice de coluna -> campo, usando cabeçalho quando disponível."""
    mapping: dict[int, str] = {}
    for idx, h in enumerate(headers):
        key = str(h or "").strip().lower()
        if key in HEADER_ALIASES:
            mapping[idx] = HEADER_ALIASES[key]
    return mapping


def _import_sheet(ws_name: str, ws) -> list[dict[str, Any]]:
    """Retorna lista de dicts normalizados de uma aba.

    Tenta ler o cabeçalho da primeira linha para mapear colunas por nome.
    Se nenhum cabeçalho for reconhecido, usa o fallback posicional
    (layout mensal padrão).
    """
    rows: list[dict[str, Any]] = []
    header_map: dict[int, str] | None = None

    for row in ws.iter_rows(values_only=True):
        if not row or _blank(row):
            continue

        if header_map is None:
            header_map = _header_map(list(row))
            if len(header_map) >= 2:
                continue  # primeira linha é cabeçalho
            header_map = None  # cai para fallback posicional

        entry = dict.fromkeys(MODEL_FIELDS)
        entry["source_name"] = ws_name
        mapping = header_map or {v: k for k, v in COL_INDEX.items()}
        for idx, campo in mapping.items():
            if idx >= len(row):
                continue
            valor = row[idx]
            if campo in ("data_publicacao", "entrada_em_vigor"):
                entry[campo] = _to_iso_date(valor)
            else:
                entry[campo] = _clean_text(valor)
        rows.append(entry)
    return rows


def import_spreadsheet(path: Path = DEFAULT_PATH, clear: bool = False) -> int:
    """Importa o XLSX completo para a tabela regulatory_analysis (source_id=spreadsheet)."""
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    wb = load_workbook(path, read_only=True, data_only=True)
    entries: list[dict[str, Any]] = []

    # Abas que NÃO são gabarito de extração de normas da web (plano de ação
    # interno e relatórios de acompanhamento com schema diferente).
    skip_sheets = {"plano de ação"}

    for name in wb.sheetnames:
        if name.lower() in skip_sheets:
            continue
        entries.extend(_import_sheet(name.lower(), wb[name]))

    Base.metadata.create_all(bind=engine)
    if clear:
        db = SessionLocal()
        try:
            db.execute(
                models.RegulatoryAnalysis.__table__.delete().where(
                    models.RegulatoryAnalysis.source_id == "spreadsheet"
                )
            )
            db.commit()
        finally:
            db.close()

    persisted = 0
    db = SessionLocal()
    try:
        existing = {h for (h,) in db.query(models.RegulatoryAnalysis.documento_hash).all() if h}
    finally:
        db.close()

    for entry in entries:
        key = hashlib.sha256(
            f"{entry['source_name']}|{entry['norma']}|{entry['requisito']}|"
            f"{entry.get('data_publicacao') or ''}|{entry.get('entrada_em_vigor') or ''}".encode()
        ).hexdigest()
        if key in existing:
            continue
        try:
            row = persistence.build_row(entry | {"documento_hash": key, "source_id": "spreadsheet"})
            db.add(row)
            db.commit()
            persisted += 1
        except Exception:
            db.rollback()

    db.close()
    return persisted


if __name__ == "__main__":
    n = import_spreadsheet(clear=True)
    print(f"Importadas {n} novas linhas do XLSX.")
