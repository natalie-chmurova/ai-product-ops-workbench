"""Resolve an extracted owner name to a real ClickUp assignee.

ClickUp assigns by numeric user id, but a transcript only gives a name. This
resolves a name to a workspace member id via, in order:

  1. an explicit alias map (OWNER_ALIASES env) — teams have nicknames/aliases,
     and it's also how the synthetic demo cast maps onto a real account;
  2. a fuzzy match against the workspace members (first name, case-insensitive);
  3. otherwise None — the task is left unassigned (honest fallback).

Nothing here talks to ClickUp: the members come in as an argument, from
`src/clickup.py`, where the token and every request live. What is left is the work that
can be read and tested on its own — the alias map, the roster and the resolution.
"""

from __future__ import annotations

import os

from .clickup import known_members


def normalize(name: str | None) -> str:
    return (name or "").strip().lower()


def alias_map() -> dict[str, str]:
    """Parse OWNER_ALIASES='Name:id,Name:id' into {normalized_name: id}."""
    raw = os.environ.get("OWNER_ALIASES", "")
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            name, uid = pair.split(":", 1)
            name, uid = name.strip(), uid.strip()
            if name and uid:
                out[normalize(name)] = uid
    return out


def build_roster(members: list[dict], raw_aliases: str) -> list[dict]:
    """The closed list of people this pipeline is allowed to recognise.

    Workspace members from the tracker, plus the configured aliases (teams have
    nicknames, and in the demo the synthetic cast maps onto one real account).
    Names keep their original spelling because they go into the prompt for the
    model to match against — a closed list is what stops it inventing people.

    Pure function: takes members and the raw OWNER_ALIASES string, hits nothing.
    """
    roster: list[dict] = []
    seen: set = set()

    def add(name: str, uid: str) -> None:
        name = (name or "").strip()
        key = normalize(name)
        if not name or key in seen:
            return
        seen.add(key)
        roster.append({"name": name, "id": str(uid)})

    for m in members:
        add(m.get("name", ""), m.get("id", ""))
    for pair in (raw_aliases or "").split(","):
        if ":" in pair:
            alias_name, uid = pair.split(":", 1)
            add(alias_name, uid.strip())
    return roster


def roster_line(roster: list[dict]) -> str:
    """Roster as a single line for a prompt: 'Dana, Marco, Priya'."""
    return ", ".join(r["name"] for r in roster)


def team_roster() -> list[dict]:
    """The live roster: tracker members plus configured aliases.

    Never raises. A member read that failed becomes no members in one place,
    `clickup.known_members`, so with no ClickUp credentials — or a tracker that cannot be
    reached — you still get the aliases; with nothing configured at all you get an empty
    roster, and the prompts simply fall back to reading names out of the transcript.
    """
    return build_roster(known_members(), os.environ.get("OWNER_ALIASES", ""))


def resolve_owner(name: str | None, members: list[dict], aliases: dict[str, str]) -> str | None:
    """Name -> ClickUp user id, or None if it can't be resolved."""
    n = normalize(name)
    if not n or n == "unassigned":
        return None
    if n in aliases:
        return aliases[n]
    for m in members:
        mn = normalize(m.get("name"))
        if not mn:
            continue
        first = mn.split()[0]
        if n == mn or n == first or n in mn.split():
            return str(m["id"])
    return None
