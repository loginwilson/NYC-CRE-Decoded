# Acris — synchronization

Keeps the database live: sits at the CRFN edge; any CRFN movement triggers an edge walk on the source that populates new ids. One monitor worker, the rest walkers. Fills the doc_id cell.
