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
