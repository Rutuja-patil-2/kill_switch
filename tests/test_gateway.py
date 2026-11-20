"""Integration checks for the running Kill Switch stack (standard library only)."""
import json
import os
import sys
import urllib.error
import urllib.request


GATEWAY = os.environ.get("GATEWAY", "http://localhost:8000")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "dev-admin")

with open(os.environ.get("TOKENS", "tokens.json"), "r", encoding="utf-8") as f:
    TOKENS = json.load(f)

failures = 0


def request(method, path, token=None, body=None, admin=False):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if admin:
        headers["X-Admin-Key"] = ADMIN_KEY
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(GATEWAY + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            response_body = r.read()
            return r.status, dict(r.headers.items()), response_body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def json_body(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def ledger(limit=200):
    code, headers, raw = request("GET", "/admin/ledger?limit=" + str(limit), admin=True)
    if code != 200:
        raise RuntimeError("ledger lookup failed with HTTP " + str(code))
    return json.loads(raw.decode("utf-8"))


def action_by_header(response_headers):
    action_id = next(
        (value for key, value in response_headers.items() if key.lower() == "x-action-id"),
        None,
    )
    if not action_id:
        return None
    for row in ledger():
        if row["id"] == action_id:
            return row
    return None


def check(name, ok, reason):
    global failures
    if ok:
        print("PASS " + name)
    else:
        failures += 1
        print("FAIL " + name + ": " + reason)


try:
    code, headers, raw = request("GET", "/health")
    check("health", code == 200 and json_body(raw) == {"ok": True}, "expected HTTP 200 and ok=true")

    code, headers, raw = request("GET", "/tools/records/r1", token=TOKENS["clerk"])
    row = action_by_header(headers)
    check("clerk read", code == 200 and row is not None and row["reads"] >= 1,
          "response or X-Action-Id ledger read count was missing")

    code, headers, raw = request(
        "PUT", "/tools/records/r1", token=TOKENS["clerk"],
        body={"customer": "Acme", "status": "renewed"},
    )
    row = action_by_header(headers)
    check("clerk write", code == 200 and row is not None and row["changes"] >= 1,
          "response or X-Action-Id ledger change count was missing")

    code, headers, raw = request(
        "PUT", "/tools/records/r2", token=TOKENS["reader"],
        body={"customer": "Globex", "status": "hacked"},
    )
    row = action_by_header(headers)
    check("reader write blocked", code == 403 and row is not None and row["status"] == "blocked",
          "expected 403 and a blocked ledger action")

    code, headers, raw = request("GET", "/tools/records/r1")
    check("missing authorization", code == 401,
          "expected HTTP 401; got " + str(code) + " " + str(json_body(raw)))

    tampered = TOKENS["clerk"][:-1] + ("A" if TOKENS["clerk"][-1:] != "A" else "B")
    code, headers, raw = request("GET", "/tools/records/r1", token=tampered)
    check("tampered token", code == 401,
          "expected HTTP 401; got " + str(code) + " " + str(json_body(raw)))

    code, headers, raw = request("GET", "/admin/verify", admin=True)
    verify = json_body(raw)
    check("chain verify", code == 200 and verify is not None and verify.get("ok") is True,
          "verify did not return ok=true")

    status_code, status_headers, status_raw = request(
        "POST", "/admin/agents/clerk/status", admin=True, body={"status": "read_only"},
    )
    read_only_set = status_code == 200 and json_body(status_raw) == {"agent_id": "clerk", "status": "read_only"}

    code, headers, raw = request(
        "PUT", "/tools/records/r1", token=TOKENS["clerk"],
        body={"customer": "Acme", "status": "readonly-test"},
    )
    write_blocked = code == 403

    code, headers, raw = request("GET", "/tools/records/r1", token=TOKENS["clerk"])
    read_allowed = code == 200

    status_code, status_headers, status_raw = request(
        "POST", "/admin/agents/clerk/status", admin=True, body={"status": "active"},
    )
    active_restored = status_code == 200

    code, headers, raw = request(
        "PUT", "/tools/records/r1", token=TOKENS["clerk"],
        body={"customer": "Acme", "status": "active-again"},
    )
    write_restored = code == 200

    check("read_only status", read_only_set and write_blocked and read_allowed,
          "read_only setup/write/read checks did not all succeed")
    check("active status restored", active_restored and write_restored,
          "agent did not return to active or write successfully")

    code, headers, raw = request("GET", "/tools/not-a-tool/r1", token=TOKENS["clerk"])
    unknown = json_body(raw)
    check("unknown tool", code == 404 and unknown is not None and "unknown tool" in str(unknown).lower(),
          "expected JSON 404 unknown-tool message")
finally:
    try:
        request("POST", "/admin/agents/clerk/status", admin=True, body={"status": "active"})
    except Exception as exc:
        print("FAIL status restore: " + str(exc))
        failures += 1

sys.exit(1 if failures else 0)
