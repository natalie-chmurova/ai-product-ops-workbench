"""Owner → assignee resolution (pure logic), and the one live roster it is built from."""

from src import clickup
from src.assignees import build_roster, normalize, resolve_owner, roster_line, team_roster

MEMBERS = [
    {"id": "222150225", "name": "Natallia Chmurova"},
    {"id": "999", "name": "Marco Rossi"},
]
ALIASES = {"dana": "222150225", "priya": "222150225"}


def test_normalize():
    assert normalize("  Dana ") == "dana"
    assert normalize(None) == ""


def test_alias_takes_priority():
    # Dana isn't a member, but the alias resolves her.
    assert resolve_owner("Dana", MEMBERS, ALIASES) == "222150225"


def test_fuzzy_first_name_match():
    # "Marco" matches "Marco Rossi" by first name.
    assert resolve_owner("Marco", MEMBERS, ALIASES) == "999"


def test_full_name_match():
    assert resolve_owner("Natallia Chmurova", MEMBERS, ALIASES) == "222150225"


def test_unassigned_is_none():
    assert resolve_owner("Unassigned", MEMBERS, ALIASES) is None
    assert resolve_owner("", MEMBERS, ALIASES) is None
    assert resolve_owner(None, MEMBERS, ALIASES) is None


def test_unknown_name_is_none():
    # A name with no alias and no member match stays unassigned.
    assert resolve_owner("Zoltan", MEMBERS, ALIASES) is None


# --- roster: the closed list of people the pipeline is allowed to recognise ---

RAW_ALIASES = "Dana:222150225, Priya:222150225"


def test_roster_combines_members_and_aliases():
    roster = build_roster(MEMBERS, RAW_ALIASES)
    names = [r["name"] for r in roster]
    assert "Natallia Chmurova" in names
    assert "Marco Rossi" in names
    assert "Dana" in names and "Priya" in names


def test_roster_keeps_original_spelling():
    # the prompt shows these names to the model, so "Dana" must not arrive as "dana"
    roster = build_roster([], "Dana:1,  marco :2")
    assert [r["name"] for r in roster] == ["Dana", "marco"]


def test_roster_carries_ids():
    roster = build_roster([], RAW_ALIASES)
    assert roster[0] == {"name": "Dana", "id": "222150225"}


def test_roster_dedupes_by_name():
    # the same person configured both ways should appear once
    roster = build_roster([{"id": "999", "name": "Marco Rossi"}], "Marco Rossi:999")
    assert len(roster) == 1


def test_roster_empty_when_nothing_configured():
    assert build_roster([], "") == []


def test_roster_line_is_prompt_ready():
    assert roster_line(build_roster([], RAW_ALIASES)) == "Dana, Priya"
    assert roster_line([]) == ""


# --- the live roster: read from the tracker, and never a raise -----------------

TEAMS = f"{clickup.API}/team"


def _configured(monkeypatch) -> None:
    monkeypatch.setenv("CLICKUP_TEAM_ID", "9018")
    monkeypatch.setenv("OWNER_ALIASES", RAW_ALIASES)


def test_the_live_roster_is_the_tracker_s_members_and_the_aliases(monkeypatch, transport):
    _configured(monkeypatch)
    transport.answers(TEAMS, {"teams": [{"id": "9018", "members": [
        {"user": {"id": 999, "username": "Marco Rossi"}}]}]})
    assert team_roster() == [{"name": "Marco Rossi", "id": "999"},
                             {"name": "Dana", "id": "222150225"},
                             {"name": "Priya", "id": "222150225"}]


def test_a_roster_the_tracker_cannot_be_reached_for_is_the_aliases(monkeypatch, transport):
    # The roster is read before every run, and it is not what a run is for: raising here
    # would stop a transcript that needs no tracker at all. The aliases still name people,
    # and with none of them the prompts read names out of the transcript.
    _configured(monkeypatch)
    transport.drops(TEAMS)
    assert [r["name"] for r in team_roster()] == ["Dana", "Priya"]


def test_a_roster_the_tracker_answered_strangely_is_the_aliases(monkeypatch, transport):
    # Every way a member read can fail degrades the same way — a refused token, a dropped
    # connection, and a 200 that is not the shape a reader can read.
    _configured(monkeypatch)
    transport.answers(TEAMS, status=401, text="Token invalid")
    assert [r["name"] for r in team_roster()] == ["Dana", "Priya"]
    transport.answers(TEAMS, {"teams": "none"})
    assert [r["name"] for r in team_roster()] == ["Dana", "Priya"]


def test_an_unconfigured_roster_asks_the_tracker_nothing(monkeypatch, transport):
    monkeypatch.delenv("CLICKUP_TEAM_ID", raising=False)
    monkeypatch.setenv("OWNER_ALIASES", RAW_ALIASES)
    assert [r["name"] for r in team_roster()] == ["Dana", "Priya"]
    assert transport.calls == []
