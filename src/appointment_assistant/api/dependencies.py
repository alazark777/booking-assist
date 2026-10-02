from __future__ import annotations

from fastapi import Header, Request

from appointment_assistant.domain.models import DomainError, Principal


async def current_principal(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise DomainError("authentication_required", "A valid bearer credential is required.", 401)
    token = authorization.removeprefix("Bearer ").strip()
    principal_id = request.app.state.settings.credential_map().get(token)
    if not principal_id:
        raise DomainError("authentication_failed", "The bearer credential is invalid.", 401)
    return Principal(principal_id)
