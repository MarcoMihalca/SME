-- ============================================================================
-- Script de inițializare PostgreSQL + TimescaleDB pentru containerul Docker SME
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- 1. Tabelul principal pentru măsurătorile la 2 secunde (Date Brute)
CREATE TABLE IF NOT EXISTS pxr25_measurements (
    time TIMESTAMPTZ NOT NULL,
    slave_id TEXT NOT NULL,
    primary_status TEXT,
    secondary_status TEXT,
    cause_of_status TEXT,
    i_a DOUBLE PRECISION,
    i_b DOUBLE PRECISION,
    i_c DOUBLE PRECISION,
    i_g DOUBLE PRECISION,
    i_n DOUBLE PRECISION,
    v_ab DOUBLE PRECISION,
    v_bc DOUBLE PRECISION,
    v_ca DOUBLE PRECISION,
    v_an DOUBLE PRECISION,
    v_bn DOUBLE PRECISION,
    v_cn DOUBLE PRECISION,
    p_tot DOUBLE PRECISION,
    q_tot DOUBLE PRECISION,
    s_tot DOUBLE PRECISION,
    pf_tot DOUBLE PRECISION,
    freq DOUBLE PRECISION,
    e_fwd DOUBLE PRECISION,
    e_rev DOUBLE PRECISION,
    e_tot DOUBLE PRECISION,
    e_app DOUBLE PRECISION,
    load_pct DOUBLE PRECISION,
    i_unbal DOUBLE PRECISION,
    v_ll_unbal DOUBLE PRECISION,
    v_ln_unbal DOUBLE PRECISION,
    pf_quality DOUBLE PRECISION,
    in_ratio DOUBLE PRECISION,
    freq_dev DOUBLE PRECISION,
    d_power DOUBLE PRECISION
);

-- Transformare în Hypertable TimescaleDB (partiționat automat în chunk-uri de 1 zi)
SELECT create_hypertable(
    'pxr25_measurements',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_pxr25_meas_slave_time
    ON pxr25_measurements (slave_id, time DESC);

-- 2. Tabelul separat pentru Evenimente și Declanșări (păstrat permanent fără ștergere)
CREATE TABLE IF NOT EXISTS trip_events (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    slave_id INT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    cause TEXT NOT NULL,
    currents TEXT,
    UNIQUE (slave_id, event_id, event_timestamp, cause)
);

-- 3. Agregare Continuă la 1 minut (AVG, MIN, MAX) — păstrată 1 an
CREATE MATERIALIZED VIEW IF NOT EXISTS pxr25_metrics_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket_1m,
    slave_id,
    AVG(i_a) AS avg_ia, MIN(i_a) AS min_ia, MAX(i_a) AS max_ia,
    AVG(i_b) AS avg_ib, MIN(i_b) AS min_ib, MAX(i_b) AS max_ib,
    AVG(i_c) AS avg_ic, MIN(i_c) AS min_ic, MAX(i_c) AS max_ic,
    AVG(v_ab) AS avg_vab, MIN(v_ab) AS min_vab, MAX(v_ab) AS max_vab,
    AVG(p_tot) AS avg_p_tot, MAX(p_tot) AS max_p_tot,
    AVG(q_tot) AS avg_q_tot,
    AVG(pf_tot) AS avg_pf,
    MAX(load_pct) AS max_load_pct,
    MAX(i_unbal) AS max_i_unbal
FROM pxr25_measurements
GROUP BY bucket_1m, slave_id
WITH NO DATA;

-- 4. Agregare Continuă la 15 minute (Curba de sarcină & Energie kWh) — păstrată 5 ani
CREATE MATERIALIZED VIEW IF NOT EXISTS pxr25_metrics_15m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', time) AS bucket_15m,
    slave_id,
    AVG(p_tot) AS avg_p_tot,
    MAX(p_tot) AS max_p_tot,
    AVG(q_tot) AS avg_q_tot,
    AVG(s_tot) AS avg_s_tot,
    AVG(pf_tot) AS avg_pf,
    MAX(e_tot) AS e_tot_kwh,
    MAX(e_fwd) AS e_fwd_kwh
FROM pxr25_measurements
GROUP BY bucket_15m, slave_id
WITH NO DATA;

-- Politici automate de refresh și retenție TimescaleDB
SELECT add_continuous_aggregate_policy('pxr25_metrics_1m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('pxr25_metrics_15m',
    start_offset => INTERVAL '6 hours',
    end_offset => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE);

-- Datele brute la 2 secunde se păstrează 30 de zile
SELECT add_retention_policy('pxr25_measurements', INTERVAL '30 days', if_not_exists => TRUE);
-- Datele agregate la 1 minut se păstrează 1 an
SELECT add_retention_policy('pxr25_metrics_1m', INTERVAL '365 days', if_not_exists => TRUE);
-- Datele agregate la 15 minute se păstrează 5 ani
SELECT add_retention_policy('pxr25_metrics_15m', INTERVAL '1825 days', if_not_exists => TRUE);
