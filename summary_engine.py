"""
summary_engine.py
- generate_summary : AI bullet-point summary with tone + optional user context
- identify_header  : AI header identification from snapshot (available but not active)
Both use Amazon Bedrock (Claude) via inference profile IDs.
"""

import boto3
import json
import base64
import io
from botocore.exceptions import ClientError

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

TONE_INSTRUCTIONS = {
    "Professional": (
        "Write in a professional business tone. "
        "Be precise and factual. Use clear, concise language suitable for a business report."
    ),
    "Executive (brief)": (
        "Write for a senior executive audience. "
        "Be extremely concise — lead with the most important insight. "
        "Limit to 3-4 bullets maximum. No jargon."
    ),
    "Detailed & analytical": (
        "Write in a detailed analytical tone. "
        "Explain variances, trends, and outliers with context. "
        "Include as much relevant numerical detail as possible. Use up to 6 bullets."
    ),
    "Casual / plain English": (
        "Write in plain, simple English — as if explaining to a non-finance colleague. "
        "Avoid jargon. Use everyday language. Keep it friendly and easy to read."
    ),
}


def generate_summary(
    table:               dict,
    ref_example_summary: str  = None,
    model_id:            str  = DEFAULT_MODEL,
    region:              str  = "us-east-1",
    tone:                str  = "Professional",
    user_context:        str  = None,
) -> list:
    table_text = _format_table(table)
    prompt     = _build_prompt(table_text, ref_example_summary, tone, user_context)

    try:
        client = boto3.client("bedrock-runtime", region_name=region)
        body   = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "messages": [{"role": "user", "content": prompt}],
        })
        response = client.invoke_model(
            modelId=model_id, body=body,
            contentType="application/json", accept="application/json",
        )
        raw = json.loads(response["body"].read())["content"][0]["text"].strip()
        return _parse_bullets(raw)

    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg  = e.response["Error"]["Message"]
        if code == "AccessDeniedException":
            return ["Bedrock access denied — enable model in Bedrock Console → Model Access."]
        if code in ("ResourceNotFoundException", "ValidationException"):
            return [f"Model error: {msg}"]
        return [f"AWS error ({code}): {msg}"]
    except Exception as e:
        return [f"Summary failed: {str(e)}"]


def _build_prompt(
    table_text:  str,
    ref_example: str = None,
    tone:        str = "Professional",
    user_context: str = None,
) -> str:
    tone_instruction = TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["Professional"])

    style_section = ""
    if ref_example:
        style_section = f"""
=== REFERENCE STYLE (match this tone and level of detail) ===
{ref_example[:800]}
=== END REFERENCE ===

"""

    context_section = ""
    if user_context:
        context_section = f"""
=== ADDITIONAL INSTRUCTIONS FROM USER ===
{user_context.strip()}
=== END INSTRUCTIONS ===

"""

    return f"""You are an operations analyst. Analyze the table data below and write a concise summary.

TONE: {tone_instruction}
{style_section}{context_section}
=== TABLE DATA ===
{table_text}
=== END TABLE DATA ===

STRICT RULES:
- Every number, percentage, site name, or value you mention MUST come directly from the table above
- Do NOT invent or assume any data not present in the table
- Write 4 to 6 bullet points, each 1-2 sentences (fewer if Executive tone)
- Focus on: key totals, notable variances (over/under budget), trends, outliers
- Use plain text — no markdown bold, no headers
- Start each bullet with a dash (-)
- If the table shows Budget vs Actuals, highlight sites significantly over or under budget
- If the user gave additional instructions above, follow them precisely

Summary:"""


def _format_table(table: dict) -> str:
    headers  = table.get("headers", [])
    all_rows = table.get("all_rows", [])
    rows     = table.get("rows", all_rows[1:] if len(all_rows) > 1 else [])

    lines = [" | ".join(str(h) for h in headers[:16])]
    lines.append("-" * 80)
    for row in rows[:40]:
        line = " | ".join(str(c) for c in row[:16])
        if line.strip(" |"):
            lines.append(line)
    if len(rows) > 40:
        lines.append(f"... and {len(rows) - 40} more rows")
    return "\n".join(lines)


def _parse_bullets(raw: str) -> list:
    bullets = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line[0] in ("-", "•", "*", "–", "—"):
            bullets.append(line[1:].strip())
        elif line[0].isdigit() and len(line) > 2 and line[1] in (".", ")"):
            bullets.append(line[2:].strip())
        elif line and not line.startswith("#") and not line.startswith("==="):
            bullets.append(line)
    return bullets if bullets else ["No summary generated."]


def identify_header(
    snapshot,
    model_id: str = DEFAULT_MODEL,
    region:   str = "us-east-1",
) -> str:
    """Available but not active in current flow."""
    if snapshot is None:
        return None
    try:
        buf = io.BytesIO()
        snapshot.save(buf, format="PNG")
        img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        client  = boto3.client("bedrock-runtime", region_name=region)
        body    = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": (
                        "What is the section title or report name shown in the header "
                        "row or just above the table? Reply with ONLY the title text. "
                        "If no clear title, reply: NONE"
                    )},
                ],
            }],
        })
        response = client.invoke_model(modelId=model_id, body=body,
                                       contentType="application/json", accept="application/json")
        result = json.loads(response["body"].read())["content"][0]["text"].strip()
        return None if result.upper() == "NONE" else result.strip('"\'')
    except Exception:
        return None


def get_available_models() -> dict:
    return {
        "Claude Sonnet 4.6 (Recommended)": "us.anthropic.claude-sonnet-4-6",
        "Claude Haiku 4.5 (Fast)":          "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "Claude Sonnet 4.5":                "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "Claude Opus 4.6 (Most capable)":   "us.anthropic.claude-opus-4-6-v1",
    }
