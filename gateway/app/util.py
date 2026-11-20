"""Pure helpers (stdlib only) so they are easy to unit-test."""
import hashlib
import json
import re

GENESIS = "0" * 64
_SENSITIVE = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.I)


def redact(obj):
    """Mask secret-looking keys so they never land in the ledger."""
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if _SENSITIVE.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def chain_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(payload)).encode()).hexdigest()


def parse_json(body: bytes):
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def body_version(body: bytes, headers=None) -> str:
    """Version of a resource: its own 'version' field, else the ETag, else a content hash."""
    data = parse_json(body)
    if isinstance(data, dict) and "version" in data:
        return str(data["version"])
    etag = headers.get("etag") if headers is not None else None
    if etag:
        return etag.strip('"')
    return "h:" + hashlib.sha256(body or b"").hexdigest()[:16]


def summarize(body: bytes, limit: int = 2000):
    data = parse_json(body)
    if data is not None:
        return redact(data)
    return {"text": (body or b"").decode(errors="replace")[:limit]}
