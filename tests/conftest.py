"""Shared pytest fixtures and helpers for the store-and-forward test suite."""

from __future__ import annotations

import json
from typing import Callable

import httpx
import pytest


class FakeClock:
    """An injectable, manually-advanced clock.

    The Forwarder's backoff and TTL logic are both time-based. Rather than
    making tests actually sleep for seconds (slow, flaky), tests inject one
    of these as the Forwarder's `clock` and move it forward explicitly with
    `advance()`.
    """

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


class RecordingEndpoint:
    """A togglable, order-recording fake cloud endpoint.

    Used as the handler for an ``httpx.MockTransport``, so tests can flip
    the endpoint "up"/"down" mid-test, with no real network involved.
    """

    def __init__(self) -> None:
        self.up = True
        self.received_ids: list[int] = []
        self.request_count = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        if not self.up:
            return httpx.Response(503, json={"error": "cloud unavailable"})

        body = json.loads(request.content.decode("utf-8"))
        self.received_ids.append(body.get("id", body.get("source")))
        return httpx.Response(201, json={"stored": True})


@pytest.fixture
def recording_endpoint() -> RecordingEndpoint:
    return RecordingEndpoint()


def make_mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://cloud.test")
