"""Helpers de streaming NDJSON."""
import json
from typing import AsyncGenerator


async def ndjson_wrap(events: AsyncGenerator[dict, None]) -> AsyncGenerator[str, None]:
    """Serializa um generator de dicts como linhas NDJSON."""
    async for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"


def serialize_event(event: dict) -> str:
    """Serializa um único evento como linha NDJSON."""
    return json.dumps(event, ensure_ascii=False) + "\n"
