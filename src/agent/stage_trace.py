"""Request-local, text-free execution spans for the specialist graph."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator


TraceId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class StageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


class StageFailure(StrEnum):
    STAGE_ERROR = "stage_error"
    WORKER_ERROR = "worker_error"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    PROVIDER_FALLBACK = "provider_fallback"
    UNSUPPORTED_REQUEST = "unsupported_request"
    RELEASE_WITHHELD = "release_withheld"


class StageTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: TraceId
    stage: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,64}$")]
    start_time: AwareDatetime
    end_time: AwareDatetime
    status: StageStatus
    source_ids: tuple[TraceId, ...] = ()
    evidence_ids: tuple[TraceId, ...] = ()
    failure_reason: StageFailure | None = None
    tool_calls: int = Field(default=0, ge=0)
    retrieval_calls: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=0, ge=0)
    output_tokens: int | None = Field(default=0, ge=0)
    estimated_cost: Decimal | None = Field(default=Decimal(0), ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_interval(self) -> StageTrace:
        if self.end_time < self.start_time:
            raise ValueError("stage end must follow its start")
        return self


def trace_id(value: str) -> str:
    """Emit only a stable fingerprint, even for caller-supplied identifiers."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class StageRecorder:
    def __init__(self, request_id: str):
        self.request_id = trace_id(request_id)
        self._stages: list[StageTrace] = []
        self._lock = Lock()

    def add(self, stage: str, start: datetime, status: StageStatus, **fields) -> None:
        trace = StageTrace(request_id=self.request_id, stage=stage, start_time=start,
                           end_time=max(start, datetime.now(UTC)), status=status, **fields)
        with self._lock:
            self._stages.append(trace)

    def snapshot(self) -> tuple[StageTrace, ...]:
        with self._lock:
            return tuple(sorted(self._stages, key=lambda trace: trace.start_time))
