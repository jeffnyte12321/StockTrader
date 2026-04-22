-- StockApp Supabase schema
-- Run this in the Supabase SQL editor for a fresh setup or an incremental repair.

create extension if not exists pgcrypto;

-- Core profile and brokerage tables

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  cash float8 not null default 0.0,
  starting_cash float8 not null default 0.0,
  snaptrade_user_id text,
  snaptrade_user_secret text,
  default_brokerage_authorization_id text,
  created_at timestamptz not null default now()
);

alter table public.profiles add column if not exists cash float8;
alter table public.profiles add column if not exists starting_cash float8;
alter table public.profiles add column if not exists snaptrade_user_id text;
alter table public.profiles add column if not exists snaptrade_user_secret text;
alter table public.profiles add column if not exists default_brokerage_authorization_id text;
alter table public.profiles add column if not exists created_at timestamptz;

update public.profiles set cash = 0.0 where cash is null;
update public.profiles set starting_cash = 0.0 where starting_cash is null;
update public.profiles set created_at = now() where created_at is null;

alter table public.profiles alter column cash set default 0.0;
alter table public.profiles alter column cash set not null;
alter table public.profiles alter column starting_cash set default 0.0;
alter table public.profiles alter column starting_cash set not null;
alter table public.profiles alter column created_at set default now();
alter table public.profiles alter column created_at set not null;

create table if not exists public.positions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  quantity float8 not null,
  avg_cost float8 not null,
  unique (user_id, symbol)
);

create table if not exists public.trades (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  action text not null check (action in ('buy', 'sell')),
  quantity float8 not null,
  price float8 not null,
  created_at timestamptz not null default now()
);

create table if not exists public.alerts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  condition text not null check (condition in ('above', 'below')),
  target_price float8 not null,
  triggered boolean not null default false,
  triggered_at timestamptz,
  triggered_price float8,
  created_at timestamptz not null default now()
);

-- Brokerage sync tables

create table if not exists public.brokerage_connections (
  authorization_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null default 'snaptrade' check (provider in ('snaptrade')),
  brokerage_slug text,
  brokerage_name text,
  connection_name text,
  connection_type text,
  disabled boolean not null default false,
  disabled_date timestamptz,
  created_date timestamptz,
  last_synced_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.brokerage_connections add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table public.brokerage_connections add column if not exists provider text default 'snaptrade';
alter table public.brokerage_connections add column if not exists brokerage_slug text;
alter table public.brokerage_connections add column if not exists brokerage_name text;
alter table public.brokerage_connections add column if not exists connection_name text;
alter table public.brokerage_connections add column if not exists connection_type text;
alter table public.brokerage_connections add column if not exists disabled boolean;
alter table public.brokerage_connections add column if not exists disabled_date timestamptz;
alter table public.brokerage_connections add column if not exists created_date timestamptz;
alter table public.brokerage_connections add column if not exists last_synced_at timestamptz;
alter table public.brokerage_connections add column if not exists created_at timestamptz;

update public.brokerage_connections set provider = 'snaptrade' where provider is null;
update public.brokerage_connections set disabled = false where disabled is null;
update public.brokerage_connections set created_at = now() where created_at is null;

alter table public.brokerage_connections alter column provider set default 'snaptrade';
alter table public.brokerage_connections alter column provider set not null;
alter table public.brokerage_connections alter column disabled set default false;
alter table public.brokerage_connections alter column disabled set not null;
alter table public.brokerage_connections alter column created_at set default now();
alter table public.brokerage_connections alter column created_at set not null;

update public.profiles as p
set default_brokerage_authorization_id = null
where p.default_brokerage_authorization_id is not null
  and not exists (
    select 1
    from public.brokerage_connections as c
    where c.authorization_id = p.default_brokerage_authorization_id
  );

alter table public.profiles
  drop constraint if exists profiles_default_brokerage_authorization_id_fkey;

alter table public.profiles
  add constraint profiles_default_brokerage_authorization_id_fkey
  foreign key (default_brokerage_authorization_id)
  references public.brokerage_connections(authorization_id)
  on delete set null;

create table if not exists public.brokerage_accounts (
  snaptrade_account_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  connection_authorization_id text not null references public.brokerage_connections(authorization_id) on delete cascade,
  institution_name text,
  name text,
  number text,
  raw_type text,
  status text,
  is_paper boolean not null default false,
  currency_code text,
  balance_total float8,
  cash_available float8,
  buying_power float8,
  sync_status_holdings text,
  sync_status_transactions text,
  last_synced_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.brokerage_accounts add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table public.brokerage_accounts add column if not exists connection_authorization_id text references public.brokerage_connections(authorization_id) on delete cascade;
alter table public.brokerage_accounts add column if not exists institution_name text;
alter table public.brokerage_accounts add column if not exists name text;
alter table public.brokerage_accounts add column if not exists number text;
alter table public.brokerage_accounts add column if not exists raw_type text;
alter table public.brokerage_accounts add column if not exists status text;
alter table public.brokerage_accounts add column if not exists is_paper boolean;
alter table public.brokerage_accounts add column if not exists currency_code text;
alter table public.brokerage_accounts add column if not exists balance_total float8;
alter table public.brokerage_accounts add column if not exists cash_available float8;
alter table public.brokerage_accounts add column if not exists buying_power float8;
alter table public.brokerage_accounts add column if not exists sync_status_holdings text;
alter table public.brokerage_accounts add column if not exists sync_status_transactions text;
alter table public.brokerage_accounts add column if not exists last_synced_at timestamptz;
alter table public.brokerage_accounts add column if not exists created_at timestamptz;

update public.brokerage_accounts set is_paper = false where is_paper is null;
update public.brokerage_accounts set created_at = now() where created_at is null;

alter table public.brokerage_accounts alter column is_paper set default false;
alter table public.brokerage_accounts alter column is_paper set not null;
alter table public.brokerage_accounts alter column created_at set default now();
alter table public.brokerage_accounts alter column created_at set not null;

create table if not exists public.holdings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  connection_authorization_id text not null references public.brokerage_connections(authorization_id) on delete cascade,
  account_id text not null references public.brokerage_accounts(snaptrade_account_id) on delete cascade,
  symbol text not null,
  raw_symbol text,
  description text,
  quantity float8 not null,
  avg_cost float8,
  last_price float8,
  market_value float8,
  open_pnl float8,
  currency_code text,
  security_type text,
  is_cash_equivalent boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (account_id, symbol)
);

alter table public.holdings add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table public.holdings add column if not exists connection_authorization_id text references public.brokerage_connections(authorization_id) on delete cascade;
alter table public.holdings add column if not exists account_id text references public.brokerage_accounts(snaptrade_account_id) on delete cascade;
alter table public.holdings add column if not exists symbol text;
alter table public.holdings add column if not exists raw_symbol text;
alter table public.holdings add column if not exists description text;
alter table public.holdings add column if not exists quantity float8;
alter table public.holdings add column if not exists avg_cost float8;
alter table public.holdings add column if not exists last_price float8;
alter table public.holdings add column if not exists market_value float8;
alter table public.holdings add column if not exists open_pnl float8;
alter table public.holdings add column if not exists currency_code text;
alter table public.holdings add column if not exists security_type text;
alter table public.holdings add column if not exists is_cash_equivalent boolean;
alter table public.holdings add column if not exists synced_at timestamptz;

update public.holdings set is_cash_equivalent = false where is_cash_equivalent is null;
update public.holdings set synced_at = now() where synced_at is null;

alter table public.holdings alter column is_cash_equivalent set default false;
alter table public.holdings alter column is_cash_equivalent set not null;
alter table public.holdings alter column synced_at set default now();
alter table public.holdings alter column synced_at set not null;

-- Research, journal, events, and portfolio history tables used by backend/db/*

create table if not exists public.journal_entries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text,
  transaction_id text,
  body text not null,
  tags text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.theses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  thesis_text text not null,
  catalyst text,
  target_price float8,
  invalidation_criteria text,
  time_horizon_date date,
  status text not null default 'active' check (status in ('active', 'invalidated', 'realized', 'expired')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, symbol)
);

create table if not exists public.portfolio_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  snapshot_date date not null,
  total_value float8 not null,
  holdings_json jsonb not null default '[]'::jsonb,
  sector_breakdown jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (user_id, snapshot_date)
);

create table if not exists public.events (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  event_type text not null,
  title text not null,
  event_date date not null,
  body text,
  source text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (symbol, event_type, event_date)
);

-- Global reference data: daily close prices.
-- No RLS — service role writes, every authenticated user reads.
create table if not exists public.price_history (
  symbol text not null,
  date date not null,
  close numeric(18, 6) not null,
  source text,
  fetched_at timestamptz not null default now(),
  primary key (symbol, date)
);

-- Per-user transactions (buys/sells/dividends/splits/cash flows).
-- Used for accurate historical portfolio reconstruction and TWR/IRR.
create table if not exists public.transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id text,
  symbol text,
  side text not null check (side in (
    'buy', 'sell', 'div', 'split',
    'deposit', 'withdrawal', 'transfer_in', 'transfer_out',
    'fee', 'interest', 'other'
  )),
  quantity numeric(20, 10) not null default 0,
  price numeric(18, 6),
  amount numeric(18, 6),                -- signed cash impact, + into portfolio
  occurred_at timestamptz not null,
  external_id text,                     -- SnapTrade activity id (for idempotency)
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (user_id, external_id)
);

-- Upserts require these uniqueness guarantees even when this script repairs an older schema.

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'positions_user_id_symbol_key'
      and conrelid = 'public.positions'::regclass
  ) then
    alter table public.positions add constraint positions_user_id_symbol_key unique (user_id, symbol);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'holdings_account_id_symbol_key'
      and conrelid = 'public.holdings'::regclass
  ) then
    alter table public.holdings add constraint holdings_account_id_symbol_key unique (account_id, symbol);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'theses_user_id_symbol_key'
      and conrelid = 'public.theses'::regclass
  ) then
    alter table public.theses add constraint theses_user_id_symbol_key unique (user_id, symbol);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'portfolio_snapshots_user_id_snapshot_date_key'
      and conrelid = 'public.portfolio_snapshots'::regclass
  ) then
    alter table public.portfolio_snapshots
      add constraint portfolio_snapshots_user_id_snapshot_date_key unique (user_id, snapshot_date);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'events_symbol_event_type_event_date_key'
      and conrelid = 'public.events'::regclass
  ) then
    alter table public.events add constraint events_symbol_event_type_event_date_key unique (symbol, event_type, event_date);
  end if;
end;
$$;

-- Indexes

create index if not exists positions_user_id_idx on public.positions(user_id);
create index if not exists trades_user_id_created_at_idx on public.trades(user_id, created_at desc);
create index if not exists alerts_user_id_created_at_idx on public.alerts(user_id, created_at desc);
create index if not exists brokerage_connections_user_id_idx on public.brokerage_connections(user_id);
create index if not exists brokerage_accounts_user_id_idx on public.brokerage_accounts(user_id);
create index if not exists brokerage_accounts_connection_idx on public.brokerage_accounts(connection_authorization_id);
create index if not exists holdings_user_id_idx on public.holdings(user_id);
create index if not exists holdings_connection_idx on public.holdings(connection_authorization_id);
create index if not exists holdings_account_symbol_idx on public.holdings(account_id, symbol);
create index if not exists journal_entries_user_id_created_at_idx on public.journal_entries(user_id, created_at desc);
create index if not exists journal_entries_user_id_symbol_idx on public.journal_entries(user_id, symbol);
create index if not exists theses_user_id_created_at_idx on public.theses(user_id, created_at desc);
create index if not exists theses_user_id_symbol_idx on public.theses(user_id, symbol);
create index if not exists portfolio_snapshots_user_id_date_idx on public.portfolio_snapshots(user_id, snapshot_date);
create index if not exists events_symbol_date_idx on public.events(symbol, event_date);
create index if not exists price_history_symbol_date_idx on public.price_history(symbol, date desc);
create index if not exists transactions_user_occurred_idx on public.transactions(user_id, occurred_at desc);
create index if not exists transactions_user_symbol_occurred_idx on public.transactions(user_id, symbol, occurred_at);

-- Auth bootstrap

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id)
  values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Row level security

alter table public.profiles enable row level security;
alter table public.positions enable row level security;
alter table public.trades enable row level security;
alter table public.alerts enable row level security;
alter table public.brokerage_connections enable row level security;
alter table public.brokerage_accounts enable row level security;
alter table public.holdings enable row level security;
alter table public.journal_entries enable row level security;
alter table public.theses enable row level security;
alter table public.portfolio_snapshots enable row level security;
alter table public.events enable row level security;
alter table public.transactions enable row level security;
-- price_history is global reference data; RLS stays off (service role writes, all reads).
alter table public.price_history disable row level security;

drop policy if exists "Users can view own profile" on public.profiles;
drop policy if exists "Users can insert own profile" on public.profiles;
drop policy if exists "Users can update own profile" on public.profiles;

create policy "Users can view own profile"
  on public.profiles
  for select
  using (auth.uid() = id);

create policy "Users can insert own profile"
  on public.profiles
  for insert
  with check (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles
  for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

drop policy if exists "Users can view own positions" on public.positions;
drop policy if exists "Users can insert own positions" on public.positions;
drop policy if exists "Users can update own positions" on public.positions;
drop policy if exists "Users can delete own positions" on public.positions;

create policy "Users can view own positions"
  on public.positions
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own positions"
  on public.positions
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own positions"
  on public.positions
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own positions"
  on public.positions
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own trades" on public.trades;
drop policy if exists "Users can insert own trades" on public.trades;

create policy "Users can view own trades"
  on public.trades
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own trades"
  on public.trades
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can view own alerts" on public.alerts;
drop policy if exists "Users can insert own alerts" on public.alerts;
drop policy if exists "Users can update own alerts" on public.alerts;
drop policy if exists "Users can delete own alerts" on public.alerts;

create policy "Users can view own alerts"
  on public.alerts
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own alerts"
  on public.alerts
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own alerts"
  on public.alerts
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own alerts"
  on public.alerts
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own brokerage connections" on public.brokerage_connections;
drop policy if exists "Users can insert own brokerage connections" on public.brokerage_connections;
drop policy if exists "Users can update own brokerage connections" on public.brokerage_connections;
drop policy if exists "Users can delete own brokerage connections" on public.brokerage_connections;

create policy "Users can view own brokerage connections"
  on public.brokerage_connections
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own brokerage connections"
  on public.brokerage_connections
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own brokerage connections"
  on public.brokerage_connections
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own brokerage connections"
  on public.brokerage_connections
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own brokerage accounts" on public.brokerage_accounts;
drop policy if exists "Users can insert own brokerage accounts" on public.brokerage_accounts;
drop policy if exists "Users can update own brokerage accounts" on public.brokerage_accounts;
drop policy if exists "Users can delete own brokerage accounts" on public.brokerage_accounts;

create policy "Users can view own brokerage accounts"
  on public.brokerage_accounts
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own brokerage accounts"
  on public.brokerage_accounts
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own brokerage accounts"
  on public.brokerage_accounts
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own brokerage accounts"
  on public.brokerage_accounts
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own holdings" on public.holdings;
drop policy if exists "Users can insert own holdings" on public.holdings;
drop policy if exists "Users can update own holdings" on public.holdings;
drop policy if exists "Users can delete own holdings" on public.holdings;

create policy "Users can view own holdings"
  on public.holdings
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own holdings"
  on public.holdings
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own holdings"
  on public.holdings
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own holdings"
  on public.holdings
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own journal entries" on public.journal_entries;
drop policy if exists "Users can insert own journal entries" on public.journal_entries;
drop policy if exists "Users can update own journal entries" on public.journal_entries;
drop policy if exists "Users can delete own journal entries" on public.journal_entries;

create policy "Users can view own journal entries"
  on public.journal_entries
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own journal entries"
  on public.journal_entries
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own journal entries"
  on public.journal_entries
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own journal entries"
  on public.journal_entries
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own theses" on public.theses;
drop policy if exists "Users can insert own theses" on public.theses;
drop policy if exists "Users can update own theses" on public.theses;
drop policy if exists "Users can delete own theses" on public.theses;

create policy "Users can view own theses"
  on public.theses
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own theses"
  on public.theses
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own theses"
  on public.theses
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own theses"
  on public.theses
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Users can view own portfolio snapshots" on public.portfolio_snapshots;
drop policy if exists "Users can insert own portfolio snapshots" on public.portfolio_snapshots;
drop policy if exists "Users can update own portfolio snapshots" on public.portfolio_snapshots;
drop policy if exists "Users can delete own portfolio snapshots" on public.portfolio_snapshots;

create policy "Users can view own portfolio snapshots"
  on public.portfolio_snapshots
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own portfolio snapshots"
  on public.portfolio_snapshots
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own portfolio snapshots"
  on public.portfolio_snapshots
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own portfolio snapshots"
  on public.portfolio_snapshots
  for delete
  using (auth.uid() = user_id);

drop policy if exists "Authenticated users can view events" on public.events;
drop policy if exists "Authenticated users can insert events" on public.events;
drop policy if exists "Authenticated users can update events" on public.events;
drop policy if exists "Authenticated users can delete events" on public.events;

create policy "Authenticated users can view events"
  on public.events
  for select
  to authenticated
  using (true);

-- Events are global reference data. Authenticated users can read them, but only
-- service-role backend jobs should write because the service role bypasses RLS.

-- transactions: user-scoped RLS.
drop policy if exists "Users can view own transactions" on public.transactions;
drop policy if exists "Users can insert own transactions" on public.transactions;
drop policy if exists "Users can update own transactions" on public.transactions;
drop policy if exists "Users can delete own transactions" on public.transactions;

create policy "Users can view own transactions"
  on public.transactions
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own transactions"
  on public.transactions
  for insert
  with check (auth.uid() = user_id);

create policy "Users can update own transactions"
  on public.transactions
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own transactions"
  on public.transactions
  for delete
  using (auth.uid() = user_id);

-- Repair uniqueness constraints if running against an older schema.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'transactions_user_id_external_id_key'
      and conrelid = 'public.transactions'::regclass
  ) then
    alter table public.transactions
      add constraint transactions_user_id_external_id_key unique (user_id, external_id);
  end if;
end;
$$;
