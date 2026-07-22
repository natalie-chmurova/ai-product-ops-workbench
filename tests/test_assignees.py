"""Owner → assignee resolution (pure logic, no API)."""

from src.assignees import normalize, resolve_owner

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
