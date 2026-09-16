"""The CLI writes this run's board plan on every run, whatever the board held."""

from __future__ import annotations

import pytest

STALE_PLAN = "# Board plan\n\n## Create (1)\n\n- **[Dev] Last meeting's task** — an earlier run\n"


@pytest.fixture
def workbench(monkeypatch, tmp_path):
    """workbench.run with every model call and board read stubbed, writing under tmp_path.

    workbench.py loads .env when it is imported; this test must not see real keys, so
    that call is disabled before the first import. A request that still reaches for the
    network fails the test instead of leaving the machine.
    """
    import dotenv
    import requests

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    import workbench as wb

    def no_network(*a, **k):
        raise AssertionError("the CLI test reached for the network")

    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setattr("src.reconcile.ask", no_network)
    monkeypatch.setattr(wb, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(wb, "get_tasks", lambda: [])
    monkeypatch.setattr(wb, "team_roster", lambda: [])
    monkeypatch.setattr(wb, "extract_context", lambda transcript, roster: {
        "meeting_title": "Weekly sync",
        "decisions": [{"what": "Ship Wednesday", "affects": "the release"}],
    })
    monkeypatch.setattr(wb, "build_tasks", lambda context: [
        {"name": "[Dev] This meeting's task", "description": "Goal:\nfrom this meeting"}])
    monkeypatch.setattr(wb, "build_sprint_summary", lambda context: "sprint")
    monkeypatch.setattr(wb, "build_bug_triage", lambda context: "triage")
    monkeypatch.setattr(wb, "build_speaker_summary", lambda context, transcript, roster: "speakers")
    monkeypatch.setattr(wb, "render_report", lambda *a: "<html></html>")
    return wb


def _plan_after_a_run(wb, tmp_path) -> str:
    """Leave the previous meeting's plan in outputs/, run the CLI, return the plan."""
    transcript = tmp_path / "meeting.txt"
    transcript.write_text("Dana: the release ships Wednesday.", encoding="utf-8")
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "board_plan.md").write_text(STALE_PLAN, encoding="utf-8")
    wb.run(transcript)
    return (outputs / "board_plan.md").read_text(encoding="utf-8")


def test_an_empty_board_rewrites_the_plan(workbench, monkeypatch, tmp_path):
    # A list is configured and holds no open tasks: the plan says so and lists this
    # meeting's points, instead of going on describing the previous meeting.
    monkeypatch.setenv("CLICKUP_LIST_ID", "list1")
    plan = _plan_after_a_run(workbench, tmp_path)
    assert "Last meeting's task" not in plan
    assert "no open tasks" in plan.lower()
    assert "[Dev] This meeting's task" in plan


def test_no_board_rewrites_the_plan(workbench, monkeypatch, tmp_path):
    monkeypatch.delenv("CLICKUP_LIST_ID", raising=False)
    plan = _plan_after_a_run(workbench, tmp_path)
    assert "Last meeting's task" not in plan
    assert "No board was read" in plan


def test_the_plan_counts_the_meeting_decisions_it_shows(workbench, monkeypatch, tmp_path):
    # One plan, counted once. A meeting decision listed in a section of its own was left
    # out of the numbers the run reports, so the same run read "ask a human 0" beside a
    # decision that is waiting for exactly that.
    monkeypatch.setenv("CLICKUP_LIST_ID", "list1")
    plan = _plan_after_a_run(workbench, tmp_path)
    assert "Ship Wednesday" in plan
    assert "## Ask a human (1)" in plan
