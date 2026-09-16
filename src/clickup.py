"""ClickUp integration — the board a run is checked against, and the effects it writes.

Every request goes through one function, `_request`. It carries the token, the headers
and the timeout, and it turns each of the four ways a request can go wrong — nothing
answered it, the answer refused it, the answer is not JSON, the answer is not the shape a
reader can read — into one sentence saying what failed and what to check.

What a caller does with that sentence is the difference between reading and writing. A
read raises it as a `WorkbenchError`: a board that reads as empty because a token expired
would turn every meeting point into new work, silently. A write catches it and answers
`(False, reason)`: a run applying many effects reports the ones the tracker refused and
keeps the rest of its summary.
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

# What to check when a read fails: the token every request carries, plus the id the
# failing request was made with.
_TEAM_HINT = "Check CLICKUP_API_TOKEN and CLICKUP_TEAM_ID in your .env."
_LIST_HINT = "Check CLICKUP_API_TOKEN and CLICKUP_LIST_ID in your .env."


class _Unreachable(WorkbenchError):
    """Nothing answered the request, so what it did — if anything — is unknown.

    Kept apart from a request ClickUp answered and refused, because only the second can be
    safely offered again: a create that got no answer may have been made anyway, and
    sending it a second time is how one effect becomes two tasks on the board.
    """


def _token() -> str:
    token = os.environ.get("CLICKUP_API_TOKEN")
    if not token:
        raise WorkbenchError(
            "No CLICKUP_API_TOKEN found. Add it to your .env "
            "(ClickUp → Settings → Apps → API Token)."
        )
    return token


def _said(sentence: str, hint: str) -> str:
    """One failure, as a person reads it: what happened, then what to check."""
    return f"{sentence}\n  {hint}" if hint else sentence


def _cut(text: str) -> str:
    """Enough of a body to recognise the failure by, and no more."""
    return (text or "")[:120]


_KINDS = {list: "a list", str: "a string", bool: "a boolean", int: "a number",
          float: "a number", type(None): "nothing"}


def _kind(value) -> str:
    return _KINDS.get(type(value), "an object")


def _request(method: str, url: str, *, what: str, hint: str = "",
             params: dict | None = None, body: dict | None = None,
             timeout: int = 20) -> dict:
    """Make one ClickUp request and return the JSON object it answered with.

    The one place the token, the headers and the timeout are written, and the one place
    that decides what counts as a failure. `what` names the request the way a person would
    say it ("read the board", "comment on task 86abc"), so one sentence covers every
    caller; `hint` is what to check, and a write leaves it out because its reason is read
    in a list of failed effects, not on its own.
    """
    headers = {"Authorization": _token(), "Content-Type": "application/json"}
    try:
        response = requests.request(method, url, headers=headers, params=params,
                                    json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise _Unreachable(
            _said(f"Could not reach ClickUp to {what}: {exc}", hint)) from exc
    if not 200 <= response.status_code < 300:
        raise WorkbenchError(_said(
            f"Could not {what} (HTTP {response.status_code}): {_cut(response.text)}", hint))
    try:
        data = response.json()
    except ValueError as exc:  # requests' JSONDecodeError is a ValueError
        raise WorkbenchError(_said(
            f"Could not {what}: ClickUp sent something other than JSON "
            f"(HTTP {response.status_code}): {_cut(response.text)}", hint)) from exc
    if not isinstance(data, dict):
        raise WorkbenchError(_said(
            f"Could not {what}: ClickUp sent {_kind(data)} where the answer should be an "
            f"object (HTTP {response.status_code}): {_cut(response.text)}", hint))
    return data


def _objects(data: dict, key: str, what: str, hint: str = "",
             needs: tuple = ()) -> list[dict]:
    """The list of objects an answer should hold under `key`, or a sentence saying what
    arrived instead.

    A 200 of an unexpected shape is still a failed read: it used to stop the page with
    whatever error the reader hit first — an AttributeError on a list, a KeyError on a
    space with no id — which tells a person nothing about what to do next.
    """
    got = data.get(key) or []
    if not isinstance(got, list):
        raise WorkbenchError(_said(
            f'Could not {what}: ClickUp sent "{key}" as {_kind(got)}, not a list.', hint))
    for item in got:
        if not isinstance(item, dict):
            raise WorkbenchError(_said(
                f'Could not {what}: ClickUp sent {_kind(item)} inside "{key}" where an '
                "object was expected.", hint))
        missing = [f'"{field}"' for field in needs if not item.get(field)]
        if missing:
            raise WorkbenchError(_said(
                f'Could not {what}: an entry in "{key}" has no '
                f'{" and no ".join(missing)}.', hint))
    return got


def _read_objects(url: str, key: str, what: str, hint: str,
                  needs: tuple = ()) -> list[dict]:
    """One GET whose answer is a list of objects under `key`."""
    return _objects(_request("GET", url, what=what, hint=hint), key, what, hint, needs)


def list_url(list_id: str, team_id: str | None = None) -> str:
    team_id = team_id or os.environ.get("CLICKUP_TEAM_ID", "")
    return f"https://app.clickup.com/{team_id}/v/li/{list_id}"


def get_lists() -> list[dict]:
    """Return the workspace's lists as [{id, name, space}] for the picker.

    The same two absences as get_tasks(): no CLICKUP_TEAM_ID -> [] (nothing to list);
    configured but failing -> WorkbenchError, from whichever request failed. A picker
    that reads as empty because a token expired offers no board, and a run without one
    calls every meeting point new.
    """
    team_id = os.environ.get("CLICKUP_TEAM_ID")
    if not team_id:
        return []

    def read(url: str, key: str, what: str) -> list[dict]:
        # Every entry the picker shows is named by its id and its name, so an answer
        # missing either is a failed read rather than a nameless row in the picker.
        return _read_objects(url, key, what, _TEAM_HINT, needs=("id", "name"))

    out: list[dict] = []
    for space in read(f"{API}/team/{team_id}/space", "spaces",
                      "read the workspace's spaces"):
        sid, sname = space["id"], space["name"]
        for lst in read(f"{API}/space/{sid}/list", "lists",
                        f"read the lists in {sname}"):
            out.append({"id": lst["id"], "name": lst["name"], "space": sname})
        for folder in read(f"{API}/space/{sid}/folder", "folders",
                           f"read the folders in {sname}"):
            for lst in read(f"{API}/folder/{folder['id']}/list", "lists",
                            f"read the lists in {folder['name']}"):
                out.append({"id": lst["id"], "name": f"{folder['name']} / {lst['name']}",
                            "space": sname})
    return out


def get_members() -> list[dict]:
    """Return the workspace's members as [{'id': str, 'name': str}].

    Lives here, with every other ClickUp request, so that one function carries the token
    and says what a failure was; resolving a name against these members is
    `src/assignees.py`'s pure work. The same two absences as the other reads: no
    CLICKUP_TEAM_ID -> [], configured but failing -> WorkbenchError. `known_members()` is
    the one caller allowed to turn that failure into an unassigned task.
    """
    team_id = os.environ.get("CLICKUP_TEAM_ID")
    if not team_id:
        return []
    what = "read the workspace's members"
    for team in _read_objects(f"{API}/team", "teams", what, _TEAM_HINT):
        if str(team.get("id")) == str(team_id):
            out = []
            for member in _objects(team, "members", what, _TEAM_HINT):
                user = member.get("user")
                # A seat nobody has taken up has no user to assign anything to.
                if isinstance(user, dict) and user.get("id") is not None:
                    out.append({"id": str(user["id"]), "name": user.get("username") or ""})
            return out
    return []


def known_members() -> list[dict]:
    """The workspace's members when the tracker can be read, and none when it cannot.

    The one place a member read is allowed to degrade. An owner who cannot be resolved
    leaves a task unassigned, and a roster that cannot be read leaves the prompts reading
    names out of the transcript — both smaller failures than refusing to run. Every other
    read raises, because a board that reads as empty turns every point into new work.
    """
    try:
        return get_members()
    except WorkbenchError:
        return []


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
        data = _request(
            "GET", f"{API}/list/{list_id}/task",
            params={"include_closed": "true" if include_closed else "false", "page": page},
            what="read the board", hint=_LIST_HINT,
        )
        tasks = _objects(data, "tasks", "read the board", _LIST_HINT)
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
    try:
        _request("POST", f"{API}/task/{task_id}/comment",
                 what=f"comment on task {task_id}",
                 body={"comment_text": text, "notify_all": False})
    except WorkbenchError as exc:
        # A refused or dropped comment is a failed effect like a rejected one: reported,
        # keyless, free to be retried — not a traceback that loses the rest of the run's
        # summary.
        return False, str(exc)
    return True, task_id


def _create_task(list_id: str, task: dict, assignee_id: str | None = None) -> tuple[bool, str]:
    """Create one task. Returns (ok, task_name_or_reason)."""
    payload = {
        "name": str(task.get("name", "Untitled task"))[:250],
        # A null description is no description, not the word "None".
        "description": str(task.get("description") or ""),
    }
    priority = task.get("priority")
    if priority in (1, 2, 3, 4):
        payload["priority"] = priority
    if assignee_id:
        payload["assignees"] = [int(assignee_id)]
    tags = [str(t) for t in task.get("tags", [])]
    if tags:
        payload["tags"] = tags

    url = f"{API}/list/{list_id}/task"
    what = f'create the task "{payload["name"]}"'
    try:
        _request("POST", url, what=what, body=payload, timeout=30)
        return True, payload["name"]
    except _Unreachable as exc:
        # Nothing answered, so the task may exist already: offering it again is how one
        # effect becomes two tasks. The effect stays failed and keyless, free to be
        # retried by a person who can see the board.
        return False, str(exc)
    except WorkbenchError as exc:
        # Tags that don't exist in the space can get the create refused — offer it once
        # more without them, because the task matters more than its labels.
        if not tags:
            return False, str(exc)
    # A second payload, not the first one emptied: the first has been sent, and a request
    # that is still in flight must not have its body changed underneath it.
    tagless = {field: value for field, value in payload.items() if field != "tags"}
    try:
        _request("POST", url, what=what, body=tagless, timeout=30)
    except WorkbenchError as exc:
        return False, str(exc)
    return True, tagless["name"]


def push_context() -> tuple[list[dict], dict[str, str], str | None]:
    """Members, alias map and backlog list — read once per batch of writes."""
    from .assignees import alias_map

    # A newly found defect belongs in the backlog, not in the running sprint. With no
    # backlog list configured everything still lands in the main list, tagged with
    # the intended destination, so nothing is silently lost.
    return known_members(), alias_map(), os.environ.get("CLICKUP_BACKLOG_LIST_ID")


def push_one(
    task: dict,
    list_id: str,
    members: list[dict],
    aliases: dict[str, str],
    backlog_id: str | None,
) -> dict:
    """Create one task: resolve the owner, route to the backlog, tag type/destination.

    Returns {ok, info, assigned, backlog}. One task at a time so a caller can record
    exactly which effect succeeded — the idempotency key is committed per effect.
    """
    from .assignees import resolve_owner

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
    return {
        "ok": ok,
        "info": info,
        "assigned": bool(assignee_id) and ok,
        "backlog": wants_backlog and ok,
    }
