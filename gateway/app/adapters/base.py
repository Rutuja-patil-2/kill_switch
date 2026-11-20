"""Adapter contract. Phase 1 ships one generic REST adapter that works for any tool that follows
the usual convention (GET a resource before you change it). Tool-specific adapters (payments
holds, compensating actions) are added in Phase 2 by subclassing and overriding."""
from dataclasses import dataclass

from ..util import body_version, parse_json


@dataclass
class Snapshot:
    resource: str
    value: object
    version: str | None
    existed: bool


class Adapter:
    name = "generic-rest"

    def classify(self, method: str, path: str) -> str:
        """'read' or 'write'. (Phase 2 adds 'irreversible'.)"""
        return "read" if method in ("GET", "HEAD", "OPTIONS") else "write"

    def resource(self, tool: str, path: str) -> str:
        return f"{tool}:/{path.strip('/')}"

    async def snapshot(self, client, tool: str, url: str, method: str, path: str):
        """Before-state: read the resource just before a change. POST creates have no before-state."""
        if self.classify(method, path) != "write" or method == "POST":
            return None
        r = await client.get(url)
        res = self.resource(tool, path)
        if r.status_code == 200:
            return Snapshot(res, parse_json(r.content), body_version(r.content, r.headers), True)
        return Snapshot(res, None, None, False)

    def after(self, tool: str, method: str, path: str, body: bytes, headers):
        """After-state: returns (resource, value, version)."""
        data = parse_json(body)
        res = self.resource(tool, path)
        if method == "POST" and isinstance(data, dict) and "id" in data:
            res = self.resource(tool, f"{path.strip('/')}/{data['id']}")
        if method == "DELETE":
            return res, None, None
        return res, data, body_version(body, headers)
