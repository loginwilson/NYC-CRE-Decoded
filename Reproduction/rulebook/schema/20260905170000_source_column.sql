-- 0003  the source column  (login, 2026-09-05 16:5x)
--
-- "is it possible to structure the supabase table to be source, id, registry, document. the source will help later
-- with tables that may be cross sourced ... knowing acris, richmond, dob now, dof, bis web, etc. is helpful as we
-- expand and link datasets" - and the two sources keep their own tables ("separating acris and richmond given they
-- each have their own table for reproduction").
--
-- So each workflow table carries its source as its FIRST column - a constant the table itself enforces - and any
-- cross-source table or view built in construction carries the source in every row without a join.  The tables are
-- empty (the data move has not happened), so they are rebuilt in the dictated order rather than altered: Postgres
-- appends an added column at the end.  Every name, rule, index (0002's pending indexes on updated_at), trigger and
-- comment is kept; the claims tables are rebuilt for their foreign keys; the functions address columns by name and
-- need nothing.  doc_id keeps its name: it is the source's document id, and every program says doc_id.

drop table reproduction.acris_claims;
drop table reproduction.richmond_claims;
drop table reproduction.acris;
drop table reproduction.richmond;

-- ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
-- acris

create table reproduction.acris (
  source      text        not null default 'acris' constraint acris_source check (source = 'acris'),
  doc_id      text        collate "C" primary key,
  registry    jsonb,
  document    text,
  updated_at  timestamptz not null default now(),
  constraint acris_registry_cell check (
    registry is null
    or jsonb_typeof(registry) = 'object'
    or registry <@ '["pending", "absent"]'::jsonb
  ),
  constraint acris_document_cell check (
    document is null
    or document in ('pending', 'absent')
    or starts_with(document, 'D:\')
  )
);
comment on table  reproduction.acris            is 'acris reproduction: one row per document; each lane fills its own cell';
comment on column reproduction.acris.source     is 'the source, a constant per table (acris): every cross-source table or view carries it without a join';
comment on column reproduction.acris.doc_id     is 'filled by synchronization (the ACRIS document id; every URL is minted from it)';
comment on column reproduction.acris.registry   is 'filled by registration: the recorded details as a JSON object, or the verdict word when the source has none: pending | absent';
comment on column reproduction.acris.document   is 'filled by documentation: the full One Touch path of the saved document, or the verdict word: pending (still being checked, stays in the backfill) | absent (checked: there is none)';
comment on column reproduction.acris.updated_at is 'touched on every change of the row (any cell); the pending recheck age is measured from it';

create index acris_registration_empty    on reproduction.acris (doc_id) where registry is null;
create index acris_registration_pending  on reproduction.acris (updated_at) where registry = '"pending"'::jsonb;
create index acris_documentation_empty   on reproduction.acris (doc_id) where document is null;
create index acris_documentation_pending on reproduction.acris (updated_at) where document = 'pending';
create trigger acris_touch before update on reproduction.acris for each row execute function reproduction.touch();

create table reproduction.acris_claims (
  doc_id  text        collate "C" not null references reproduction.acris (doc_id) on delete cascade,
  lane    text        not null check (lane in ('registration', 'documentation')),
  host    text        not null,
  until   timestamptz not null,
  primary key (doc_id, lane)
);
create index acris_claims_expiry on reproduction.acris_claims (lane, until);
comment on table reproduction.acris_claims is 'rows in flight: which workstation holds which document for which lane, until when; expired claims go back on the list; rows are deleted as cells land';

-- ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
-- richmond

create table reproduction.richmond (
  source      text        not null default 'richmond' constraint richmond_source check (source = 'richmond'),
  doc_id      text        collate "C" primary key,
  registry    jsonb,
  document    text,
  updated_at  timestamptz not null default now(),
  constraint richmond_registry_cell check (
    registry is null
    or jsonb_typeof(registry) = 'object'
    or registry <@ '["pending", "absent"]'::jsonb
  ),
  constraint richmond_document_cell check (
    document is null
    or document in ('pending', 'absent')
    or starts_with(document, 'D:\')
  )
);
comment on table  reproduction.richmond            is 'richmond reproduction: one row per document; each lane fills its own cell';
comment on column reproduction.richmond.source     is 'the source, a constant per table (richmond): every cross-source table or view carries it without a join';
comment on column reproduction.richmond.doc_id     is 'filled by synchronization (the Richmond County internal id; every URL is minted from it)';
comment on column reproduction.richmond.registry   is 'filled by registration: the recorded details as a JSON object, or the verdict word when the source has none: pending | absent';
comment on column reproduction.richmond.document   is 'filled by documentation: the full One Touch path of the saved document, or the verdict word: pending (still being checked, stays in the backfill) | absent (checked: there is none)';
comment on column reproduction.richmond.updated_at is 'touched on every change of the row (any cell); the pending recheck age is measured from it';

create index richmond_registration_empty    on reproduction.richmond (doc_id) where registry is null;
create index richmond_registration_pending  on reproduction.richmond (updated_at) where registry = '"pending"'::jsonb;
create index richmond_documentation_empty   on reproduction.richmond (doc_id) where document is null;
create index richmond_documentation_pending on reproduction.richmond (updated_at) where document = 'pending';
create trigger richmond_touch before update on reproduction.richmond for each row execute function reproduction.touch();

create table reproduction.richmond_claims (
  doc_id  text        collate "C" not null references reproduction.richmond (doc_id) on delete cascade,
  lane    text        not null check (lane in ('registration', 'documentation')),
  host    text        not null,
  until   timestamptz not null,
  primary key (doc_id, lane)
);
create index richmond_claims_expiry on reproduction.richmond_claims (lane, until);
comment on table reproduction.richmond_claims is 'rows in flight for richmond; see acris_claims';
