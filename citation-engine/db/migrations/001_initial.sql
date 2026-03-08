-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────
-- TAXONOMY
-- ─────────────────────────────────────────
CREATE TABLE fields (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  slug        TEXT NOT NULL UNIQUE,
  parent_id   UUID REFERENCES fields(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Seed some top-level fields
INSERT INTO fields (name, slug) VALUES
  ('Biology',           'biology'),
  ('Chemistry',         'chemistry'),
  ('Computer Science',  'computer-science'),
  ('Economics',         'economics'),
  ('History',           'history'),
  ('Law',               'law'),
  ('Mathematics',       'mathematics'),
  ('Medicine',          'medicine'),
  ('Physics',           'physics'),
  ('Psychology',        'psychology'),
  ('Sociology',         'sociology');

-- ─────────────────────────────────────────
-- USERS & SESSIONS
-- ─────────────────────────────────────────
CREATE TABLE users (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email        TEXT UNIQUE,
  created_at   TIMESTAMPTZ DEFAULT now(),
  last_seen_at TIMESTAMPTZ
);

CREATE TABLE sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  ip_hash      TEXT NOT NULL,
  user_agent   TEXT,
  country_code TEXT,
  city         TEXT,
  created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_created_at ON sessions(created_at);

-- ─────────────────────────────────────────
-- PAPERS & CHUNKS
-- ─────────────────────────────────────────
CREATE TABLE papers (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title        TEXT NOT NULL,
  authors      TEXT[],
  year         INT,
  doi          TEXT UNIQUE,
  language     TEXT,
  field_id     UUID REFERENCES fields(id) ON DELETE SET NULL,
  storage_path TEXT,
  created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_papers_field_id ON papers(field_id);
CREATE INDEX idx_papers_year     ON papers(year);

CREATE TABLE chunks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paper_id     UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  chunk_index  INT NOT NULL,
  text         TEXT NOT NULL,
  embedding    VECTOR(1024),
  page_number  INT,
  UNIQUE(paper_id, chunk_index)
);

-- HNSW index — fast from day 1, no training needed
-- m=16, ef_construction=64 is a solid default
CREATE INDEX idx_chunks_embedding ON chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunks_paper_id ON chunks(paper_id);

-- ─────────────────────────────────────────
-- SUBMISSIONS & RESULTS
-- ─────────────────────────────────────────
CREATE TABLE submissions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
  session_id          UUID REFERENCES sessions(id) ON DELETE SET NULL,
  input_type          TEXT NOT NULL CHECK (input_type IN ('text', 'pdf', 'docx')),
  input_length        INT,
  detected_language   TEXT,
  detected_field_id   UUID REFERENCES fields(id) ON DELETE SET NULL,
  created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_submissions_user_id    ON submissions(user_id);
CREATE INDEX idx_submissions_created_at ON submissions(created_at);
CREATE INDEX idx_submissions_field_id   ON submissions(detected_field_id);

CREATE TABLE suggestion_results (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  chunk_id      UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  score         FLOAT NOT NULL,
  rank          INT NOT NULL,
  was_clicked   BOOLEAN DEFAULT false,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_suggestion_results_submission ON suggestion_results(submission_id);

-- Cache: same input hash → skip re-embedding + re-search
CREATE TABLE citation_cache (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  input_hash   TEXT NOT NULL UNIQUE,
  field_id     UUID REFERENCES fields(id),
  chunk_ids    UUID[],
  scores       FLOAT[],
  created_at   TIMESTAMPTZ DEFAULT now(),
  expires_at   TIMESTAMPTZ DEFAULT (now() + INTERVAL '7 days')
);

CREATE INDEX idx_cache_hash       ON citation_cache(input_hash);
CREATE INDEX idx_cache_expires_at ON citation_cache(expires_at);

-- ─────────────────────────────────────────
-- FEEDBACK & LOGS
-- ─────────────────────────────────────────
CREATE TABLE feedback (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id UUID REFERENCES submissions(id) ON DELETE CASCADE,
  rating        INT CHECK (rating BETWEEN 1 AND 5),
  comment       TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE search_logs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        UUID REFERENCES sessions(id) ON DELETE SET NULL,
  input_length      INT,
  detected_field_id UUID REFERENCES fields(id),
  result_count      INT,
  latency_ms        INT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_search_logs_created_at ON search_logs(created_at);
