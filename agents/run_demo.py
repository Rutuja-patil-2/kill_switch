"""Phase 1 demo: three scripted agents call tools through the gateway, then we print the ledger.
No third-party packages needed. Run after:  docker compose up -d --build
and:  docker compose exec -T gateway python -m app.cli seed-demo > tokens.json
"""
import json
import os
import urllib.error
import urllib.request

GATEWAY = os.environ.get("GATEWAY", "http://localhost:8000")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "dev-admin")
TOKENS = json.load(open(os.environ.get("TOKENS", "tokens.json")))


def call(agent, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{GATEWAY}/tools/{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {TOKENS[agent]}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            code, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read().decode()
    print(f"  {agent:8} {method:6} {path:22} -> {code}")
    return code, text


print("Agents acting:")
call("clerk",   "GET",  "records/r1")
call("clerk",   "PUT",  "records/r1", {"customer": "Acme", "status": "renewed"})
call("reader",  "GET",  "documents/d2")
call("billing", "POST", "payments", {"to": "supplier-7", "amount": 50})
call("clerk",   "POST", "records", {"customer": "Umbrella", "status": "pending"})
print("A policy violation (reader has no records:write):")
call("reader",  "PUT",  "records/r2", {"customer": "Globex", "status": "hacked"})


def admin(path):
    req = urllib.request.Request(f"{GATEWAY}/admin/{path}", headers={"X-Admin-Key": ADMIN_KEY})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


print("\nLedger (newest first):")
print(f"  {'seq':>3}  {'agent':8} {'call':32} {'result':8} chg rd")
for row in admin("ledger?limit=20"):
    call_str = f"{row['method']} {row['tool']}/{row['path']}"
    print(f"  {row['seq']:>3}  {row['agent_id']:8} {call_str:32} {row['status'] or '-':8} {row['changes']:>3} {row['reads']:>2}")
print("\nHash chain check:", admin("verify"))
