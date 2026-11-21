import json
import os
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import db, ledger
from .adapters import get_adapter
from .auth import issue_token, verify_token
from .models import Action
from .util import parse_json, redact, summarize

# Request flow:
# 1. Verify the agent JWT and identify the caller.
# 2. Write the append-only intent row before forwarding.
# 3. Apply status and scope policy, including read-only and blocked agents.
# 4. Snapshot existing state, forward the request, and capture the after-state.
# 5. Record reads or changes and the final HTTP result.
# 6. Return the upstream response plus the X-Action-Id audit identifier.
UPSTREAMS: dict[str, str] = json.loads(os.environ.get("UPSTREAMS", "{}"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
# Never forwarded upstream. The agent's own JWT stops here (credential vaulting comes in Phase 3).
_DROP_HEADERS = {"host", "content-length", "connection", "authorization", "transfer-encoding",
                 "x-session-id", "x-parent-action"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    app.state.http = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.http.aclose()
    await db.close_pool()


app = FastAPI(title="Kill Switch Gateway", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"message": detail})


def require_admin(key: str | None):
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "admin key required")


def scope_ok(scopes: list[str], tool: str, kind: str) -> bool:
    return any(s in ("*", f"{tool}:*", f"{tool}:{kind}") for s in scopes)


@app.get("/health")
async def health():
    return {"ok": True}


@app.api_route("/tools/{tool}", methods=METHODS)
@app.api_route("/tools/{tool}/{path:path}", methods=METHODS)
async def proxy(
    tool: str,
    request: Request,
    path: str = "",
    authorization: str | None = Header(None),
    x_session_id: str | None = Header(None),
    x_parent_action: str | None = Header(None),
):
    claims = verify_token(authorization)          # 1. who is calling?
    agent_id = claims["sub"]
    base = UPSTREAMS.get(tool)
    if base is None:
        raise HTTPException(404, f"unknown tool '{tool}'")

    adapter = get_adapter(tool)
    method = request.method
    kind = adapter.classify(method, path)         # read | write
    raw = await request.body()
    parsed = parse_json(raw)
    args = {
        "query": dict(request.query_params),
        "body": redact(parsed) if parsed is not None else ((raw.decode(errors="replace")[:2000]) if raw else None),
    }
    action = Action(id=str(uuid.uuid4()), agent_id=agent_id, tool=tool, method=method, path=path,
                    args=args, session_id=x_session_id, parent_id=x_parent_action)

    # 2. log the intent BEFORE anything is forwarded, then apply policy
    deny = None
    async with db.pool.connection() as conn:
        agent = await ledger.get_agent(conn, agent_id)
        if agent is None:
            raise HTTPException(401, "unknown agent")
        await ledger.append_action(conn, action)
        if agent["status"] == "blocked":
            deny = "agent is blocked"
        elif agent["status"] == "read_only" and kind != "read":
            deny = "agent is read-only"
        elif not scope_ok(agent["scopes"], tool, kind):
            deny = f"missing scope {tool}:{kind}"
        if deny:
            await ledger.record_result(conn, action.id, "blocked", 403, {"reason": deny})
    if deny:
        return JSONResponse(
            {"message": deny, "action_id": action.id},
            status_code=403,
            headers={"X-Action-Id": action.id},
        )

    # 3. capture before-state, forward, capture after-state
    http: httpx.AsyncClient = request.app.state.http
    url = base + (f"/{path}" if path else "")
    try:
        snap = await adapter.snapshot(http, tool, url, method, path)
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS}
        r = await http.request(method, url, params=list(request.query_params.multi_items()),
                               content=raw, headers=fwd_headers)
    except httpx.HTTPError as e:
        async with db.pool.connection() as conn:
            await ledger.record_result(conn, action.id, "failed", 502, {"error": str(e)})
        return JSONResponse(
            {"message": "upstream unreachable", "action_id": action.id},
            status_code=502,
            headers={"X-Action-Id": action.id},
        )

    ok = 200 <= r.status_code < 300
    async with db.pool.connection() as conn:
        if ok and kind == "write":
            res, after_value, after_version = adapter.after(tool, method, path, r.content, r.headers)
            await ledger.record_change(
                conn, action.id, res,
                snap.value if snap else None, after_value,
                snap.version if snap else None, after_version,
            )
        elif ok and kind == "read":
            res, _, version = adapter.after(tool, method, path, r.content, r.headers)
            await ledger.record_read(conn, action.id, res, version)
        await ledger.record_result(conn, action.id, "ok" if ok else "failed", r.status_code, summarize(r.content))

    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type"),
        headers={"X-Action-Id": action.id},
    )


# ---- admin / demo endpoints -------------------------------------------------

@app.get("/admin/ledger")
async def admin_ledger(limit: int = 50, x_admin_key: str | None = Header(None)):
    require_admin(x_admin_key)
    async with db.pool.connection() as conn:
        return await ledger.list_actions(conn, limit)


@app.get("/admin/verify")
async def admin_verify(x_admin_key: str | None = Header(None)):
    require_admin(x_admin_key)
    async with db.pool.connection() as conn:
        return await ledger.verify_chain(conn)


@app.post("/admin/agents")
async def admin_register_agent(payload: dict = Body(...), x_admin_key: str | None = Header(None)):
    """Register an agent (id, role, scopes) and mint its token. Lets you onboard someone else's agents
    without touching their code: they only need a base URL and this token."""
    require_admin(x_admin_key)
    agent_id = payload["id"]
    async with db.pool.connection() as conn:
        await ledger.upsert_agent(conn, agent_id, payload.get("role", ""), payload.get("scopes", []))
    return {"agent_id": agent_id, "token": issue_token(agent_id)}


@app.post("/admin/agents/{agent_id}/status")
async def admin_set_agent_status(
    agent_id: str,
    payload: dict = Body(...),
    x_admin_key: str | None = Header(None),
):
    require_admin(x_admin_key)
    status = payload.get("status")
    valid_statuses = {"active", "suspect", "read_only", "blocked"}
    if status not in valid_statuses:
        raise HTTPException(422, "status must be one of: active, suspect, read_only, blocked")
    async with db.pool.connection() as conn:
        found = await ledger.set_agent_status(conn, agent_id, status)
    if not found:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    return {"agent_id": agent_id, "status": status}
