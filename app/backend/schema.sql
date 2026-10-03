CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS tables (
  table_id   text PRIMARY KEY,
  capacity   integer NOT NULL CHECK (capacity >= 1)
);

CREATE TABLE IF NOT EXISTS reservations (
  reservation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_name    text NOT NULL CHECK (length(btrim(customer_name)) > 0),
  table_id         text NOT NULL REFERENCES tables(table_id),
  start_time       timestamptz NOT NULL,
  end_time         timestamptz NOT NULL,
  idempotency_key  text NOT NULL,
  request_hash     text NOT NULL,
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (end_time > start_time),
  UNIQUE (idempotency_key)
);

ALTER TABLE reservations DROP CONSTRAINT IF EXISTS no_overlap;
ALTER TABLE reservations ADD CONSTRAINT no_overlap
  EXCLUDE USING gist (
    table_id WITH =,
    tstzrange(start_time, end_time, '[)') WITH &&
  ) WHERE (status = 'active');

CREATE TABLE IF NOT EXISTS projects (
  id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                       text NOT NULL CHECK (length(btrim(name)) >= 2),
  slug                       text NOT NULL UNIQUE,
  description                text NOT NULL DEFAULT '',
  project_type               text NOT NULL,
  target_users               text NOT NULL DEFAULT '',
  business_domain            text NOT NULL DEFAULT '',
  functional_requirements   text NOT NULL DEFAULT '',
  nonfunctional_requirements text NOT NULL DEFAULT '',
  technology_preferences     text NOT NULL DEFAULT '',
  database_requirements     text NOT NULL DEFAULT '',
  authentication_requirement text NOT NULL DEFAULT 'No authentication',
  status                     text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'configured', 'queued', 'building', 'verified', 'failed')),
  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_designs (
  project_id         uuid PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  primary_color      text NOT NULL DEFAULT '#0B5ED7',
  secondary_color    text NOT NULL DEFAULT '#FFFFFF',
  accent_color       text NOT NULL DEFAULT '#DC2626',
  background_color   text NOT NULL DEFAULT '#FFFFFF',
  text_color         text NOT NULL DEFAULT '#111827',
  button_color       text NOT NULL DEFAULT '#0B5ED7',
  warning_color      text NOT NULL DEFAULT '#F59E0B',
  visual_style       text NOT NULL DEFAULT 'Professional',
  theme              text NOT NULL DEFAULT 'Light',
  custom_instructions text NOT NULL DEFAULT '',
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_workspaces (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
  path       text NOT NULL UNIQUE,
  status     text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready', 'busy', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_assets (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  filename         text NOT NULL,
  original_filename text NOT NULL,
  mime_type        text NOT NULL,
  size             bigint NOT NULL CHECK (size > 0),
  storage_path     text NOT NULL UNIQUE,
  url              text NOT NULL,
  alt_text         text NOT NULL DEFAULT '',
  asset_type       text NOT NULL DEFAULT 'Other',
  section          text NOT NULL DEFAULT '',
  sort_order       integer NOT NULL DEFAULT 0,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS project_assets_project_idx ON project_assets(project_id);

CREATE TABLE IF NOT EXISTS factory_runs (
  idempotency_key text PRIMARY KEY,
  id             uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  project_id     uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  status         text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'planning', 'building', 'testing', 'breaking', 'repairing', 'retesting', 'verifying', 'awaiting_approval', 'approved', 'deploying', 'deployed', 'failed', 'cancelled')),
  current_stage  text NOT NULL DEFAULT 'queued',
  error          text NOT NULL DEFAULT '',
  started_at     timestamptz,
  completed_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS factory_tasks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  factory_run_id uuid NOT NULL REFERENCES factory_runs(id) ON DELETE CASCADE,
  agent_role    text NOT NULL,
  task_type     text NOT NULL,
  status        text NOT NULL,
  input         text NOT NULL DEFAULT '',
  output        text NOT NULL DEFAULT '',
  error         text NOT NULL DEFAULT '',
  started_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz
);

CREATE TABLE IF NOT EXISTS factory_events (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  factory_run_id uuid NOT NULL REFERENCES factory_runs(id) ON DELETE CASCADE,
  stage         text NOT NULL,
  event_type    text NOT NULL,
  message       text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS factory_artifacts (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  factory_run_id uuid NOT NULL REFERENCES factory_runs(id) ON DELETE CASCADE,
  artifact_type text NOT NULL,
  path          text NOT NULL,
  sha256        text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Agent hand-off chain. Applied idempotently so existing runs keep working.
ALTER TABLE factory_runs ADD COLUMN IF NOT EXISTS execution_mode text NOT NULL DEFAULT 'deterministic';
ALTER TABLE factory_runs ADD COLUMN IF NOT EXISTS runtime jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE factory_tasks ADD COLUMN IF NOT EXISTS parent_task_id uuid;
ALTER TABLE factory_tasks ADD COLUMN IF NOT EXISTS sequence integer NOT NULL DEFAULT 0;
ALTER TABLE factory_tasks ADD COLUMN IF NOT EXISTS agent_session_id text NOT NULL DEFAULT '';
ALTER TABLE factory_tasks ADD COLUMN IF NOT EXISTS verdict text NOT NULL DEFAULT '';
ALTER TABLE factory_tasks ADD COLUMN IF NOT EXISTS handed_to text NOT NULL DEFAULT '';
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS agent_role text NOT NULL DEFAULT '';
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS task_id uuid;

-- Rich agent-event stream: source/destination agent, status, artifact, lineage.
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS source_agent text NOT NULL DEFAULT '';
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS destination_agent text NOT NULL DEFAULT '';
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT '';
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS artifact_path text NOT NULL DEFAULT '';
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS parent_event_id uuid;
ALTER TABLE factory_events ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS factory_events_type_idx ON factory_events (factory_run_id, event_type, created_at);

CREATE INDEX IF NOT EXISTS factory_tasks_run_sequence_idx ON factory_tasks (factory_run_id, sequence, started_at);
CREATE INDEX IF NOT EXISTS factory_events_run_idx ON factory_events (factory_run_id, created_at);

CREATE TABLE IF NOT EXISTS git_commits (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  factory_run_id uuid NOT NULL REFERENCES factory_runs(id) ON DELETE CASCADE,
  commit_hash   text NOT NULL,
  branch        text NOT NULL,
  message       text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  factory_run_id uuid NOT NULL REFERENCES factory_runs(id) ON DELETE CASCADE,
  approval_type text NOT NULL,
  status        text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
  reason        text NOT NULL DEFAULT '',
  created_at    timestamptz NOT NULL DEFAULT now(),
  approved_at   timestamptz
);

CREATE TABLE IF NOT EXISTS github_installations (
  installation_id bigint PRIMARY KEY,
  account_id      bigint NOT NULL,
  account_login   text NOT NULL,
  account_type    text NOT NULL DEFAULT 'User',
  status          text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'disconnected', 'error')),
  connected_at    timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_github_integrations (
  project_id       uuid PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  installation_id  bigint NOT NULL REFERENCES github_installations(installation_id),
  repository_id    bigint NOT NULL,
  owner            text NOT NULL,
  repository_name  text NOT NULL,
  default_branch   text NOT NULL DEFAULT 'main',
  status           text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'disconnected', 'error')),
  connected_at     timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS github_pull_requests (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id     uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  factory_run_id uuid REFERENCES factory_runs(id) ON DELETE SET NULL,
  number         integer NOT NULL,
  url            text NOT NULL,
  title          text NOT NULL DEFAULT '',
  source_branch  text NOT NULL,
  target_branch  text NOT NULL,
  head_sha       text NOT NULL DEFAULT '',
  status         text NOT NULL DEFAULT 'open',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, number)
);

ALTER TABLE github_pull_requests ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT '';
ALTER TABLE github_pull_requests ADD COLUMN IF NOT EXISTS head_sha text NOT NULL DEFAULT '';

ALTER TABLE git_commits ADD COLUMN IF NOT EXISTS base_branch text NOT NULL DEFAULT '';
ALTER TABLE git_commits ADD COLUMN IF NOT EXISTS remote_url text;
ALTER TABLE git_commits ADD COLUMN IF NOT EXISTS files_changed jsonb;
ALTER TABLE git_commits ADD COLUMN IF NOT EXISTS pushed_at timestamptz;

ALTER TABLE github_installations ADD COLUMN IF NOT EXISTS repository_selection text NOT NULL DEFAULT '';
ALTER TABLE github_installations ADD COLUMN IF NOT EXISTS permissions jsonb;

CREATE INDEX IF NOT EXISTS git_commits_project_idx ON git_commits(project_id);
CREATE INDEX IF NOT EXISTS github_pull_requests_run_idx ON github_pull_requests(factory_run_id);

-- ---------------------------------------------------------------------------
-- Payment / wallet workload (ledger integrity, idempotent atomic transfers)
-- Money is stored in minor units (e.g. cents) as integers so balances are exact.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS accounts (
  account_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_name    text NOT NULL CHECK (length(btrim(owner_name)) > 0),
  currency      char(3) NOT NULL DEFAULT 'USD',
  balance_minor bigint NOT NULL DEFAULT 0 CHECK (balance_minor >= 0),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transfers (
  transfer_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key text NOT NULL UNIQUE,
  request_hash    text NOT NULL,
  source_account  uuid NOT NULL REFERENCES accounts(account_id),
  target_account  uuid NOT NULL REFERENCES accounts(account_id),
  amount_minor    bigint NOT NULL CHECK (amount_minor > 0),
  currency        char(3) NOT NULL,
  status          text NOT NULL DEFAULT 'settled' CHECK (status IN ('settled')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (source_account <> target_account)
);

-- Double-entry: every transfer produces exactly one debit and one credit.
CREATE TABLE IF NOT EXISTS ledger_entries (
  entry_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  transfer_id  uuid NOT NULL REFERENCES transfers(transfer_id) ON DELETE CASCADE,
  account_id   uuid NOT NULL REFERENCES accounts(account_id),
  direction    text NOT NULL CHECK (direction IN ('debit', 'credit')),
  amount_minor bigint NOT NULL CHECK (amount_minor > 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (transfer_id, direction)
);

CREATE INDEX IF NOT EXISTS ledger_entries_transfer_idx ON ledger_entries(transfer_id);
CREATE INDEX IF NOT EXISTS ledger_entries_account_idx ON ledger_entries(account_id);
CREATE INDEX IF NOT EXISTS transfers_source_idx ON transfers(source_account);
