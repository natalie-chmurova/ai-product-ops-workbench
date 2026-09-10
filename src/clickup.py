"""ClickUp integration — push generated tasks into a real ClickUp list.

The tasks the engine produces already match ClickUp's shape (name, description,
priority 1-4, tags), so this is a thin layer: read the token/list from the
environment, create one task per item, and report what happened.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from .client import WorkbenchError

API = "https://api.clickup.com/api/v2"

# One model call is made per meeting item, and every one of those calls carries the
# whole board. Cost grows as items x board size, so a board this large stops the
# read instead of quietly running up a bill.
MAX_BOARD = 200


def _token() -> str:
    token = os.environ.get("CLICKUP_API_TOKEN")
    if not token:
        raise WorkbenchError(
            "No CLICKUP_API_TOKEN found. Add it to your .env "
            "(ClickUp → Settings → Apps → API Token)."
        )
    return token


def _headers() -> dict:
    return {"Authorization": _token(), "Content-Type": "application/json"}


def list_url(list_id: str, team_id: str | None = None) -> str:
    team_id = team_id or os.environ.get("CLICKUP_TEAM_ID", "")
    return f"https://app.clickup.com/{team_id}/v/li/{list_id}"


def get_lists() -> list[dict]:
    """Return the user's lists as [{id, name, space}] for a picker."""
    team_id = os.environ.get("CLICKUP_TEAM_ID")
    if not team_id:
        return []
    out: list[dict] = []
    spaces = requests.get(f"{API}/team/{team_id}/space", headers=_headers(), timeout=20)
    for space in spaces.json().get("spaces", []):
        sid, sname = space["id"], space["name"]
        r = requests.get(f"{API}/space/{sid}/list", headers=_headers(), timeout=20)
        for lst in r.json().get("lists", []):
            out.append({"id": lst["id"], "name": lst["name"], "space": sname})
        folders = requests.get(f"{API}/space/{sid}/folder", headers=_headers(), timeout=20)
        for folder in folders.json().get("folders", []):
            fr = requests.get(f"{API}/folder/{folder['id']}/list", headers=_headers(), timeout=20)
            for lst in fr.json().get("lists", []):
                out.append({"id": lst["id"], "name": f"{folder['name']} / {lst['name']}", "space": sname})
    return out


def get_tasks(list_id: str | None = None, include_closed: bool = False) -> list[dict]:
    """Read the board: open tasks in a list, as [{id, name, status, assignees, due_date}].

    Two different absences, kept apart on purpose:
    - no list id configured -> [] — board-blind mode, and the callers say so out loud;
    - configured but failing -> WorkbenchError. A board that reads as empty because a
      token expired would turn every meeting point into new work, silently, which is
      the exact failure the whole reconcile stage exists to prevent.

    ClickUp hands tasks over a page at a time; every page is read.
    """
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        return []
    out: list[dict] = []
    page = 0
    while True:
        try:
            r = requests.get(
                f"{API}/list/{list_id}/task",
                params={"include_closed": "true" if include_closed else "false", "page": page},
                headers=_headers(),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WorkbenchError(f"Could not reach ClickUp to read the board: {exc}") from exc
        if r.status_code != 200:
            raise WorkbenchError(
                f"Could not read the ClickUp board (HTTP {r.status_code}): {r.text[:120]}\n"
                "  Check CLICKUP_API_TOKEN and CLICKUP_LIST_ID in your .env."
            )
        data = r.json()
        tasks = data.get("tasks", [])
        out.extend(_task_row(t) for t in tasks)
        # Checked here, inside the loop, right after each page is added — not after
        # the loop breaks. A page sequence that never reports last_page (or keeps
        # repeating the same non-empty page) never breaks the loop on its own, so
        # this is what actually bounds it. Once we're over the ceiling the true
        # total can only be larger, so stopping now is strictly safer than reading
        # on to find an exact count.
        if len(out) > MAX_BOARD:
            raise WorkbenchError(
                f"The board has at least {len(out)} open tasks; the ceiling is {MAX_BOARD}. "
                "Every meeting item is matched against the whole board in its own model call, "
                "so this run would be slow and expensive. Narrow the list, or raise MAX_BOARD "
                "in src/clickup.py once you have measured what it costs."
            )
        if data.get("last_page", True) or not tasks:
            break
        page += 1
    return out


def _task_row(t: dict) -> dict:
    """One ClickUp task -> the board row every consumer expects."""
    return {
        "id": t.get("id", ""),
        "name": t.get("name", ""),
        "status": (t.get("status") or {}).get("status", ""),
        "assignees": [a.get("username", "") for a in t.get("assignees", [])],
        "due_date": _iso_date(t.get("due_date")),
    }


def _iso_date(raw) -> str:
    """ClickUp hands over a due date as epoch milliseconds, or null. We want a date.

    A deadline the agent cannot read is a deadline it cannot reason about, which is
    why "they said Thursday" has so far gone nowhere near the board's own date.
    """
    if not raw:
        return ""
    try:
        seconds = int(raw) / 1000
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()


def load_board_fixture(path) -> list[dict]:
    """Read a board from a file, in the same shape `get_tasks()` returns.

    A fixture is how a transcript gets a board that belongs to its own world. The
    live board stays the default everywhere; this is opt-in, because a demo that
    quietly stopped talking to a real tracker would lose the thing worth showing.

    Unlike `get_tasks()`, a bad path raises. An unreadable fixture is a mistake in an
    argument someone typed, and reconciling against an empty board instead would
    silently turn every point into new work.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkbenchError(f"Board fixture not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkbenchError(f"Board fixture is not valid JSON: {path} ({exc})") from exc

    board = []
    for task in raw.get("tasks", []):
        board.append(
            {
                "id": task.get("id", ""),
                "name": task.get("name", ""),
                "status": task.get("status", ""),
                # list() so two tasks can never share one list of owners
                "assignees": list(task.get("assignees", [])),
                "due_date": task.get("due_date", ""),
            }
        )
    return board


def add_comment(task_id: str, text: str) -> tuple[bool, str]:
    """Comment on an existing task — the effect that replaces creating a duplicate."""
    r = requests.post(
        f"{API}/task/{task_id}/comment",
        headers=_headers(),
        json={"comment_text": text, "notify_all": False},
        timeout=20,
    )
    if r.status_code in (200, 201):
        return True, task_id
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def _create_task(list_id: str, task: dict, assignee_id: str | None = None) -> tuple[bool, str]:
    """Create one task. Returns (ok, task_name_or_error)."""
    payload = {
        "name": str(task.get("name", "Untitled task"))[:250],
        "description": str(task.get("description", "")),
    }
    priority = task.get("priority")
    if priority in (1, 2, 3, 4):
        payload["priority"] = priority
    if assignee_id:
        payload["assignees"] = [int(assignee_id)]
    tags = [str(t) for t in task.get("tags", [])]
    if tags:
        payload["tags"] = tags

    try:
        r = requests.post(
            f"{API}/list/{list_id}/task", headers=_headers(), json=payload, timeout=30
        )
    except requests.RequestException as exc:
        return False, f"network error: {exc}"

    if r.status_code == 200:
        return True, payload["name"]
    # Tags that don't exist in the space can cause a rejection — retry without them.
    if tags:
        payload.pop("tags", None)
        retry = requests.post(
            f"{API}/list/{list_id}/task", headers=_headers(), json=payload, timeout=30
        )
        if retry.status_code == 200:
            return True, payload["name"]
    return False, f"{r.status_code}: {r.text[:120]}"


def push_tasks(tasks: list, list_id: str | None = None) -> dict:
    """Create every task in the target list. Returns a summary dict."""
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        raise WorkbenchError(
            "No target list. Set CLICKUP_LIST_ID in your .env or pass a list_id."
        )
    if not tasks:
        raise WorkbenchError("There are no tasks to send. Generate artifacts first.")

    # Resolve owners to real assignees once (members + alias map fetched up front).
    from .assignees import alias_map, get_members, resolve_owner

    try:
        members = get_members()
    except Exception:
        members = []
    aliases = alias_map()

    # A newly found defect belongs in the backlog, not in the running sprint.
    # If no backlog list is configured, everything still lands in the main list —
    # but the intended destination is tagged, so nothing is silently lost.
    backlog_id = os.environ.get("CLICKUP_BACKLOG_LIST_ID")

    created, assigned, to_backlog, failures = 0, 0, 0, []
    for task in tasks:
        assignee_id = resolve_owner(task.get("owner"), members, aliases)
        wants_backlog = str(task.get("destination", "")).lower() == "backlog"
        target = backlog_id if (wants_backlog and backlog_id) else list_id

        task = dict(task)
        tags = [t for t in task.get("tags", []) if t]
        for marker in (task.get("type"), task.get("destination")):
            marker = str(marker or "").lower()
            if marker in ("bug", "backlog") and marker not in tags:
                tags.append(marker)
        task["tags"] = tags

        ok, info = _create_task(target, task, assignee_id)
        if ok:
            created += 1
            if assignee_id:
                assigned += 1
            if wants_backlog:
                to_backlog += 1
        else:
            failures.append(info)

    return {
        "created": created,
        "assigned": assigned,
        "backlog": to_backlog,
        "backlog_list_configured": bool(backlog_id),
        "failed": failures,
        "total": len(tasks),
        "list_url": list_url(list_id),
    }
