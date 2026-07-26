from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentFrontendDefinition:
    agent_id: str
    agent_version: str
    module_id: str
    contract_version: str


DEFAULT_AGENT_FRONTEND = AgentFrontendDefinition(
    agent_id="general",
    agent_version="1",
    module_id="general-chat",
    contract_version="lumina-frontend-v1",
)

_BUILTIN_AGENT_FRONTENDS = {
    (
        DEFAULT_AGENT_FRONTEND.agent_id,
        DEFAULT_AGENT_FRONTEND.agent_version,
    ): DEFAULT_AGENT_FRONTEND,
}


def agent_frontend_payload(agent_id: str, agent_version: str) -> dict[str, object]:
    definition = _BUILTIN_AGENT_FRONTENDS.get((agent_id, agent_version))
    fallback = definition is None
    resolved = definition or DEFAULT_AGENT_FRONTEND
    return {
        "id": agent_id,
        "version": agent_version,
        "frontendModule": resolved.module_id,
        "frontendContract": resolved.contract_version,
        "fallback": fallback,
    }


def normalize_agent_frontend_payload(
    snapshot: object, *, agent_id: str, agent_version: str
) -> dict[str, object]:
    if isinstance(snapshot, dict):
        snapshot_agent_id = snapshot.get("id")
        snapshot_agent_version = snapshot.get("version")
        module_id = snapshot.get("frontendModule")
        contract_version = snapshot.get("frontendContract")
        if all(
            isinstance(value, str) and value
            for value in (
                snapshot_agent_id,
                snapshot_agent_version,
                module_id,
                contract_version,
            )
        ):
            return {
                "id": snapshot_agent_id,
                "version": snapshot_agent_version,
                "frontendModule": module_id,
                "frontendContract": contract_version,
                "fallback": bool(snapshot.get("fallback", False)),
            }
        if isinstance(snapshot_agent_id, str) and snapshot_agent_id:
            agent_id = snapshot_agent_id
        if isinstance(snapshot_agent_version, str) and snapshot_agent_version:
            agent_version = snapshot_agent_version
    return agent_frontend_payload(agent_id, agent_version)
