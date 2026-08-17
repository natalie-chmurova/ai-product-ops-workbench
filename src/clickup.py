"""ClickUp integration — push generated tasks into a real ClickUp list.

The tasks the engine produces already match ClickUp's shape (name, description,
priority 1-4, tags), so this is a thin layer: read the token/list from the
environment, create one task per item, and report what happened.
"""

from __future__ import annotations

import os

import requests

from .client import WorkbenchError

API = "https://api.clickup.com/api/v2"


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
    """Read the board: open tasks in a list, as [{id, name, status, assignees}].

    Until this existed the pipeline could only write. Without reading the board
    first, every meeting point looks like new work — which is how a decision
    turns into a task and work already in progress turns into a duplicate.
    Returns [] rather than raising when nothing is configured, so callers can
    degrade to board-blind behaviour instead of failing.
    """
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        return []
    params = "include_closed=true" if include_closed else "include_closed=false"
    r = requests.get(f"{API}/list/{list_id}/task?{params}", headers=_headers(), timeout=20)
    if r.status_code != 200:
        return []
    out = []
    for t in r.json().get("tasks", []):
        out.append(
            {
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "status": (t.get("status") or {}).get("status", ""),
                "assignees": [a.get("username", "") for a in t.get("assignees", [])],
            }
        )
    return out


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

    created, assigned, failures = 0, 0, []
    for task in tasks:
        assignee_id = resolve_owner(task.get("owner"), members, aliases)
        ok, info = _create_task(list_id, task, assignee_id)
        if ok:
            created += 1
            if assignee_id:
                assigned += 1
        else:
            failures.append(info)

    return {
        "created": created,
        "assigned": assigned,
        "failed": failures,
        "total": len(tasks),
        "list_url": list_url(list_id),
    }
