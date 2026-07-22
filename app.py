"""AI Product Ops Workbench — web app.

A simple point-and-click interface over the same engine the CLI uses:
paste a meeting transcript, click one button, and get ClickUp-ready tasks,
a sprint summary, and a bug triage table — right in the browser.

Run it with:  streamlit run app.py
(or just double-click start.command)
"""

from __future__ import annotations

import html
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.artifacts import build_bug_triage, build_sprint_summary, build_tasks
from src.clickup import get_lists, push_tasks
from src.client import WorkbenchError
from src.extract import extract_context

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEMO_TRANSCRIPT = (ROOT / "samples" / "transcript_demo.txt").read_text(encoding="utf-8")

PRIORITY = {
    1: ("Urgent", "#ff5c6c"),
    2: ("High", "#ff9f43"),
    3: ("Normal", "#6c8cff"),
    4: ("Low", "#8a94a6"),
}
DESC_LABELS = ("Goal:", "Context:", "What needs to be done:", "Acceptance criteria:")

st.set_page_config(page_title="AI Product Ops Workbench", page_icon="🛠️", layout="wide")


# ---------- styling ----------
st.markdown(
    """
    <style>
      :root {
        --bg:#0f1216; --panel:#171b21; --line:#262c34; --panel2:#1c222a;
        --text:#e6e9ee; --muted:#9aa4b2; --soft:#cdd3db; --accent:#8ea2ff;
      }
      .block-container { padding-top: 2.4rem; max-width: 1440px; }
      h1, h2, h3 { letter-spacing: -0.01em; }
      /* metrics strip */
      .wb-metrics { display:flex; gap:10px; margin:2px 0 18px; flex-wrap:wrap; }
      .wb-metric { background:var(--panel); border:1px solid var(--line);
        border-radius:12px; padding:10px 16px; min-width:92px; }
      .wb-metric .n { font-size:22px; font-weight:750; color:var(--text); line-height:1.1;
        font-variant-numeric: tabular-nums; }
      .wb-metric .l { font-size:10.5px; color:var(--muted); text-transform:uppercase;
        letter-spacing:.07em; margin-top:2px; }
      .wb-metric.accent .n { color:#ff8090; }
      /* task card */
      .wb-card { position:relative; background:var(--panel); border:1px solid var(--line);
        border-radius:14px; padding:15px 18px 14px 20px; margin-bottom:13px; overflow:hidden; }
      .wb-card::before { content:''; position:absolute; left:0; top:0; bottom:0; width:4px;
        background:var(--stripe); }
      .wb-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
      .wb-title { font-weight:650; font-size:14.5px; color:var(--text); line-height:1.35; }
      .wb-pill { flex:none; font-size:10.5px; font-weight:700; padding:3px 11px;
        border-radius:999px; color:#0f1216; white-space:nowrap; }
      .wb-owner { color:var(--muted); font-size:12.5px; margin:7px 0 9px; }
      .wb-owner b { color:var(--soft); font-weight:600; }
      .wb-desc { font-size:12.7px; color:var(--soft); line-height:1.5; }
      .wb-desc .lbl { color:var(--accent); font-weight:600; }
      .wb-tags { margin-top:11px; display:flex; flex-wrap:wrap; gap:6px; }
      .wb-tag { font-size:10.5px; color:var(--muted); border:1px solid var(--line);
        border-radius:6px; padding:2px 8px; }
      /* tame the big markdown headings coming from sprint / triage docs */
      [data-testid="stMarkdownContainer"] h1 { font-size:19px; margin:4px 0 8px; }
      [data-testid="stMarkdownContainer"] h2 { font-size:13px; text-transform:uppercase;
        letter-spacing:.06em; color:var(--muted); margin:14px 0 6px; }
      /* markdown tables inside tabs */
      [data-testid="stMarkdownContainer"] table { border-collapse:collapse; width:100%;
        font-size:12.7px; margin:8px 0; }
      [data-testid="stMarkdownContainer"] th, [data-testid="stMarkdownContainer"] td {
        border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }
      [data-testid="stMarkdownContainer"] th { background:var(--panel2); color:var(--muted); }
      /* subtitle chip */
      .wb-chip { display:inline-block; font-size:11px; color:var(--muted);
        border:1px solid var(--line); border-radius:999px; padding:2px 10px; margin-left:4px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- header ----------
st.title("🛠️ AI Product Ops Workbench")
st.markdown(
    "Turn a raw meeting transcript into ClickUp-ready tasks, a sprint summary, "
    "and a bug triage table — in one click. "
    "<span class='wb-chip'>synthetic demo data</span>",
    unsafe_allow_html=True,
)
st.write("")


# ---------- helpers ----------
def _format_description(desc: str) -> str:
    safe = html.escape(desc)
    for label in DESC_LABELS:
        safe = safe.replace(label, f"<span class='lbl'>{label}</span>")
    safe = safe.replace("\n", "<br>").replace("<br>- ", "<br>• ")
    return safe


def render_metrics(context: dict, tasks: list) -> None:
    urgent = sum(1 for t in tasks if t.get("priority") == 1)
    bugs = len(context.get("bugs", []))
    decisions = len(context.get("decisions", []))
    cards = [
        ("n", len(tasks), "Tasks"),
        ("accent", urgent, "Urgent"),
        ("n", bugs, "Bugs"),
        ("n", decisions, "Decisions"),
    ]
    html_parts = ['<div class="wb-metrics">']
    for kind, num, label in cards:
        cls = "wb-metric accent" if kind == "accent" else "wb-metric"
        html_parts.append(f'<div class="{cls}"><div class="n">{num}</div><div class="l">{label}</div></div>')
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_tasks(tasks: list) -> None:
    for task in tasks:
        label, color = PRIORITY.get(task.get("priority", 3), PRIORITY[3])
        name = html.escape(str(task.get("name", "Untitled task")))
        owner = html.escape(str(task.get("owner", "Unassigned")))
        desc = _format_description(str(task.get("description", "")))
        tags = "".join(
            f"<span class='wb-tag'>{html.escape(str(t))}</span>" for t in task.get("tags", [])
        )
        st.markdown(
            f"""
            <div class="wb-card" style="--stripe:{color}">
              <div class="wb-head">
                <div class="wb-title">{name}</div>
                <div class="wb-pill" style="background:{color}">{label}</div>
              </div>
              <div class="wb-owner">👤 Owner: <b>{owner}</b></div>
              <div class="wb-desc">{desc}</div>
              <div class="wb-tags">{tags}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


@st.cache_data(show_spinner=False, ttl=300)
def _cached_lists() -> list:
    try:
        return get_lists()
    except Exception:
        return []


def render_clickup(tasks: list) -> None:
    """A row that pushes the generated tasks into a real ClickUp list."""
    if not os.environ.get("CLICKUP_API_TOKEN"):
        return  # integration not configured — hide the control entirely
    lists = _cached_lists()
    default_id = os.environ.get("CLICKUP_LIST_ID", "")
    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        if lists:
            labels = [f"{l['space']} / {l['name']}" for l in lists]
            ids = [l["id"] for l in lists]
            idx = ids.index(default_id) if default_id in ids else 0
            choice = c1.selectbox("ClickUp list", labels, index=idx, label_visibility="collapsed")
            target = ids[labels.index(choice)]
        else:
            target = default_id
            c1.caption("Sending to the default list from .env")
        send = c2.button("📤 Send to ClickUp", use_container_width=True)
        if send:
            try:
                with st.spinner("Creating tasks in ClickUp…"):
                    summary = push_tasks(tasks, target)
                if summary["created"]:
                    st.success(
                        f"Created {summary['created']} of {summary['total']} tasks in ClickUp"
                        f" · {summary.get('assigned', 0)} assigned to an owner."
                    )
                    st.markdown(f"➡️ [Open the ClickUp board]({summary['list_url']})")
                if summary["failed"]:
                    st.warning(
                        f"{len(summary['failed'])} task(s) didn't go through: "
                        + "; ".join(summary["failed"][:3])
                    )
            except (WorkbenchError, ValueError) as exc:
                st.error(str(exc))


# ---------- input ----------
left, right = st.columns([1, 1.35], gap="large")

with left:
    st.subheader("Input — meeting transcript")
    audio = st.file_uploader(
        "🎙️ Upload an audio recording (transcribed locally, nothing leaves your machine):",
        type=["m4a", "mp3", "wav", "aiff", "aac", "mp4"],
    )
    if audio is not None:
        key = f"{audio.name}:{audio.size}"
        if st.session_state.get("tx_key") != key:
            import os
            import tempfile

            from src.transcribe import transcribe_audio

            with st.spinner("Transcribing audio locally…"):
                suffix = os.path.splitext(audio.name)[1] or ".m4a"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
                    tf.write(audio.getvalue())
                    tmp = tf.name
                try:
                    st.session_state["tx_text"] = transcribe_audio(tmp)
                    st.session_state["tx_key"] = key
                finally:
                    os.unlink(tmp)
        default_text = st.session_state.get("tx_text", DEMO_TRANSCRIPT)
    else:
        default_text = DEMO_TRANSCRIPT

    transcript = st.text_area(
        "Paste a transcript, use the built-in demo, or edit the transcription above:",
        value=default_text,
        height=400,
    )
    col_a, col_b = st.columns([1, 1])
    run = col_a.button("✨ Generate artifacts", type="primary", use_container_width=True)
    if col_b.button("↺ Reset to demo", use_container_width=True):
        st.session_state.pop("tx_key", None)
        st.session_state.pop("tx_text", None)
        st.rerun()


# ---------- run + output ----------
with right:
    st.subheader("Output — generated artifacts")

    if run:
        try:
            with st.status("Working through the transcript...", expanded=True) as status:
                st.write("Stage 1/3 — understanding the transcript")
                context = extract_context(transcript)
                st.write("Stage 2/3 — building tasks, sprint summary, bug triage")
                tasks = build_tasks(context)
                sprint_md = build_sprint_summary(context)
                triage_md = build_bug_triage(context)
                st.write("Stage 3/3 — done")
                status.update(label="Done ✓", state="complete", expanded=False)
            st.session_state["result"] = {
                "context": context, "tasks": tasks, "sprint": sprint_md, "triage": triage_md,
            }
        except (WorkbenchError, ValueError) as exc:
            st.session_state["result"] = None
            st.error(str(exc))

    result = st.session_state.get("result")
    if not result:
        st.info("Paste a transcript on the left and click **Generate artifacts**.")
    else:
        render_metrics(result["context"], result["tasks"])
        render_clickup(result["tasks"])
        tab_tasks, tab_sprint, tab_triage = st.tabs(
            ["Tasks", "Sprint Summary", "Bug Triage"]
        )
        with tab_tasks:
            render_tasks(result["tasks"])
        with tab_sprint:
            st.markdown(result["sprint"])
        with tab_triage:
            st.markdown(result["triage"])
