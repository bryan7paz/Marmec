"""QA Baseline: expõe o Acompanhamento Normativo Completo (XLSX) como gabarito.

Endpoints:
- GET  /qa/baseline/import   — (re)importa o XLSX como registros source_id="spreadsheet"
- GET  /qa/baseline/stats    — estatísticas do gabarito carregado (contagem, preenchimento)
- GET  /qa/baseline/rows     — lista paginada dos registros de referência
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from typing import Any

from fastapi import APIRouter, Depends, Query
from processor.spreadsheet_import import DEFAULT_PATH, import_spreadsheet
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/qa", tags=["qa-baseline"])


@router.post("/baseline/import")
def import_baseline(path: str | None = None, db: Session = Depends(get_db)):
    """Re-importa o XLSX completo, limpando registros de spreadsheet anteriores."""
    xlsx = Path(path) if path else DEFAULT_PATH
    count = import_spreadsheet(xlsx, clear=True)
    total = db.query(models.RegulatoryAnalysis).filter_by(source_id="spreadsheet").count()
    return {"imported": count, "total_spreadsheet_rows": total}


@router.get("/baseline/stats")
def baseline_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Estatísticas de preenchimento do gabarito por campo."""
    rows = db.query(models.RegulatoryAnalysis).filter_by(source_id="spreadsheet").all()
    total = len(rows)
    if total == 0:
        return {"total": 0}

    fields = ("norma", "requisito", "aplicacao", "status", "entrada_em_vigor", "item")
    por_campo: dict[str, dict[str, int]] = {}
    for campo in fields:
        preenchido = sum(
            1 for r in rows if getattr(r, campo) is not None and str(getattr(r, campo)).strip()
        )
        por_campo[campo] = {"total_ref": total, "preenchido": preenchido}

    requisitos: dict[str, int] = {}
    for r in rows:
        key = r.requisito or "(vazio)"
        requisitos[key] = requisitos.get(key, 0) + 1

    return {
        "total_ref": total,
        "por_campo": por_campo,
        "top_requisitos": sorted(requisitos.items(), key=lambda kv: -kv[1])[:10],
    }


@router.get("/baseline/rows")
def baseline_rows(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Lista paginada dos registros de referência do XLSX."""
    rows = (
        db.query(models.RegulatoryAnalysis)
        .filter_by(source_id="spreadsheet")
        .order_by(models.RegulatoryAnalysis.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "norma": r.norma,
            "requisito": r.requisito,
            "aplicacao": r.aplicacao,
            "status": r.status,
            "entrada_em_vigor": r.entrada_em_vigor.isoformat() if r.entrada_em_vigor else None,
            "item": r.item,
            "itens_modificados": r.itens_modificados,
            "acao_sugerida": r.acao_sugerida,
            "source_name": r.source_name,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
