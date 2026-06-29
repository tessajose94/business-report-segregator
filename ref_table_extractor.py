"""
ref_table_extractor.py
Extracts tables from a reference DOCX or PDF.
For DOCX: reads native Word tables.
For PDF:  uses pdfplumber.
Returns list of dicts with headers + sample rows.
"""

import os
import pdfplumber
from docx import Document


def extract_ref_tables(file_path: str) -> list:
    """
    Extracts tables from a reference document (DOCX or PDF).
    Returns:
    [
        {
            "index":       int,
            "headers":     [str, ...],
            "sample_rows": [[str, ...], ...],  # first 3 rows
            "total_rows":  int,
            "source":      "docx" | "pdf",
        }
    ]
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".docx", ".doc"):
        return _from_docx(file_path)
    elif ext == ".pdf":
        return _from_pdf(file_path)
    return []


def _from_docx(path: str) -> list:
    doc     = Document(path)
    results = []
    for i, table in enumerate(doc.tables, 1):
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(cells)
        if not rows:
            continue
        # Deduplicate merged cells (Word repeats merged cell text)
        headers = _dedup_headers(rows[0])
        results.append({
            "index":       i,
            "headers":     headers,
            "sample_rows": rows[1:4],
            "total_rows":  len(rows) - 1,
            "source":      "docx",
        })
    return results


def _from_pdf(path: str) -> list:
    results = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for i, table in enumerate(page.extract_tables() or [], 1):
                if not table or len(table) < 1:
                    continue
                cleaned = [[str(c or "").strip() for c in row] for row in table]
                headers = _dedup_headers(cleaned[0])
                results.append({
                    "index":       i,
                    "headers":     headers,
                    "sample_rows": cleaned[1:4],
                    "total_rows":  len(cleaned) - 1,
                    "source":      "pdf",
                })
    return results


def _dedup_headers(row: list) -> list:
    """Removes duplicate adjacent values (common in merged Word table headers)."""
    seen    = []
    headers = []
    for cell in row:
        if cell and cell not in seen:
            headers.append(cell)
            seen.append(cell)
        elif not cell:
            headers.append("")
    return headers
