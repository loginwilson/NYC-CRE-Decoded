# Richmond — synchronization

Keeps the database live: walks from the last recorded id by date range; a date monitor. One monitor worker, the rest walkers. Fills the doc_id cell.
