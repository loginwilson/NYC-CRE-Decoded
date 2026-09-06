-- statement by statement
-- 0008 LOOKUP, MORE (login 2026-09-06): "make sure that block and lot and BBL, all of it, is able to be derived - if I wanted
-- to just say Manhattan block and lot, I didn't have to do the BBL"; and the one gap 0005 left, partial text: "parties whose
-- name contains DEUTSCHE" was not indexed, only the exact full name.  Re-runnable (if not exists / or replace); built one
-- statement at a time by `supabase.py push --rest`.  Nothing here touches a row.
--
--   block keys      reproduction.block_keys(registry) -> text[] of '<borough digit>-<block>' per parcel ('1-00573'), with a GIN
--                   over the array: "everything on Manhattan block 573" reads the index.  reproduction.block_key('MANHATTAN', 573)
--                   builds the key from words, reproduction.parcel('MANHATTAN', 573, 24) builds the containment value for one lot,
--                   reproduction.bbl('MANHATTAN', 573, 24) the ten digits - nobody assembles a bbl by hand.
--   party names     reproduction.party_names(registry) -> every party name in one text, with a trigram GIN (pg_trgm): ILIKE
--                   '%deutsche bank%' reads the index.
--   expiration      a typed date index on registry->>'expiration' (3,956,313 documents carry one: UCC terms, leases).
--   parcels views   reproduction.acris_parcels / richmond_parcels: one row per document and parcel with borough, block, lot,
--                   unit, address, use, partial derived from the bbl - for reading and joining, never assembling.
set statement_timeout = 0;
set max_parallel_maintenance_workers = 0;
create extension if not exists pg_trgm with schema extensions;

create or replace function reproduction.block_keys(r jsonb) returns text[] language plpgsql immutable strict parallel safe as $$
declare
  keys text[] := '{}';
  p jsonb;
  b text;
begin
  if jsonb_typeof(r->'parcels') <> 'array' then
    return keys;
  end if;
  for p in select * from jsonb_array_elements(r->'parcels') loop
    b := p->>'bbl';
    if b is not null and length(b) = 10 and translate(b, '0123456789', '') = '' then
      keys := array_append(keys, substr(b, 1, 1) || '-' || substr(b, 2, 5));
    end if;
  end loop;
  return keys;
end $$;

create or replace function reproduction.borough_digit(borough text) returns text language plpgsql immutable strict parallel safe as $$
begin
  return case upper(trim(borough))
    when 'MANHATTAN' then '1' when 'BRONX' then '2' when 'BROOKLYN' then '3' when 'QUEENS' then '4' when 'STATEN ISLAND' then '5'
    when '1' then '1' when '2' then '2' when '3' then '3' when '4' then '4' when '5' then '5' end;
end $$;

create or replace function reproduction.block_key(borough text, block integer) returns text language sql immutable strict parallel safe as $$
  select reproduction.borough_digit(borough) || '-' || lpad(block::text, 5, '0')
$$;

create or replace function reproduction.bbl(borough text, block integer, lot integer) returns text language sql immutable strict parallel safe as $$
  select reproduction.borough_digit(borough) || lpad(block::text, 5, '0') || lpad(lot::text, 4, '0')
$$;

create or replace function reproduction.parcel(borough text, block integer, lot integer) returns jsonb language sql immutable strict parallel safe as $$
  select jsonb_build_object('parcels', jsonb_build_array(jsonb_build_object('bbl', reproduction.bbl(borough, block, lot))))
$$;

create or replace function reproduction.party_names(r jsonb) returns text language plpgsql immutable strict parallel safe as $$
declare
  names text := '';
  p jsonb;
begin
  if jsonb_typeof(r->'parties') <> 'array' then
    return null;
  end if;
  for p in select * from jsonb_array_elements(r->'parties') loop
    names := names || coalesce(p->>'name', '') || ' | ';
  end loop;
  return nullif(names, '');
end $$;

create index if not exists acris_blocks on reproduction.acris using gin (reproduction.block_keys(registry));
create index if not exists acris_expiration on reproduction.acris (reproduction.us_date(registry->>'expiration'));
create index if not exists acris_party_names on reproduction.acris using gin (reproduction.party_names(registry) extensions.gin_trgm_ops);
create index if not exists richmond_blocks on reproduction.richmond using gin (reproduction.block_keys(registry));
create index if not exists richmond_party_names on reproduction.richmond using gin (reproduction.party_names(registry) extensions.gin_trgm_ops);

create or replace view reproduction.acris_parcels as
select a.doc_id,
       p->>'bbl'                                              as bbl,
       case substr(p->>'bbl', 1, 1) when '1' then 'MANHATTAN' when '2' then 'BRONX' when '3' then 'BROOKLYN'
                                    when '4' then 'QUEENS' when '5' then 'STATEN ISLAND' end as borough,
       substr(p->>'bbl', 2, 5)                                as block,
       substr(p->>'bbl', 7, 4)                                as lot,
       p->>'unit'                                             as unit,
       p->>'address'                                          as address,
       p->>'use'                                              as use,
       p->>'partial'                                          as partial
from reproduction.acris a,
     jsonb_array_elements(case when jsonb_typeof(a.registry->'parcels') = 'array' then a.registry->'parcels' else '[]'::jsonb end) p;

create or replace view reproduction.richmond_parcels as
select r.doc_id,
       p->>'bbl'                                              as bbl,
       'STATEN ISLAND'                                        as borough,
       substr(p->>'bbl', 2, 5)                                as block,
       substr(p->>'bbl', 7, 4)                                as lot
from reproduction.richmond r,
     jsonb_array_elements(case when jsonb_typeof(r.registry->'parcels') = 'array' then r.registry->'parcels' else '[]'::jsonb end) p;

analyze reproduction.acris;
analyze reproduction.richmond;
