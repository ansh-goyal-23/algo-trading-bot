-- Supabase schema for the algo-trading-bot project (unattended paper
-- trading state — see DEPLOY.md). Recreates the three tables + RLS lockdown
-- currently live in the "algo-trading-bot" Supabase project (ref
-- soxpkhlfzvacwfjcxyuf, region ap-south-1, https://soxpkhlfzvacwfjcxyuf.supabase.co).
--
-- This is a snapshot of that project's actual migration history (pulled
-- straight from supabase_migrations.schema_migrations on 2026-08-25), kept
-- here so you don't have to reconstruct the schema by hand if you ever need
-- to recreate it — e.g. a fresh Supabase project, a second environment, or
-- disaster recovery. It is NOT run automatically by anything (run_daily.py /
-- execution/state_store.py just talk to whatever tables already exist via
-- REST) — it only runs when you execute it yourself.
--
-- How to run it:
--   * Supabase dashboard -> SQL Editor -> paste this whole file -> Run, or
--   * Supabase CLI: supabase db execute -f supabase_schema.sql --project-ref <ref>
--
-- Safe to re-run: every statement is guarded with IF NOT EXISTS, so running
-- this against a project that already has these tables is a no-op rather
-- than an error.
--
-- After creating a NEW project with this file, you'd also need to: point
-- SUPABASE_URL/SUPABASE_KEY (the secret key, not the publishable one) at
-- it, and reseed any open position(s) into `positions` to match your local
-- open_positions.csv — see DEPLOY.md.

-- ── positions ──────────────────────────────────────────────────────────
-- Open positions (mirrors reports/paper_trading/open_positions.csv locally)
create table if not exists positions (
    symbol             text primary key,
    entry_price        numeric not null,
    quantity           integer not null,
    stop_price         numeric not null,
    entry_date         date not null,
    partial_exit_done  boolean not null default false,
    updated_at         timestamptz not null default now()
);

-- ── trades ─────────────────────────────────────────────────────────────
-- Trade log (mirrors reports/paper_trading/paper_trades_YYYYMMDD.csv locally)
create table if not exists trades (
    id          bigint generated always as identity primary key,
    trade_date  date not null,
    ts          timestamptz not null default now(),
    action      text not null,
    symbol      text not null,
    price       numeric not null,
    quantity    integer not null,
    reason      text
);
create index if not exists trades_trade_date_idx on trades (trade_date);

-- ── ohlc_state ─────────────────────────────────────────────────────────
-- Intraday OHLC-building state (mirrors reports/paper_trading/ohlc_state_YYYYMMDD.json locally)
create table if not exists ohlc_state (
    symbol           text not null,
    trade_date       date not null,
    open             numeric,
    high             numeric,
    low              numeric,
    close            numeric,
    volume           bigint default 0,
    tick_count       integer default 0,
    first_tick_time  text,
    last_tick_time   text,
    updated_at       timestamptz not null default now(),
    primary key (symbol, trade_date)
);

-- ── lock down RLS ──────────────────────────────────────────────────────
-- These tables are only ever touched by the trading bot's server-side
-- process (using the secret/service key, which bypasses RLS). Enabling RLS
-- with no policies blocks all access via the public/publishable key, so
-- nothing is readable or writable from a browser or anon client.
alter table positions enable row level security;
alter table trades enable row level security;
alter table ohlc_state enable row level security;
