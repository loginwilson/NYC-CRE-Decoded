-- statement by statement
-- 0005  filtering on any field, without a scan  (login, 2026-09-06 11:5x)
--
-- "say i wanted to look up deeds, or page numbers, or boroughs, etc."  "i think we need to assure filtering works on
-- any row and column if its possible, without causing massive load issues"
--
-- The registry stays what it is: the recorded details as the lane landed them, jsonb, in the four-column table.  What
-- changes is what stands beside it.  (1) An index on each field a person filters by, as an expression over the
-- registry, so equality, a range and ORDER BY on that field read the index and not 18 GB of rows.  (2) One GIN index
-- per table over the whole registry (jsonb_path_ops), so a containment test on ANY key and value at ANY depth - a
-- parcel by its bbl, a party by its name, a unit, an address - reads the index:  registry @> '{"parcels":[{"bbl":"4001230001"}]}'.
-- (3) An index on the document cell for a prefix (one day folder: document like 'D:\...\23\%' escape '') or one path.
-- (4) Two views, acris_fields and richmond_fields, that show the registry's fields as columns; a filter on a view column
-- is the very expression its index was built on, so the Table Editor's filters and sorts use the indexes.
-- Three small immutable functions read the fields as the lanes wrote them ('1/23/2003 9:26:58 AM' -> a date,
-- '$1,250,000.00' -> a number, '4' -> an integer) and give null for anything else, so no value can break a build.
-- Built while the lanes are idle, STATEMENT BY STATEMENT (the first line): each index its own transaction with the
-- instance's default build memory and no parallel worker - the one-transaction build of 11:36 brought the 1 GB
-- instance down at 11:48 (restart, everything rolled back).  A crash now costs one index; a re-run skips what exists.
-- A plain CREATE INDEX holds the table against writes for its build.  Nothing in any row changes.
set statement_timeout = 0;
set max_parallel_maintenance_workers = 0;   -- one process per build, the instance's default 64 MB of build memory

create or replace function reproduction.us_date(t text) returns date
language plpgsql immutable strict parallel safe as $$
begin
  -- '1/23/2003 9:26:58 AM' or '8/23/1993' -> 2003-01-23 / 1993-08-23; anything else, or an impossible day, -> null
  return make_date(split_part(split_part(t, ' ', 1), '/', 3)::int,
                   split_part(t, '/', 1)::int,
                   split_part(split_part(t, ' ', 1), '/', 2)::int);
exception when others then
  return null;
end $$;

create or replace function reproduction.us_money(t text) returns numeric
language sql immutable strict parallel safe as $$
  -- '$1,250,000.00' -> 1250000.00; anything else -> null
  select case when t ~ '^\$?-?[0-9,]+(\.[0-9]+)?$' then replace(replace(t, '$', ''), ',', '')::numeric end
$$;

create or replace function reproduction.whole_number(t text) returns integer
language sql immutable strict parallel safe as $$
  select case when t ~ '^[0-9]{1,9}$' then t::integer end
$$;

-- acris: the fields a person filters by
create index if not exists acris_type      on reproduction.acris ((registry->>'type'));
create index if not exists acris_borough   on reproduction.acris ((registry->>'borough'));
create index if not exists acris_recorded  on reproduction.acris (reproduction.us_date(registry->>'recorded'));
create index if not exists acris_doc_date  on reproduction.acris (reproduction.us_date(registry->>'doc_date'));
create index if not exists acris_pages     on reproduction.acris (reproduction.whole_number(registry->>'pages'));
create index if not exists acris_amount    on reproduction.acris (reproduction.us_money(registry->>'amount'));
create index if not exists acris_crfn      on reproduction.acris ((registry->>'crfn'));
-- acris: any key and value at any depth (parcels, parties, units, addresses, remarks) by containment
create index if not exists acris_registry  on reproduction.acris using gin (registry jsonb_path_ops);
-- acris: the document cell by prefix or path (only cells that hold a word or a path)
create index if not exists acris_document  on reproduction.acris (document text_pattern_ops) where document is not null;

-- richmond: the same, by its own field names
create index if not exists richmond_doc_type   on reproduction.richmond ((registry->>'doc_type'));
create index if not exists richmond_recorded   on reproduction.richmond (reproduction.us_date(registry->>'recorded'));
create index if not exists richmond_book_page  on reproduction.richmond ((registry->>'book'), (registry->>'page'));
create index if not exists richmond_instrument on reproduction.richmond ((registry->>'instrument'));
create index if not exists richmond_amount     on reproduction.richmond (reproduction.us_money(registry->>'amount'));
create index if not exists richmond_registry   on reproduction.richmond using gin (registry jsonb_path_ops);
create index if not exists richmond_document   on reproduction.richmond (document text_pattern_ops) where document is not null;

-- the registry's fields as columns, for the Table Editor and for anyone who would rather not write ->>
create or replace view reproduction.acris_fields as
select doc_id,
       registry->>'type'                             as type,
       registry->>'borough'                          as borough,
       reproduction.us_date(registry->>'recorded')   as recorded,
       reproduction.us_date(registry->>'doc_date')   as doc_date,
       reproduction.whole_number(registry->>'pages') as pages,
       reproduction.us_money(registry->>'amount')    as amount,
       registry->>'crfn'                             as crfn,
       registry->>'reel_page'                        as reel_page,
       registry->>'remarks'                          as remarks,
       registry->'parcels'                           as parcels,
       registry->'parties'                           as parties,
       document
from reproduction.acris;

create or replace view reproduction.richmond_fields as
select doc_id,
       registry->>'doc_type'                         as doc_type,
       reproduction.us_date(registry->>'recorded')   as recorded,
       registry->>'book'                             as book,
       registry->>'page'                             as page,
       registry->>'instrument'                       as instrument,
       reproduction.us_money(registry->>'amount')    as amount,
       registry->>'status'                           as status,
       registry->'parcels'                           as parcels,
       registry->'parties'                           as parties,
       document
from reproduction.richmond;

analyze reproduction.acris;
analyze reproduction.richmond;
