-- Kill Switch ledger schema (Phase 1). Runs once, on first start of the db container.

CREATE TABLE IF NOT EXISTS agents (
  id            text PRIMARY KEY,
  role          text NOT NULL DEFAULT '',
  scopes        text[] NOT NULL DEFAULT '{}',
  budget_limit  numeric,
  status        text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','suspect','read_only','blocked')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- One row per attempted action, written BEFORE it is forwarded. Append-only + hash-chained.
CREATE TABLE IF NOT EXISTS actions (
  seq         bigserial PRIMARY KEY,
  id          uuid NOT NULL UNIQUE,
  agent_id    text NOT NULL REFERENCES agents(id),
  session_id  text,
  parent_id   uuid,
  tool        text NOT NULL,
  method      text NOT NULL,
  path        text NOT NULL,
  args        jsonb,
  started_at  timestamptz NOT NULL DEFAULT now(),
  prev_hash   text NOT NULL,
  hash        text NOT NULL
);

-- Outcome of each action (kept separate so `actions` can stay strictly append-only).
CREATE TABLE IF NOT EXISTS action_results (
  action_id    uuid PRIMARY KEY REFERENCES actions(id),
  status       text NOT NULL CHECK (status IN ('ok','failed','blocked')),
  http_status  int,
  response     jsonb,
  finished_at  timestamptz NOT NULL DEFAULT now()
);

-- What each write changed (before/after + versions). Basis for rollback in Phase 2.
CREATE TABLE IF NOT EXISTS changes (
  id             bigserial PRIMARY KEY,
  action_id      uuid NOT NULL REFERENCES actions(id),
  resource       text NOT NULL,
  before_value   jsonb,
  after_value    jsonb,
  before_version text,
  after_version  text,
  reversible     boolean NOT NULL DEFAULT true
);

-- What each action READ (resource + version). Basis for taint tracking in Phase 2.
CREATE TABLE IF NOT EXISTS reads (
  id            bigserial PRIMARY KEY,
  action_id     uuid NOT NULL REFERENCES actions(id),
  resource      text NOT NULL,
  version_read  text
);

CREATE INDEX IF NOT EXISTS idx_actions_agent ON actions(agent_id, seq);
CREATE INDEX IF NOT EXISTS idx_changes_resource ON changes(resource);
CREATE INDEX IF NOT EXISTS idx_reads_resource ON reads(resource);

-- The ledger cannot be edited or deleted, even by the gateway's own database user.
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'ledger is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS actions_immutable ON actions;
CREATE TRIGGER actions_immutable BEFORE UPDATE OR DELETE ON actions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

DROP TRIGGER IF EXISTS results_immutable ON action_results;
CREATE TRIGGER results_immutable BEFORE UPDATE OR DELETE ON action_results
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
