from dataclasses import dataclass


@dataclass
class Action:
    """The one internal shape every request is normalised into (HTTP now, MCP later)."""
    id: str
    agent_id: str
    tool: str
    method: str
    path: str
    args: dict
    session_id: str | None = None
    parent_id: str | None = None
