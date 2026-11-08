-- Run only in the dedicated, user-selected project after its cost is approved.
begin;
create table public.sixc_guest_entries (
  id uuid primary key default gen_random_uuid(),
  thread text not null check (thread in ('guestbook','post-249','post-251','post-256','post-258')),
  title text not null default '' check (char_length(title) <= 160),
  message text not null check (char_length(message) between 1 and 12000),
  name text not null default '' check (char_length(name) <= 80),
  created_at timestamptz not null default now(),
  approved boolean not null default false,
  photo_path text
);
alter table public.sixc_guest_entries enable row level security;
revoke all on public.sixc_guest_entries from public, anon, authenticated;
grant select, insert, update, delete on public.sixc_guest_entries to service_role;
create index sixc_guest_entries_published on public.sixc_guest_entries(thread, created_at desc) where approved;

create table public.sixc_guest_attempts (
  id bigint generated always as identity primary key,
  fingerprint text not null,
  created_at timestamptz not null default now()
);
alter table public.sixc_guest_attempts enable row level security;
revoke all on public.sixc_guest_attempts from public, anon, authenticated;
grant select, insert, delete on public.sixc_guest_attempts to service_role;
grant usage, select on sequence public.sixc_guest_attempts_id_seq to service_role;
create index sixc_guest_attempts_rate on public.sixc_guest_attempts(fingerprint, created_at desc);

create function public.sixc_reserve_attempt(p_fingerprint text) returns boolean
language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_fingerprint, 0));
  if (select count(*) from public.sixc_guest_attempts
      where fingerprint=p_fingerprint and created_at > now() - interval '15 minutes') >= 6 then
    return false;
  end if;
  delete from public.sixc_guest_attempts where created_at < now() - interval '1 day';
  insert into public.sixc_guest_attempts(fingerprint) values(p_fingerprint);
  return true;
end;
$$;
revoke all on function public.sixc_reserve_attempt(text) from public, anon, authenticated;
grant execute on function public.sixc_reserve_attempt(text) to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('sixc-guest-photos','sixc-guest-photos',false,8388608,array['image/jpeg','image/png','image/webp']);
-- No browser Storage policies: pending photos stay private; the edge function signs approved photos.
commit;
