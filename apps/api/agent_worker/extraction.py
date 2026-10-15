"""The one extraction entry point, shared by the pipeline and the eval harness.

`extract_node` (nodes.py) and the eval harness (eval/run_eval.py) both call `extract_page`
(or `extract_image` for a poster), so the eval always measures exactly what the pipeline
sends. A2 learned this the hard way with the instruction text (prompts.py); A2.1 adds a
routing decision, a second model call and a set of experiment switches, so the whole request
lives here now (docs/dev/implementations/a2.1-extraction-reliability.md, Design §1).

How to read it:
- `ExtractionConfig` holds the switches A2.1's experiment ladder flips one at a time. Each
  defaults to today's behaviour; `PIPELINE_CONFIG` / `PIPELINE_OPTIONS` are what the pipeline
  runs, and adopting a rung means changing a default there (plan, "Experiment protocol").
- `extract_page` chooses a route (Gap C): the venue's own JSON-LD when the page has
  usable events, otherwise the full-page model extraction A2 built.
- `_from_model` and `_from_jsonld` are the two routes; `PageExtractionResult` records which
  one ran, the text sent, and anything worth noting, for the eval now and the audit trail
  (A4) later.
"""

import datetime
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel

from agent_worker import act_split, status_check
from agent_worker.llm import RequestOptions, instructor_client, request_kwargs
from agent_worker.normalize import infer_year
from agent_worker.prompts import extraction_instruction
from agent_worker.schemas import (
    ActExtraction,
    ShowExtraction,
    VenueListingsExtraction,
    VenuePageExtraction,
    page_model,
    show_model,
)
from agent_worker.sources import jsonld
from app.config import settings

__all__ = [
    "PIPELINE_CONFIG", "PIPELINE_OPTIONS", "ExtractionConfig", "PageExtractionResult",
    "RequestOptions", "clean_text", "extract_image", "extract_page", "instructor_client", "usable_events",
]


@dataclass(frozen=True)
class ExtractionConfig:
    """The experiment ladder's switches. Every default is today's (A2's) behaviour, so the
    `a21-rebaseline` label is current code and each rung flips exactly one field."""

    # "auto" = Gap C's routing (JSON-LD first); "model" = always the full-page model route.
    route: Literal["auto", "model"] = "model"
    # Clean with get_text(separator="\n") instead of " ": keeps the act boundaries Terminal
    # Bar marks with <br> (plan review #1). Rung `a21-newlines`.
    keep_line_breaks: bool = False
    # False = A2's `schema-only` instruction (no exclusion / one-show rules); kept so A2's
    # middle label can still be reproduced.
    include_new_rules: bool = True
    # D12: the schema variant with `status`, plus the cancelled sentence. Rung `a21-cancelled`.
    status_field: bool = False
    # D13: each model-route date's year set from the fetch date, in code. Rung `a21-year`.
    year_rule: bool = False
    # D5's conventions sent on the model route too (round 2 #2). Rung `a21-act-conventions`.
    act_conventions: bool = False
    # F9: the `acts` description that says to split listings into separate acts. Rung
    # `a21-acts-desc`.
    acts_split_description: bool = False
    # D12 as decided by Ari (October 11): cancelled/postponed listings found by a separate narrow
    # question (status_check.py) instead of a schema field. Rung `a21-status-pass`.
    status_pass: bool = False
    # S6 (October 11): the page model copies each listing's performer text verbatim and the act
    # splitter splits it, as on the JSON-LD route. Rung `a21-title-split`.
    title_split: bool = False
    # A3, G25: keep each <img> URL in the cleaned text as a "[image: URL]" line so the model can copy
    # a poster's address (it was null in practice before: cleaning kept visible text only). Off until
    # one gated eval run shows the gate holds (A3 plan, D12) — adding text to every page the model reads
    # is exactly the kind of change that moved act splitting before.
    keep_image_urls: bool = False
    # A3, G5: what a retry adds to its requests. Empty on the first attempt, which leaves the
    # request byte-identical to the one that scored 56/60. `policy.plan_for_attempt` sets them from
    # what the earlier attempts failed on, each aimed at the call that produces the field: `retry_hint`
    # is appended to the page model's instruction, `splitter_hint` to the act splitter's.
    retry_hint: str = ""
    splitter_hint: str = ""


# What the pipeline runs. The harness starts from this same pair and overrides one field per
# flag (run_eval.configure), so a later label measures whatever the pipeline has adopted.
# Temperature 0: adopted by Ari on October 10, 2026 (D8), after `a21-temp0-quick` scored about the
# same as the model's default of 1 and made 5 of 6 gated pages byte-identical run to run.
PIPELINE_OPTIONS = RequestOptions(model=settings.model_name, temperature=0.0)
# Adopted by Ari on October 11, 2026: the year rule (`a21-year`) and the JSON-LD route
# (`a21-structured`) after the overnight ladder, and the separate status question
# (`a21-status-pass`) that morning. The other switches stay off until a rung for them is kept.
# Later on October 11, after `a21-title-split`: the act conventions, line-break cleaning and title
# split on the model route.
PIPELINE_CONFIG = ExtractionConfig(
    route="auto", year_rule=True, status_pass=True,
    act_conventions=True, keep_line_breaks=True, title_split=True,
)


@dataclass
class PageExtractionResult:
    """One page's extraction, plus how it was produced."""

    extraction: VenuePageExtraction
    source: Literal["jsonld", "model", "image"]
    # What the model was actually given as the page (cleaned text, or the numbered titles on
    # the JSON-LD route). Stored per eval run so a missed act boundary can be traced to "never
    # sent" vs "sent and ignored" (plan, step 9).
    sent_text: str
    notes: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Building the request
# ---------------------------------------------------------------------------


def clean_text(html: str, keep_line_breaks: bool, keep_image_urls: bool = False) -> str:
    """The page's visible text: <script> and <style> dropped (A2/Phase 5: a 93 KB page was
    97% markup around 2.7 KB of content). With `keep_line_breaks`, each element and <br> line
    becomes its own line instead of being joined with spaces.

    With `keep_image_urls` (A3, G25) each <img> becomes a "[image: URL]" piece of text where it sits,
    so a poster's address is something the model can copy. The URL is the attribute as the page wrote
    it (entities already unescaped by the parser), not resolved against the page's address, so it
    stays checkable as "appears verbatim in the page". `data-src` stands in when `src` is absent or a
    `data:` placeholder (lazy-loaded images); an image with neither, or only a `data:` URI, adds nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    if keep_image_urls:
        for img in soup.find_all("img"):
            src = str(img.get("src") or "")
            if not src or src.startswith("data:"):
                src = str(img.get("data-src") or "")
            if src and not src.startswith("data:"):
                img.replace_with(f"[image: {src}]")
    return soup.get_text(separator="\n" if keep_line_breaks else " ", strip=True)


# What the retry hints are introduced with. Fixed text, so a hint never changes the first attempt's
# request (an empty hint adds nothing at all).
_HINT_INTRO = "Problems found in an earlier attempt at this page; fix them this time:\n"


def instruction_for(config: ExtractionConfig) -> str:
    """The instruction text this configuration sends (prompts.py assembles it), with the retry
    hint for the page model appended when there is one."""
    text = _base_instruction_for(config)
    if config.retry_hint:
        # Two newlines at the end: the unhinted instruction ends with a blank line before the page
        # text, and the hinted one must keep it, or the last hint line runs into the page's first.
        text += "\n" + _HINT_INTRO + config.retry_hint + "\n\n"
    return text


def _base_instruction_for(config: ExtractionConfig) -> str:
    return extraction_instruction(
        config.include_new_rules,
        cancelled_rule=config.status_field,
        # On the title-split route the page model doesn't split, so the splitting conventions go
        # to the act splitter only; the page model still gets the layout rule.
        act_conventions=config.act_conventions and not config.title_split,
        date_heading=config.act_conventions or config.title_split,
        title_split=config.title_split,
    )


def usable_events(html: str) -> list[dict[str, Any]]:
    """The page's JSON-LD events that can produce a show: they need a start (the date) and a name
    (what the act splitter reads). Every page carries SOME JSON-LD (WebSite, Restaurant…), so "the
    page has JSON-LD" is the wrong test, and an Event that can't produce a show doesn't count. The
    routing condition, shared by `extract_page` and `extract_node` (which records the route an
    attempt used even when the attempt fails)."""
    return [e for e in jsonld.find_events(html) if e.get("startDate") and e.get("name")]


def page_model_for(config: ExtractionConfig) -> type[BaseModel]:
    """The response schema this configuration asks for (schemas.page_model builds variants; the
    title-split route asks for listings instead of shows)."""
    if config.title_split:
        return VenueListingsExtraction
    return page_model(status=config.status_field, split_acts=config.acts_split_description)


def _apply_year_rule(extraction: VenuePageExtraction, fetch_date: datetime.date) -> None:
    """D13: every show's year from the fetch date, not the model (in place)."""
    for show in extraction.shows:
        show.date = infer_year(show.date, fetch_date)


# ---------------------------------------------------------------------------
# The two routes
# ---------------------------------------------------------------------------


def _from_model(
    html: str, *, venue_name: str, fetch_date: datetime.date, client: Any, options: RequestOptions,
    config: ExtractionConfig, seed: int | None,
) -> PageExtractionResult:
    """The full-page model extraction, as A2 built it: cleaned text after the instruction."""
    text = clean_text(html, config.keep_line_breaks, config.keep_image_urls)
    answer = client.chat.completions.create(
        response_model=page_model_for(config),
        messages=[{"role": "user", "content": instruction_for(config) + text}],
        **request_kwargs(options, seed),
    )
    notes: dict[str, Any] = {}
    if config.title_split:
        extraction = _shows_from_listings(
            answer, client=client, options=options, seed=seed, notes=notes, hint=config.splitter_hint
        )
    else:
        extraction = answer
    if config.year_rule:
        _apply_year_rule(extraction, fetch_date)
    if config.status_pass:
        # D12: ask separately, and only if the page says "cancelled"/"postponed" at all.
        asked = status_check.mentions_status(text)
        answer = (
            status_check.ask(text, client=client, options=options, seed=seed)
            if asked else status_check.StatusAnswer(items=[])
        )
        splitter = (
            (lambda titles: act_split.split_titles(
                titles, client=client, options=options, seed=seed, hint=config.splitter_hint,
            ).acts)
            if config.title_split else None
        )
        extraction, merge_notes = status_check.apply(
            extraction, answer, page_text=text, fetch_date=fetch_date if config.year_rule else None,
            venue_name=venue_name, split_titles=splitter,
        )
        # The positions of shows the merge added (placeholder confidence, no model judged them) go to the
        # top level, where validation reads them; the rest of the merge's notes stay nested.
        notes["added_indices"] = merge_notes.pop("added_indices", [])
        notes["status_question"] = {"asked": asked, "listings": len(answer.items), **merge_notes}
    return PageExtractionResult(extraction=extraction, source="model", sent_text=text, notes=notes)


def _shows_from_listings(
    listings: VenueListingsExtraction, *, client: Any, options: RequestOptions, seed: int | None,
    notes: dict[str, Any], hint: str = "",
) -> VenuePageExtraction:
    """The title-split route's second step: split every listing's verbatim title into acts with
    the act splitter (the JSON-LD route's narrow task), keeping every other field as the page
    model read it. A title the splitter gives no acts is kept with `acts: []` for A3, as on both
    other routes. The titles go into `notes` (the verbatim display text, D5)."""
    titles = [item.title for item in listings.listings]
    split = act_split.split_titles(titles, client=client, options=options, seed=seed, hint=hint)
    shows = [
        ShowExtraction(
            **item.model_dump(exclude={"title"}),
            acts=[ActExtraction(name=name) for name in acts],
        )
        for item, acts in zip(listings.listings, split.acts, strict=True)
    ]
    notes.update({
        "titles": titles,
        "no_acts": [t for t, acts in zip(titles, split.acts, strict=True) if not acts],
        "missing_ids": split.missing_ids,
        "title_mismatches": split.title_mismatches,
    })
    return VenuePageExtraction(page_readable=listings.page_readable, shows=shows)


def _from_jsonld(
    events: list[dict[str, Any]], *, html: str, venue_name: str, metro_timezone: str, client: Any,
    options: RequestOptions, seed: int | None, hint: str = "",
) -> PageExtractionResult:
    """Shows from the venue's JSON-LD; only the acts come from a model (act_split.py).

    A title the splitter gives no acts (a non-music entry: JSON-LD lists the whole calendar)
    is kept with `acts: []`, exactly as the model route does, so A3's completeness check sees
    the same shapes from both routes (A2 Design, "Consequences"). `confidence` 1.0 is a
    placeholder: it claims a certainty about acts the splitter doesn't have, and A3's decision
    on combining checks with confidence replaces it (plan review #15).
    """
    # The page's own visible text, so an end time is kept only where the page states it (D10).
    page_text = clean_text(html, keep_line_breaks=False)
    names = [str(e.get("name", "")) for e in events]
    structured = [jsonld.to_structured_show(e, metro_timezone, page_text, names) for e in events]
    titles = [s.title for s in structured]
    split = act_split.split_titles(titles, client=client, options=options, seed=seed, hint=hint)

    show_cls = show_model(status=True, split_acts=False)
    shows = [
        show_cls(
            venue=venue_name, date=s.date, time=s.time, end_time=s.end_time,
            acts=[ActExtraction(name=name) for name in acts], is_ambiguous=False,
            admission_advance=s.admission_advance, admission_day=s.admission_day,
            free_admission=s.free_admission, image_url=s.image_url, confidence=1.0,
            status=s.status,
        )
        for s, acts in zip(structured, split.acts, strict=True)
    ]
    page_cls = page_model(status=True, split_acts=False)
    notes = {
        "events": len(events),
        # The verbatim titles, in show order: A3's checks pair each show with its title (act names
        # must appear in it; an end time must be stated near it).
        "titles": titles,
        "no_acts": [t for t, acts in zip(titles, split.acts, strict=True) if not acts],
        "missing_ids": split.missing_ids,
        "title_mismatches": split.title_mismatches,
    }
    return PageExtractionResult(
        extraction=page_cls(page_readable=True, shows=shows), source="jsonld",
        sent_text="\n".join(f"{i}: {t}" for i, t in enumerate(titles)), notes=notes,
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def extract_page(
    html: str, *, venue_name: str, metro_timezone: str, fetch_date: datetime.date, client: Any,
    options: RequestOptions, config: ExtractionConfig, seed: int | None = None,
) -> PageExtractionResult:
    """Extract every show on one fetched page (raw HTML).

    `venue_name` and `metro_timezone` are facts from the venue's database row; the worker
    doesn't read the database yet (A4/A5), so the caller passes them — there is deliberately
    no default zone in this code (`metro.timezone` is the source of truth). `fetch_date` is
    when the page was fetched (D13's year rule).
    """
    if config.route == "auto":
        # Deterministic first, the model only where judgement is needed. The decision is recorded
        # (`source` on the result) so an audit can see which path ran (A2.1 plan, D4 and Design §3).
        # The test is subtle: every page carries SOME JSON-LD (WebSite, Restaurant…), so "the page
        # has JSON-LD" is the wrong test. An Event that can't produce a show doesn't count either: it
        # needs a start (the date) and a name (what the splitter reads). `usable_events` applies that.
        events = usable_events(html)
        if events:
            return _from_jsonld(events, html=html, venue_name=venue_name, metro_timezone=metro_timezone,
                                client=client, options=options, seed=seed, hint=config.splitter_hint)

    return _from_model(
        html, venue_name=venue_name, fetch_date=fetch_date, client=client, options=options,
        config=config, seed=seed,
    )


def extract_image(
    image_b64: str, *, mime: str, fetch_date: datetime.date, client: Any, options: RequestOptions,
    config: ExtractionConfig, seed: int | None = None,
) -> PageExtractionResult:
    """Extract the show a poster image depicts (the image path; build plan §8 defers reading
    images out of live pages, so this serves local poster fixtures).

    `mime` is passed through; every caller still passes "image/png", including for the .webp
    poster — the pre-existing label noted in A2 (Step 1), kept so results stay comparable.
    """
    # Title split is a page-route mechanism (titles, then the act splitter); a poster is read in one
    # call, so the image route always asks for shows with their acts.
    config = replace(config, title_split=False)
    instruction = instruction_for(config)
    content = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
    ]
    extraction: VenuePageExtraction = client.chat.completions.create(
        response_model=page_model_for(config),
        messages=[{"role": "user", "content": content}],
        **request_kwargs(options, seed),
    )
    if config.year_rule:
        _apply_year_rule(extraction, fetch_date)
    return PageExtractionResult(extraction=extraction, source="image", sent_text="")
