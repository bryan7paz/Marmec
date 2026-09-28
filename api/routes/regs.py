"""Routes for regulations: CRUD, search, filters, batch validate, export."""

from __future__ import annotations

import csv
import io
import unicodedata
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..schemas import AnalysisDetail, AnalysisOut, ValidationAction

router = APIRouter(prefix="/regs", tags=["regs"])


# ── Search helpers (accent-insensitive, multi-word, quoted phrase) ──

# PostgreSQL translate() map (SQLite uses the `unaccent` SQL function instead)
_PG_FROM = "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_PG_TO = "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN"

_SEARCH_FIELDS = (
    "norma",
    "requisito",
    "item",
    "itens_modificados",
    "acao_sugerida",
    "source_name",
)


def _strip_accents(text: str) -> str:
    """Remove accents from a Python string (for query terms)."""
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")


def _accent_expr(col, dialect: str):
    """Return an accent-stripped SQL expression for the column."""
    if dialect == "postgresql":
        return func.translate(col, _PG_FROM, _PG_TO)
    return func.unaccent(col)


def _search_filter(q: str, dialect: str):
    """Build accent-insensitive search filter.

    - `"frase com aspas"` → exact substring (accent-insensitive)
    - multi-word → every word must match at least one field (AND)
    """
    q = q.strip()
    cols = [getattr(models.RegulatoryAnalysis, f) for f in _SEARCH_FIELDS]

    if q.startswith('"') and q.endswith('"') and len(q) >= 2:
        phrase = _strip_accents(q[1:-1].strip())
        if not phrase:
            return None
        return or_(*[_accent_expr(c, dialect).ilike(f"%{phrase}%") for c in cols])

    words = [_strip_accents(w) for w in q.split() if w]
    if not words:
        return None
    return and_(*[or_(*[_accent_expr(c, dialect).ilike(f"%{w}%") for c in cols]) for w in words])


# ── List with search + filters + pagination ────────────────────────


@router.get("/")
def list_analyses(
    q: str | None = None,
    assunto: str | None = None,
    aplicacao: str | None = None,
    status: str | None = None,
    validacao: str | None = None,
    fonte: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = Query(
        default="created_at",
        regex="^(created_at|data_publicacao|entrada_em_vigor|norma|assunto|aplicacao|status|validacao)$",
    ),
    sort_order: str = Query(default="desc", regex="^(asc|desc)$"),
    fields: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q_query = db.query(models.RegulatoryAnalysis)

    # Full-text search (accent-insensitive, multi-word, quoted phrase)
    if q:
        expr = _search_filter(q, db.get_bind().dialect.name)
        if expr is not None:
            q_query = q_query.filter(expr)

    # Enum filters
    if assunto:
        q_query = q_query.filter(models.RegulatoryAnalysis.assunto == assunto)
    if aplicacao:
        q_query = q_query.filter(models.RegulatoryAnalysis.aplicacao == aplicacao)
    if status:
        q_query = q_query.filter(models.RegulatoryAnalysis.status == status)
    if validacao:
        q_query = q_query.filter(models.RegulatoryAnalysis.status_validacao == validacao)
    if fonte:
        q_query = q_query.filter(models.RegulatoryAnalysis.source_id == fonte)

    # Date range filters
    if date_from:
        try:
            from datetime import date

            df = date.fromisoformat(date_from)
            q_query = q_query.filter(models.RegulatoryAnalysis.data_publicacao >= df)
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import date

            dt = date.fromisoformat(date_to)
            q_query = q_query.filter(models.RegulatoryAnalysis.data_publicacao <= dt)
        except ValueError:
            pass

    # Sorting
    sort_column = getattr(models.RegulatoryAnalysis, sort_by, models.RegulatoryAnalysis.created_at)
    if sort_order == "asc":
        q_query = q_query.order_by(sort_column.asc())
    else:
        q_query = q_query.order_by(sort_column.desc())

    # Pagination
    total = q_query.count()
    offset = (page - 1) * size
    items = q_query.offset(offset).limit(size).all()

    # Field selection
    result_items = [AnalysisOut.model_validate(r) for r in items]
    if fields:
        field_list = [f.strip() for f in fields.split(",")]
        result_items = [
            {k: v for k, v in item.model_dump().items() if k in field_list} for item in result_items
        ]

    return {
        "items": result_items,
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
        "sort_by": sort_by,
        "sort_order": sort_order,
    }


# ── CSV export (MUST be before /{analysis_id}) ────────────────────


@router.get("/export/csv")
def export_csv(
    validacao: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.RegulatoryAnalysis)
    if validacao:
        q = q.filter(models.RegulatoryAnalysis.status_validacao == validacao)
    rows = q.order_by(models.RegulatoryAnalysis.created_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "fonte",
            "data_publicacao",
            "entrada_em_vigor",
            "requisito",
            "norma",
            "assunto",
            "aplicacao",
            "status",
            "item",
            "itens_modificados",
            "acao_sugerida",
            "validacao",
            "validado_por",
            "url_origem",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.source_id,
                r.data_publicacao.isoformat() if r.data_publicacao else "",
                r.entrada_em_vigor.isoformat() if r.entrada_em_vigor else "",
                r.requisito or "",
                r.norma or "",
                r.assunto or "",
                r.aplicacao or "",
                r.status or "",
                r.item or "",
                r.itens_modificados or "",
                r.acao_sugerida or "",
                r.status_validacao or "",
                r.validated_by or "",
                r.url_origem or "",
            ]
        )

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=regulatory_analysis.csv"},
    )


# ── Batch validate ─────────────────────────────────────────────────


class BatchValidationRequest(BaseModel):
    ids: list[str]
    action: str  # "aprovado" | "reprovado"
    validated_by: str = "especialista"


@router.post("/batch-validate")
def batch_validate(body: BatchValidationRequest, db: Session = Depends(get_db)):
    from core.notify import notify_validation

    if body.action not in ("aprovado", "reprovado"):
        raise HTTPException(status_code=400, detail="action deve ser 'aprovado' ou 'reprovado'")

    rows = (
        db.query(models.RegulatoryAnalysis).filter(models.RegulatoryAnalysis.id.in_(body.ids)).all()
    )
    now = datetime.now(UTC)
    updated = 0
    for row in rows:
        row.status_validacao = body.action
        row.validated_at = now
        row.validated_by = body.validated_by[:100]
        updated += 1

    db.commit()

    # Notify batch validation
    if updated > 0:
        notify_validation(
            doc_id=f"batch ({updated} documentos)",
            action=body.action,
            validated_by=body.validated_by,
        )
    return {"updated": updated}


# ── Single detail ──────────────────────────────────────────────────


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    row = db.get(models.RegulatoryAnalysis, analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return AnalysisDetail.model_validate(row)


# ── Validate single ────────────────────────────────────────────────


@router.post("/{analysis_id}/validate", response_model=AnalysisOut)
def validate_single(
    analysis_id: str,
    body: ValidationAction,
    db: Session = Depends(get_db),
):
    from core.notify import notify_validation

    row = db.get(models.RegulatoryAnalysis, analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Registro não encontrado")

    row.status_validacao = body.action
    row.validated_at = datetime.now(UTC)
    row.validated_by = (body.validated_by or "especialista")[:100]
    db.commit()
    db.refresh(row)

    notify_validation(analysis_id, body.action, row.validated_by)
    return row


# ── PDF Export ───────────────────────────────────────────────────


@router.get("/export/pdf")
def export_pdf(
    validacao: str | None = None,
    fonte: str | None = None,
    db: Session = Depends(get_db),
):
    """Export analysis results as a formatted PDF."""
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    q = db.query(models.RegulatoryAnalysis)
    if validacao:
        q = q.filter(models.RegulatoryAnalysis.status_validacao == validacao)
    if fonte:
        q = q.filter(models.RegulatoryAnalysis.source_id == fonte)
    rows = q.order_by(models.RegulatoryAnalysis.created_at.desc()).all()

    items = [AnalysisOut.model_validate(r).model_dump() for r in rows]

    # Count statuses
    approved = sum(1 for r in items if r.get("status_validacao") == "aprovado")
    rejected = sum(1 for r in items if r.get("status_validacao") == "reprovado")
    pending = sum(1 for r in items if r.get("status_validacao") in (None, "pendente"))

    # Build filter description
    filters_parts = []
    if validacao:
        filters_parts.append(f"Validação: {validacao}")
    if fonte:
        filters_parts.append(f"Fonte: {fonte}")
    filters = " | ".join(filters_parts) if filters_parts else "Nenhum filtro"

    # Render template
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("pdf_report.html")

    # Logo Marmec embutido em base64 (WeasyPrint não resolve URLs do static)
    logo_path = Path(__file__).parent.parent / "static" / "img" / "logo.png"
    logo_data_uri = ""
    if logo_path.is_file():
        import base64

        logo_data_uri = "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode(
            "ascii"
        )

    html_content = template.render(
        items=items,
        total=len(items),
        approved=approved,
        rejected=rejected,
        pending=pending,
        filters=filters,
        generated_at=datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC"),
        logo_data_uri=logo_data_uri,
    )

    # Generate PDF
    pdf_bytes = HTML(string=html_content).write_pdf()

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=regulatory_analysis.pdf"},
    )


# ── Excel Export ─────────────────────────────────────────────────


# Rótulos legíveis — códigos crus não comunicam nada numa planilha
ASSUNTO_LABELS = {
    "SEG": "SEG — Segurança",
    "INC": "INC — Incêndio",
    "COM": "COM — Comunicação / Rádio",
    "NAV": "NAV — Navegação",
    "CON": "CON — Construção Naval",
    "TRI": "TRI — Tripulação / Certificação",
    "AMB": "AMB — Meio Ambiente",
    "NAU": "NAU — Naufrágio / Salvamento",
    "IMO": "IMO — Convenções Gerais",
}
APLICACAO_LABELS = {
    "D": "D — Ação Direta",
    "I": "I — Ação Indireta",
    "NP": "NP — Não Pertinente",
}
STATUS_LABELS = {"R": "R — Revisão", "N": "N — Nova Versão"}
VALIDACAO_LABELS = {
    "aprovado": "Aprovado",
    "reprovado": "Reprovado",
    "pendente": "Pendente",
}

# Significados completos (aba "Legenda")
LEGENDA_APLICACAO = [
    (
        "D — Ação Direta",
        "Norma diretamente aplicável à Marmec: deve constar em procedimentos ou exige ação.",
    ),
    (
        "I — Ação Indireta",
        "A Marmec precisa estar ciente, mas sem medidas diretas de implementação.",
    ),
    (
        "NP — Não Pertinente",
        "Fora do escopo da Marmec (construção naval, operação exclusivamente em outros países, ou assunto não aplicável às suas atividades/embarcações).",
    ),
]
LEGENDA_STATUS = [
    ("R — Revisão", "Norma estabelecida ou revisada (atualizada/alterada), para conhecimento."),
    ("N — Nova Versão", "Norma nova, para conhecimento."),
]
LEGENDA_VALIDACAO = [
    ("Pendente", "Aguardando análise/validação humana."),
    ("Aprovado", "Revisado e aprovado pela equipe."),
    ("Reprovado", "Revisado e reprovado pela equipe."),
]
LEGENDA_REGRA = (
    "Marcar NP quando a norma se refere exclusivamente a construção naval, operações "
    "fora do Brasil/Panamá ou assuntos fora do escopo da Marmec. EXCEÇÃO: assuntos de "
    "aplicação geral (segurança, incêndio, naufrágio/salvamento, convenções IMO) são "
    "pertinentes mesmo globais — não marque NP por isso."
)

# Larguras por coluna (caracteres)
_EXCEL_WIDTHS = {
    "Data Publicação": 13,
    "Entrada em Vigor": 13,
    "Fonte": 16,
    "Norma": 26,
    "Assunto": 24,
    "Aplicação": 20,
    "Status": 17,
    "Requisito": 20,
    "Item": 20,
    "Itens Modificados": 42,
    "Ação Sugerida": 46,
    "Validação": 13,
    "Validado por": 16,
    "URL Origem": 30,
    "ID": 12,
}

# Cores semânticas (estilo Excel: fundo claro + fonte escura)
_APLICACAO_FILL = {"D": "C6EFCE", "I": "DDEBF7", "NP": "E7E6E6"}
_APLICACAO_FONT = {"D": "006100", "I": "1F4E79", "NP": "595959"}
_STATUS_FILL = {"R": "FFEB9C", "N": "BDD7EE"}
_STATUS_FONT = {"R": "9C6500", "N": "1F4E79"}
_VALIDACAO_FILL = {"aprovado": "C6EFCE", "reprovado": "FFC7CE", "pendente": "FFEB9C"}
_VALIDACAO_FONT = {"aprovado": "006100", "reprovado": "9C0006", "pendente": "9C6500"}


def _excel_value(col: str, row) -> tuple[str, str | None, str | None]:
    """Return (value, fill_hex, font_hex) for a data cell."""
    if col == "Data Publicação":
        fmt = "%d/%m/%Y"
        return (row.data_publicacao.strftime(fmt) if row.data_publicacao else "—", None, None)
    if col == "Entrada em Vigor":
        fmt = "%d/%m/%Y"
        return (row.entrada_em_vigor.strftime(fmt) if row.entrada_em_vigor else "—", None, None)
    if col == "Fonte":
        return (row.source_name or row.source_id or "—", None, None)
    if col == "Norma":
        return (row.norma or "—", None, None)
    if col == "Assunto":
        code = (row.assunto or "").strip()
        return (ASSUNTO_LABELS.get(code, code or "—"), None, None)
    if col == "Aplicação":
        code = (row.aplicacao or "").strip()
        return (
            APLICACAO_LABELS.get(code, code or "—"),
            _APLICACAO_FILL.get(code),
            _APLICACAO_FONT.get(code),
        )
    if col == "Status":
        code = (row.status or "").strip()
        fill = _STATUS_FILL.get(code)
        return (STATUS_LABELS.get(code, code or "—"), fill, _STATUS_FONT.get(code))
    if col == "Requisito":
        return (row.requisito or "—", None, None)
    if col == "Item":
        return (row.item or "—", None, None)
    if col == "Itens Modificados":
        return (row.itens_modificados or "— (sem alterações registradas)", None, None)
    if col == "Ação Sugerida":
        if row.acao_sugerida:
            return (row.acao_sugerida, "FFF2CC", None)
        if (row.aplicacao or "").strip() == "NP":
            return ("— (não pertinente: sem ação necessária)", None, None)
        return ("— (sem ação registrada)", None, None)
    if col == "Validação":
        code = (row.status_validacao or "pendente").strip()
        return (
            VALIDACAO_LABELS.get(code, code),
            _VALIDACAO_FILL.get(code),
            _VALIDACAO_FONT.get(code),
        )
    if col == "Validado por":
        return (row.validated_by or "—", None, None)
    if col == "URL Origem":
        return (row.url_origem or "—", None, None)
    if col == "ID":
        return (row.id or "—", None, None)
    return ("—", None, None)


@router.get("/export/excel")
def export_excel(
    validacao: str | None = None,
    fonte: str | None = None,
    db: Session = Depends(get_db),
):
    """Export analysis results as a formatted Excel spreadsheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    q = db.query(models.RegulatoryAnalysis)
    if validacao:
        q = q.filter(models.RegulatoryAnalysis.status_validacao == validacao)
    if fonte:
        q = q.filter(models.RegulatoryAnalysis.source_id == fonte)
    rows = q.order_by(models.RegulatoryAnalysis.created_at.desc()).all()

    headers = [
        "Data Publicação",
        "Entrada em Vigor",
        "Fonte",
        "Norma",
        "Assunto",
        "Aplicação",
        "Status",
        "Requisito",
        "Item",
        "Itens Modificados",
        "Ação Sugerida",
        "Validação",
        "Validado por",
        "URL Origem",
        "ID",
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Análise Regulatória"

    header_fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[1].height = 26

    # Data rows — valores traduzidos + cores semânticas
    for row_idx, row in enumerate(rows, 2):
        max_lines = 1
        for col_idx, header in enumerate(headers, 1):
            value, fill_color, font_color = _excel_value(header, row)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if fill_color:
                fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
                cell.fill = fill
            if font_color:
                cell.font = Font(color=font_color, bold=True, size=10)
            if header == "URL Origem" and value not in ("—", ""):
                cell.hyperlink = value
                cell.font = Font(color="0563C1", underline="single", size=10)
            width = _EXCEL_WIDTHS.get(header, 20)
            lines = max(1, -(-len(str(value)) // max(width - 2, 8)))
            max_lines = max(max_lines, lines)
        ws.row_dimensions[row_idx].height = min(15 * max_lines + 4, 150)

    # Column widths
    for col_idx, header in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = _EXCEL_WIDTHS.get(header, 20)

    # Freeze header + autofilter
    ws.freeze_panes = "A2"
    if rows:
        last = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A1:{last}{len(rows) + 1}"

    # ── Aba Legenda ────────────────────────────────────────────
    leg = wb.create_sheet("Legenda")
    leg.column_dimensions["A"].width = 26
    leg.column_dimensions["B"].width = 100
    wrap = Alignment(vertical="top", wrap_text=True)

    leg["A1"] = "Legenda — como ler esta planilha"
    leg["A1"].font = Font(bold=True, size=13, color="0D6EFD")

    def _section(r: int, text: str) -> int:
        fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
        cell = leg.cell(row=r, column=1, value=text)
        cell.font = Font(bold=True, size=11, color="FFFFFF")
        cell.fill = fill
        leg.cell(row=r, column=2).fill = fill
        return r + 1

    def _pairs(r: int, pairs: list[tuple[str, str]]) -> int:
        for code, meaning in pairs:
            a = leg.cell(row=r, column=1, value=code)
            a.font = Font(bold=True, size=10)
            a.alignment = wrap
            b = leg.cell(row=r, column=2, value=meaning)
            b.alignment = wrap
            leg.row_dimensions[r].height = max(15, 14 * (-(-len(meaning) // 96)))
            r += 1
        return r + 1

    r = 3
    r = _section(r, "Aplicação")
    r = _pairs(r, LEGENDA_APLICACAO)
    r = _section(r, "Status da Norma")
    r = _pairs(r, LEGENDA_STATUS)
    r = _section(r, "Assunto")
    r = _pairs(r, list(ASSUNTO_LABELS.items()))
    r = _section(r, "Validação Humana")
    r = _pairs(r, LEGENDA_VALIDACAO)
    r = _section(r, "Regra de Pertinência")
    cell = leg.cell(row=r, column=1, value=LEGENDA_REGRA)
    cell.alignment = wrap
    leg.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    leg.row_dimensions[r].height = 14 * (-(-len(LEGENDA_REGRA) // 120)) + 10

    # Save to buffer
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=regulatory_analysis.xlsx"},
    )
