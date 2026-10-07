"""Shared fixtures for the System One gate tests."""

import json
from typing import Any, Dict, List, Optional

import httpx
import pytest

from mem0.configs.systemone import SystemOneConfig
from mem0.systemone import client as client_module
from mem0.systemone.gates import SystemOneGates


class FakeGateway:
    """A System One endpoint backed by httpx.MockTransport."""

    def __init__(
        self,
        probabilities: Optional[Dict[str, float]] = None,
        status_code: int = 200,
        transport_error: Optional[Exception] = None,
    ):
        self.probabilities = probabilities or {}
        self.status_code = status_code
        self.transport_error = transport_error
        self.requests: List[Dict[str, Any]] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.requests.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("authorization"),
                "payload": payload,
            }
        )
        if self.transport_error:
            raise self.transport_error
        answers = {
            question_id: {"type": "noul", "noul": self.probabilities[question_id]}
            for question_id in payload["questions"]
            if question_id in self.probabilities
        }
        return httpx.Response(self.status_code, json={"answers": answers, "usage": {}})

    def install(self, monkeypatch) -> "FakeGateway":
        transport = httpx.MockTransport(self._handle)
        # Captured before patching: the factories must call the real httpx classes,
        # not themselves.
        real_client = httpx.Client
        real_async_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return real_client(*args, transport=transport, **kwargs)

        def async_client_factory(*args, **kwargs):
            return real_async_client(*args, transport=transport, **kwargs)

        monkeypatch.setattr(client_module.httpx, "Client", client_factory)
        monkeypatch.setattr(client_module.httpx, "AsyncClient", async_client_factory)
        return self


@pytest.fixture
def systemone(monkeypatch):
    """Build a ``(gateway, gates)`` pair: canned probabilities, real gate code."""

    def build(**config_overrides):
        gateway = FakeGateway(
            probabilities=config_overrides.pop("probabilities", None),
            status_code=config_overrides.pop("status_code", 200),
            transport_error=config_overrides.pop("transport_error", None),
        ).install(monkeypatch)
        config = SystemOneConfig(
            base_url=config_overrides.pop("base_url", "http://systemone.test/v1"),
            model=config_overrides.pop("model", "clef-flash:9b-8k"),
            **config_overrides,
        )
        return gateway, SystemOneGates(config)

    return build
