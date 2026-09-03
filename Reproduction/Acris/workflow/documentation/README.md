# Acris — documentation

Acquires the document itself by minted access, saves it to the drive, records the full One Touch path. Fills the document cell: the path, or pending, or absent.

Today's code (runs from the decoder folder until the restructure; this is its home):

- `doc_lane.py` — the lane as one command: `status | checks | launch [label] | stop --reason`.
- `night_supervisor.py` — the redial policy (wifi waits; 3 tries per incident; then park with the reason).
- `block_watch.py` — the per-minute socket/process record with a snapshot at every stop.
- `tools/` — exit_draws, tls_contrast, block_ledger, board_row, night_filter, conc_test.
- `RUNBOOK.md` — the procedure in words.
