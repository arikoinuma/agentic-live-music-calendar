-- Saved queries over the audit trail (agent_run + audit_log).  Milestone A4, alpha-build-plan.md §2 point 3:
-- "every step of that run is queryable afterward ... entirely from the database".
--
-- HOW TO RUN ONE (from the repo root; psql runs inside the container, so the file is piped in):
--     cat docs/dev/audit-queries.sql | docker compose exec -T postgres psql -U postgres -d calendar_dev \
--         -v run_id=3 -v show_id=12 -f -
--   That runs all six queries. For one query, paste it into `make db-shell` after
--     \set run_id 3
--     \set show_id 12
--   (`\i` doesn't work here: it reads the file from inside the container, which doesn't have the repo.)
-- The same file is executed by agent_worker/tests/test_audit_queries.py, which binds :run_id and
-- :show_id as SQLAlchemy parameters; that is why the queries use CAST(... AS ...) rather than the `::`
-- shorthand, which SQLAlchemy would read as a bind parameter.
--
-- WHAT `detail` HOLDS (agent_worker/audit.py is the source of truth):
--   fetch     url, fetched_on, error, text_chars
--   extract   tier, route, error, staging_id (the MongoDB document), shows, larger_model_used
--   validate  route, verdict, reasons, errors, warnings, repairs, excluded
--   reconcile summary   counts (per action), coverage ({start, end} the removals were judged inside, or null),
--                       needs_review and withheld (lists of {action, date, time, stored_id, acts, reason}),
--                       artists (resolutions per outcome), model_decisions
--   reconcile artist    one row per artist the MODEL decided: entity_type = 'artist', entity_id = the artist linked
--                       (null when the answer was "new"), model_used, confidence; detail has name, outcome, reason,
--                       candidates
--   commit summary      counts (exactly inserted, updated, removed, no_op, skip: the first three are what was WRITTEN, the
--                       last two what reconcile left alone), artists_created, failed (a list of {action, date, time,
--                       stored_id, reconcile_reason, sqlstate, error} for shows the database refused), all_failed (true when
--                       three or more writes all failed: looks like a bug, not bad listings), withheld (removals the guard
--                       held back; never written). entity_type = 'venue', no outcome. Written LAST, after every row below.
--   commit show         one row per show WRITTEN: entity_type = 'show', entity_id = the show, outcome = inserted / updated /
--                       removed, previous_value and new_value = the snapshots a revert restores (the whole show row except
--                       its timestamps, plus a `lineup` list; previous_value is null for an insert). detail: action,
--                       reconcile_reason (why: 'new show', 'details changed', 'reappeared', 'cancelled', 'absent from the
--                       page'), changed (the columns), needs_review. An unchanged show writes NO row (A6-D1).
--   commit artist       one row per artist created: entity_type = 'artist', outcome = inserted, new_value = {id, name}.
--   commit failure      one row per show the database refused: entity_type = 'show', entity_id = the stored show (null for an
--                       insert), no outcome, no snapshots (nothing was written). detail: action, reconcile_reason, date, time,
--                       stored_id, sqlstate, error. (Its key is `reconcile_reason`, not `reason`, because run_history labels
--                       detail ->> 'reason' "escalation_reason".)
--   escalate  reason

-- name: run_history
-- "Show me everything that happened in run N", oldest first. One row per step; a retry is another row.
-- staging_id is the _id of the raw extraction document in MongoDB (db.extraction_staging).
SELECT al.id,
       al.created_at,
       al.step_type,
       al.attempt_number,
       al.model_used,
       al.confidence,
       al.outcome,
       al.detail ->> 'route'      AS route,
       al.detail ->> 'tier'       AS tier,
       al.detail ->> 'verdict'    AS verdict,
       CAST(al.detail -> 'reasons' AS text) AS reasons,
       al.detail ->> 'error'      AS error,
       al.detail ->> 'reason'     AS escalation_reason,
       al.detail ->> 'staging_id' AS staging_id
FROM audit_log al
WHERE al.run_id = :run_id
ORDER BY al.id;

-- name: escalated_runs
-- "Which runs escalated, and why", newest first. attempts is how many extract attempts were made (NULL when
-- the page could not be fetched, so extraction never started).
SELECT r.id AS run_id,
       v.name AS venue,
       r.started_at,
       r.finished_at,
       (SELECT max(x.attempt_number)
          FROM audit_log x
         WHERE x.run_id = r.id AND x.step_type = 'extract') AS attempts,
       e.detail ->> 'reason' AS reason
FROM agent_run r
JOIN venue v ON v.id = r.venue_id
JOIN audit_log e ON e.run_id = r.id AND e.step_type = 'escalate' AND e.outcome = 'escalated'
ORDER BY r.started_at DESC, r.id DESC;

-- name: show_history
-- "What changed about this show, and when". Every audit row that acted on show :show_id, with the row's
-- before and after, from commit's per-show rows (A6). An insert has no previous_value; an update's two snapshots differ in
-- exactly the columns it changed. A show that never changed has no rows (A6-D1).
SELECT al.created_at,
       al.run_id,
       al.step_type,
       al.outcome,
       al.previous_value,
       al.new_value
FROM audit_log al
WHERE al.entity_type = 'show'
  AND al.entity_id = :show_id
ORDER BY al.id;

-- name: unfinished_runs
-- Runs that did not end properly: still open (no finished_at), or closed without ever reaching the END of commit or
-- escalate, which means the process crashed mid-run (agent_worker/main.py closes a crashed run in a finally,
-- so the two cases look different here). A run with no finished_at is either still in progress or its
-- process died without reaching the finally; check the time. Closed with neither step = an exception.
-- "The end of commit" is commit's SUMMARY row (entity_type = 'venue'), not any commit row: since A6 commit writes a row
-- per show, so a run that wrote one show and then died has a commit row but no summary and must still be listed
-- (A6-M5). Runs finished BEFORE A6 in a dev database that was not reset have only the old stub commit row (no entity),
-- so they are listed too; `make db-reset` clears them.
SELECT r.id AS run_id,
       v.name AS venue,
       r.started_at,
       r.finished_at,
       (SELECT max(al.step_type) FROM audit_log al WHERE al.run_id = r.id) AS furthest_step
FROM agent_run r
JOIN venue v ON v.id = r.venue_id
WHERE r.finished_at IS NULL
   OR NOT EXISTS (
        SELECT 1 FROM audit_log al
         WHERE al.run_id = r.id
           AND ((al.step_type = 'commit' AND al.entity_type = 'venue') OR al.step_type = 'escalate')
      )
ORDER BY r.id DESC;

-- name: artist_match_decisions
-- "Which artists did the model decide, and what did it say" (A5). Reconcile asks the model only about an artist
-- whose name is close to, but not equal to, one we already have, and writes one row for each answer. This is the
-- one place a model makes a database decision, so these rows are what to read when two acts look wrongly merged
-- or wrongly split. artist_id is the existing artist it linked (NULL when it decided "new"); outcome is
-- matched_by_model, or new_after_model (a different act, an unsure answer, or a failed call: see reason).
SELECT al.id,
       al.run_id,
       v.name AS venue,
       al.created_at,
       al.entity_id AS artist_id,
       al.detail ->> 'name' AS incoming_name,
       al.detail ->> 'outcome' AS outcome,
       al.model_used,
       al.confidence,
       al.detail ->> 'reason' AS reason,
       CAST(al.detail -> 'candidates' AS text) AS candidates
FROM audit_log al
JOIN agent_run r ON r.id = al.run_id
JOIN venue v ON v.id = r.venue_id
WHERE al.step_type = 'reconcile'
  AND al.entity_type = 'artist'
ORDER BY al.id DESC;

-- name: failed_commits
-- "Which shows failed to write, and why" (A6-D2). When the database refuses one show's row (an overflowing price, a
-- constraint), commit records it, skips it and writes the rest. One row per refused show, newest first, with WHICH show
-- (its date and time; an insert has no id), the reconcile reason it was being written for, the SQLSTATE and the error.
-- A recurring failure shows up as the same show on successive runs; several shows failing with the same SQLSTATE in one
-- run looks like a bug in the writes, not bad listings (the run's summary row says all_failed). To count by cause, wrap
-- this query: SELECT sqlstate, count(*) FROM (<this query>) GROUP BY sqlstate. LEFT JOINs keep a row whose run was lost.
SELECT al.id,
       al.run_id,
       v.name AS venue,
       al.created_at,
       al.detail ->> 'action' AS action,
       al.detail ->> 'date' AS show_date,
       al.detail ->> 'time' AS show_time,
       al.entity_id AS stored_id,
       al.detail ->> 'reconcile_reason' AS reconcile_reason,
       al.detail ->> 'sqlstate' AS sqlstate,
       al.detail ->> 'error' AS error
FROM audit_log al
LEFT JOIN agent_run r ON r.id = al.run_id
LEFT JOIN venue v ON v.id = r.venue_id
WHERE al.step_type = 'commit'
  AND al.entity_type = 'show'
  AND al.detail ->> 'error' IS NOT NULL
ORDER BY al.id DESC;
