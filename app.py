"""FactChecker AI — Streamlit fact-checking web application."""

from __future__ import annotations

from html import escape

import streamlit as st

from src.config import create_gemini_client, reload_settings, validate_settings
from src.fact_checker import FactChecker
from src.pdf_extractor import PDFExtractionError, extract_text_from_pdf
from src.report_generator import (
    generate_csv_report,
    generate_html_report,
    generate_json_report,
    generate_markdown_report,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="FactChecker AI",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — modern SaaS aesthetic
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.main .block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1100px;
}

.hero {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px;
    padding: 2.5rem 2rem;
    color: white;
    margin-bottom: 2rem;
    box-shadow: 0 10px 40px rgba(102, 126, 234, 0.25);
}
.hero h1 { margin: 0 0 0.5rem 0; font-size: 2.2rem; font-weight: 700; }
.hero p  { margin: 0; opacity: 0.92; font-size: 1.05rem; }

.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1.25rem 1rem;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.metric-card .value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
}
.metric-card .label {
    font-size: 0.8rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.25rem;
}
.metric-trust .value { color: #2563eb; }
.metric-source .value { color: #7c3aed; }
.metric-verified .value { color: #059669; }
.metric-inaccurate .value { color: #d97706; }
.metric-false .value { color: #dc2626; }

.claim-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.claim-card h4 { margin-top: 0; color: #1e293b; }

.status-verified  { background:#d1fae5; color:#065f46; padding:0.25rem 0.75rem; border-radius:999px; font-weight:600; font-size:0.8rem; }
.status-inaccurate{ background:#fef3c7; color:#92400e; padding:0.25rem 0.75rem; border-radius:999px; font-weight:600; font-size:0.8rem; }
.status-false     { background:#fee2e2; color:#991b1b; padding:0.25rem 0.75rem; border-radius:999px; font-weight:600; font-size:0.8rem; }

.fact-box {
    background: #f8fafc;
    border-left: 4px solid #2563eb;
    padding: 1rem 1.25rem;
    border-radius: 0 8px 8px 0;
    margin: 1rem 0;
}

.upload-zone {
    border: 2px dashed #cbd5e1;
    border-radius: 12px;
    padding: 2rem;
    text-align: center;
    background: #f8fafc;
}

.sidebar-info {
    background: #f1f5f9;
    border-radius: 8px;
    padding: 1rem;
    font-size: 0.85rem;
    color: #475569;
}

#MainMenu, footer { visibility: hidden; }
</style>
""",
    unsafe_allow_html=True,
)


def render_hero() -> None:
    st.markdown(
        """
<div class="hero">
  <h1>🔍 FactChecker AI</h1>
  <p>Upload a PDF to extract claims, verify them against live web data, and download a full report.</p>
</div>
""",
        unsafe_allow_html=True,
    )


def render_metric(label: str, value: str, css_class: str) -> None:
    st.markdown(
        f"""
<div class="metric-card {css_class}">
  <div class="value">{value}</div>
  <div class="label">{label}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> str:
    css = status.lower()
    return f'<span class="status-{css}">{status}</span>'


def render_claim_card(claim, index: int) -> None:
    sources_html = ""
    if claim.source_urls:
        links = "".join(
            f'<li><a href="{escape(url)}" target="_blank">{escape(url)}</a></li>'
            for url in claim.source_urls
        )
        sources_html = f"<ul style='margin:0.5rem 0'>{links}</ul>"

    details_html = ""
    if claim.source_details:
        rows = "".join(
            f"<li>{escape(str(d['domain']))} — {escape(str(d['category']))} "
            f"({d['credibility_score']}/100)</li>"
            for d in claim.source_details
        )
        details_html = f"<ul style='font-size:0.85rem;color:#64748b'>{rows}</ul>"

    st.markdown(
        f"""
<div class="claim-card">
  <h4>Claim {index}: {escape(claim.claim)}</h4>
  <p>{status_badge(claim.status)}
     &nbsp;·&nbsp; Type: <strong>{escape(claim.claim_type)}</strong>
     &nbsp;·&nbsp; Confidence: <strong>{claim.confidence_score}%</strong>
     &nbsp;·&nbsp; Source Credibility: <strong>{claim.source_credibility_score}/100</strong>
  </p>
  <div class="fact-box">
    <strong>✅ Correct Fact</strong><br/>{escape(claim.correct_fact)}
  </div>
  <p style="color:#64748b;font-size:0.9rem"><em>{escape(claim.reasoning)}</em></p>
  <strong>Sources</strong>
  {sources_html or '<p><em>No sources cited</em></p>'}
  {details_html}
</div>
""",
        unsafe_allow_html=True,
    )


def main() -> None:
    settings = reload_settings()
    missing = validate_settings(settings)

    # ---- Sidebar ----
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/search.png", width=64)
        st.title("FactChecker AI")
        st.caption("Powered by Gemini + Google Search")

        st.markdown("---")
        st.subheader("How it works")
        st.markdown(
            """
1. **Upload** a PDF document
2. **Extract** factual claims with Gemini
3. **Verify** each claim via Gemini Google Search grounding
4. **Review** trust scores & download report
"""
        )

        st.markdown("---")
        st.subheader("Source Credibility")
        st.markdown(
            """
| Source | Score |
|--------|-------|
| Government | 100 |
| Research Paper | 90 |
| Major News | 75 |
| Blog | 50 |
"""
        )

        if missing:
            st.error(f"Missing API keys: {', '.join(missing)}")
            st.markdown(
                """
<div class="sidebar-info">
Set keys in <code>.env</code> locally or
Streamlit Cloud <strong>Secrets</strong>.
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            st.success("API keys configured ✓")

    render_hero()

    if missing:
        st.warning(
            "Configure `GEMINI_API_KEY` in your `.env` file "
            "or Streamlit Cloud secrets before running an analysis."
        )
        st.code(
            "GEMINI_API_KEY=your_gemini_key",
            language="toml",
        )
        return

    # ---- Upload ----
    st.subheader("📄 Upload Document")
    uploaded = st.file_uploader(
        "Drop your PDF here or click to browse",
        type=["pdf"],
        help="Text-based PDFs work best. Scanned/image PDFs may not extract text.",
    )

    analyze = st.button("🚀 Analyze Document", type="primary", disabled=uploaded is None)

    if not uploaded:
        st.markdown(
            """
<div class="upload-zone">
  <p style="font-size:3rem;margin:0">📑</p>
  <p style="color:#64748b">Upload a PDF to begin fact-checking</p>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    if not analyze and "report" not in st.session_state:
        st.info(f"Ready to analyze **{uploaded.name}** ({uploaded.size / 1024:.1f} KB). Click **Analyze Document**.")
        return

    if analyze or "report" in st.session_state:
        if analyze:
            st.session_state.pop("report", None)

        if "report" not in st.session_state:
            progress_bar = st.progress(0, text="Starting analysis...")
            status_text = st.empty()

            def on_progress(message: str, fraction: float) -> None:
                progress_bar.progress(fraction, text=message)
                status_text.caption(message)

            try:
                analysis_settings = reload_settings()
                pdf_bytes = uploaded.read()
                document_text, page_count = extract_text_from_pdf(
                    pdf_bytes,
                    max_pages=analysis_settings.max_pdf_pages,
                )
                gemini = create_gemini_client()
                checker = FactChecker(
                    gemini,
                    max_claims=analysis_settings.max_claims,
                )

                report = checker.run(
                    document_text,
                    filename=uploaded.name,
                    page_count=page_count,
                    progress_callback=on_progress,
                )
                st.session_state["report"] = report

            except PDFExtractionError as exc:
                st.error(str(exc))
                return
            except ValueError as exc:
                st.error(str(exc))
                return
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")
                return
            finally:
                progress_bar.empty()
                status_text.empty()

        report = st.session_state["report"]

        # ---- Summary metrics ----
        st.subheader("📊 Analysis Summary")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            render_metric("Trust Score", f"{report.trust_score}", "metric-trust")
        with c2:
            render_metric("Source Credibility", f"{report.source_credibility_score}", "metric-source")
        with c3:
            render_metric("Verified", str(report.verified_count), "metric-verified")
        with c4:
            render_metric("Inaccurate", str(report.inaccurate_count), "metric-inaccurate")
        with c5:
            render_metric("False", str(report.false_count), "metric-false")

        st.caption(
            f"Document: **{report.filename}** · {report.page_count} pages · "
            f"{len(report.claims)} claims · Generated {report.generated_at}"
        )

        # ---- Download reports ----
        st.subheader("📥 Download Report")
        base_name = report.filename.rsplit(".", 1)[0]

        dl1, dl2, dl3, dl4 = st.columns(4)
        with dl1:
            st.download_button(
                "⬇️ Markdown",
                generate_markdown_report(report),
                file_name=f"{base_name}_factcheck.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "⬇️ HTML",
                generate_html_report(report),
                file_name=f"{base_name}_factcheck.html",
                mime="text/html",
                use_container_width=True,
            )
        with dl3:
            st.download_button(
                "⬇️ JSON",
                generate_json_report(report),
                file_name=f"{base_name}_factcheck.json",
                mime="application/json",
                use_container_width=True,
            )
        with dl4:
            st.download_button(
                "⬇️ CSV",
                generate_csv_report(report),
                file_name=f"{base_name}_factcheck.csv",
                mime="text/csv",
                use_container_width=True,
            )

        # ---- Claim details ----
        st.subheader("🔎 Claim-by-Claim Results")
        for idx, claim in enumerate(report.claims, start=1):
            render_claim_card(claim, idx)

        if st.button("🔄 Analyze a New Document"):
            st.session_state.pop("report", None)
            st.rerun()


if __name__ == "__main__":
    main()
