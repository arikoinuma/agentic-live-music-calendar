-- Saved queries over the audit trail (agent_run + audit_log).  Milestone A4, alpha-build-plan.md §2 point 3:
-- "every step of that run is queryable afterward ... entirely from the database".
--
-- HOW TO RUN ONE (from the repo root; psql runs inside the container, so the file is piped in):
--     cat docs/dev/audit-queries.sql | docker compose exec -T postgres psql -U postgres -d calendar_dev \
--         -v run_id=3 -v show_id=12 -f -
--   That runs all four queries. For one query, paste it into `make db-shell` after
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
--   commit              stub (true until A6)
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
-- before and after. EMPTY until A6 writes per-show commit rows; the query is here so A6 has its test.
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
-- Runs that did not end properly: still open (no finished_at), or closed without ever reaching commit or
-- escalate, which means the process crashed mid-run (agent_worker/main.py closes a crashed run in a finally,
-- so the two cases look different here). A run with no finished_at is either still in progress or its
-- process died without reaching the finally; check the time. Closed with neither step = an exception.
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
         WHERE al.run_id = r.id AND al.step_type IN ('commit', 'escalate')
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
