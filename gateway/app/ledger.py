from uuid import UUID

from psycopg.types.json import Jsonb

from .models import Action
from .util import GENESIS, chain_hash

_LOCK_ID = 727001  # serialises ledger appends so the hash chain has a single order


def _payload(a_id, agent_id, tool, method, path, args) -> dict:
    return {"id": str(a_id), "agent_id": agent_id, "tool": tool, "method": method, "path": path, "args": args}


async def get_agent(conn, agent_id: str):
    cur = await conn.execute("SELECT * FROM agents WHERE id = %s", (agent_id,))
    return await cur.fetchone()


async def upsert_agent(conn, agent_id: str, role: str, scopes: list[str]):
    await conn.execute(
        """INSERT INTO agents (id, role, scopes) VALUES (%s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, scopes = EXCLUDED.scopes""",
        (agent_id, role, scopes),
    )


async def set_agent_status(conn, agent_id: str, status: str) -> bool:
    cur = await conn.execute(
        "UPDATE agents SET status = %s WHERE id = %s",
        (status, agent_id),
    )
    return cur.rowcount == 1


async def append_action(conn, a: Action) -> None:
    """Write the intent row before the call is forwarded (so a crash mid-call is still on record)."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
        cur = await conn.execute("SELECT hash FROM actions ORDER BY seq DESC LIMIT 1")
        row = await cur.fetchone()
        prev = row["hash"] if row else GENESIS
        h = chain_hash(prev, _payload(a.id, a.agent_id, a.tool, a.method, a.path, a.args))
        await conn.execute(
            """INSERT INTO actions (id, agent_id, session_id, parent_id, tool, method, path, args, prev_hash, hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                UUID(a.id), a.agent_id, a.session_id,
                UUID(a.parent_id) if a.parent_id else None,
                a.tool, a.method, a.path, Jsonb(a.args), prev, h,
            ),
        )


async def record_result(conn, action_id: str, status: str, http_status: int | None, response):
    await conn.execute(
        "INSERT INTO action_results (action_id, status, http_status, response) VALUES (%s,%s,%s,%s)",
        (UUID(action_id), status, http_status, Jsonb(response)),
    )


async def record_change(conn, action_id, resource, before_value, after_value, before_version, after_version):
    await conn.execute(
        """INSERT INTO changes (action_id, resource, before_value, after_value, before_version, after_version)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (UUID(action_id), resource, Jsonb(before_value), Jsonb(after_value), before_version, after_version),
    )


async def record_read(conn, action_id, resource, version):
    await conn.execute(
        "INSERT INTO reads (action_id, resource, version_read) VALUES (%s,%s,%s)",
        (UUID(action_id), resource, version),
    )


async def list_actions(conn, limit: int = 50):
    cur = await conn.execute(
        """SELECT a.seq, a.id, a.agent_id, a.tool, a.method, a.path, a.started_at,
                  r.status, r.http_status,
                  (SELECT count(*) FROM changes c WHERE c.action_id = a.id) AS changes,
                  (SELECT count(*) FROM reads d WHERE d.action_id = a.id) AS reads
           FROM actions a LEFT JOIN action_results r ON r.action_id = a.id
           ORDER BY a.seq DESC LIMIT %s""",
        (limit,),
    )
    return await cur.fetchall()


async def verify_chain(conn) -> dict:
    cur = await conn.execute(
        "SELECT seq, id, agent_id, tool, method, path, args, prev_hash, hash FROM actions ORDER BY seq"
    )
    rows = await cur.fetchall()
    prev = GENESIS
    for r in rows:
        if r["prev_hash"] != prev:
            return {"ok": False, "broken_at_seq": r["seq"], "reason": "prev_hash mismatch"}
        expected = chain_hash(prev, _payload(r["id"], r["agent_id"], r["tool"], r["method"], r["path"], r["args"]))
        if expected != r["hash"]:
            return {"ok": False, "broken_at_seq": r["seq"], "reason": "hash mismatch (row was altered)"}
        prev = r["hash"]
    return {"ok": True, "length": len(rows)}
