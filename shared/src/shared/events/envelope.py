from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: str
    aggregate_id: str
    tenant_id: int | None = None
    payload: dict[str, Any] = {}
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
