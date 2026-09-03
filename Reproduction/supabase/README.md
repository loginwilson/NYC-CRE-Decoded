# supabase

The phase's schema as migrations: one numbered SQL file per dictated decision. Push with `db_push.ps1` (reads `C:\dev\nyc-cre-decoded.env`, never prints it; `-Extra --dry-run` first). `decoded_sql.py` runs ad-hoc SQL (`--check` lists what exists). `test_claims.py` proves claim / land / heartbeat / reconcile on the live project with throwaway rows. The folder name `supabase` is the Supabase CLI's requirement; the push script runs from `Reproduction/` so the CLI finds it.
