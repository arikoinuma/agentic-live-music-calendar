from typing import Literal

from pydantic import BaseModel

from agent_worker.schemas import VenuePageExtraction

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

    # page_content — str | None. What fetch_node produces: raw
    # fetched content, defaulting to None since it doesn't exist yet at
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

    # confidence — float | None. Distinct from the per-show
    # confidence field already inside each ShowExtraction in
    # `extraction.shows` — this is what validate_node reads to make its
    # conditional-edge routing decision, so decide now whether it's an
    # aggregate (e.g. the minimum, or the average, across
    # extraction.shows) computed by validate_node, or something else.
    # Worth deciding deliberately rather than leaving implicit, since
    # the next Phase 6 step wires add_conditional_edges directly against
    # this field.
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
