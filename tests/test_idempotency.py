from __future__ import annotations

import json
from pathlib import Path

from src.idempotency import effect_key, normalize

VECTORS = json.loads(
    (Path(__file__).resolve().parent / "idempotency_vectors.json").read_text(encoding="utf-8")
)


def test_normalize_vectors():
    for case in VECTORS["normalize"]:
        assert normalize(case["in"]) == case["out"]


def test_normalize_handles_none():
    assert normalize(None) == ""


def test_effect_key_matches_pinned_vectors():
    for case in VECTORS["effect_key"]:
        assert effect_key(case["kind"], case["target"], case["content"]) == case["key"]


def test_new_and_update_keys_differ_for_same_text():
    assert effect_key("NEW", "", "ship it") != effect_key("UPDATE", "t1", "ship it")


def test_update_key_depends_on_target():
    assert effect_key("UPDATE", "t1", "x") != effect_key("UPDATE", "t2", "x")
