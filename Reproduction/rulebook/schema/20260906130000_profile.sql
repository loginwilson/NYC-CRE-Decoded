-- 0006  the profile: the registry's shapes at a glance  (login, 2026-09-06 12:0x)
--
-- "the things we'd want to filter on ... are the things found in the registry realistically ... when training a rounded
-- framework, we need to look at all types of registry scenarios"
--
-- Two summary tables per source, each built by scanning the rows once and refreshed on demand, so a person or a model
-- sees the whole variety of the registry without reading it.  <source>_profile counts documents by type, borough and
-- year, by how many parcels and parties a document carries, and by its page count, with the fields that did not parse
-- counted alongside (a recorded date, an amount or a page count the functions of 0005 could not read).  <source>_keys
-- counts which keys appear in a registry, in a parcel and in a party, so an unusual field is visible with its
-- frequency.  Examples of any shape are then pulled through 0005's indexes.  Nothing in the rows changes.  The tables
-- are materialized views: `refresh materialized view concurrently reproduction.acris_profile` rebuilds one while it stays
-- readable (each has the unique index that allows it).
set statement_timeout = 0;

-- acris: documents by type / borough / year, by parcels, by parties, by pages, and all together
create materialized view reproduction.acris_profile as
with d as (
  select registry->>'type'                                                    as type,
         registry->>'borough'                                                 as borough,
         extract(year from reproduction.us_date(registry->>'recorded'))::int  as year,
         jsonb_array_length(case when jsonb_typeof(registry->'parcels') = 'array' then registry->'parcels' else '[]'::jsonb end) as parcels,
         jsonb_array_length(case when jsonb_typeof(registry->'parties') = 'array' then registry->'parties' else '[]'::jsonb end) as parties,
         reproduction.whole_number(registry->>'pages')                        as pages,
         (registry ? 'recorded' and reproduction.us_date(registry->>'recorded') is null)    as recorded_unparsed,
         (registry ? 'amount'   and reproduction.us_money(registry->>'amount') is null)      as amount_unparsed,
         (registry ? 'pages'    and reproduction.whole_number(registry->>'pages') is null)   as pages_unparsed,
         (document is not null and document <> 'pending' and document <> 'absent')          as with_document
  from reproduction.acris
  where jsonb_typeof(registry) = 'object'
)
select case grouping(type, borough, year, parcels, parties, pages)
         when 7  then 'type, borough, year'
         when 31 then 'type'
         when 47 then 'borough'
         when 55 then 'year'
         when 59 then 'parcels'
         when 61 then 'parties'
         when 62 then 'pages'
         else 'all' end                                   as facet,
       type, borough, year, parcels, parties, pages,
       count(*)                                           as documents,
       count(*) filter (where with_document)              as with_document,
       count(*) filter (where recorded_unparsed)          as recorded_unparsed,
       count(*) filter (where amount_unparsed)            as amount_unparsed,
       count(*) filter (where pages_unparsed)             as pages_unparsed
from d
group by grouping sets ((type, borough, year), (type), (borough), (year), (parcels), (parties), (pages), ())
with data;
create unique index acris_profile_key on reproduction.acris_profile (facet, type, borough, year, parcels, parties, pages) nulls not distinct;

-- acris: which keys appear, at the registry's top level, inside a parcel, inside a party
create materialized view reproduction.acris_keys as
select 'registry' as level, k as key, count(*) as documents
from reproduction.acris,
     jsonb_object_keys(case when jsonb_typeof(registry) = 'object' then registry else '{}'::jsonb end) k
group by k
union all
select 'parcel', k, count(*)
from reproduction.acris,
     jsonb_array_elements(case when jsonb_typeof(registry->'parcels') = 'array' then registry->'parcels' else '[]'::jsonb end) p,
     jsonb_object_keys(case when jsonb_typeof(p) = 'object' then p else '{}'::jsonb end) k
group by k
union all
select 'party', k, count(*)
from reproduction.acris,
     jsonb_array_elements(case when jsonb_typeof(registry->'parties') = 'array' then registry->'parties' else '[]'::jsonb end) p,
     jsonb_object_keys(case when jsonb_typeof(p) = 'object' then p else '{}'::jsonb end) k
group by k
with data;
create unique index acris_keys_key on reproduction.acris_keys (level, key);

-- richmond: the same by its own fields (one county, so no borough; a book and page, so no page count)
create materialized view reproduction.richmond_profile as
with d as (
  select registry->>'doc_type'                                                as doc_type,
         extract(year from reproduction.us_date(registry->>'recorded'))::int  as year,
         jsonb_array_length(case when jsonb_typeof(registry->'parcels') = 'array' then registry->'parcels' else '[]'::jsonb end) as parcels,
         jsonb_array_length(case when jsonb_typeof(registry->'parties') = 'array' then registry->'parties' else '[]'::jsonb end) as parties,
         (registry ? 'recorded' and reproduction.us_date(registry->>'recorded') is null)    as recorded_unparsed,
         (registry ? 'amount'   and reproduction.us_money(registry->>'amount') is null)      as amount_unparsed,
         (document is not null and document <> 'pending' and document <> 'absent')          as with_document
  from reproduction.richmond
  where jsonb_typeof(registry) = 'object'
)
select case grouping(doc_type, year, parcels, parties)
         when 3  then 'doc_type, year'
         when 7  then 'doc_type'
         when 11 then 'year'
         when 13 then 'parcels'
         when 14 then 'parties'
         else 'all' end                                   as facet,
       doc_type, year, parcels, parties,
       count(*)                                           as documents,
       count(*) filter (where with_document)              as with_document,
       count(*) filter (where recorded_unparsed)          as recorded_unparsed,
       count(*) filter (where amount_unparsed)            as amount_unparsed
from d
group by grouping sets ((doc_type, year), (doc_type), (year), (parcels), (parties), ())
with data;
create unique index richmond_profile_key on reproduction.richmond_profile (facet, doc_type, year, parcels, parties) nulls not distinct;

create materialized view reproduction.richmond_keys as
select 'registry' as level, k as key, count(*) as documents
from reproduction.richmond,
     jsonb_object_keys(case when jsonb_typeof(registry) = 'object' then registry else '{}'::jsonb end) k
group by k
union all
select 'parcel', k, count(*)
from reproduction.richmond,
     jsonb_array_elements(case when jsonb_typeof(registry->'parcels') = 'array' then registry->'parcels' else '[]'::jsonb end) p,
     jsonb_object_keys(case when jsonb_typeof(p) = 'object' then p else '{}'::jsonb end) k
group by k
union all
select 'party', k, count(*)
from reproduction.richmond,
     jsonb_array_elements(case when jsonb_typeof(registry->'parties') = 'array' then registry->'parties' else '[]'::jsonb end) p,
     jsonb_object_keys(case when jsonb_typeof(p) = 'object' then p else '{}'::jsonb end) k
group by k
with data;
create unique index richmond_keys_key on reproduction.richmond_keys (level, key);
