from __future__ import annotations

import html
import json
import threading
from datetime import datetime
from pathlib import Path
from textwrap import dedent

import streamlit as st

from comicpublish.config import ConfigError, load_workflow_config, workflow_env_status
from comicpublish.runner import (
    load_background_run,
    regenerate_page_image,
    snapshot_is_terminal,
    start_background_run,
)
from comicpublish.studio import (
    AUDIENCE_OPTIONS,
    DEFAULT_SOURCE_TEXT,
    DEFAULT_TONE_NOTES,
    LANGUAGE_OPTIONS,
    STYLE_PRESETS,
    WORKFLOW_PRESETS,
    StudioRequest,
    humanize_bytes,
)

APP_NAME = "AtSolution Comic Studio"
STEP_LABELS = (
    ("01 · Validate", "Source text and run settings passed preflight."),
    ("02 · Dispatch", "Payload sent to the backend target."),
    ("03 · Generate", "Page scripts and image calls execute in the runner."),
    ("04 · Save", "Manifest and local project files are preserved for review."),
    ("05 · Review", "Operator can inspect pages before export."),
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --paper: #f6f0e7;
          --paper-2: #fbf7f1;
          --ink: #161412;
          --ink-muted: #5f5851;
          --border: #2b2723;
          --red: #cf4c36;
          --cyan: #6ea7a3;
          --green: #2f6b45;
          --amber: #b7791f;
          --shadow: 0 10px 30px rgba(22, 20, 18, 0.10);
          --radius: 18px;
          --mono: "SFMono-Regular", "JetBrains Mono", "IBM Plex Mono", Menlo, monospace;
          --body: "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
          --display: "Arial Narrow", "HelveticaNeue-CondensedBold", "Franklin Gothic Condensed", Impact, sans-serif;
        }

        html, body, [class*="css"]  {
          font-family: var(--body);
        }

        .stApp {
          background:
            radial-gradient(circle at 12% 18%, rgba(207, 76, 54, 0.06) 0 1px, transparent 1px) 0 0 / 16px 16px,
            radial-gradient(circle at 84% 12%, rgba(22, 20, 18, 0.05) 0 1px, transparent 1px) 0 0 / 14px 14px,
            linear-gradient(180deg, var(--paper-2), var(--paper));
          color: var(--ink);
        }

        [data-testid="stHeader"] {
          background: transparent;
        }

        [data-testid="stAppViewContainer"] > .main {
          padding-top: 0.6rem;
        }

        .block-container {
          max-width: 1540px;
          padding-top: 0.6rem;
          padding-bottom: 2.2rem;
        }

        .page-shell {
          border: 2px solid var(--border);
          border-radius: 26px;
          overflow: hidden;
          background: rgba(255, 255, 255, 0.62);
          box-shadow: 0 28px 60px rgba(22, 20, 18, 0.14);
          backdrop-filter: blur(10px);
        }

        .desk-topbar {
          display: grid;
          grid-template-columns: auto 1fr auto;
          gap: 18px;
          align-items: center;
          padding: 18px 22px;
          border-bottom: 2px solid var(--border);
          background:
            linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0.15)),
            linear-gradient(90deg, rgba(110,167,163,0.08), transparent 28%);
        }

        .traffic {
          display: inline-flex;
          gap: 7px;
          align-items: center;
        }

        .traffic span {
          width: 12px;
          height: 12px;
          border: 1px solid var(--border);
          border-radius: 999px;
          background: rgba(22, 20, 18, 0.08);
        }

        .topbar-title {
          font: 34px/0.92 var(--display);
          letter-spacing: 0.01em;
          text-transform: uppercase;
        }

        .topbar-subtitle {
          margin-top: 4px;
          color: var(--ink-muted);
          font: 11px/1 var(--mono);
          letter-spacing: 0.1em;
          text-transform: uppercase;
        }

        .badge-row {
          display: flex;
          gap: 10px;
          align-items: center;
          flex-wrap: wrap;
          justify-content: flex-end;
        }

        .pill {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 7px 12px;
          border-radius: 999px;
          border: 1.5px solid currentColor;
          font: 11px/1 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
          background: rgba(255, 255, 255, 0.72);
        }

        .pill.success { color: var(--green); }
        .pill.warn { color: var(--amber); }
        .pill.ink { color: var(--ink); }
        .pill.signal { color: var(--cyan); }

        .caption-bar {
          display: inline-flex;
          align-items: center;
          width: fit-content;
          padding: 8px 14px;
          background: var(--ink);
          color: white;
          transform: skew(-16deg);
          font: 11px/1 var(--mono);
          letter-spacing: 0.1em;
          text-transform: uppercase;
        }

        .caption-bar span {
          transform: skew(16deg);
        }

        .section-head {
          display: grid;
          gap: 8px;
          margin-bottom: 14px;
        }

        .section-title {
          font: 24px/0.95 var(--display);
          text-transform: uppercase;
          letter-spacing: 0.01em;
        }

        .section-meta {
          color: var(--ink-muted);
          font: 11px/1.3 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .panel-block {
          border: 2px solid rgba(43, 39, 35, 0.16);
          border-radius: var(--radius);
          background: rgba(255, 255, 255, 0.82);
          box-shadow: var(--shadow);
          padding: 16px;
          margin-bottom: 18px;
        }

        .field-label {
          color: var(--ink-muted);
          font: 11px/1 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin: 0 0 8px 0;
        }

        .chip-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
          margin-bottom: 14px;
        }

        .chip {
          min-height: 44px;
          display: grid;
          place-items: center;
          text-align: center;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          border-radius: 14px;
          background: rgba(246,240,231,0.86);
          padding: 10px 12px;
          font-weight: 700;
        }

        .chip.active {
          border-color: var(--ink);
          background: rgba(22, 20, 18, 0.08);
        }

        .stage-toolbar {
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: center;
          flex-wrap: wrap;
          margin-bottom: 18px;
        }

        .status-banner {
          border: 2px solid var(--border);
          border-radius: 22px;
          background:
            linear-gradient(180deg, rgba(255,255,255,0.9), rgba(246,240,231,0.9)),
            linear-gradient(120deg, rgba(183,121,31,0.08), transparent 44%);
          padding: 18px;
          box-shadow: var(--shadow);
          margin-bottom: 18px;
        }

        .status-main {
          display: flex;
          justify-content: space-between;
          gap: 18px;
          align-items: start;
          flex-wrap: wrap;
        }

        .status-title {
          font: 38px/0.92 var(--display);
          text-transform: uppercase;
          letter-spacing: 0.01em;
          margin-top: 10px;
        }

        .status-copy {
          display: grid;
          gap: 8px;
          max-width: 54ch;
        }

        .status-copy p {
          color: var(--ink-muted);
          line-height: 1.55;
        }

        .status-meta {
          min-width: 280px;
          display: grid;
          gap: 8px;
          justify-items: end;
          text-align: right;
          color: var(--ink-muted);
          font: 12px/1.35 var(--mono);
        }

        .progress-bar {
          height: 12px;
          border: 1.5px solid rgba(43, 39, 35, 0.18);
          border-radius: 999px;
          overflow: hidden;
          background: rgba(22, 20, 18, 0.06);
          margin: 16px 0;
        }

        .progress-bar span {
          display: block;
          height: 100%;
          background:
            repeating-linear-gradient(135deg, var(--red) 0 16px, #b64330 16px 32px);
        }

        .progress-steps {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 10px;
          margin-bottom: 14px;
        }

        .progress-step {
          min-height: 68px;
          border-radius: 16px;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          background: rgba(255,255,255,0.84);
          padding: 12px;
          display: grid;
          gap: 6px;
        }

        .progress-step strong {
          font: 11px/1 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .progress-step span {
          font-size: 13px;
          color: var(--ink-muted);
          line-height: 1.35;
        }

        .progress-step.done {
          background: rgba(47,107,69,0.08);
          border-color: rgba(47,107,69,0.28);
        }

        .progress-step.current {
          background: rgba(207,76,54,0.08);
          border-color: rgba(207,76,54,0.32);
        }

        .log-list {
          display: grid;
          gap: 8px;
        }

        .log-entry {
          display: grid;
          grid-template-columns: 72px 1fr;
          gap: 12px;
          padding-top: 8px;
          border-top: 1px solid rgba(43, 39, 35, 0.10);
          font-size: 13px;
        }

        .log-entry time {
          color: var(--ink-muted);
          font-family: var(--mono);
        }

        .metrics-grid {
          display: grid;
          grid-template-columns: 1.45fr repeat(5, minmax(0, 1fr));
          gap: 10px;
        }

        .metric {
          min-height: 118px;
          border-radius: 18px;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          background: rgba(255,255,255,0.84);
          padding: 14px;
          display: grid;
          gap: 10px;
          align-content: start;
        }

        .metric-label {
          color: var(--ink-muted);
          font: 11px/1 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .metric-value {
          font: 42px/0.9 var(--display);
          letter-spacing: 0.01em;
          text-transform: uppercase;
        }

        .metric-value.series {
          font-size: 28px;
          line-height: 1.02;
        }

        .panel-head {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          flex-wrap: wrap;
          margin-bottom: 14px;
        }

        .gallery-card {
          border-radius: 18px;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          background: rgba(255,255,255,0.84);
          padding: 12px;
          box-shadow: var(--shadow);
          margin-bottom: 8px;
        }

        .gallery-card.failed {
          background:
            linear-gradient(180deg, rgba(183,121,31,0.12), rgba(255,255,255,0.9));
          border-color: rgba(183,121,31,0.34);
        }

        .gallery-card.selected {
          border-color: var(--ink);
          box-shadow: 0 0 0 2px rgba(110,167,163,0.22), var(--shadow);
        }

        .thumb {
          aspect-ratio: 3 / 4;
          border-radius: 14px;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          position: relative;
          overflow: hidden;
          background:
            linear-gradient(180deg, rgba(110,167,163,0.16), rgba(255,255,255,0.94));
          margin-bottom: 12px;
        }

        .thumb::before,
        .thumb::after {
          content: "";
          position: absolute;
          border: 1px solid rgba(43, 39, 35, 0.18);
          background: rgba(255,255,255,0.88);
        }

        .thumb::before {
          inset: 12px 12px auto 12px;
          height: 30%;
          transform: skew(-11deg);
        }

        .thumb::after {
          inset: auto 16px 14px 30%;
          height: 34%;
        }

        .thumb.failed {
          background:
            linear-gradient(135deg, rgba(255,255,255,0.92) 0 44%, rgba(183,121,31,0.32) 44% 48%, rgba(255,255,255,0.92) 48% 52%, rgba(183,121,31,0.32) 52% 56%, rgba(255,255,255,0.92) 56% 100%);
        }

        .thumb.failed::before {
          inset: 20% 18%;
          height: auto;
          transform: skew(-8deg);
          background: rgba(255,245,230,0.88);
          border-color: rgba(183,121,31,0.44);
        }

        .thumb.failed::after {
          display: none;
        }

        .page-head {
          display: flex;
          justify-content: space-between;
          align-items: start;
          gap: 10px;
          margin-bottom: 8px;
        }

        .page-title {
          font-weight: 800;
        }

        .page-sub {
          margin-top: 3px;
          color: var(--ink-muted);
          font: 12px/1.35 var(--mono);
        }

        .page-copy {
          color: var(--ink-muted);
          font-size: 13px;
          line-height: 1.45;
          min-height: 56px;
        }

        .detail-card {
          border-radius: 18px;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          background: rgba(255,255,255,0.84);
          box-shadow: var(--shadow);
          padding: 14px;
          margin-bottom: 12px;
        }

        .inspector-placeholder {
          min-height: 520px;
          border-radius: 20px;
          border: 2px solid var(--border);
          position: relative;
          overflow: hidden;
          background:
            linear-gradient(180deg, rgba(183,121,31,0.10), rgba(255,255,255,0.96)),
            linear-gradient(90deg, rgba(110,167,163,0.10), transparent 35%);
        }

        .inspector-placeholder::before,
        .inspector-placeholder::after {
          content: "";
          position: absolute;
          border: 1px solid rgba(43, 39, 35, 0.18);
          background: rgba(255,255,255,0.88);
        }

        .inspector-placeholder::before {
          inset: 24px 24px auto 24px;
          height: 42%;
          transform: skew(-8deg);
        }

        .inspector-placeholder::after {
          inset: auto 28px 24px 36%;
          height: 28%;
        }

        .inspector-note {
          position: absolute;
          top: 18px;
          right: -24px;
          transform: rotate(8deg);
          padding: 8px 16px;
          background: var(--red);
          color: white;
          font: 11px/1 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .detail-row {
          display: flex;
          justify-content: space-between;
          gap: 14px;
          flex-wrap: wrap;
          color: var(--ink-muted);
          font-size: 13px;
          margin-bottom: 8px;
        }

        .detail-row strong {
          color: var(--ink);
          font-size: 17px;
        }

        .detail-card p {
          color: var(--ink);
          line-height: 1.55;
          margin: 0;
        }

        .kv-line {
          display: flex;
          justify-content: space-between;
          gap: 14px;
          padding-top: 10px;
          border-top: 1px solid rgba(43, 39, 35, 0.10);
          color: var(--ink-muted);
          font-size: 13px;
        }

        .kv-line:first-child {
          padding-top: 0;
          border-top: 0;
        }

        .kv-line span:last-child {
          color: var(--ink);
          font-family: var(--mono);
          text-align: right;
        }

        .download-card {
          min-height: 118px;
          border-radius: 18px;
          border: 1.5px solid rgba(43, 39, 35, 0.16);
          background: rgba(255,255,255,0.84);
          padding: 14px;
          box-shadow: var(--shadow);
          margin-bottom: 10px;
        }

        .download-card.primary {
          border: 2px solid var(--border);
          background:
            linear-gradient(180deg, rgba(207,76,54,0.09), rgba(255,255,255,0.92));
        }

        .download-card small {
          color: var(--ink-muted);
          font: 11px/1 var(--mono);
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .download-card strong {
          font-size: 18px;
          line-height: 1.2;
          display: block;
          margin: 8px 0;
        }

        .download-card p {
          color: var(--ink-muted);
          font-size: 13px;
          margin: 0;
        }

        .footer-note {
          color: var(--ink-muted);
          font: 11px/1.4 var(--mono);
          text-transform: uppercase;
          letter-spacing: 0.08em;
          margin-top: 4px;
        }

        div[data-baseweb="input"] input,
        div[data-baseweb="select"] > div,
        div[data-baseweb="textarea"] textarea,
        [data-testid="stNumberInput"] input {
          width: 100%;
          border: 1.5px solid rgba(43, 39, 35, 0.16) !important;
          border-radius: 14px !important;
          background: rgba(255,255,255,0.92) !important;
          color: var(--ink) !important;
          padding: 12px 14px !important;
          box-shadow: none !important;
        }

        [data-testid="stTextArea"] textarea {
          min-height: 176px !important;
        }

        [data-testid="stTextArea"] label,
        [data-testid="stTextInput"] label,
        [data-testid="stSelectbox"] label,
        [data-testid="stNumberInput"] label {
          display: none !important;
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] button {
          min-height: 48px;
          border-radius: 14px !important;
          border: 1.5px solid var(--border) !important;
          background: white !important;
          color: var(--ink) !important;
          font-weight: 800 !important;
          letter-spacing: 0.01em !important;
          box-shadow: none !important;
        }

        div[data-testid="stButton"][id*="generate_comic_button"] button {
          background: var(--red) !important;
          border-color: var(--red) !important;
          color: white !important;
        }

        [data-baseweb="select"],
        [data-baseweb="select"] *,
        [data-baseweb="popover"] * {
          color: var(--ink) !important;
        }

        [data-baseweb="select"] > div {
          min-height: 48px !important;
          align-items: center !important;
        }

        [data-baseweb="select"] > div > div:first-child {
          min-height: 22px !important;
          height: auto !important;
          padding: 0 8px !important;
          align-items: center !important;
        }

        [data-baseweb="select"] > div > div:first-child > div {
          min-height: 18px !important;
          height: auto !important;
          line-height: 1.25 !important;
        }

        [data-baseweb="popover"] [role="option"] {
          background: rgba(255,255,255,0.98) !important;
        }

        @media (max-width: 1220px) {
          .metrics-grid,
          .progress-steps {
            grid-template-columns: 1fr 1fr;
          }

          .metrics-grid .metric:first-child {
            grid-column: 1 / -1;
          }
        }

        @media (max-width: 960px) {
          .desk-topbar {
            grid-template-columns: 1fr;
          }

          .badge-row {
            justify-content: flex-start;
          }

          .status-meta {
            min-width: 0;
            justify-items: start;
            text-align: left;
          }

          .progress-steps,
          .metrics-grid {
            grid-template-columns: 1fr;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_session_state() -> None:
    defaults = {
        "source_text": "",
        "title_override": "",
        "audience": AUDIENCE_OPTIONS[0],
        "output_language": LANGUAGE_OPTIONS[0],
        "workflow_preset": WORKFLOW_PRESETS[0],
        "page_count": 4,
        "comic_style": STYLE_PRESETS[1],
        "tone_notes": "",
        "view_state": "partial",
        "selected_page_id": "page-03",
        "current_run": None,
        "run_job_id": "",
        "form_error": "",
        "info_message": "",
        "blank_initial_fields_applied": False,
        "regen_threads": {},
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if not st.session_state.blank_initial_fields_applied:
        if st.session_state.source_text == DEFAULT_SOURCE_TEXT:
            st.session_state.source_text = ""
        if st.session_state.title_override == "How Mangroves Protect a Coastline":
            st.session_state.title_override = ""
        if st.session_state.tone_notes == DEFAULT_TONE_NOTES:
            st.session_state.tone_notes = ""
        st.session_state.blank_initial_fields_applied = True


def reset_form() -> None:
    st.session_state.source_text = ""
    st.session_state.title_override = ""
    st.session_state.audience = AUDIENCE_OPTIONS[0]
    st.session_state.output_language = LANGUAGE_OPTIONS[0]
    st.session_state.workflow_preset = WORKFLOW_PRESETS[0]
    st.session_state.page_count = 4
    st.session_state.comic_style = STYLE_PRESETS[1]
    st.session_state.tone_notes = ""
    st.session_state.form_error = ""
    st.session_state.info_message = "Form reset."
    st.session_state.view_state = "idle"
    st.rerun()


def load_example() -> None:
    st.session_state.source_text = DEFAULT_SOURCE_TEXT
    st.session_state.title_override = "How Mangroves Protect a Coastline"
    st.session_state.audience = AUDIENCE_OPTIONS[0]
    st.session_state.output_language = LANGUAGE_OPTIONS[0]
    st.session_state.workflow_preset = WORKFLOW_PRESETS[0]
    st.session_state.page_count = 4
    st.session_state.comic_style = STYLE_PRESETS[1]
    st.session_state.tone_notes = DEFAULT_TONE_NOTES
    st.session_state.form_error = ""
    st.session_state.info_message = "Example loaded."
    st.rerun()


def refresh_runner_snapshot() -> None:
    job_id = st.session_state.run_job_id
    if not job_id:
        return

    snapshot = load_background_run(job_id)
    if snapshot is None:
        return

    st.session_state.current_run = snapshot
    st.session_state.view_state = snapshot["status"]
    pages = snapshot.get("pages") or []
    if pages and st.session_state.selected_page_id not in {page["id"] for page in pages}:
        st.session_state.selected_page_id = pages[0]["id"]

    if snapshot_is_terminal(snapshot):
        st.session_state.run_job_id = ""
        if snapshot["status"] == "completed":
            st.session_state.info_message = f"Run {snapshot['run_id']} finished successfully."
        elif snapshot["status"] == "partial":
            st.session_state.info_message = f"Run {snapshot['run_id']} finished with partial page failures."
        else:
            st.session_state.form_error = f"Run {snapshot['run_id']} failed: {snapshot.get('error') or 'unknown error'}"


def load_latest_local_run() -> None:
    if st.session_state.current_run is not None or st.session_state.run_job_id:
        return
    config = load_workflow_config()
    manifests = sorted(
        (config.output_dir / "projects").glob("*/CP-*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        return
    st.session_state.current_run = json_load(manifests[0])
    st.session_state.view_state = st.session_state.current_run.get("status", "completed")
    pages = st.session_state.current_run.get("pages") or []
    if pages:
        st.session_state.selected_page_id = pages[0]["id"]


def refresh_current_run_from_manifest() -> None:
    run = st.session_state.current_run
    if not run or not run.get("manifest_path"):
        return
    manifest_path = Path(run["manifest_path"])
    if manifest_path.exists():
        st.session_state.current_run = json_load(manifest_path)
        if not any(
            page.get("status") == "in-progress"
            for page in st.session_state.current_run.get("pages", [])
        ):
            st.session_state.regen_threads = {}


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def demo_states() -> dict[str, dict]:
    completed_pages = [
        {
            "id": "page-01",
            "page": "01",
            "title": "Opening shoreline",
            "excerpt": "Roots break the incoming wave before it can hit the village edge all at once.",
            "status": "success",
            "script": "海岸边的红树林先拆散海浪，再让水慢下来。",
            "notes": "Use a wide establishing shoreline and keep the village visible in the back plane.",
            "file": "page-01-shoreline.png",
            "url": "/runs/page-01-shoreline.png",
            "image_path": "",
            "mime_type": "image/png",
            "error": "",
        },
        {
            "id": "page-02",
            "page": "02",
            "title": "Sediment capture",
            "excerpt": "The soil stays put because the root mesh traps mud before the current carries it away.",
            "status": "success",
            "script": "根系减慢水流，让泥沙沉下来。",
            "notes": "Make the before/after current difference legible in one reading.",
            "file": "page-02-sediment.png",
            "url": "/runs/page-02-sediment.png",
            "image_path": "",
            "mime_type": "image/png",
            "error": "",
        },
        {
            "id": "page-03",
            "page": "03",
            "title": "Root detail",
            "excerpt": "The root maze becomes a shelter line for juvenile fish and calmer water.",
            "status": "success",
            "script": "幼鱼躲在根系之间，避开强流和大鱼。",
            "notes": "Keep the fish large enough to read on mobile.",
            "file": "page-03-root-detail.png",
            "url": "/runs/page-03-root-detail.png",
            "image_path": "",
            "mime_type": "image/png",
            "error": "",
        },
        {
            "id": "page-04",
            "page": "04",
            "title": "Storm payoff",
            "excerpt": "The final page shows calmer water reaching homes behind the coastline.",
            "status": "success",
            "script": "风暴来时，村庄后方接到的水势更缓。",
            "notes": "Land the recap with one teacher-friendly caption.",
            "file": "page-04-storm-payoff.png",
            "url": "/runs/page-04-storm-payoff.png",
            "image_path": "",
            "mime_type": "image/png",
            "error": "",
        },
    ]
    partial_pages = [
        {
            "id": "page-03",
            "page": "03",
            "title": "Root detail",
            "excerpt": "Image generation failed after prompt expansion. Text payload exists, but the page image field returned empty.",
            "status": "failed",
            "script": "这一页的讲解文本已经生成，但图像字段为空，需要重新触发图片步骤。",
            "notes": "Prompt parsing failed after visual style merge. Preserve the page slot and the Chinese teaching text.",
            "file": "page-03-root-detail.png",
            "url": "Unavailable",
            "image_path": "",
            "mime_type": "image/png",
            "error": "backend parsing / empty image field",
        },
        completed_pages[0],
        completed_pages[1],
        completed_pages[3],
    ]
    generating_pages = [
        completed_pages[0],
        {
            "id": "page-02",
            "page": "02",
            "title": "Sediment capture",
            "excerpt": "The runner has reserved this slot while image generation is still in flight.",
            "status": "in-progress",
            "script": "第二页脚本已经返回，图像还在处理中。",
            "notes": "Keep the slot stable while the runner thread finishes the image call.",
            "file": "page-02-sediment.png",
            "url": "Processing",
            "image_path": "",
            "mime_type": "image/png",
            "error": "",
        },
    ]
    return {
        "idle": {
            "label": "Idle",
            "tone": "ink",
            "annotation": "Ready",
            "title": "Awaiting source text",
            "body": "The desk is ready for a new source brief. No active run exists yet.",
            "run_id": "—",
            "elapsed": "—",
            "error": "No active run",
            "progress": 0,
            "step": -1,
            "logs": [["Ready", "Paste source material and start a run."]],
            "summary": {
                "series": "No active series",
                "requested": "—",
                "returned": "—",
                "success": "—",
                "failure": "—",
                "bundle": "Unavailable",
                "timestamp": "No run yet",
                "zip": "No project files available",
                "order": "No pages returned",
                "count": "0 cards",
                "ready_label": "Waiting for run",
            },
            "pages": [],
            "download_ready": False,
            "archive_path": "",
            "manifest_path": "",
        },
        "validating": {
            "label": "Validating",
            "tone": "signal",
            "annotation": "Preparing payload",
            "title": "Checking source text and run settings",
            "body": "The runner thread is normalizing the brief, writing the input snapshot, and preparing the workflow calls.",
            "run_id": "CP-240519-0818",
            "elapsed": "00:18",
            "error": "Validation in progress",
            "progress": 18,
            "step": 0,
            "logs": [["00:06", "Run record created."], ["00:18", "Payload checks still in progress."]],
            "summary": {
                "series": "How Mangroves Protect a Coastline",
                "requested": "4",
                "returned": "0",
                "success": "0",
                "failure": "0",
                "bundle": "Pending",
                "timestamp": "19 May 2026 · 20:18",
                "zip": "Project files are not ready",
                "order": "No pages returned",
                "count": "0 cards",
                "ready_label": "Bundle pending",
            },
            "pages": [],
            "download_ready": False,
            "archive_path": "",
            "manifest_path": "",
        },
        "generating": {
            "label": "Generating",
            "tone": "signal",
            "annotation": "Runner active",
            "title": "Pages are arriving while the run is active",
            "body": "The generation thread is writing prompt files, calling the image backend, and saving page images one by one.",
            "run_id": "CP-240519-0820",
            "elapsed": "02:46",
            "error": "Page image generation still active",
            "progress": 68,
            "step": 2,
            "logs": [["00:10", "Validation passed and payload dispatched."], ["02:46", "Page 01 returned; page 02 still running."]],
            "summary": {
                "series": "How Mangroves Protect a Coastline",
                "requested": "4",
                "returned": "1",
                "success": "1",
                "failure": "0",
                "bundle": "Pending",
                "timestamp": "19 May 2026 · 20:20",
                "zip": "Image generation is still running",
                "order": "Reserved page slots stay visible",
                "count": "2 cards",
                "ready_label": "Generating",
            },
            "pages": generating_pages,
            "download_ready": False,
            "archive_path": "",
            "manifest_path": "",
        },
        "completed": {
            "label": "Completed",
            "tone": "success",
            "annotation": "All pages saved",
            "title": "The comic project folder is ready",
            "body": "All page images saved successfully. The operator can inspect the pages and project files.",
            "run_id": "CP-240519-0822",
            "elapsed": "04:12",
            "error": "Workflow completed cleanly",
            "progress": 100,
            "step": 4,
            "logs": [["00:10", "Validation passed and payload dispatched."], ["04:12", "All four pages saved and ready."]],
            "summary": {
                "series": "How Mangroves Protect a Coastline",
                "requested": "4",
                "returned": "4",
                "success": "4",
                "failure": "0",
                "bundle": "28.4 MB",
                "timestamp": "19 May 2026 · 20:22",
                "zip": "4 successful pages · 28.4 MB local files · manifest included",
                "order": "Showing proof order",
                "count": "4 cards",
                "ready_label": "Bundle ready",
            },
            "pages": completed_pages,
            "download_ready": False,
            "archive_path": "",
            "manifest_path": "",
        },
        "partial": {
            "label": "Partial failure",
            "tone": "warn",
            "annotation": "Pages returned: 3 of 4",
            "title": "Three pages good, one page needs retry",
            "body": "The request completed with usable output. Successful pages remain reviewable and downloadable, while the failed page stays visible with its error context intact.",
            "run_id": "CP-240519-0823",
            "elapsed": "04:51",
            "error": "Failure source · empty image field after prompt expansion",
            "progress": 100,
            "step": 3,
            "logs": [["00:10", "Validation passed and payload dispatched."], ["03:58", "Three pages returned with valid local image files and notes."], ["04:51", "Page 03 failed after prompt expansion; partial project preserved."]],
            "summary": {
                "series": "How Mangroves Protect a Coastline",
                "requested": "4",
                "returned": "3",
                "success": "3",
                "failure": "1",
                "bundle": "21.1 MB",
                "timestamp": "19 May 2026 · 20:23",
                "zip": "3 successful pages · 21.1 MB local files · manifest included",
                "order": "Failed page sorted to the front",
                "count": "4 cards",
                "ready_label": "Partial project preserved",
            },
            "pages": partial_pages,
            "download_ready": False,
            "archive_path": "",
            "manifest_path": "",
        },
        "failed": {
            "label": "Failed",
            "tone": "warn",
            "annotation": "No usable pages returned",
            "title": "The run failed before valid images were produced",
            "body": "No image assets were preserved. The operator can retry the request without retyping the source text.",
            "run_id": "CP-240519-0825",
            "elapsed": "00:52",
            "error": "Failure source · backend parsing error",
            "progress": 42,
            "step": 1,
            "logs": [["00:10", "Validation passed and payload dispatched."], ["00:52", "Backend returned invalid image payloads for all pages."]],
            "summary": {
                "series": "How Mangroves Protect a Coastline",
                "requested": "4",
                "returned": "0",
                "success": "0",
                "failure": "4",
                "bundle": "Unavailable",
                "timestamp": "19 May 2026 · 20:25",
                "zip": "No images available",
                "order": "No pages returned",
                "count": "0 cards",
                "ready_label": "Run failed",
            },
            "pages": [],
            "download_ready": False,
            "archive_path": "",
            "manifest_path": "",
        },
    }


def build_live_state() -> dict | None:
    run = st.session_state.current_run
    if run is None:
        return None

    created_at = format_timestamp(run["created_at"])
    pages = []
    for page in run["pages"]:
        pages.append(
            {
                "id": page["id"],
                "page_number": page["page_number"],
                "page": f"{page['page_number']:02d}",
                "title": page["title"],
                "excerpt": page["excerpt"],
                "status": page["status"],
                "script": page["script"],
                "notes": page["notes"],
                "file": page["filename"] or "Unavailable",
                "url": page["public_url"] or page["image_path"] or "Unavailable",
                "image_path": page["image_path"],
                "mime_type": page["mime_type"],
                "prompt": page.get("prompt", ""),
                "prompt_path": page.get("prompt_path", ""),
                "error": page.get("error") or "",
            }
        )

    status = run["status"]
    success_count = int(run["success_count"])
    failure_count = int(run["failure_count"])
    requested_count = int(run["requested_page_count"])
    returned_count = success_count if status in {"partial", "failed"} else len(pages)
    bundle_size = humanize_bytes(run["bundle_size_bytes"])

    label_map = {
        "validating": "Validating",
        "generating": "Generating",
        "completed": "Completed",
        "partial": "Partial failure",
        "failed": "Failed",
    }
    tone_map = {
        "validating": "signal",
        "generating": "signal",
        "completed": "success",
        "partial": "warn",
        "failed": "warn",
    }
    annotation_map = {
        "validating": "Preparing payload",
        "generating": f"Pages returned: {success_count} of {requested_count}",
        "completed": "All pages saved",
        "partial": f"Pages returned: {success_count} of {requested_count}",
        "failed": "No usable pages returned",
    }
    title_map = {
        "validating": "Checking source text and run settings",
        "generating": "The runner thread is actively building pages",
        "completed": "The comic project folder is ready",
        "partial": "Some pages are good, one or more pages need retry",
        "failed": "The run failed before valid images were produced",
    }
    body_map = {
        "validating": "The runner thread is normalizing the brief and preparing the workflow calls.",
        "generating": "Prompt files are already persisted. Image generation continues in the background while the desk stays responsive.",
        "completed": "All page images saved successfully. The operator can inspect the pages and project files.",
        "partial": "The request completed with usable output. Successful pages remain reviewable and downloadable, while failed pages stay visible with error context intact.",
        "failed": "No image assets were preserved. The operator can retry the request without retyping the source text.",
    }

    return {
        "label": label_map[status],
        "tone": tone_map[status],
        "annotation": annotation_map[status],
        "title": title_map[status],
        "body": body_map[status],
        "run_id": run["run_id"],
        "elapsed": format_elapsed(run["elapsed_seconds"]),
        "error": run.get("error") or default_error_label(status, failure_count),
        "progress": int(run.get("progress", 0)),
        "step": int(run.get("step", 0)),
        "logs": run["logs"],
        "summary": {
            "series": run["title"],
            "requested": str(requested_count),
            "returned": str(returned_count),
            "success": str(success_count),
            "failure": str(failure_count),
            "bundle": bundle_size,
            "timestamp": created_at,
            "zip": f"{success_count} successful pages · {bundle_size} local files · manifest included" if success_count else "No images available",
            "order": "Failed page sorted to the front" if status == "partial" else "Showing proof order",
            "count": f"{len(pages)} cards",
            "ready_label": "Partial project preserved" if status == "partial" else "Project ready" if status == "completed" else "Generating" if status == "generating" else "Project pending",
        },
        "pages": pages,
        "download_ready": status in {"completed", "partial"} and success_count > 0,
        "archive_path": run["archive_path"],
        "manifest_path": run["manifest_path"],
    }


def resolve_display_state() -> dict:
    live_state = build_live_state()
    if live_state is not None and (
        st.session_state.run_job_id
        or st.session_state.view_state == st.session_state.current_run["status"]
    ):
        return live_state
    return demo_states()[st.session_state.view_state]


def current_page(payload: dict) -> dict | None:
    pages = payload["pages"]
    if not pages:
        st.session_state.selected_page_id = ""
        return None

    selected = st.session_state.selected_page_id
    for page in pages:
        if page["id"] == selected:
            return page

    st.session_state.selected_page_id = pages[0]["id"]
    return pages[0]


def format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%d %b %Y · %H:%M")
    except ValueError:
        return value


def format_elapsed(value: float) -> str:
    total_seconds = max(0, int(round(value)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def default_error_label(status: str, failure_count: int) -> str:
    if status == "validating":
        return "Validation in progress"
    if status == "generating":
        return "Runner thread active"
    if status == "partial":
        return f"{failure_count} page failures preserved in project files"
    if status == "failed":
        return "No valid local pages returned"
    return "Workflow completed cleanly"


def status_pill_class(tone: str) -> str:
    return {
        "success": "success",
        "warn": "warn",
        "signal": "signal",
        "ink": "ink",
    }.get(tone, "ink")


def status_label(status: str) -> str:
    return {
        "success": "Success",
        "failed": "Failed",
        "in-progress": "Generating",
        "queued": "Queued",
    }.get(status, status.title())


def status_tone(status: str) -> str:
    return {
        "success": "success",
        "failed": "warn",
        "in-progress": "signal",
        "queued": "signal",
    }.get(status, "ink")


def html_block(markup: str) -> str:
    return dedent(markup).strip()


def render_topbar(display_state: dict) -> None:
    configured, _ = workflow_env_status()
    connection_label = "API configured" if configured else "edit .env"
    connection_class = "success" if configured else "warn"
    run_label = f"Run {display_state['run_id']}" if display_state["run_id"] != "—" else "No active run"
    st.markdown(
        f"""
        <div class="page-shell">
          <div class="desk-topbar">
            <div class="traffic" aria-hidden="true"><span></span><span></span><span></span></div>
            <div>
              <div class="topbar-title">{html.escape(APP_NAME)}</div>
              <div class="topbar-subtitle">Generate teachable comics from raw text</div>
            </div>
            <div class="badge-row">
              <span class="pill {connection_class}">{html.escape(connection_label)}</span>
              <span class="pill ink">{html.escape(run_label)}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_close() -> None:
    return


def render_section_head(caption: str, title: str, meta: str) -> None:
    st.markdown(
        f"""
        <div class="section-head">
          <div class="caption-bar"><span>{html.escape(caption)}</span></div>
          <div class="section-title">{html.escape(title)}</div>
          <div class="section-meta">{html.escape(meta)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_input_rail() -> None:
    locked = bool(st.session_state.run_job_id)
    render_section_head("Issue controls", "Source Input", "Single operator · form locked while run is active")

    if st.session_state.form_error:
        st.error(st.session_state.form_error)
    elif st.session_state.info_message:
        st.info(st.session_state.info_message)

    st.markdown('<div class="field-label">Source text</div>', unsafe_allow_html=True)
    st.text_area(
        "Source text",
        key="source_text",
        height=176,
        disabled=locked,
        label_visibility="collapsed",
    )
    st.markdown('<div class="field-label">Title override</div>', unsafe_allow_html=True)
    st.text_input(
        "Title override",
        key="title_override",
        disabled=locked,
        label_visibility="collapsed",
    )

    st.markdown('<div class="field-label">Output language</div>', unsafe_allow_html=True)
    st.selectbox(
        "Output language",
        LANGUAGE_OPTIONS,
        key="output_language",
        disabled=locked,
        label_visibility="collapsed",
    )

    st.markdown('<div class="field-label">Target pages</div>', unsafe_allow_html=True)
    st.number_input(
        "Target pages",
        min_value=1,
        max_value=8,
        step=1,
        key="page_count",
        disabled=locked,
        label_visibility="collapsed",
    )
    st.markdown('<div class="field-label">Comic style</div>', unsafe_allow_html=True)
    st.selectbox(
        "Comic style",
        STYLE_PRESETS,
        key="comic_style",
        disabled=locked,
        label_visibility="collapsed",
    )

    st.markdown('<div class="field-label">Tone or character notes</div>', unsafe_allow_html=True)
    st.text_area(
        "Tone or character notes",
        key="tone_notes",
        height=112,
        disabled=locked,
        label_visibility="collapsed",
    )
    submitted = st.button(
        "Generate Comic" if not locked else "Run in progress",
        key="generate_comic_button",
        use_container_width=True,
        disabled=locked,
    )

    action_col1, action_col2 = st.columns(2)
    with action_col1:
        if st.button("Load Example", use_container_width=True, disabled=locked):
            load_example()
    with action_col2:
        if st.button("Reset", use_container_width=True, disabled=locked):
            reset_form()
    st.markdown(
        '<div class="footer-note">Fill the API credentials in <code>.env</code> before starting a live run. Outputs are saved under the local project folder.</div>',
        unsafe_allow_html=True,
    )

    if submitted:
        handle_generate()


def handle_generate() -> None:
    st.session_state.form_error = ""
    st.session_state.info_message = ""
    source_text = st.session_state.source_text.strip()
    if not source_text:
        st.session_state.form_error = "Source text is required before a run can be generated."
        st.session_state.view_state = "idle"
        st.rerun()

    request_payload = StudioRequest(
        source_text=source_text,
        title_override=st.session_state.title_override,
        audience=st.session_state.audience,
        output_language=st.session_state.output_language,
        workflow_preset=st.session_state.workflow_preset,
        page_count=int(st.session_state.page_count),
        comic_style=st.session_state.comic_style,
        tone_notes=st.session_state.tone_notes,
    )
    try:
        job_id = start_background_run(request_payload)
    except ConfigError as exc:
        st.session_state.form_error = f"Workflow configuration error: {exc}. Update .env and retry."
        st.session_state.view_state = "idle"
        st.rerun()

    st.session_state.current_run = None
    st.session_state.run_job_id = job_id
    st.session_state.view_state = "validating"
    st.session_state.info_message = f"Runner thread started: {job_id}"
    st.rerun()


def render_stage(display_state: dict) -> None:
    st.markdown(
        f"""
        <div class="stage-toolbar">
          <div class="section-head" style="margin:0;">
            <div class="caption-bar"><span>Run feedback</span></div>
            <div class="section-title">Full production desk</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_status_banner(display_state)
    render_summary(display_state)
    render_gallery(display_state)
    render_inspector(display_state)
    render_downloads(display_state)

def render_status_banner(payload: dict) -> None:
    progress_steps = []
    for index, (title, text) in enumerate(STEP_LABELS):
        classes = []
        if payload["step"] >= 0 and index < payload["step"]:
            classes.append("done")
        if index == payload["step"]:
            classes.append("current")
        progress_steps.append(
            html_block(
                f"""
                <div class="progress-step {' '.join(classes)}">
                  <strong>{html.escape(title)}</strong>
                  <span>{html.escape(text)}</span>
                </div>
                """
            )
        )

    logs = []
    for time_label, line in payload["logs"][-6:]:
        logs.append(
            html_block(
                f"""
                <div class="log-entry">
                  <time>{html.escape(time_label)}</time>
                  <div>{html.escape(line)}</div>
                </div>
                """
            )
        )

    st.markdown(
        html_block(
            f"""
            <div class="status-banner">
              <div class="status-main">
                <div class="status-copy">
                  <div class="badge-row" style="justify-content:flex-start;">
                    <span class="pill {status_pill_class(payload['tone'])}">{html.escape(payload['label'])}</span>
                    <span class="pill ink">{html.escape(payload['annotation'])}</span>
                  </div>
                  <div class="status-title">{html.escape(payload['title'])}</div>
                  <p>{html.escape(payload['body'])}</p>
                </div>
                <div class="status-meta">
                  <span>Run ID · {html.escape(payload['run_id'])}</span>
                  <span>Elapsed · {html.escape(payload['elapsed'])}</span>
                  <span>{html.escape(payload['error'])}</span>
                </div>
              </div>
              <div class="progress-bar" aria-hidden="true"><span style="width:{payload['progress']}%;"></span></div>
              <div class="progress-steps">{''.join(progress_steps)}</div>
              <div class="log-list">{''.join(logs)}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def render_summary(payload: dict) -> None:
    summary = payload["summary"]
    st.markdown(
        f"""
        <div class="panel-block">
          <div class="panel-head">
            <div class="section-head" style="gap:6px; margin:0;">
              <div class="section-title">Result summary</div>
              <div class="section-meta">{html.escape(summary['timestamp'])}</div>
            </div>
            <span class="pill ink">{html.escape(summary['ready_label'])}</span>
          </div>
          <div class="metrics-grid">
            {metric_cell("Series", summary["series"], True)}
            {metric_cell("Requested", summary["requested"])}
            {metric_cell("Returned", summary["returned"])}
            {metric_cell("Succeeded", summary["success"])}
            {metric_cell("Failed", summary["failure"])}
            {metric_cell("Output size", summary["bundle"])}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_cell(label: str, value: str, series: bool = False) -> str:
    value_class = "metric-value series" if series else "metric-value"
    return (
        f'<div class="metric"><div class="metric-label">{html.escape(label)}</div>'
        f'<div class="{value_class}">{html.escape(value)}</div></div>'
    )


def render_gallery(payload: dict) -> None:
    st.markdown(
        f"""
        <div class="panel-block">
          <div class="panel-head">
            <div class="section-head" style="gap:6px; margin:0;">
              <div class="section-title">Image generation list</div>
              <div class="section-meta">Every planned page image stays visible and regeneratable</div>
            </div>
            <span class="pill {'warn' if int(str(payload['summary']['failure']).replace('—','0') or 0) else 'ink'}">{html.escape(payload['summary']['count'])}</span>
          </div>
        """,
        unsafe_allow_html=True,
    )

    pages = payload["pages"]
    if not pages:
        st.markdown(
            """
            <div class="gallery-card">
              <div class="page-title">No pages returned yet</div>
              <div class="page-copy">The gallery will populate here as soon as the runner returns page artifacts.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    cols = st.columns(4)
    for index, page in enumerate(pages):
        with cols[index % 4]:
            selected = st.session_state.selected_page_id == page["id"]
            classes = ["gallery-card"]
            if page["status"] == "failed":
                classes.append("failed")
            if selected:
                classes.append("selected")
            image_path = page.get("image_path", "")
            if image_path and Path(image_path).exists():
                st.image(image_path, use_container_width=True)
            else:
                st.markdown(
                    f'<div class="thumb {"failed" if page["status"] == "failed" else ""}"></div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f"""
                <div class="{' '.join(classes)}">
                  <div class="page-head">
                    <div>
                      <div class="page-title">Page {html.escape(page['page'])}</div>
                      <div class="page-sub">{html.escape(page['title'])}</div>
                    </div>
                    <span class="pill {status_tone(page['status'])}">{html.escape(status_label(page['status']))}</span>
                  </div>
                  <div class="page-copy">{html.escape(page['excerpt'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                f"Inspect Page {page['page']}",
                key=f"inspect-{page['id']}",
                use_container_width=True,
            ):
                st.session_state.selected_page_id = page["id"]
                st.rerun()
            if st.button(
                f"Regenerate Page {page['page']}",
                key=f"regenerate-{page['id']}",
                use_container_width=True,
                disabled=not can_regenerate_page(page),
            ):
                start_page_regeneration(page["id"])
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def can_regenerate_page(page: dict) -> bool:
    run = st.session_state.current_run
    if not run or not run.get("manifest_path") or not run.get("root_path"):
        return False
    if page.get("status") == "in-progress":
        return False
    if page.get("prompt_path") and Path(page["prompt_path"]).exists():
        return True
    if page.get("prompt"):
        return True

    page_number = page.get("page_number") or page.get("page")
    try:
        page_path = Path(run["root_path"]) / "pages" / f"page-{int(page_number):02d}.json"
    except (TypeError, ValueError):
        return False
    if not page_path.exists():
        return False
    page_json = json_load(page_path)
    prompt_path = page_json.get("prompt_path")
    return bool(page_json.get("prompt") or (prompt_path and Path(prompt_path).exists()))


def start_page_regeneration(page_id: str) -> None:
    run = st.session_state.current_run
    if not run or not run.get("manifest_path"):
        st.session_state.form_error = "No manifest is available for page regeneration."
        return

    def worker() -> None:
        regenerate_page_image(run["manifest_path"], page_id)

    thread = threading.Thread(target=worker, name=f"regen-{page_id}", daemon=True)
    st.session_state.regen_threads[page_id] = True
    thread.start()
    st.session_state.info_message = f"Regeneration started for {page_id}."


def render_inspector(payload: dict) -> None:
    page = current_page(payload)
    st.markdown(
        """
        <div class="panel-block">
          <div class="panel-head">
            <div class="section-head" style="gap:6px; margin:0;">
              <div class="section-title">Page detail inspector</div>
              <div class="section-meta">Selected page stays inspectable even in partial-failure runs</div>
            </div>
          </div>
        """,
        unsafe_allow_html=True,
    )

    if page is None:
        st.markdown(
            """
            <div class="detail-card">
              <p>No page is selected yet.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    left, right = st.columns([1.05, 0.95], gap="large")
    with left:
        if page.get("image_path") and Path(page["image_path"]).exists():
            st.image(page["image_path"], use_container_width=True)
        else:
            note = "Retry candidate" if page["status"] == "failed" else "Selected page"
            st.markdown(
                f"""
                <div class="inspector-placeholder">
                  <div class="inspector-note">{html.escape(note)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with right:
        st.markdown(
            f"""
            <div class="detail-card">
              <div class="detail-row">
                <strong>Page {html.escape(page['page'])} · {html.escape(page['title'])}</strong>
                <span class="pill {status_tone(page['status'])}">{html.escape(status_label(page['status']))}</span>
              </div>
              <p>{html.escape(page['script'])}</p>
            </div>
            <div class="detail-card">
              <div class="metric-label">Generation notes</div>
              <p>{html.escape(page['notes'])}</p>
            </div>
            <div class="detail-card">
              <div class="kv-line"><span>File name</span><span>{html.escape(page['file'])}</span></div>
              <div class="kv-line"><span>Image path</span><span>{html.escape(page['url'])}</span></div>
              <div class="kv-line"><span>Failure class</span><span>{html.escape(page.get('error') or 'none')}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if page.get("image_path") and Path(page["image_path"]).exists():
            st.download_button(
                "Download selected page",
                data=Path(page["image_path"]).read_bytes(),
                file_name=Path(page["image_path"]).name,
                mime=page.get("mime_type", "image/png"),
                use_container_width=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)


def render_downloads(payload: dict) -> None:
    summary = payload["summary"]
    st.markdown(
        f"""
        <div class="panel-block">
          <div class="panel-head">
            <div class="section-head" style="gap:6px; margin:0;">
              <div class="section-title">Project files</div>
              <div class="section-meta">Manifest, image paths, and local project folder</div>
            </div>
            <span class="pill ink">{html.escape(summary['ready_label'])}</span>
          </div>
        """,
        unsafe_allow_html=True,
    )

    manifest_path = payload.get("manifest_path", "")
    ready = payload["download_ready"] and manifest_path and Path(manifest_path).exists()
    run = st.session_state.current_run

    cols = st.columns(3)
    card_specs = [
        ("Project folder", "Local files are saved", summary["zip"], "primary"),
        ("Manifest", "Download manifest JSON", "Notes, filenames, prompts, and run metadata.", ""),
        ("Clipboard", "Copy image paths", "Useful for review docs and downstream scripts.", ""),
    ]
    for col, (small, strong, copy, extra) in zip(cols, card_specs, strict=True):
        with col:
            st.markdown(
                f"""
                <div class="download-card {extra}">
                  <small>{html.escape(small)}</small>
                  <strong>{html.escape(strong)}</strong>
                  <p>{html.escape(copy)}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if not ready or run is None:
        st.markdown(
            """
            <div class="detail-card">
              <p>Project file actions unlock after a live run writes a manifest.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    image_paths = "\n".join(
        page["public_url"] or page["image_path"]
        for page in run["pages"]
        if page["public_url"] or page["image_path"]
    )
    action_cols = st.columns(3)
    with action_cols[0]:
        st.download_button(
            "Download manifest JSON",
            data=Path(manifest_path).read_bytes(),
            file_name=Path(manifest_path).name,
            mime="application/json",
            use_container_width=True,
        )
    with action_cols[1]:
        st.download_button(
            "Copy image paths",
            data=image_paths.encode("utf-8"),
            file_name="image-paths.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with action_cols[2]:
        st.code(run["root_path"], language=None)
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="🖨️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_styles()
    initialize_session_state()
    refresh_runner_snapshot()
    load_latest_local_run()
    refresh_current_run_from_manifest()
    display_state = resolve_display_state()
    render_topbar(display_state)
    rail, stage = st.columns([0.32, 0.68], gap="large")
    with rail:
        render_input_rail()
    with stage:
        render_stage(display_state)
    render_page_close()

    if st.session_state.run_job_id or st.session_state.regen_threads:
        st.caption("Runner thread active. The page auto-refreshes every second while the workflow is running.")
        st.markdown(
            """
            <script>
            setTimeout(function () {
              window.location.reload();
            }, 1000);
            </script>
            """,
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
