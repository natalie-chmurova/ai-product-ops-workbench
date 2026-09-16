"""The one fake transport every ClickUp test runs against.

`src.clickup` sends every request through one function, and that function makes exactly
one call: `requests.request`. Faking it here, once, is what lets a test say only what
ClickUp answered, without knowing which of the module's functions asked, or how. Answers
are routed by URL and queued: route two and the first request gets the first, while the
last one routed answers every request after it. An unrouted URL is a test failure, so a
request nobody expected cannot pass unnoticed.
"""

from __future__ import annotations

import copy
import json

import pytest
import requests

from src import clickup


class Call:
    """One request the module made, as the transport received it."""

    def __init__(self, method: str, url: str, kwargs: dict):
        self.method = method
        self.url = url
        self.params = kwargs.get("params")
        # Copied, because a real transport turns the body into bytes as it sends it: what
        # the caller does to that dict afterwards cannot change what ClickUp received,
        # and a fake that kept the live object would say it could.
        self.body = copy.deepcopy(kwargs.get("json"))
        self.headers = kwargs.get("headers") or {}
        self.timeout = kwargs.get("timeout")

    def __repr__(self) -> str:
        return f"<Call {self.method} {self.url} {self.body!r}>"


class _Answer:
    """What ClickUp sends back: a status, and a body that need not be JSON."""

    def __init__(self, status: int, body, text: str):
        self.status_code = status
        self._body = body
        self.text = text or ("" if body is None else json.dumps(body))

    def json(self):
        if self._body is None:
            # What requests itself raises from .json() for a body that is not JSON. It
            # is a ValueError, which is what the module catches.
            raise requests.exceptions.JSONDecodeError("Expecting value", self.text or "", 0)
        return self._body


class Transport:
    """Stands in for the network: the answers a test routed, and what actually reached it."""

    def __init__(self) -> None:
        self.calls: list = []
        self._routes: dict = {}
        # A read that never stops paging would hang the suite rather than fail it, and a
        # hang issues real requests the day the fake is not in place. Bound it here, once.
        self.max_calls = 100

    def answers(self, url: str, body=None, *, status: int = 200, text: str = "") -> "Transport":
        """ClickUp answers `url` with `status` and `body`. No body means the answer is
        not JSON at all — an HTML error page from a proxy, say."""
        self._routes.setdefault(url, []).append(_Answer(status, body, text))
        return self

    def drops(self, url: str, error: Exception | None = None) -> "Transport":
        """The request to `url` never gets an answer."""
        self._routes.setdefault(url, []).append(error or requests.ConnectionError("down"))
        return self

    @property
    def urls(self) -> list:
        return [call.url for call in self.calls]

    def __call__(self, method: str, url: str, **kwargs):
        self.calls.append(Call(method, url, kwargs))
        if len(self.calls) > self.max_calls:
            raise AssertionError(
                f"the module made more than {self.max_calls} requests without stopping")
        queue = self._routes.get(url)
        if not queue:
            raise AssertionError(f"the test routed no answer for {method} {url}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def no_network(monkeypatch) -> None:
    """Nothing in this suite reaches the network — including the code a test forgot to
    fake. The red run of this ticket sent real requests to api.clickup.com, because the
    module still made them from a site the fake did not cover; one request path is what
    makes a single fake enough, and this is what says so if that stops being true."""

    def refuse(self, request, *args, **kwargs):
        raise AssertionError(f"a test reached the network: {request.method} {request.url}")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", refuse)


@pytest.fixture
def transport(monkeypatch) -> Transport:
    """Fake the one call src.clickup makes to the network, and configure a token, so a
    test that is not about the token does not have to mention one."""
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    fake = Transport()
    monkeypatch.setattr(clickup.requests, "request", fake)
    return fake
