"""Resolve an extracted owner name to a real ClickUp assignee.

ClickUp assigns by numeric user id, but a transcript only gives a name. This
resolves a name to a workspace member id via, in order:

  1. an explicit alias map (OWNER_ALIASES env) — teams have nicknames/aliases,
     and it's also how the synthetic demo cast maps onto a real account;
  2. a fuzzy match against the workspace members (first name, case-insensitive);
  3. otherwise None — the task is left unassigned (honest fallback).

The resolution itself is pure (takes members + aliases), so it's unit-testable
without hitting the API.
"""

from __future__ import annotations

import os

import requests

from .client import WorkbenchError

API = "https://api.clickup.com/api/v2"


def normalize(name: str | None) -> str:
    return (name or "").strip().lower()


def _headers() -> dict:
    token = os.environ.get("CLICKUP_API_TOKEN")
    if not token:
        raise WorkbenchError("No CLICKUP_API_TOKEN found.")
    return {"Authorization": token}


def get_members() -> list[dict]:
    """Return workspace members as [{'id': str, 'name': str}]."""
    team_id = os.environ.get("CLICKUP_TEAM_ID")
    if not team_id:
        return []
    teams = requests.get(f"{API}/team", headers=_headers(), timeout=20).json().get("teams", [])
    for t in teams:
        if str(t.get("id")) == str(team_id):
            out = []
            for m in t.get("members", []):
                u = m.get("user", {})
                if u.get("id") is not None:
                    out.append({"id": str(u["id"]), "name": u.get("username") or ""})
            return out
    return []


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
