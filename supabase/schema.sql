-- StockApp Supabase schema
-- Run this in the Supabase SQL editor for a fresh setup.

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  cash float8 not null default 10000.0,
  starting_cash float8 not null default 10000.0,
  created_at timestamptz not null default now()
);

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

create index if not exists positions_user_id_idx on public.positions(user_id);
create index if not exists trades_user_id_created_at_idx on public.trades(user_id, created_at desc);
create index if not exists alerts_user_id_created_at_idx on public.alerts(user_id, created_at desc);

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

alter table public.profiles enable row level security;
alter table public.positions enable row level security;
alter table public.trades enable row level security;
alter table public.alerts enable row level security;

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
