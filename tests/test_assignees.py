"""Owner → assignee resolution (pure logic, no API)."""

from src.assignees import build_roster, normalize, resolve_owner, roster_line

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
