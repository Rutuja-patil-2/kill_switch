"""Usage (inside the gateway container):
  python -m app.cli issue clerk --scopes records:*,documents:read
  python -m app.cli seed-demo            # prints JSON {agent: token} for the demo agents
"""
import argparse
import json
import os

import psycopg

from .auth import issue_token

DEMO_AGENTS = {
    "clerk":   ("edits records",        ["records:*", "documents:read"]),
    "billing": ("makes payments",       ["payments:*", "records:read"]),
    "reader":  ("reads documents only", ["documents:read", "records:read"]),
}


def upsert(conn, agent_id, role, scopes):
    conn.execute(
        """INSERT INTO agents (id, role, scopes) VALUES (%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role, scopes = EXCLUDED.scopes""",
        (agent_id, role, scopes),
    )


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue")
    i.add_argument("agent_id")
    i.add_argument("--role", default="")
    i.add_argument("--scopes", default="")
    sub.add_parser("seed-demo")
    args = p.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        if args.cmd == "issue":
            scopes = [s for s in args.scopes.split(",") if s]
            upsert(conn, args.agent_id, args.role, scopes)
            print(issue_token(args.agent_id))
        else:
            tokens = {}
            for agent_id, (role, scopes) in DEMO_AGENTS.items():
                upsert(conn, agent_id, role, scopes)
                tokens[agent_id] = issue_token(agent_id)
            print(json.dumps(tokens, indent=2))


if __name__ == "__main__":
    main()
