"""AI Product Ops Workbench — web app.

A simple point-and-click interface over the same engine the CLI uses:
paste a meeting transcript, click one button, and get ClickUp-ready tasks,
a sprint summary, and a bug triage table — right in the browser.

Run it with:  streamlit run app.py
(or just double-click start.command)
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.artifacts import build_bug_triage, build_sprint_summary, build_tasks
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

st.set_page_config(page_title="AI Product Ops Workbench", page_icon="🛠️", layout="wide")


# ---------- header ----------
st.title("🛠️ AI Product Ops Workbench")
st.caption(
    "Turn a raw meeting transcript into ClickUp-ready tasks, a sprint summary, "
    "and a bug triage table — in one click."
)


# ---------- input ----------
left, right = st.columns([1, 1.35], gap="large")

with left:
    st.subheader("Input — meeting transcript")
    transcript = st.text_area(
        "Paste a transcript, or use the built-in demo:",
        value=DEMO_TRANSCRIPT,
        height=420,
        label_visibility="visible",
    )
    col_a, col_b = st.columns([1, 1])
    run = col_a.button("✨ Generate artifacts", type="primary", use_container_width=True)
    if col_b.button("↺ Reset to demo", use_container_width=True):
        st.rerun()


def render_tasks(tasks: list) -> None:
    st.markdown(f"**{len(tasks)} tasks generated**")
    for task in tasks:
        label, color = PRIORITY.get(task.get("priority", 3), PRIORITY[3])
        with st.container(border=True):
            head = st.columns([5, 1])
            head[0].markdown(f"**{task.get('name', 'Untitled task')}**")
            head[1].markdown(
                f"<span style='background:{color};color:#0f1216;padding:2px 10px;"
                f"border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap;'>"
                f"{label}</span>",
                unsafe_allow_html=True,
            )
            st.caption(f"Owner: {task.get('owner', 'Unassigned')}")
            st.markdown(task.get("description", "").replace("\n", "  \n"))
            tags = task.get("tags", [])
            if tags:
                st.markdown(" ".join(f"`{t}`" for t in tags))


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

            tab_tasks, tab_sprint, tab_triage = st.tabs(
                ["Tasks", "Sprint Summary", "Bug Triage"]
            )
            with tab_tasks:
                render_tasks(tasks)
            with tab_sprint:
                st.markdown(sprint_md)
            with tab_triage:
                st.markdown(triage_md)

        except (WorkbenchError, ValueError) as exc:
            st.error(str(exc))
    else:
        st.info("Paste a transcript on the left and click **Generate artifacts**.")
