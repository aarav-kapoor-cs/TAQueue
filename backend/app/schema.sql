-- One table is the whole database.
-- A row is one student's request for help. It moves through three states:
--   waiting  ->  claimed  ->  completed
CREATE TABLE IF NOT EXISTS queue_entries (
    id            SERIAL PRIMARY KEY,           -- auto-incrementing; lower id = joined earlier (FIFO order)
    student_name  TEXT NOT NULL,
    topic         TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'waiting'
                  CHECK (status IN ('waiting', 'claimed', 'completed')),
    claimed_by    TEXT,                         -- TA name; NULL until a TA claims the student
    claim_token   TEXT,                         -- secret for the tab that claimed; never sent in the public queue
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ
);

-- CREATE TABLE does nothing if the table already exists, so add the column
-- for databases created before claim_token existed.
ALTER TABLE queue_entries ADD COLUMN IF NOT EXISTS claim_token TEXT;

-- Almost every query filters by status, so index it.
CREATE INDEX IF NOT EXISTS idx_queue_entries_status ON queue_entries (status);
