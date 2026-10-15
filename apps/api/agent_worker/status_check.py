"""Cancelled and postponed listings, found by a separate narrow question — A2.1-D12 as decided by Ari.

A2.1-D12 (docs/dev/implementations/a2.1-extraction-reliability.md): a cancelled or postponed listing
is not a show to display, but it must be extracted with its status, because the show was most
likely stored on an earlier scan and reconcile has to find it and update it. The first attempt
put a `status` field into the main extraction schema (`a21-cancelled`): the status came back
right on every cancelled listing, but the extra field made act splitting worse on pages with no
cancelled shows at all — the same schema-shape sensitivity behind A2-F9. Ari chose (October 11,
2026) to ask separately instead, so the main schema stays exactly as it is.

How to read it, in order:
1. `mentions_status` — a code check: does the page's text say "cancelled" or "postponed" at all?
   Most pages don't, and they cost no model call.
2. `ask` — one small model call that lists only the cancelled/postponed listings (date, acts,
   which) — the narrow-task idea again (arch-initial.md §7).
3. `apply` — code merges the answer into the extraction: a matching show gets its status; a
   listing the main extraction skipped is added with its status.

This is the full-page model route's mechanism. The JSON-LD route reads schema.org `eventStatus`
directly (sources/jsonld.py).
"""

import datetime
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_worker.llm import RequestOptions, request_kwargs
from agent_worker.normalize import fold_text, identifying_words, infer_year
from agent_worker.schemas import (
    ActExtraction,
    VenuePageExtraction,
    page_model,
    show_model,
)

# The words a page uses for it ("Cancelled", "CANCELED", "postponed"). Spelled out rather than
# left to the model: if a page never says it, there is nothing to ask.
_STATUS_WORDS = re.compile(r"\b(cancell?ed|postponed)\b", re.IGNORECASE)


class StatusItem(BaseModel):
    """One listing the page marks cancelled or postponed."""

    date: datetime.date = Field(description="The listing's date, as YYYY-MM-DD")
    acts: list[str] = Field(description="The performing acts the listing names, as written")
    status: Literal["cancelled", "postponed"] = Field(description="Whether it is cancelled or postponed")


class StatusAnswer(BaseModel):
    """The model's answer: only the cancelled or postponed listings; empty if there are none."""

    items: list[StatusItem] = Field(description="Every listing marked cancelled or postponed")


def mentions_status(page_text: str) -> bool:
    """True when the page's visible text says "cancelled", "canceled" or "postponed"."""
    return bool(_STATUS_WORDS.search(page_text))


def _instruction() -> str:
    """The narrow question. It asks for nothing but the marked listings."""
    return (
        "Below is the text of a live-music venue's calendar page. List ONLY the listings that "
        "the page marks as cancelled or postponed. For each, give its date, the performing acts "
        "it names (as written), and whether it is cancelled or postponed. If no listing is "
        "marked cancelled or postponed, return an empty list.\n\n"
    )


def ask(page_text: str, *, client: Any, options: RequestOptions, seed: int | None = None) -> StatusAnswer:
    """Ask the model which listings are cancelled or postponed (one small call)."""
    answer: StatusAnswer = client.chat.completions.create(
        response_model=StatusAnswer,
        messages=[{"role": "user", "content": _instruction() + page_text}],
        **request_kwargs(options, seed),
    )
    return answer


def _same_listing(answer_acts: list[str], show_acts: list[str]) -> int:
    """How strongly a status answer and a show name the same listing: the number of identifying
    words they share (filler such as "the" and "with" excluded), or, for names too short to have
    any ("MO", "U2"), the number of act names they share exactly. 0 = not the same listing."""
    shared = identifying_words(" ".join(answer_acts)) & identifying_words(" ".join(show_acts))
    if shared:
        return len(shared)
    return len({fold_text(a) for a in answer_acts} & {fold_text(a) for a in show_acts})


def _on_page(acts: list[str], page_text: str) -> bool:
    """True when every identifying word of the answer's acts appears in the page text — the
    check that keeps a status answer from ever adding a show the page doesn't list."""
    page = identifying_words(page_text)
    words = identifying_words(" ".join(acts))
    if words:
        return words <= page
    folded = fold_text(page_text)
    return all(fold_text(a) in folded for a in acts)


def apply(
    extraction: VenuePageExtraction, answer: StatusAnswer, *, page_text: str,
    fetch_date: datetime.date | None, venue_name: str,
    split_titles: Callable[[list[str]], list[list[str]]] | None = None,
) -> tuple[VenuePageExtraction, dict[str, Any]]:
    """Merge the status answer into the extraction; return it in the status-carrying schema,
    with notes of what was matched, added and refused.

    Every show starts `scheduled`. Each answered listing is matched to the show it names — the
    one sharing the most identifying words (or exact short names), on its date or, failing
    that, a day either side (this model sometimes shifts a listing by a day) — and given its
    status. A listing nothing matches was skipped by the main extraction and is added with its
    status, **only if its acts appear in the page text**; otherwise it is recorded in the notes
    and not added (A2.1-CR2-1). An added listing's acts go through `split_titles`
    when given (the title-split route's act splitter, #4). Its date follows the year rule when
    `fetch_date` is given (A2.1-D13); it has no time (the question doesn't ask for one: missing is
    tolerated, a wrong value is not) and `confidence` 1.0 — a placeholder, like the JSON-LD
    route's, which A3's confidence aggregate ignores (`notes["added_indices"]`).
    """
    show_cls = show_model(status=True, split_acts=False)
    shows = [show_cls.model_validate({**s.model_dump(), "status": "scheduled"}) for s in extraction.shows]
    notes: dict[str, Any] = {"matched": 0, "added": 0, "not_on_page": []}
    to_add: list[tuple[datetime.date, list[str], str]] = []
    for item in answer.items:
        listed = infer_year(item.date, fetch_date) if fetch_date else item.date
        best, best_score = None, 0
        for slip in (0, 1):  # the listed date first, then a day either side
            for show in shows:
                if abs((show.date - listed).days) != slip:
                    continue
                score = _same_listing(item.acts, [a.name for a in show.acts])
                if score > best_score:
                    best, best_score = show, score
            if best is not None:
                break
        if best is not None:
            best.status = item.status  # type: ignore[attr-defined]
            notes["matched"] += 1
        elif _on_page(item.acts, page_text):
            to_add.append((listed, item.acts, item.status))
        else:
            notes["not_on_page"].append(item.acts)
    if to_add and split_titles is not None:
        split = split_titles([", ".join(acts) for _, acts, _ in to_add])
        to_add = [(d, acts_split or acts, st) for (d, acts, st), acts_split in zip(to_add, split, strict=True)]
    # Where the merge's own additions sit in the returned list: they carry a placeholder confidence of
    # 1.0 that no model judged, so validation leaves them out of the confidence minimum (A3).
    notes["added_indices"] = list(range(len(shows), len(shows) + len(to_add)))
    for listed, acts, status in to_add:
        shows.append(show_cls(
            venue=venue_name, date=listed, acts=[ActExtraction(name=a) for a in acts],
            is_ambiguous=False, confidence=1.0, status=status,
        ))
        notes["added"] += 1
    page_cls = page_model(status=True, split_acts=False)
    return page_cls(page_readable=extraction.page_readable, shows=shows), notes
