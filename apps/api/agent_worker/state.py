import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_worker.policy import (
    DEFAULT_POLICY,
    AttemptPlan,
    AttemptRecord,
    RetryPolicy,
    Route,
)
from agent_worker.schemas import VenuePageExtraction
from agent_worker.validation import ValidationResult

# Pydantic model vs TypedDict — the doc leaves this open, and it's a
# real choice, not a formality. LangGraph supports both equally; TypedDict
# is the more common choice in LangGraph's own tutorials (lighter weight,
# no validation overhead, since it's just a plain dict at runtime).
# Pydantic (what's used below, and everywhere else in this codebase so
# far — Settings, ShowExtraction) buys you the same thing it's bought you
# in every other file: a bug in how a node constructs its state update
# becomes an immediate validation error instead of a silent bad value
# that surfaces three nodes later. This file assumes Pydantic for that
# consistency, but reconsider if it turns out awkward once you're
# actually wiring add_node/add_conditional_edges in the next step.


class VenueGraphState(BaseModel):
    """Shared state LangGraph passes between fetch/extract/validate/
    reconcile/commit/escalate nodes for one venue's processing run.

    Per docs/dev/env-setup.md Phase 6: venue, fetched page content, the
    extracted record, confidence, attempt count, and the eventual
    reconcile decision.
    """

    # venue_id — int. Which venue row (from the `venue` table
    # created in Phase 3's migration) this run belongs to. Needed by
    # reconcile_node/commit_node to know what to write against.
    venue_id: int

    # calendar_url — str. The specific field fetch_node actually
    # needs to know what to fetch; pulled from the venue row's
    # calendar_url column rather than re-deriving it from venue_id every
    # node that needs it.
    calendar_url: str

    # venue_name, metro_timezone — facts from the venue's database row that extraction needs
    # (A2.1): the JSON-LD route names the venue on each show, and converts a structured
    # source's UTC/offset times into the metro's wall clock (`metro.timezone`, the source of
    # truth — data-model-initial.md). The worker doesn't read the database yet (A4/A5), so
    # whoever builds the state passes them. Deliberately no default: a default zone hidden
    # here would quietly be wrong for a second metro.
    venue_name: str
    metro_timezone: str

    # page_html — the raw fetched HTML (None for an image). A2.1's JSON-LD route needs it:
    # JSON-LD lives in <script> blocks, which cleaning strips from page_content.
    page_html: str | None = None

    # fetched_on — the date fetch_node ran; the year rule (A2.1-D13) reads it.
    fetched_on: datetime.date | None = None

    # page_content — str | None. What fetch_node produces: the cleaned
    # text of the fetched page (or base64 for an image), defaulting to None since it doesn't exist yet at
    # graph start. Note this needs to hold either HTML/text OR a
    # base64-encoded image depending on what the venue's page turns out
    # to be — same text-vs-image distinction the eval script's
    # load_text_fixture/load_image_fixture dealt with, just from a live
    # fetch instead of a saved file this time.
    page_content: str | None = None

    # extraction — VenuePageExtraction | None (the class imported
    # above). What extract_node produces. Reusing the schema you already
    # built rather than inventing a second one — this is the same shape,
    # just now coming from a live fetch instead of a static fixture.
    extraction: VenuePageExtraction | None = None

    # confidence — float | None. Decided in A3 (it was an open question here): the minimum of the
    # model's per-show confidence over the shows a model judged and that were kept, or None when no
    # model judged the record (the JSON-LD route stamps a placeholder 1.0 on every show; a page with
    # nothing kept has nothing to be confident about). It is one input to the verdict
    # (`validation.verdict`, set by policy.combine) and the number A8 checks for calibration. The
    # router does not read it: it reads the verdict, so a `None` here can't reach a comparison.
    confidence: float | None = None

    # attempt_count — int, defaulting to 0. Incremented each time
    # validate_node routes back to extract_node on a low-confidence or
    # inconsistent result. Retries are capped at 3 per the architecture
    # doc ("Retries are capped (3 attempts). Exhausting the cap escalates
    # to human review") — this is the field that cap gets checked
    # against.
    attempt_count: int = 0

    # reconcile_decision — the doc's own outcome table
    # (docs/arch/arch-initial.md Section 7) names exactly five possible
    # values: no-op, delete, insert, update, ambiguous match. A
    # `Literal[...]` of those five (as short, code-friendly strings, e.g.
    # "no_op", "delete", "insert", "update", "ambiguous_match") is a
    # better fit than a bare `str` — it makes an invalid/misspelled
    # outcome a validation error instead of a typo that silently reaches
    # commit_node. Defaults to None, since nothing's been decided yet at
    # graph start.
    reconcile_decision: (
        Literal["no_op", "delete", "insert", "update", "ambiguous_match"] | None
    ) = None

    # ---------------------------------------------------------------------
    # A3: validation and retry. Everything below is defaulted, so
    # `VenueGraphState(**result)` re-wrapping still works. Who sets each field and who reads it:
    # ---------------------------------------------------------------------

    # policy — the retry settings for this run (confidence threshold, attempt cap, escalation
    # model). On the state rather than in a graph factory (A3-D11): the compiled graph stays
    # a singleton, and A8 or a test varies a run by passing a different policy. Read by the
    # routers and by extract_node / validate_node.
    policy: RetryPolicy = DEFAULT_POLICY

    # fetch_error — set by fetch_node when the page couldn't be fetched (after the transient-error
    # retries), or came back empty. Read by route_after_fetch and by escalate_node.
    fetch_error: str | None = None

    # extraction_source / route_attempted / extraction_notes / extract_error / last_plan — what
    # extract_node did this attempt. All are assigned on EVERY attempt (to None where nothing was
    # produced): LangGraph keeps a field's old value when a node leaves it alone, so without the
    # reset an attempt-2 success would still carry attempt 1's error. `route_attempted` is set
    # before the call, so a failed attempt still says which route it used (the sticky fallback
    # reads it). The notes are PageExtractionResult.notes (route, titles, status merge) — A4
    # persists them (A2.1-E17).
    extraction_source: Route | None = None
    route_attempted: Route | None = None
    extraction_notes: dict[str, Any] = Field(default_factory=dict)
    extract_error: str | None = None
    last_plan: AttemptPlan | None = None

    # validation — validate_node's evidence plus the verdict (None before it has run); read by
    # route_after_validate. validated_extraction is the shows to commit: repairs applied, excluded
    # shows removed. `extraction` stays the model's raw answer (the audit record). Reconcile (A5)
    # reads `validated_extraction`, and the graph only reaches it on a pass.
    validation: ValidationResult | None = None
    validated_extraction: VenuePageExtraction | None = None

    # attempt_history — one AttemptRecord per attempt, appended by validate_node. Retries add rows;
    # nothing is overwritten (the same idea as `audit_log`). A4 persists it; A8 measures the retry
    # loop from it; plan_for_attempt reads it to build the next attempt's hints and route.
    attempt_history: list[AttemptRecord] = Field(default_factory=list)

    # escalation_reason — a plain-English reason, composed by escalate_node. A6 writes it.
    escalation_reason: str | None = None

    # ---------------------------------------------------------------------
    # A4: auditability (docs/dev/implementations/a4-auditability.md)
    # ---------------------------------------------------------------------

    # run_id — the `agent_run.id` of this venue's processing cycle: the `parent_run_id` of
    # arch-initial.md §7. Set by `main.run_venue` before the graph starts and carried here, not in a module
    # global, so every node's audit row points at the run that produced it. None when a caller runs the
    # graph without a run (a test of one node); the rows then have a NULL run_id.
    run_id: int | None = None

    # extraction_sent_text — what the model was actually given as the page on the attempt that just ran
    # (PageExtractionResult.sent_text), kept so the raw-staging document can record it (A2.1-E17). Assigned
    # on EVERY attempt, None where the call failed before returning it, for the same reason as the A3
    # per-attempt fields above.
    extraction_sent_text: str | None = None
