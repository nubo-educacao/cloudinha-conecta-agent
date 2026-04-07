from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class UIContext(BaseModel):
    current_page: str               # ex: "/oportunidades"
    page_data: Optional[dict] = None
    form_state: Optional[dict] = None
    focused_field: Optional[str] = None


class ChatRequest(BaseModel):
    chatInput: str
    userId: UUID
    active_profile_id: UUID
    sessionId: str
    intent_type: Optional[str] = "user_message"  # "user_message" | "system_intent"
    ui_context: Optional[UIContext] = None
