# Kill Switch: Phase 1 starter

A gateway that sits in front of an agent network, tags every action with the agent that took it,
and writes an append-only, hash-chained ledger of what each agent read and changed.
This is Phase 1 of the roadmap: attribution and logging. Quarantine, monitoring and rollback come next.

## Status: read this first

Phase 1 is implementation-verified on Docker Desktop with Postgres 16 and Python 3.12.
All Phase 1 tasks are complete. Verified: clean build/start, three seeded demo agents, allowed
and denied demo calls, append-only hash chaining, before/after change captures, read captures,
tamper detection, plain-update immutability, dynamic admin status changes, gateway and container
restart persistence, integration tests, and repeatability checks.

Fixed during verification:
- Added `X-Action-Id` and a clear JSON `message` to upstream-unreachable (502) responses.
- Updated the tampered-token integration check to alter the first character of the JWT signature.
- Removed the reload-verification comment from the gateway source.

## Run it

```bash
docker compose up -d --build
docker compose exec -T gateway python -m app.cli seed-demo > tokens.json   # creates 3 demo agents + tokens
python agents/run_demo.py                                                  # agents act, ledger is printed
```

Expected: five actions succeed (200), the sixth (reader trying to write a record) is blocked with 403 and still appears
in the ledger, and the final line says `Hash chain check: {'ok': True, 'length': 6}`.

Tamper test (proves the chain detects edits):

```bash
docker compose exec db psql -U ks killswitch -c "ALTER TABLE actions DISABLE TRIGGER actions_immutable; UPDATE actions SET path='x' WHERE seq=2; ALTER TABLE actions ENABLE TRIGGER actions_immutable;"
curl -s -H "X-Admin-Key: dev-admin" localhost:8000/admin/verify      # ok: false, broken_at_seq: 2
```

## Phase 1 admin status endpoint

Set an agent status (admin key required):

```bash
curl -s -X POST \
  -H "X-Admin-Key: dev-admin" \
  -H "Content-Type: application/json" \
  -d '{"status":"read_only"}' \
  http://localhost:8000/admin/agents/clerk/status
```

Allowed statuses are `active`, `suspect`, `read_only`, and `blocked`.
The status is read from Postgres on every proxied call.

## Tests and repeatability

```bash
python tests/test_util.py
python tests/test_gateway.py
bash scripts/phase1_check.sh
```

`test_gateway.py` uses only the Python standard library and reads `tokens.json`.
Set `ADMIN_KEY` in the environment if it differs from `dev-admin`.
The phase 1 script builds the stack, waits for health, reseeds demo tokens, and runs
the utility, demo, and gateway integration checks.

## Layout

| Path | What it is |
|---|---|
| `docker-compose.yml` | Postgres, mock world, gateway (port 8000) |
| `db/schema.sql` | agents, actions (hash-chained, immutable), action_results, changes, reads |
| `gateway/app/main.py` | The proxy: `/tools/{tool}/{path}` plus `/admin/*` |
| `gateway/app/auth.py` | JWT issue and verify (identity) |
| `gateway/app/ledger.py` | Append with hash chain, record results, changes and reads, verify chain |
| `gateway/app/adapters/` | Adapter contract and a generic REST adapter (before/after state, versions) |
| `gateway/app/util.py` | Pure helpers: redaction, hashing, version extraction |
| `gateway/app/cli.py` | Register agents and mint tokens |
| `mockworld/main.py` | Fake records, payments and documents (versioned) |
| `agents/run_demo.py` | Three scripted agents plus a ledger printout |

## How a request flows

1. Agent calls `POST /tools/records/...` with `Authorization: Bearer <jwt>` (the only change an existing agent needs: a base URL and a token).
2. Gateway verifies the JWT and loads the agent.
3. It writes the intent row to the ledger BEFORE forwarding, then applies policy (blocked, read-only, scopes). Blocked attempts are logged too.
4. Adapter takes a before-snapshot (reads the resource), the call is forwarded, then the after-state is captured.
5. `changes` (writes) or `reads` (reads) rows record resource and version. These two tables power rollback and taint tracking in Phase 2.
6. The agent's JWT is never forwarded upstream.

## Design choices worth knowing (differences from the scope sheet)

- Results live in `action_results`, not in `actions`, so the `actions` table can be strictly append-only (a database trigger blocks UPDATE and DELETE).
- Pool connections use autocommit, so an error later in a request can never roll back an audit row already written.
- Scopes and status are read from the database on every call, so a status change takes effect on the very next request.
- Unknown tools return 404 for now. In Phase 2 unknown tools become "gated" instead.

## Known shortcuts (fix in later phases)

- HS256 shared secret and no token revocation list yet.
- One database read per request for the agent row (add a cache with invalidation when quarantine goes live).
- Upstream credentials are not vaulted yet (the gateway drops the agent's token but adds none).
- Only HTTP is handled. The MCP front door is added later and must produce the same `Action` object.
- Default secrets (`dev-change-me`, `dev-admin`) are for local use only.

## Phase 1 checklist

- [x] docker-compose with Postgres and the gateway service
- [x] Schema for the tables in the scope sheet
- [x] Action model and adapter interface
- [x] JWT issue and verify, one token per agent
- [x] HTTP pass-through proxy that logs every call to the ledger
- [x] Mock records, payments and document services
- [x] Scripted test agents calling tools through the gateway
- [x] First end-to-end run completed and implementation verified

## Next: Phase 2

Graded quarantine (active, suspect, read_only, blocked) wired to a monitor, then `rollback(agent)` that walks that agent's
`changes` in reverse, undoes a change only if the resource is still at the bad agent's `after_version`, and flags
healthy actions whose `reads` touched the bad data.
