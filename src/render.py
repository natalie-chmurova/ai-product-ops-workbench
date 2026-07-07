"""Stage 3 — the "Presenter".

Takes the original transcript plus the three generated artifacts and assembles a
single self-contained HTML page: the raw meeting on the left, and the AI-generated
deliverables on the right. No JavaScript framework, no server — just open the file.
"""

from __future__ import annotations

import html
from datetime import date

import markdown as md

_MD_EXTENSIONS = ["tables", "sane_lists"]


def _md_to_html(text: str) -> str:
    return md.markdown(text, extensions=_MD_EXTENSIONS)


def _priority_label(priority) -> tuple[str, str]:
    """Map ClickUp priority number to (label, css-class)."""
    mapping = {
        1: ("Urgent", "prio-1"),
        2: ("High", "prio-2"),
        3: ("Normal", "prio-3"),
        4: ("Low", "prio-4"),
    }
    return mapping.get(priority, ("Normal", "prio-3"))


def _render_task_card(task: dict) -> str:
    name = html.escape(str(task.get("name", "Untitled task")))
    owner = html.escape(str(task.get("owner", "Unassigned")))
    label, prio_class = _priority_label(task.get("priority", 3))
    description = html.escape(str(task.get("description", ""))).replace("\n", "<br>")
    tags = "".join(
        f'<span class="tag">{html.escape(str(t))}</span>' for t in task.get("tags", [])
    )
    return f"""
    <div class="task-card">
      <div class="task-head">
        <span class="task-name">{name}</span>
        <span class="badge {prio_class}">{label}</span>
      </div>
      <div class="task-meta">Owner: <strong>{owner}</strong></div>
      <div class="task-desc">{description}</div>
      <div class="task-tags">{tags}</div>
    </div>
    """


def render_report(
    transcript: str,
    tasks: list,
    sprint_md: str,
    bug_triage_md: str,
) -> str:
    """Return a complete HTML document as a string."""
    transcript_html = html.escape(transcript).replace("\n", "<br>")
    tasks_html = "".join(_render_task_card(t) for t in tasks) or "<p>No tasks generated.</p>"
    sprint_html = _md_to_html(sprint_md)
    triage_html = _md_to_html(bug_triage_md)
    today = date.today().isoformat()

    return _TEMPLATE.format(
        today=today,
        task_count=len(tasks),
        transcript_html=transcript_html,
        tasks_html=tasks_html,
        sprint_html=sprint_html,
        triage_html=triage_html,
    )


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Product Ops Workbench — Report</title>
<style>
  :root {{
    --bg: #0f1216; --panel: #171b21; --line: #262c34;
    --text: #e6e9ee; --muted: #9aa4b2; --accent: #6c8cff;
    --p1: #ff5c6c; --p2: #ff9f43; --p3: #6c8cff; --p4: #8a94a6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  header {{
    padding: 22px 32px; border-bottom: 1px solid var(--line);
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  }}
  header h1 {{ font-size: 18px; margin: 0; }}
  header .sub {{ color: var(--muted); font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1.35fr; gap: 0; min-height: calc(100vh - 66px); }}
  .col {{ padding: 24px 32px; }}
  .col.left {{ border-right: 1px solid var(--line); background: #12151a; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .08em;
        color: var(--muted); margin: 0 0 14px; }}
  .transcript {{ font-size: 13px; color: #c7cdd6; white-space: normal; }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 18px; }}
  .tab {{ padding: 7px 14px; border: 1px solid var(--line); border-radius: 8px;
          cursor: pointer; color: var(--muted); background: var(--panel); font-size: 13px; }}
  .tab.active {{ color: var(--text); border-color: var(--accent); }}
  .pane {{ display: none; }}
  .pane.active {{ display: block; }}
  .task-card {{ background: var(--panel); border: 1px solid var(--line);
                border-radius: 12px; padding: 16px; margin-bottom: 14px; }}
  .task-head {{ display: flex; justify-content: space-between; align-items: start; gap: 12px; }}
  .task-name {{ font-weight: 600; }}
  .task-meta {{ color: var(--muted); font-size: 13px; margin: 6px 0 10px; }}
  .task-desc {{ font-size: 13.5px; color: #d4d9e0; }}
  .badge {{ font-size: 11px; padding: 3px 9px; border-radius: 999px; white-space: nowrap; color: #0f1216; font-weight: 700; }}
  .prio-1 {{ background: var(--p1); }} .prio-2 {{ background: var(--p2); }}
  .prio-3 {{ background: var(--p3); }} .prio-4 {{ background: var(--p4); }}
  .tag {{ display: inline-block; font-size: 11px; color: var(--muted);
          border: 1px solid var(--line); border-radius: 6px; padding: 2px 7px; margin: 8px 6px 0 0; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 10px 0; }}
  th, td {{ border: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #1c222a; color: var(--muted); }}
  .pane h1 {{ font-size: 17px; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>AI Product Ops Workbench</h1>
  <span class="sub">Generated {today} &middot; {task_count} tasks &middot; transcript &rarr; ClickUp tasks, sprint summary, bug triage</span>
</header>
<div class="grid">
  <div class="col left">
    <h2>Input &mdash; Raw meeting transcript</h2>
    <div class="transcript">{transcript_html}</div>
  </div>
  <div class="col right">
    <h2>Output &mdash; Generated artifacts</h2>
    <div class="tabs">
      <div class="tab active" data-pane="tasks">Tasks</div>
      <div class="tab" data-pane="sprint">Sprint Summary</div>
      <div class="tab" data-pane="triage">Bug Triage</div>
    </div>
    <div class="pane active" id="tasks">{tasks_html}</div>
    <div class="pane" id="sprint">{sprint_html}</div>
    <div class="pane" id="triage">{triage_html}</div>
  </div>
</div>
<script>
  document.querySelectorAll('.tab').forEach(function (tab) {{
    tab.addEventListener('click', function () {{
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(tab.dataset.pane).classList.add('active');
    }});
  }});
</script>
</body>
</html>
"""
