-- Saved queries over the audit trail (agent_run + audit_log).  Milestone A4, alpha-build-plan.md §2 point 3:
-- "every step of that run is queryable afterward ... entirely from the database".
--
-- HOW TO RUN ONE (psql):
--     make db-shell
--     \set run_id 3
--     \set show_id 12
--     <paste the query>        (or: \i docs/dev/audit-queries.sql  to run all four)
-- The same file is executed by agent_worker/tests/test_audit_queries.py, which binds :run_id and
-- :show_id as SQLAlchemy parameters; that is why the queries use CAST(... AS ...) rather than the `::`
-- shorthand, which SQLAlchemy would read as a bind parameter.
--
-- WHAT `detail` HOLDS (agent_worker/audit.py is the source of truth):
--   fetch     url, fetched_on, error, text_chars
--   extract   tier, route, error, staging_id (the MongoDB document), shows, larger_model_used
--   validate  route, verdict, reasons, errors, warnings, repairs, excluded
--   reconcile / commit   stub (true until A5 / A6), decision
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
