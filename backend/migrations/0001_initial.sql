-- Phase 1.5: durable experiment record + canonical persisted event log.
-- Forward-only, additive philosophy (see docs/SPEC.md schema_version notes).

CREATE TABLE experiments (
    experiment_id     UUID PRIMARY KEY,
    seed              BIGINT NOT NULL,
    config            JSONB NOT NULL,
    defense_enabled   BOOLEAN GENERATED ALWAYS AS ((config->>'defense_enabled')::boolean) STORED,
    node_count        INT    GENERATED ALWAYS AS ((config->>'node_count')::int) STORED,
    schema_version    INT NOT NULL,
    app_version       TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    final_status      TEXT CHECK (final_status IN ('finished', 'stopped')),
    final_sim_tick    INT,
    final_last_seq    INT,
    -- NULL until finalization runs (or attempts to run). TRUE only when
    -- finalization has proven experiment_events holds a gapless
    -- seq range [0, final_last_seq] with no duplicates -- never inferred
    -- from final_status alone. FALSE means finalization ran but found a
    -- gap (a batch failed to persist somewhere in the run). A row that
    -- crashed mid-run (process died, finalize never ran) keeps
    -- final_status AND is_complete both NULL forever -- itself an honest
    -- "untrustworthy" signal.
    is_complete       BOOLEAN,
    completed_at      TIMESTAMPTZ
);

CREATE INDEX ix_experiments_created_at ON experiments (created_at DESC);

CREATE TABLE experiment_events (
    experiment_id     UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    seq               INT NOT NULL,
    event_id          UUID NOT NULL UNIQUE,
    sim_tick          INT NOT NULL,
    event_type        TEXT NOT NULL,
    agent_id          TEXT,
    source_agent_id   TEXT,
    target_agent_id   TEXT,
    risk_score        DOUBLE PRECISION,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_version    INT NOT NULL,
    wall_time         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (experiment_id, seq)
);

CREATE INDEX ix_experiment_events_type ON experiment_events (experiment_id, event_type, seq);
