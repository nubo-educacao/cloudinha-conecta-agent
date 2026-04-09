import json
from typing import Optional
from src.models.chat_request import UIContext


def build_lean_context(
    user_id: str,
    active_profile_id: str,
    full_name: str,
    age: Optional[int],
    cognitive_memory: Optional[dict],
    recent_messages: list[dict],  # últimas 5 msgs [{role, content}]
    ui_context: Optional[UIContext],
) -> str:
    """Monta o contexto mínimo injetado em TODOS os agentes.

    Este é o ÚNICO ponto de montagem de contexto. Planning, Reasoning e
    Response recebem variações deste output — nunca um dump bruto de user_profiles.
    """
    parts: list[str] = []

    # 1. Identidade
    parts.append(f"USER_ID: {user_id}")
    parts.append(f"ACTIVE_PROFILE_ID: {active_profile_id}")
    parts.append(f"NOME: {full_name or 'Desconhecido'}")
    if age:
        parts.append(f"IDADE: {age}")

    # 2. Long-Term Memory
    if cognitive_memory:
        parts.append(f"\nMEMÓRIA DE LONGO PRAZO:\n{cognitive_memory}")

    # 3. Sessão curta (últimas 5 mensagens)
    if recent_messages:
        history = "\n".join(
            f"{'Usuário' if m['sender'] == 'user' else 'Cloudinha'}: {m['content']}"
            for m in recent_messages[-5:]
        )
        parts.append(f"\nHISTÓRICO RECENTE DA SESSÃO:\n{history}")

    # 4. UI Context
    if ui_context:
        parts.append(f"\nPÁGINA ATUAL: {ui_context.current_page}")
        if ui_context.page_data:
            parts.append(f"DADOS DA TELA: {ui_context.page_data}")
        if ui_context.form_state:
            parts.append(
                f"ESTADO DO FORMULÁRIO: {json.dumps(ui_context.form_state, ensure_ascii=False)}"
            )
            if ui_context.focused_field:
                parts.append(f"CAMPO EM FOCO: {ui_context.focused_field}")

    return "\n".join(parts)
