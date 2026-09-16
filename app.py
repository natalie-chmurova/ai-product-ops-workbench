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
import time
from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.apply import apply_plan
from src.artifacts import (
    build_bug_triage,
    build_speaker_summary,
    build_sprint_summary,
    build_tasks,
)
from src.assignees import roster_line, team_roster
from src.clickup import get_lists, get_tasks
from src.client import WorkbenchError
from src.extract import extract_context
from src.plan import Plan, ask_label, build_plan, plan_markdown
from src.reconcile import reconcile, reconcile_decisions

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


def render_apply(result: dict) -> None:
    """The plan, and one button that applies it — once, to the board it was built on."""
    if not os.environ.get("CLICKUP_API_TOKEN"):
        return  # integration not configured — hide the control entirely
    plan = result.get("plan")
    if not isinstance(plan, Plan):
        # an older result in session_state, from before the plan was one value
        st.caption("Generate again to build a plan for this board.")
        return
    if not plan.scope:
        st.caption("No ClickUp list was selected for this run, so the plan cannot be applied.")
        return
    # The plan belongs to the board it was reconciled against. If the picker has moved
    # since, applying would write into a board this plan never saw.
    stale = st.session_state.get("scope_choice_id", plan.scope) != plan.scope
    # The same counts the Board plan tab shows, off the same value: while the tab counted
    # tasks and this caption counted tasks and meeting decisions, one run read "ask a
    # human 2" in the tab and "ask a human 4" here.
    counts = plan.counts

    with st.container(border=True):
        st.caption(
            f"Plan for **{result.get('scope_label', plan.scope)}** · "
            f"create **{counts['create']}** · "
            f"comment on existing **{counts['comment']}** · "
            f"ask a human **{counts['ask']}** (gate {plan.gate:.2f})"
        )
        if stale:
            st.warning(
                "The list changed after this plan was built. Generate again before applying — "
                "writing a plan to a board it was not reconciled against is how duplicates "
                "are made."
            )
        # Items below the gate are applied only when a person ticks them, one by one,
        # the way the agent intended. This is the human in the loop, not auto-apply.
        approved = []
        for i, effect in enumerate(plan.ask):
            # A doubtful comment names the task it would land on, and a guardrail cause
            # says what fired: that match is what the person is being asked to check.
            label = ask_label(effect)
            if effect.intent and st.checkbox(label, key=f"ask_{i}"):
                approved.append(effect)
            elif not effect.intent:
                st.caption(f"⚠️ {label} — needs manual handling")

        if st.button("📤 Apply plan to ClickUp", use_container_width=True, key="apply_plan",
                     disabled=stale):
            # The meeting date as the input shows it now, not as it was at Generate: a date
            # corrected after the plan was built is the one the person means. The date is in
            # no key, so reading it here cannot make an effect apply twice.
            meeting_date = st.session_state.get("meeting_date")
            try:
                with st.spinner("Applying the plan…"):
                    summary = apply_plan(
                        plan, approved,
                        meeting_title=result["context"].get("meeting_title", ""),
                        when=meeting_date.isoformat() if meeting_date else None,
                    )
                st.success(
                    f"Created {summary['created']} · commented {summary['commented']} · "
                    f"skipped {summary['skipped']} already applied · "
                    f"{summary['assigned']} assigned to an owner."
                )
                st.markdown(f"➡️ [Open the ClickUp board]({summary['list_url']})")
                if summary["failed"]:
                    st.warning(
                        f"{len(summary['failed'])} effect(s) didn't go through: "
                        + "; ".join(summary["failed"][:3])
                    )
            except (WorkbenchError, ValueError) as exc:
                st.error(str(exc))


@st.cache_data(show_spinner=False, ttl=300)
def _cached_lists() -> list:
    # A failure is raised, not returned as []: the cache keeps results only, so a failing
    # read is retried on the next rerun instead of being remembered as "no lists" for five
    # minutes — and the picker can say why, rather than "No ClickUp list configured".
    return get_lists()


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

    # The board this plan is built against is the board it will be applied to. Choosing
    # the list afterwards is how a plan reconciled against one board gets written to
    # another — which is precisely the duplicate the reconcile stage exists to prevent.
    lists, lists_error = [], ""
    if os.environ.get("CLICKUP_API_TOKEN"):
        try:
            lists = _cached_lists()
        except (WorkbenchError, ValueError) as exc:
            # Configured but failing is not "no list configured": it is a board that cannot
            # be read. Say why here; Generate refuses to run board-blind below.
            lists_error = str(exc)
    default_id = os.environ.get("CLICKUP_LIST_ID", "")
    c_scope, c_date = st.columns([2, 1])
    if lists:
        labels = [f"{l['space']} / {l['name']}" for l in lists]
        ids = [l["id"] for l in lists]
        idx = ids.index(default_id) if default_id in ids else 0
        choice = c_scope.selectbox("ClickUp list — reconciled against, and applied to",
                                   labels, index=idx, key="clickup_list")
        scope_id, scope_label = ids[labels.index(choice)], choice
    elif lists_error:
        scope_id, scope_label = "", ""
        c_scope.error(f"{lists_error}\n\nGenerate stops with this error until the lists can be "
                      "read: without the board, every point would count as new.")
    else:
        scope_id = default_id
        scope_label = "the list from .env" if default_id else "No ClickUp list configured"
        c_scope.caption("ClickUp list: the one from .env" if default_id
                        else "No ClickUp list configured — every point will count as new")
    st.session_state["scope_choice_id"] = scope_id
    # The date that goes into every comment is the date of the MEETING, not of the
    # click. It is also excluded from the idempotency key (Task 4), so re-applying the
    # same plan on another day stays a no-op. render_apply reads it at the Apply click,
    # so a date corrected after Generate is the date that is used.
    c_date.date_input("Meeting date", value=date.today(), key="meeting_date")

    col_a, col_b = st.columns([1, 1])
    run = col_a.button("✨ Generate artifacts", type="primary", use_container_width=True,
                       key="generate")
    if col_b.button("↺ Reset to demo", use_container_width=True, key="reset_demo"):
        st.session_state.pop("tx_key", None)
        st.session_state.pop("tx_text", None)
        st.rerun()


# ---------- run + output ----------
with right:
    st.subheader("Output — generated artifacts")

    if run:
        try:
            # A token that is set but cannot list the workspace is a failing board read:
            # stop here, before any model call, rather than reconcile against nothing.
            if lists_error:
                raise WorkbenchError(lists_error)
            started = time.monotonic()
            with st.status("Working through the transcript...", expanded=True) as status:
                # Read the board before any model call: a bad token fails here, for free.
                board = get_tasks(scope_id) if scope_id else []
                if not scope_id:
                    st.write("Board: no list selected — every point will count as new")
                else:
                    st.write(f"Board: {len(board)} open tasks in {scope_label}"
                             + ("" if board else " — empty, so every point counts as new"))
                roster = team_roster()
                if roster:
                    st.write(f"Team roster ({len(roster)}): {roster_line(roster)}")
                st.write("Stage 1/3 — understanding the transcript")
                context = extract_context(transcript, roster)
                st.write("Stage 2/3 — building tasks, sprint summary, bug triage, per-speaker notes")
                tasks = build_tasks(context)
                sprint_md = build_sprint_summary(context)
                triage_md = build_bug_triage(context)
                speakers_md = build_speaker_summary(context, transcript, roster)
                st.write(f"Stage 2.5/3 — reconciling against the board ({len(board)} tasks)")
                # One plan, built once here: the tab below, the caption over the Apply
                # button and the button itself all read this one value, so they cannot
                # count the same run differently or send what the tab never showed.
                plan = build_plan(
                    reconcile(tasks, board),
                    reconcile_decisions(context.get("decisions", []), board),
                    board, scope_id,
                )
                elapsed = time.monotonic() - started
                st.write(f"Stage 3/3 — done in {elapsed:.0f}s")
                status.update(label=f"Done ✓ · {elapsed:.0f}s", state="complete", expanded=False)
            st.session_state["result"] = {
                "context": context, "tasks": tasks, "sprint": sprint_md, "triage": triage_md,
                "speakers": speakers_md, "elapsed": elapsed,
                "board": board, "plan": plan, "board_plan_md": plan_markdown(plan),
                "scope_label": scope_label,
            }
            # A fresh plan means fresh choices for the items below the gate.
            for k in [k for k in st.session_state if str(k).startswith("ask_")]:
                del st.session_state[k]
        except (WorkbenchError, ValueError) as exc:
            st.session_state["result"] = None
            st.error(str(exc))

    result = st.session_state.get("result")
    if not result:
        st.info("Paste a transcript on the left and click **Generate artifacts**.")
    else:
        render_metrics(result["context"], result["tasks"])
        render_apply(result)
        tab_tasks, tab_plan, tab_sprint, tab_triage, tab_speakers = st.tabs(
            ["Tasks", "Board plan", "Sprint Summary", "Bug Triage", "By Speaker"]
        )
        with tab_tasks:
            render_tasks(result["tasks"])
        with tab_plan:
            # older results in session_state predate the plan
            st.markdown(result.get("board_plan_md") or "_Re-run to reconcile against the board._")
        with tab_sprint:
            st.markdown(result["sprint"])
        with tab_triage:
            st.markdown(result["triage"])
        with tab_speakers:
            # older results in session_state predate this tab
            st.markdown(result.get("speakers") or "_Re-run to generate the per-speaker view._")
