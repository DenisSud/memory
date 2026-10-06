from typing import Optional

from pydantic import BaseModel, Field


class SystemOneGateConfig(BaseModel):
    """A single System One gate: whether it runs and the probability floor it keeps."""

    enabled: bool = Field(description="Whether this gate runs", default=True)
    threshold: float = Field(
        description="Minimum System One probability (0-1) for an item to pass the gate",
        default=0.5,
        ge=0.0,
        le=1.0,
    )

    model_config = {"extra": "forbid"}


class SystemOneConfig(BaseModel):
    """System One decision model that filters memories on ingest and on output.

    The model is asked one question per item, so a gate is one extra HTTP call
    per add or search. Items whose probability falls below the gate's threshold
    are dropped; a gate that errors or times out keeps everything (fails open),
    because a flaky decision model must never lose or hide memories.
    """

    base_url: str = Field(description="System One base URL, e.g. 'http://localhost:11434/v1'")
    model: str = Field(description="System One model name, e.g. 'clef-flash:9b-8k'", default="clef-flash:9b-8k")
    api_key: Optional[str] = Field(description="API key, if the endpoint requires one", default=None)
    timeout_ms: int = Field(description="Timeout for one gate call", default=5000, gt=0)
    ingest: SystemOneGateConfig = Field(
        description="Gate applied to extracted facts before they are stored",
        default_factory=lambda: SystemOneGateConfig(),
    )
    output: SystemOneGateConfig = Field(
        description="Gate applied to search results before they are returned",
        default_factory=lambda: SystemOneGateConfig(),
    )

    model_config = {"extra": "forbid"}
