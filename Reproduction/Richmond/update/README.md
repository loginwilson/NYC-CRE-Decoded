# Richmond update

One program, always running, reading only, two tabs. Tab 1 (`reproduction.richmond_update`): the phase — rows with all three cells filled against rows, 60-second and 5-minute rate, increase, percentage, eta, status, as of. Tab 2 (`reproduction.richmond_update_lanes`): one row per lane — that lane's cells filled against rows, same columns; the status follows the lane's heartbeat: active | pending | stalled | complete. Counters come from land(); reconcile() recounts hourly.
