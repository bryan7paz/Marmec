"""Move downloads antigos (data/<fonte>/<hash>.pdf) para data/downloads/.

Layout novo: data/downloads/<fonte>/<Título> [hash8].ext — nome legível para
o usuário localizar e apagar quando quiser. Idempotente: rodar de novo não
move nada. Arquivos renomeados usam a `norma` do banco (match por hash).
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from core.config import logger

from crawler.storage import DATA_DIR, DOWNLOADS_SUBDIR, sanitize_filename

SKIP_DIRS = {DOWNLOADS_SUBDIR, "logs", "__pycache__"}
_EXTS = {".pdf", ".html"}
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def _norma_map(db_path: Path) -> dict[str, str]:
    """Mapa hash16 -> norma, lido do banco (somente leitura)."""
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT documento_hash, norma FROM regulatory_analysis "
                "WHERE documento_hash IS NOT NULL AND norma IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("Migração: banco indisponível (%s) — renomeia sem norma", exc)
        return {}
    return {h[:16]: n for h, n in rows if h and n}


def _target_name(path: Path, norma_map: dict[str, str]) -> str:
    """Nome de destino: '<norma> [hash8].ext' se achar norma, senão original."""
    stem = path.stem
    if _HEX16.match(stem) and stem in norma_map:
        ext = path.suffix
        readable = sanitize_filename(norma_map[stem], "", ext)[: -len(ext)]
        return f"{readable} [{stem[:8]}]{ext}"
    return path.name


def migrate_downloads() -> dict[str, Any]:
    """Move arquivos da raiz das fontes para data/downloads/. Idempotente."""
    stats: dict[str, Any] = {"moved": 0, "renamed": 0, "removed": 0}
    if not DATA_DIR.is_dir():
        return stats

    norma_map = _norma_map(DATA_DIR / "regulatory.db")
    mapping: dict[str, str] = {}

    for src_dir in sorted(DATA_DIR.iterdir()):
        if not src_dir.is_dir() or src_dir.name in SKIP_DIRS:
            continue
        dest_dir = DATA_DIR / DOWNLOADS_SUBDIR / src_dir.name
        for f in sorted(src_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _EXTS:
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            new_name = _target_name(f, norma_map)
            dest = dest_dir / new_name
            if dest.exists():
                # mesmo conteúdo já migrado (hash igual) — descarta a cópia
                f.unlink()
                stats["removed"] += 1
            else:
                shutil.move(str(f), str(dest))
                stats["moved"] += 1
                if new_name != f.name:
                    stats["renamed"] += 1
            mapping[str(f)] = str(dest)
        with contextlib.suppress(OSError):
            src_dir.rmdir()  # só esvazia se não sobrou nada (backups etc.)

    if mapping:
        _update_queue_paths(mapping)
        logger.info(
            "Migração de downloads: %d movidos (%d renomeados), %d duplicatas removidas",
            stats["moved"],
            stats["renamed"],
            stats["removed"],
        )
    return stats


def _update_queue_paths(mapping: dict[str, str]) -> None:
    """Reaponta local_path da fila pendente para os arquivos movidos."""
    queue_path = DATA_DIR / "queue.jsonl"
    if not queue_path.exists():
        return
    lines = queue_path.read_text(encoding="utf-8").splitlines()
    changed = False
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        old = entry.get("local_path", "")
        if old in mapping:
            entry["local_path"] = mapping[old]
            out.append(json.dumps(entry, ensure_ascii=False))
            changed = True
        else:
            out.append(line)
    if changed:
        queue_path.write_text("\n".join(out) + "\n", encoding="utf-8")
