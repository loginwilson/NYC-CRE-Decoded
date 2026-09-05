# UPDATE — the phase board

Nothing runs here yet. Each source has its own board today - `<Source>/update/<Source> Update.py`, one program that
always runs and only reads, writing two tabs in Supabase: the phase row of that source (rows with all three cells
filled against rows) and its lane rows (each cell filled against rows), with the 60-second and 5-minute rate,
increase, percent and eta, landed, needed, percent of total, the computed status and the as-of stamp.

The phase board is the same two tabs across every source: one row per source on tab 1, the sources' lane rows on tab 2,
the phase's own total on top. It reads the sources' update tables through a master view - a later migration in
`../supabase/migrations/`, after the data move - and `Update.py` beside this file will read that view the way every
board does (`../rulebook/board.py`: one subtraction, every percentage over needed, the four statuses, never a clamp,
never a scan on a tick). Until then this folder holds this file, so the phase has the same three folders a source has.

## History

2026-09-05 — Created as the phase's third folder (login: "rulebook workflow update ... and then you have all the sources
underneath"). The master view is the Supabase step's business, after the GitHub tree is complete.
