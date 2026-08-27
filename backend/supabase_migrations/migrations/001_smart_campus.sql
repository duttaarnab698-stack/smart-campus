-- Run in Supabase SQL Editor. Service-role access remains backend-only.
create table if not exists public.rooms (
  id text primary key, room_number text not null unique,
  building text not null, floor integer not null, capacity integer not null default 40,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.devices (
  id text primary key, device_id text not null unique,
  room_id text not null references public.rooms(id), firmware_version text,
  status text not null default 'OFFLINE', last_seen timestamptz, created_at timestamptz not null default now()
);
create table if not exists public.room_telemetry (
  id bigint generated always as identity primary key, room_id text not null references public.rooms(id),
  device_id text references public.devices(id), occupancy boolean not null, power_kw numeric not null check(power_kw >= 0),
  temperature numeric, humidity numeric check(humidity between 0 and 100), appliances jsonb not null default '{}'::jsonb,
  recorded_at timestamptz not null default now(), unique(room_id, recorded_at)
);
create table if not exists public.device_commands (
  id uuid primary key default gen_random_uuid(), command_id text not null unique, room_id text not null references public.rooms(id),
  device_id text not null references public.devices(id), action text not null, payload jsonb not null, status text not null,
  retry_count integer not null default 0, created_at timestamptz not null default now(), acknowledged_at timestamptz
);
create table if not exists public.alerts (
  id uuid primary key default gen_random_uuid(), room_id text references public.rooms(id), type text not null,
  severity text not null, message text not null, status text not null default 'OPEN', created_at timestamptz not null default now(), resolved_at timestamptz
);
create index if not exists rooms_number_idx on public.rooms(room_number);
create index if not exists devices_device_id_idx on public.devices(device_id);
create index if not exists telemetry_room_time_idx on public.room_telemetry(room_id, recorded_at desc);
create index if not exists commands_status_idx on public.device_commands(status);
create index if not exists alerts_open_idx on public.alerts(status) where status='OPEN';

alter table public.rooms enable row level security;
alter table public.devices enable row level security;
alter table public.room_telemetry enable row level security;
alter table public.device_commands enable row level security;
alter table public.alerts enable row level security;
-- Browser clients use no direct tables. Authenticated application users may read only.
create policy "authenticated read rooms" on public.rooms for select to authenticated using (true);
create policy "authenticated read devices" on public.devices for select to authenticated using (true);
create policy "authenticated read telemetry" on public.room_telemetry for select to authenticated using (true);
create policy "authenticated read alerts" on public.alerts for select to authenticated using (true);
-- No anonymous writes: all telemetry/commands are validated by FastAPI service-role backend.
