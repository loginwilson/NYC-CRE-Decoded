# Acris Audit

One program, `Acris Audit.py`, and one command per question. It answers whether the `document` cell says what ACRIS
actually holds, and it repairs only what a person has read a list of first.

Written 2026-09-09, the day changes I made to the documentation lane wrote verdicts they had no business writing. What
it found is recorded at the end, because the numbers are the reason the lane's rules are what they are.

## The law it audits against

The `document` cell may hold four things, and each is a claim about ACRIS, never about us:

| cell | what it claims | who is entitled to say it |
|---|---|---|
| a `D:\` path | the pdf is on the drive, page for page as the viewer counted | the viewer, then the images |
| `pending` | ACRIS has no image yet, and the recording date is inside the lag | ACRIS twice, then the registry's clock |
| `absent` | ACRIS has no image, and the lag has passed | ACRIS twice, then the registry's clock |
| NULL | we do not know | — |

**A non-answer is never a verdict.** A refused door, a 404, a page we could not read: the cell stays as it was. That
line is the whole audit, and breaking it is what cost us the day.

## The commands

    python "Acris Audit.py" absent                        every absent cell against the registry's page count
    python "Acris Audit.py" pending                       every pending cell against the recording date
    python "Acris Audit.py" pages    --port 1200          landed pdfs against the viewer's count
    python "Acris Audit.py" proof    --port 1200          absent candidates: make ACRIS hand page 1 over
    python "Acris Audit.py" scan                          write time of every recent path (one walk, every window)
    python "Acris Audit.py" fingerprint                   which source drove the page count, bucketed by clock
    python "Acris Audit.py" restore  --set pending        put corrupted cells back to NULL           (--write)
    python "Acris Audit.py" window   --from T --to T      delete the pdfs written in a window        (--write)

`restore` and `window` are the only two that change anything, both default to counting, and both need `--write`.
Everything else reads.

## What the instruments are, and what each cannot do

**The registry** is the clerk's record of what was FILED. It is not a record of what ACRIS imaged, and it is unreliable
in both directions: 4 of 24 documents whose registration recorded no page count turned out to have real images (one of
13 pages), and 200 of 200 whose registration DID record pages had no image at all. So `absent` cannot be decided from
it. Its one reliable contribution is the RECORDING DATE, which decides `pending` from `absent` once ACRIS has said
there is no image.

**The registry's page count cannot judge a pdf.** It undercounts - it misses title pages, covers and riders, so a
nine-page document registers as seven - and it also overcounts: 2003012101793002 registers as 39 pages where the viewer
says 3, our pdf holds 3, and page 4 is the end marker. Both directions measured. `pages` therefore asks the viewer.

**The viewer** (`DocumentImageView`, `hid_TotalPages`) is the only authority on how many pages a document has, and it
has never been wrong when tested: 608 pdfs across twelve years, every count matched. Read it with the lane's own token,
`TotalPages%22%3A(-?\d+)`; a looser pattern matches the `%22` of the URL encoding and reads 22 for every document.

**The end marker is a TIFF.** ACRIS's 13,684-byte placeholder must be ruled out before any "is this a real page" test,
and it can also stand in for every page of a refused block - so it confirms an absence only from a door that is
otherwise serving.

**Never `order by random()`.** Over 21.6M rows it is a full scan and a sort; it cancelled on the statement timeout and
produced nothing, twice. Walk the primary key with keyset pagination, or take an identifier range.

## What it found, 2026-09-09

    pending      64,698 cells, 100% wrong.  Not one inside the lag; the youngest was 19.7 years past its recording
                 date.  The proven lane could not have written them - acris.fresh() reads registry['recorded'] and
                 returns False at 19 years, which yields 'absent'.  All reset to NULL.

    absent       267,289 cells.  Of the 137,697 whose registration recorded pages, two doors at two providers agreed
                 that ~65% hand over a real page when asked, and a page-1 fetch proved 62 of 120 outright.  Stretch by
                 stretch: 2004 clean at 0 of 100, 2005 clean at 0 of 100, 2006 broken at 69 of 100.  All 267,289 reset
                 to NULL - the only route to 100% is to decide them again.

    pages        608 pdfs matched the viewer exactly.  Nine did not, all short, all written 09-09 between 03:41 and
                 08:33 - inside the window when --trust-registry-pages took the count from registration.  The
                 fingerprint dated that window from the pdfs themselves: while the flag was on, the class of pdfs
                 holding MORE pages than registration vanished entirely for sixteen consecutive buckets, which cannot
                 happen by chance.  39,360 pdfs deleted, files and cells together.

    mechanism    still unknown for the absent damage.  A false zero was the hypothesis; measured today on a healthy
                 door it was 0 of 73.  The precedent is real though - total_pages() carries it in its own docstring:
                 "2026-08-28: a fixed 4,922-byte error page read as 0 produced thousands of false imageless verdicts in
                 ten minutes."  The August fix covered a page with NO token; a page carrying a ZERO still passed until
                 the corroboration guard.

## What the audit changed in the lane

Nothing about how a document is fetched. Three repairs, all deletions or guards:

1. `--trust-registry-pages` removed - the lane, the rulebook's forwarding, and the argument itself.
2. A non-answer raises `Retry`. Only a positive `TotalPages <= 0` may become a verdict.
3. `absent` needs ACRIS to say it twice: the viewer's zero, then `GetImage` page 1 returning the end marker or 404.

And one in the door tooling: the station's gate now reads the `absent` count beside the pdf count and burns a door
whose absent share runs far above the corpus's 6.0%. A door that lands nothing was always burned; this is for the door
that lands something and poisons the rest.
