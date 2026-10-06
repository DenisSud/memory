"""System One client: one HTTP call per batch of questions.

System One is TypeSafe's classification protocol. A call posts
``{"model", "state", "questions"}`` to ``{base_url}/systemone`` and receives
one answer per question; for a ``noul`` question the answer carries the
probability that the proposition is true.
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class SystemOneError(Exception):
    """Raised when a System One call fails. Callers decide whether to fail open."""


class SystemOneClient:
    """Sync and async System One client.

    One client instance per call site; each call opens its own connection, so
    the client holds no resources and needs no closing.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_ms: int = 5000,
    ):
        self.url = f"{base_url.rstrip('/')}/systemone"
        self.model = model
        self.timeout = timeout_ms / 1000.0
        self.headers = {"content-type": "application/json"}
        if api_key:
            self.headers["authorization"] = f"Bearer {api_key}"

    def _payload(self, state: Dict[str, Any], questions: Dict[str, Any]) -> Dict[str, Any]:
        return {"model": self.model, "state": state, "questions": questions}

    def ask(self, state: Dict[str, Any], questions: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """Return ``{question_id: probability}``; ``None`` when an answer is missing."""
        payload = self._payload(state, questions)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.url, headers=self.headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as e:
            raise SystemOneError(f"System One request failed: {e}") from e
        return _answers(body, questions)

    async def ask_async(self, state: Dict[str, Any], questions: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """Async counterpart of :meth:`ask`."""
        payload = self._payload(state, questions)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, headers=self.headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as e:
            raise SystemOneError(f"System One request failed: {e}") from e
        return _answers(body, questions)


def _answers(body: Any, questions: Dict[str, Any]) -> Dict[str, Optional[float]]:
    answers = body.get("answers") if isinstance(body, dict) else None
    result: Dict[str, Optional[float]] = {}
    for question_id in questions:
        answer = answers.get(question_id) if isinstance(answers, dict) else None
        probability = answer.get("noul") if isinstance(answer, dict) else None
        result[question_id] = float(probability) if isinstance(probability, (int, float)) else None
    return result
