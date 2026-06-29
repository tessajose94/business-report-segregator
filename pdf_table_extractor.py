"""
pdf_table_extractor.py
Extracts tables AND snapshots from a PDF.
Each PDF page is rendered ONCE and reused for all table crops on that page.
"""

import pdfplumber
import fitz
from PIL import Image

SNAPSHOT_DPI     = 150
MAX_WORD_WIDTH   = 6.4
TITLE_LOOKAHEAD  = 70


def extract_all_tables(pdf_path: str) -> list:
    results = []

    # Pre-render all pages once — keyed by page index
    rendered_pages = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            table_objs = page.find_tables()
            table_data = page.extract_tables()

            if not table_objs:
                continue

            # Render this page once and cache it
            page_idx = page_num - 1
            if page_idx not in rendered_pages:
                rendered_pages[page_idx] = _render_page(pdf_path, page_idx)

            img, pix_w, pix_h = rendered_pages[page_idx]
            sx = pix_w  / page.width
            sy = pix_h / page.height

            for idx, (tobj, tdata) in enumerate(zip(table_objs, table_data), start=1):
                if not tdata or len(tdata) < 1:
                    continue

                cleaned = [
                    [str(c).strip() if c is not None else "" for c in row]
                    for row in tdata
                ]

                x0, top, x1, bottom = tobj.bbox

                # Tight crop for Word report
                snapshot = _crop_from_image(img, x0, top, x1, bottom,
                                            sx, sy, pix_w, pix_h, pad=8)

                # Extended crop (title area above) for optional AI use
                title_top = max(0, top - TITLE_LOOKAHEAD)
                snapshot_with_title = _crop_from_image(img, x0, title_top, x1, bottom,
                                                       sx, sy, pix_w, pix_h, pad=4)

                results.append({
                    "page":                page_num,
                    "table_index":         idx,
                    "bbox":                tobj.bbox,
                    "all_rows":            cleaned,
                    "headers":             cleaned[0] if cleaned else [],
                    "rows":                cleaned[1:] if len(cleaned) > 1 else [],
                    "total_rows":          len(cleaned) - 1,
                    "total_cols":          len(cleaned[0]) if cleaned else 0,
                    "snapshot":            snapshot,
                    "snapshot_with_title": snapshot_with_title,
                    "source":              "pdf",
                })

    return results


def _render_page(pdf_path: str, page_idx: int):
    """Renders a single PDF page to a PIL image. Called once per page."""
    zoom = SNAPSHOT_DPI / 72
    doc  = fitz.open(pdf_path)
    page = doc[page_idx]
    pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img, pix.width, pix.height


def _crop_from_image(img, x0, top, x1, bottom, sx, sy, pix_w, pix_h, pad=8):
    """Crops a region from an already-rendered page image."""
    px0 = max(0, int(x0 * sx) - pad)
    py0 = max(0, int(top * sy) - pad)
    px1 = min(pix_w, int(x1 * sx) + pad)
    py1 = min(pix_h, int(bottom * sy) + pad)
    return img.crop((px0, py0, px1, py1))


def snapshot_word_width(snapshot) -> float:
    """Returns Word insertion width in inches, capped at MAX_WORD_WIDTH."""
    if snapshot is None:
        return 0.0
    return min(MAX_WORD_WIDTH, snapshot.size[0] / SNAPSHOT_DPI)
