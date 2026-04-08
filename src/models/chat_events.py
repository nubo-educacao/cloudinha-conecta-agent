from pydantic import BaseModel
from typing import Optional, List


class TextEvent(BaseModel):
    type: str = "text"
    content: str


class ToolStartEvent(BaseModel):
    type: str = "tool_start"
    tool: str
    args: Optional[dict] = None


class ToolEndEvent(BaseModel):
    type: str = "tool_end"
    tool: str
    output: Optional[str] = None


class SuggestionsEvent(BaseModel):
    type: str = "suggestions"
    items: List[str]


class ErrorEvent(BaseModel):
    type: str = "error"
    message: str
