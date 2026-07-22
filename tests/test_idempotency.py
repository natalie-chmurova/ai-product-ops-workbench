from __future__ import annotations

import json
from pathlib import Path

from src.idempotency import IdempotencyStore, effect_key, normalize

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


def test_store_empty_is_not_duplicate(tmp_path):
    store = IdempotencyStore(tmp_path / "s.jsonl")
    assert store.is_duplicate("abc") is False


def test_commit_makes_key_duplicate_and_persists(tmp_path):
    p = tmp_path / "s.jsonl"
    store = IdempotencyStore(p)
    store.commit("abc", {"kind": "NEW", "preview": "x"})
    assert store.is_duplicate("abc") is True
    # a fresh instance reads the committed key back from disk
    assert IdempotencyStore(p).is_duplicate("abc") is True


def test_mark_seen_catches_second_in_same_batch(tmp_path):
    store = IdempotencyStore(tmp_path / "s.jsonl")
    assert store.is_duplicate("k") is False
    store.mark_seen("k")            # first effect, not yet applied/committed
    assert store.is_duplicate("k") is True  # second identical effect in the batch


def test_malformed_line_is_ignored(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"key": "good"}\nnot json\n{"nokey": 1}\n', encoding="utf-8")
    store = IdempotencyStore(p)
    assert store.is_duplicate("good") is True
