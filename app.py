"""
app.py  —  Business Report Segregator
Flow:
  1. (Optional) Upload reference doc  → extract its table headers
  2. Upload PDF                        → extract tables + snapshots
  3. Cross-match headers               → find reference equivalent per table
  4. Claude generates summary          → using ONLY real data from the table
  5. Download Word report              → summary on top, snapshot below
Run: streamlit run app.py
"""

import streamlit as st
import tempfile, os
from datetime import datetime

from credentials_helper  import inject_credentials
from pdf_table_extractor import extract_all_tables
from ref_table_extractor import extract_ref_tables
from header_matcher      import match_pdf_to_reference
from summary_engine      import generate_summary, get_available_models
from word_output         import build_word_report

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Business Report Segregator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.main-header { font-size:2rem; font-weight:700; color:#1F497D; margin-bottom:.1rem; }
.sub-header  { font-size:.95rem; color:#666; margin-bottom:1.2rem; }
.cred-ok     { background:#f0f7ee; border-left:4px solid #4CAF50;
               padding:.6rem 1rem; border-radius:4px; font-size:.9rem; }
.cred-fail   { background:#fff0f0; border-left:4px solid #e53935;
               padding:.6rem 1rem; border-radius:4px; font-size:.9rem; }
.info-box    { background:#EBF3FB; border-left:4px solid #2E74B5;
               padding:.7rem 1rem; border-radius:4px; margin:.4rem 0; }
.ok-box      { background:#f0f7ee; border-left:4px solid #4CAF50;
               padding:.7rem 1rem; border-radius:4px; margin:.4rem 0; }
.warn-box    { background:#fff8e1; border-left:4px solid #f9a825;
               padding:.7rem 1rem; border-radius:4px; margin:.4rem 0; }
.match-row   { padding:.4rem .8rem; border-radius:4px; margin:.2rem 0;
               background:#f8f9fa; font-size:.9rem; }
.summary-box { background:#EBF3FB; border-radius:6px;
               padding:.7rem 1rem; margin-bottom:.6rem; }
</style>
""", unsafe_allow_html=True)

# ── Credentials (once per session) ────────────────────────────────────────────
if "cred_ok" not in st.session_state:
    try:
        with st.spinner("🔐 Fetching AWS credentials..."):
            ok, msg, identity = inject_credentials()
    except Exception as e:
        ok, msg, identity = False, f"Credential error: {str(e)}", ""
    st.session_state.update(cred_ok=ok, cred_msg=msg, cred_identity=identity)

cred_ok = st.session_state["cred_ok"]

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️  Settings")
    st.markdown("---")

    # AWS status
    st.markdown("### 🔐 AWS Status")
    if cred_ok:
        st.markdown(
            f'<div class="cred-ok">✅ <b>Connected</b><br>'
            f'{st.session_state["cred_identity"]}</div>',
            unsafe_allow_html=True,
        )
        if st.button("🔄 Refresh credentials", use_container_width=True):
            for k in ("cred_ok", "cred_msg", "cred_identity"):
                st.session_state.pop(k, None)
            st.rerun()
    else:
        st.markdown(
            f'<div class="cred-fail">❌ <b>Not connected</b><br>'
            f'{st.session_state["cred_msg"]}</div>',
            unsafe_allow_html=True,
        )
        if st.button("🔄 Retry", use_container_width=True):
            for k in ("cred_ok", "cred_msg", "cred_identity"):
                st.session_state.pop(k, None)
            st.rerun()
        st.caption("Run `mwinit -o` in Terminal then click Retry.")

    st.markdown("---")
    st.markdown("### 🌍 Bedrock Region")
    region = st.selectbox("Region",
        ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"])

    st.markdown("### 🤖 Claude Model")
    model_map = get_available_models()
    model_id = model_map[st.selectbox("Model", list(model_map.keys()))]

    st.markdown("### 🎨 Summary Tone")
    tone_choice = st.selectbox("Tone", [
        "Professional",
        "Executive (brief)",
        "Detailed & analytical",
        "Casual / plain English",
    ], index=0)

    st.markdown("---")
    match_threshold = st.slider(
        "Header match threshold", 0.05, 0.5, 0.15, 0.05,
        help="Lower = more tables matched; Higher = stricter matching",
    )
    show_unmatched = st.checkbox("Include unmatched tables in report", value=True)

    st.markdown("---")
    st.markdown("""
**How it works:**
1. (Optional) Upload reference doc
2. Upload PDF
3. Headers cross-compared automatically
4. Claude summarises using real table data
5. Download Word report
""")

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown('<p class="main-header">📊 Business Report Segregator</p>',
            unsafe_allow_html=True)


if not cred_ok:
    st.error("⚠️ AWS credentials unavailable. Run `mwinit -o` in Terminal then click Retry in sidebar.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Reference document (OPTIONAL)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("## 📎 Step 1 — Reference Document  *(Optional)*")
st.markdown(
    '<div class="info-box">'
    'Upload a reference DOCX or PDF that contains tables with similar headers to your input PDF. '
    'The app will cross-compare headers and use the reference to guide Claude\'s summary style. '
    '<b>Leave blank</b> to skip — summaries will still be generated from the PDF data.'
    '</div>', unsafe_allow_html=True)

ref_file   = st.file_uploader("Reference document (DOCX or PDF)",
                               type=["docx", "pdf"], key="ref_upload")
ref_tables = []
ref_name   = None
ref_style_example = None

if ref_file:
    with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=os.path.splitext(ref_file.name)[1]) as t:
        t.write(ref_file.read())
        ref_tmp = t.name

    with st.spinner("Reading reference document..."):
        ref_tables = extract_ref_tables(ref_tmp)
    os.unlink(ref_tmp)

    ref_name = ref_file.name
    st.metric("📋 Tables found in reference", len(ref_tables))

    if ref_tables:
        with st.expander("🔍 Reference table headers", expanded=False):
            for rt in ref_tables:
                hdrs = ", ".join(str(h) for h in rt["headers"][:8] if str(h).strip())
                st.markdown(f'**Ref Table {rt["index"]}:** {hdrs}')
    else:
        st.markdown('<div class="warn-box">⚠️ No tables found in reference document — will use default style</div>',
                    unsafe_allow_html=True)
else:
    st.markdown(
        '<div class="warn-box">i️ No reference document — '
        'all PDF tables will be summarised using default style.</div>',
        unsafe_allow_html=True)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Input PDF
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("## 📤 Step 2 — Upload PDF")

pdf_file = st.file_uploader("Input PDF", type=["pdf"], key="pdf_upload")
pdf_tables   = None
pdf_name     = None
user_context = ""

if pdf_file:
    pdf_name = pdf_file.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as t:
        t.write(pdf_file.read())
        pdf_tmp = t.name

    with st.spinner("Extracting tables from PDF..."):
        pdf_tables = extract_all_tables(pdf_tmp)
    os.unlink(pdf_tmp)

    st.metric("📋 Tables found", len(pdf_tables))

    if pdf_tables:
        with st.expander("🔍 PDF table headers", expanded=False):
            for pt in pdf_tables:
                hdrs = ", ".join(str(h) for h in pt["headers"][:8] if str(h).strip())
                st.markdown(
                    f'**Table {pt["table_index"]}** '
                    f'({pt["total_rows"]} rows × {pt["total_cols"]} cols): {hdrs}')
    else:
        st.warning("⚠️ No tables detected in this PDF.")

if pdf_tables:
    st.markdown("#### 💬 Additional Instructions *(optional)*")
    user_context = st.text_area(
        label       = "Any specific focus, exclusions, or context for the AI summaries?",
        placeholder = "e.g. Focus on sites that are over budget. Ignore March data. Highlight US_East region only.",
        height      = 90,
        key         = "user_context_input",
    )

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Generate
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("## 🚀 Step 3 — Generate Report")

can_run = pdf_tables is not None and len(pdf_tables) > 0

if not can_run:
    st.markdown('<div class="warn-box">⚠️ Upload a PDF above to enable report generation.</div>',
                unsafe_allow_html=True)

if st.button("🚀 Generate Report", type="primary",
             use_container_width=True, disabled=not can_run):

    # ── A: Header cross-matching ───────────────────────────────────────────
    with st.spinner("🔗 Cross-comparing headers..."):
        enriched = match_pdf_to_reference(
            pdf_tables, ref_tables, threshold=match_threshold
        )

    # Show match results
    st.markdown("### 🔗 Header Matching Results")
    matched_count   = sum(1 for t in enriched if t["ref_match"])
    unmatched_count = len(enriched) - matched_count

    c1, c2, c3 = st.columns(3)
    c1.metric("Total tables",    len(enriched))
    c2.metric("✅ Matched",       matched_count)
    c3.metric("⬜ No ref match",  unmatched_count)

    with st.expander("🔍 Matching details", expanded=True):
        for t in enriched:
            pdf_hdrs = ", ".join(str(h) for h in t["headers"][:5] if str(h).strip())
            if t["ref_match"]:
                ref_hdrs = ", ".join(
                    str(h) for h in t["ref_match"]["headers"][:5] if str(h).strip()
                )
                score = int(t["match_score"] * 100)
                st.markdown(
                    f'<div class="match-row">'
                    f'✅ <b>PDF Table {t["table_index"]}</b>: {pdf_hdrs}<br>'
                    f'&nbsp;&nbsp;&nbsp;↔ Ref: {ref_hdrs} &nbsp; <i>(score: {score}%)</i>'
                    f'</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div class="match-row">'
                    f'⬜ <b>PDF Table {t["table_index"]}</b>: {pdf_hdrs} '
                    f'— no reference match'
                    f'</div>', unsafe_allow_html=True)

    # Decide which tables to process
    to_process = enriched if show_unmatched else [t for t in enriched if t["ref_match"]]
    if not to_process:
        st.warning("No tables to process. Lower the match threshold or enable 'Include unmatched tables'.")
        st.stop()

    # ── B: Generate summaries ──────────────────────────────────────────────
    st.markdown("### 🤖 Generating Summaries")
    progress = st.progress(0, text="Starting...")
    status   = st.empty()
    total    = len(to_process)

    for i, table in enumerate(to_process):
        label = table.get("match_label") or f"Table {table['table_index']}"
        status.text(f"Summarising Table {i+1}/{total}: {label[:60]}...")

        # Get reference style example if matched
        ref_example = None
        if table["ref_match"]:
            sample = table["ref_match"].get("sample_rows", [])
            if sample:
                ref_example = "Reference table rows:\n" + "\n".join(
                    " | ".join(str(c) for c in row[:8]) for row in sample[:3]
                )

        table["summary"] = generate_summary(
            table               = table,
            ref_example_summary = ref_example,
            model_id            = model_id,
            region              = region,
            tone                = tone_choice,
            user_context        = user_context if user_context.strip() else None,
        )

        progress.progress((i + 1) / total,
                          text=f"Done {i+1}/{total}")

    status.empty()
    progress.empty()
    st.success(f"✅ Summaries generated for {total} table(s)")

    # ── C: Preview ─────────────────────────────────────────────────────────
    st.markdown("### 📊 Preview")
    for i, table in enumerate(to_process, 1):
        label   = table.get("match_label") or f"Table {table['table_index']}"
        summary = table.get("summary", [])
        with st.expander(f"Table {i}  |  {label}", expanded=(i == 1)):
            # Summary
            st.markdown("**Summary:**")
            html = "<div class='summary-box'><ul>"
            for b in summary:
                html += f"<li>{b}</li>"
            html += "</ul></div>"
            st.markdown(html, unsafe_allow_html=True)

            # Snapshot + data side by side
            col_a, col_b = st.columns([1, 1])
            with col_a:
                st.markdown("**Snapshot:**")
                if table.get("snapshot"):
                    st.image(table["snapshot"], use_container_width=True)
            with col_b:
                st.markdown("**Data preview:**")
                import pandas as pd
                try:
                    df = pd.DataFrame(
                        table.get("rows", table.get("all_rows", [[]])[1:]),
                        columns=table.get("headers", [])
                    )
                    st.dataframe(df.head(10), use_container_width=True)
                except Exception:
                    st.caption("Could not render as dataframe.")

    # ── D: Build & download Word doc ───────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📥 Download Report")
    with st.spinner("Building Word document..."):
        word_bytes = build_word_report(
            tables       = to_process,
            pdf_filename = pdf_name,
            ref_filename = ref_name,
        )

    out_name = (pdf_name or "report").replace(".pdf", "_table_report.docx")
    st.download_button(
        label    = "⬇️  Download Word Report (.docx)",
        data     = word_bytes,
        file_name= out_name,
        mime     = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type     = "primary",
        use_container_width=True,
    )
    st.balloons()
    st.success(
        f"🎉 Report ready! {total} table(s) — "
        f"{matched_count} matched to reference, "
        f"{unmatched_count} with default style."
    )
