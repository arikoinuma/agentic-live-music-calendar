# Adding a venue (or a new capture) to the evaluation pool

How to put a venue's calendar page into the hand-labelled pool that the evaluation harness scores (`make eval-graph`, `agent_worker/eval/run_eval.py`). This is the procedure behind the `C5-K1` gap in `docs/dev/implementations/c5-pipeline-eval-harness.md`, and the labelling half of C6's held-out set (`docs/dev/alpha-deployment-plan.md`, C5 and C6). Everything below runs on a machine that can reach the venue's website (a laptop; the cloud sandbox cannot), from `apps/api`.

**Two cases, one procedure.** A *new venue* needs steps 1 to 7. A *new capture of a venue we already have* (say, Mortimer's again, a month later) skips steps 1 and 2: it is a new page and gets its own label entry. Re-capturing a venue is useful twice over: it is a fresh page to score, and two captures of one venue are what the `sequence` and `overlap` scenarios need.

## The steps

| # | Step | Where | What it is |
|---|---|---|---|
| 1 | **Pick the venue and its calendar URL** | the venue's website | A page that lists *many dated shows*, not one event. Then check that a plain fetch can read it (below). |
| 2 | **Register the venue** | `agent_worker/eval/labels.py`, `VENUE_FACTS` | One entry: a short key, the venue's name, the URL. |
| 3 | **Capture the page** | `uv run python -m agent_worker.eval.capture <key>` | Saves `agent_worker/eval/fixtures/<key>-<YYYY-MM-DD>.html` (gitignored). |
| 4 | **Read the page** | `uv run python -m agent_worker.eval.label_draft agent_worker/eval/fixtures/<file>` | Prints the page's visible lines, numbered. It does **not** write labels. |
| 5 | **Write the label** | `agent_worker/eval/labels.py`, `PAGE_LABELS` | One `PageLabel` for the whole page, by hand. Decide `gated` and `held_out` here. |
| 6 | **Run the label tests** | `uv run pytest agent_worker/tests/test_labels.py` | And, for a *gated* venue, add its key to `GATED_VENUES` in that test file first. |
| 7 | **(Separate) add it to the production venue list** | `app/db/seed.py` | Only if the worker should fetch it for real. The eval does not need it. |

### 1. Pick the venue, and check the page can be fetched

The pipeline fetches with **one plain GET** (`nodes.fetch_html`, no JavaScript). So a venue is usable only if the shows are in what that GET returns.

- Find the page that lists upcoming shows (the one a visitor would call "the calendar").
- Run step 3 and watch the output. `WARNING: almost no visible text` means the listings are drawn by JavaScript and a plain fetch cannot see them (Zhora Darling). A `403` or a challenge page means a bot check, which this project does not work around (the Midway, A2.1-D3).
- Such a venue can still be registered, with `blocked="why"` on its `VenueFacts`. A bare `capture` then skips it, but it can be captured by naming it.

### 2. Register the venue

Add one entry to `VENUE_FACTS` in `labels.py`:

```python
"new_venue": VenueFacts("The New Venue", "https://newvenue.example/calendar/"),
```

- The **key** (`new_venue`) is what you type after `capture`, what a `PageLabel` points at (`venue="new_venue"`), and the start of the fixture's file name. Short, lower-case, underscores.
- The **name** should match how the venue will be named in the database (`app/db/seed.py`), so the eval and the worker agree.
- The metro zone defaults to `America/Chicago`; the label tests currently require that, since the alpha serves one metro.
- Adding the entry does **not** touch `tests/test_labels.py`. That file changes only for a gated venue (step 6).

### 3. Capture the page

```
uv run python -m agent_worker.eval.capture new_venue      # one venue
uv run python -m agent_worker.eval.capture                # every venue that is not blocked
```

- It uses the pipeline's own fetch, so the file is exactly what production would see.
- The file is named with *today's date in the metro*: `new_venue-2026-10-30.html`. That date matters (step 5).
- **It never replaces an existing file** for the same venue and date unless you pass `--force`. A label describes that exact page, so re-capturing means re-labelling (A2.1-CR1-10).
- A page changes daily. A capture is a frozen fixture: label it once, and treat it as a snapshot, not as the venue's whole season.

### 4. Read the page

`label_draft` prints every distinct visible line, numbered, with the lines that look dated flagged `>`. It is a reading aid: copy the lines you mean as `source_line`s. It never prints act names from structured data, and it does not decide what is a show or who the acts are. Those are the judgements that make a label a label.

### 5. Write the label

Add one entry to `PAGE_LABELS`, keyed by the **exact fixture file name**, above the `TODO(Ari)` block at the end of the dict. The whole page goes in, every real show it lists; a partial label makes the scorer count the shows you skipped as invented.

```python
"new_venue-2026-10-30.html": PageLabel(
    venue="new_venue",             # the VENUE_FACTS key
    gated=True,                    # see below
    captured_on=D(2026, 10, 30),   # the capture date: the year rule reads it (A2.1-D13)
    held_out=False,                # see below
    shows=(
        S(D(2026, 11, 2), ("Act One", "Act Two"), "Act One w. Act Two / Mon Nov 2", T(20, 0)),
        # one S(...) row per real show on the page
    ),
    non_shows=(NonShow("OPEN MIC Every Monday", None, 0, "open mic"),),
),
```

How to decide each row:

- **From the page text, never from JSON-LD or a model's output.** Labelling from what the model returned makes the score measure agreement with the model, not correctness. `source_line` is the line you read it from, so a reviewer can check a row without opening the fixture.
- **A field you leave as `None` means the page does not state it**, so any value the model returns there is scored wrong. Label a start time only where the page's text states one.
- **Acts follow A2.1-D5's conventions** (`prompts._act_conventions()`): for example, a tour name is not an act, a night's name is not an act, a named DJ is. Where a call was a judgement, say which in `convention=`; where a title is genuinely ambiguous, list the other acceptable readings in `alternatives=`.
- **Not shows** (karaoke, comedy, a recurring "OPEN MIC Every Monday" header) go in `non_shows`, so the scorer can tell a tolerated leak from an invented show.
- **Cancelled and postponed listings are labelled with their status** (`status="cancelled"`, A2.1-D12).

**`gated`.** `True` when production can fetch the page and you want it to count toward Ari's accuracy standard (every run must meet every tier on every gated page, A2.1-D1). `False` means the page is scored and reported but never fails the gate. A new gated page makes the gate stricter, so it is a decision, not a default.

**`held_out`.** `True` sets the page aside for C6's held-out test (C5-D3). A held-out page is labelled now but is in no default set: `make eval-graph` and `run_eval` skip it unless you pass `SET=held_out`, so its results cannot be seen, and tuned against, before C6 scores it.

- The unit is a whole page.
- Decide *when you capture*, before any model has run on the page. Choosing the easy pages afterwards defeats the purpose.
- Suggested split: hold out about a third, preferring pages from venues the prompt was never tuned on (so C6 tests generalization). Reading a page to label it is fine; looking at the model's results on it is the thing to avoid.

### 6. Run the label tests

```
uv run pytest agent_worker/tests/test_labels.py
```

It checks the shape: every page has shows, every show names a source line and an act, no show appears twice on a page, every labelled venue has its facts, and every non-show can match something. It checks the *form* of a label, not whether it is true; that is why `source_line` exists.

For a **gated** venue, add its key to `GATED_VENUES` at the top of that test file. `test_gated_pages_are_the_reachable_venues` asserts the gated set equals that list exactly, so a new gated page fails it until you do. (`gated=False` pages need no change.)

The local guard `test_every_captured_fixture_is_labelled` fails if a file in `eval/fixtures/` has no label. A capture deliberately not scored goes in `UNLABELLED_ON_PURPOSE` in the same file, with the reason.

### 7. The production venue list (optional, separate)

`app/db/seed.py` holds the venues the worker fetches and the API lists (one list for every environment, Dep-D16). Adding a venue there is its own decision, with its own re-seed step (`make db-reset`), and the evaluation does not need it. The harness creates the venue rows it needs in its own scratch database.

## After labelling

Run the harness over the new pages (`make eval-graph LABEL=<name> ONLY=<key>`). Held-out pages are excluded unless `SET=held_out`. `docs/dev/implementations/c5-pipeline-eval-harness.md` (Step 8) says how the baseline is recorded.

## Checklist

- [ ] The calendar page lists many dated shows, and a plain fetch can read it (no thin-page warning, no challenge).
- [ ] `VENUE_FACTS` has the entry (key, name, URL), with `blocked=` only if it genuinely cannot be fetched.
- [ ] The capture is in `eval/fixtures/` and its date is today's.
- [ ] The `PageLabel` is keyed by the exact file name, holds **every** show on the page, and `captured_on` is the capture date.
- [ ] Rows are read from the page text; judgement calls are noted in `convention=` / `alternatives=`.
- [ ] `gated` and `held_out` are set on purpose, before any results have been seen.
- [ ] `GATED_VENUES` updated if the venue is gated; `test_labels.py` passes.
