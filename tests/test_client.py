"""The model client: what comes back when a reply does not fit its ceiling.

The current models think before they answer, and that thinking is spent from the same
`max_tokens` as the visible reply. A ceiling sized for the reply alone — 400 tokens for a
four-line match answer — is then sometimes spent before the answer is written: on
2026-10-13 one live match came back as `DECISION: UPDATE`, `TASK_ID: ...`,
`CONFIDENCE:` and stopped, and another lost its `DECISION:` line entirely and was sent to
a person as unreadable. The model is faked at the SDK's edge, where `stop_reason` arrives.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import client
from src.client import WorkbenchError, ask

FULL = "DECISION: UPDATE\nTASK_ID: 86abc\nCONFIDENCE: 0.9\nREASON: same release"


class FakeModel:
    """Answers each request from a script of (text, stop_reason), and keeps what it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        text, stop = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
        return SimpleNamespace(content=blocks, stop_reason=stop)


@pytest.fixture
def model(monkeypatch):
    def install(*replies):
        fake = FakeModel(*replies)
        monkeypatch.setattr(client, "_get_client", lambda: fake)
        return fake
    return install


def test_a_reply_that_finished_is_asked_for_once(model):
    fake = model((FULL, "end_turn"))
    assert ask("system", "prompt", max_tokens=400) == FULL
    assert len(fake.requests) == 1


def test_a_reply_cut_off_by_its_ceiling_is_asked_again_with_room_to_finish(model):
    # Returned as it stood, the cut-off reply reads as a match with no confidence, or as
    # no match at all, and goes to a person for a reason that has nothing to do with doubt.
    fake = model(("DECISION: UPDATE\nTASK_ID: 86abc\nCONFIDENCE:", "max_tokens"),
                 (FULL, "end_turn"))
    assert ask("system", "prompt", max_tokens=400) == FULL
    assert [r["max_tokens"] for r in fake.requests] == [400, client.TOKEN_CEILING]


def test_a_reply_still_cut_off_at_the_ceiling_is_an_error_not_half_a_document(model):
    # A sprint summary or a triage table cut off mid-sentence used to reach the screen as
    # if it were the whole document.
    model(("## Sprint summary\n- Checkout ships Wed", "max_tokens"))
    with pytest.raises(WorkbenchError) as exc:
        ask("system", "prompt", max_tokens=2000)
    assert "cut off" in str(exc.value)
