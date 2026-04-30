from typing import Optional, List, Any, Literal
from pydantic import BaseModel, Field


class ContextRequest(BaseModel):
    scope: Literal["category", "merchant", "customer", "trigger"]
    context_id: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    payload: dict
    delivered_at: Optional[str] = None


class ContextAccepted(BaseModel):
    accepted: bool = True
    ack_id: str
    stored_at: str


class ContextRejected(BaseModel):
    accepted: bool = False
    reason: str
    current_version: Optional[int] = None
    details: Optional[str] = None


class TickRequest(BaseModel):
    now: Optional[str] = None
    available_triggers: List[str] = Field(default_factory=list, max_length=100)


class ReplyRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: Literal["merchant", "customer", "system"] = "merchant"
    message: str = Field(max_length=8000)
    received_at: Optional[str] = None
    turn_number: int = Field(ge=1, default=2)


class HealthzResponse(BaseModel):
    status: str
    uptime_seconds: int
    contexts_loaded: dict
    llm_configured: bool


class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str
