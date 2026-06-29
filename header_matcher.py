"""
header_matcher.py
Cross-compares PDF table headers with reference document table headers.
Uses fuzzy string matching — no external libraries needed.
"""

import re


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse spaces."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def header_similarity(headers_a: list, headers_b: list) -> float:
    """
    Returns similarity score 0.0–1.0 between two header lists.
    Based on token overlap after normalization.
    """
    # Flatten all tokens from both header lists
    tokens_a = set()
    for h in headers_a:
        tokens_a.update(normalize(str(h)).split())

    tokens_b = set()
    for h in headers_b:
        tokens_b.update(normalize(str(h)).split())

    # Remove very common stop words
    stopwords = {'the', 'a', 'an', 'of', 'in', 'to', 'and', 'or',
                 'for', 'is', 'by', 'as', 'at', 'on', 'none', ''}
    tokens_a -= stopwords
    tokens_b -= stopwords

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union        = tokens_a | tokens_b
    return len(intersection) / len(union)


def match_pdf_to_reference(pdf_tables: list, ref_tables: list,
                            threshold: float = 0.15) -> list:
    """
    For each PDF table, finds the best matching reference table by header similarity.
    Returns enriched PDF tables list:
    [
        {
            ...all original pdf_table fields...,
            "ref_match":       ref_table dict or None,
            "match_score":     float,
            "match_label":     str,   # e.g. "Employee Relations ↔ AGL Employee Relations"
        }
    ]
    If no reference provided, all tables are returned with ref_match=None.
    """
    results = []

    for pdf_table in pdf_tables:
        pdf_headers = [str(h) for h in pdf_table.get("headers", [])]
        # Also include first data row headers for better matching
        all_rows = pdf_table.get("all_rows", [])
        if len(all_rows) > 1:
            pdf_headers += [str(c) for c in all_rows[1]]

        best_ref   = None
        best_score = 0.0

        for ref_table in (ref_tables or []):
            ref_headers = [str(h) for h in ref_table.get("headers", [])]
            score = header_similarity(pdf_headers, ref_headers)
            if score > best_score:
                best_score = ref_table
                best_score = score
                best_ref   = ref_table

        if best_ref and best_score >= threshold:
            pdf_label = " / ".join(h for h in pdf_headers[:3] if h.strip())
            ref_label = " / ".join(h for h in best_ref.get("headers", [])[:3]
                                   if str(h).strip())
            label = f"{pdf_label}  ↔  {ref_label}"
            results.append({
                **pdf_table,
                "ref_match":   best_ref,
                "match_score": best_score,
                "match_label": label,
            })
        else:
            pdf_label = " / ".join(h for h in pdf_headers[:3] if h.strip())
            results.append({
                **pdf_table,
                "ref_match":   None,
                "match_score": best_score,
                "match_label": pdf_label or f"Table {pdf_table.get('table_index','')}",
            })

    return results
