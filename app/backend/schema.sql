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
