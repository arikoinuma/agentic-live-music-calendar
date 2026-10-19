"""Matching an act named on a venue page to an artist we already have: exact, none, or ask the model.

HOW TO READ THIS
  Reconcile (reconcile.py) needs an `artist` row for every act on every scheduled listing. This module answers
  "which one?" in three steps, cheapest first:

  1. `artist_key` — one tidied form of a name (case, accents, "&" vs "and", punctuation, a leading "The"),
     so "Poliça" and "Polica" are the same artist without anyone being asked (D8).
  2. `classify_artist` — **K4**: exact, ambiguous (similar but not equal) or new (D8, D12).
  3. `decide_ambiguous` — **K5**: the one place a model makes a database decision. It is asked about at most
     three candidates; an unsure answer, a refusal, a made-up id or a failed call all mean "new artist" (D9).
  `resolve_artists` runs the three once per distinct name in a run, so the same unknown act on three shows is
  one new artist and one model call, not three.

  Artist matching is global, not metro-scoped (requirements-initial.md, "Agent Artist Creation & Matching").

WHY IT'S SHAPED THIS WAY
  The thresholds are starting values in a named `ArtistMatchPolicy`, to be calibrated against labelled data in A8,
  the way A3's confidence threshold was. Similarity is Python's `difflib` over every artist loaded for the run
  (D12): no new dependency and no migration at alpha size. Import order: this module sits below `state.py`
  (reconcile.py and the state import it), so it takes `EXTRACTION_ERRORS` from llm.py, not nodes.py.

docs/dev/implementations/a5-reconcile.md, D8, D9, D12; K4, K5.
"""

import difflib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_worker import prompts
from agent_worker.llm import EXTRACTION_ERRORS, RequestOptions, request_kwargs
from agent_worker.normalize import fold_text

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnownArtist:
    """An artist row, as much of it as matching needs."""

    id: int
    name: str


@dataclass(frozen=True)
class ArtistMatchPolicy:
    """The named, injectable settings for artist matching (D12), as `RetryPolicy` is for retries.

    Starting values, not measurements: A8 calibrates them against labelled data. `ratio` is the
    `difflib` similarity at or above which two different names are "close"; `max_candidates` is how many
    close artists the model is shown; `min_confidence` is the model confidence below which its "same act"
    is not trusted (D9).
    """

    ratio: float = 0.85
    max_candidates: int = 3
    min_confidence: float = 0.8


DEFAULT_ARTIST_POLICY = ArtistMatchPolicy()


@dataclass(frozen=True)
class Exact:
    """A known artist whose tidied name equals the incoming one. `duplicates` are other artists with the same
    tidied name (merging duplicates is a deferred feature; the lowest id is used, deterministically)."""

    artist_id: int
    duplicates: tuple[int, ...] = ()


@dataclass(frozen=True)
class Ambiguous:
    """Known artists whose names are close to the incoming one but not equal: the model's question."""

    candidates: tuple[KnownArtist, ...]


@dataclass(frozen=True)
class New:
    """No known artist is close: create one."""


Classification = Exact | Ambiguous | New

Outcome = Literal["exact", "new", "matched_by_model", "new_after_model"]


@dataclass(frozen=True)
class ArtistResolution:
    """What reconcile decided for one distinct artist name, and how.

    `artist_id` is the existing artist to link, or None when a new one is to be created (A6 creates it, once,
    from `name`). `decided_by` says whether a rule or the model decided: the audit trail writes one row for
    each model decision (`audit.model_decision_entries`), with `model_used`, `confidence` and `reason`.
    """

    name: str  # the spelling first seen on a page, used to create a new artist
    key: str
    outcome: Outcome
    artist_id: int | None
    decided_by: Literal["rule", "model"]
    model_used: str | None = None
    confidence: float | None = None
    candidates: tuple[KnownArtist, ...] = ()
    reason: str | None = None
    duplicates: tuple[int, ...] = ()


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def artist_key(name: str) -> str:
    """One comparison form for an artist name (D8): folded, accents removed, "&" read as "and",
    punctuation dropped, a leading "the" dropped. Never stored or shown; for comparing only.

    A name that is nothing but punctuation ("!!!", a real touring band) would come out empty, and an empty
    key equals every other empty key, so it falls back to the plain folded name (A5-PR1-11).
    """
    text = unicodedata.normalize("NFKD", fold_text(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("&", " and ")
    words = "".join(c if c.isalnum() else " " for c in text).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words) if words else fold_text(name)


def _is_close(key: str, other: str, policy: ArtistMatchPolicy) -> bool:
    """Similar enough to ask about: `difflib` ratio at or above the policy's, or one name's words are all in
    the other's ("Zhora" in "Zhora Band", which a ratio alone scores far too low: 0.667)."""
    if difflib.SequenceMatcher(None, key, other).ratio() >= policy.ratio:
        return True
    shorter, longer = sorted((key.split(), other.split()), key=len)
    return bool(shorter) and set(shorter) <= set(longer)


def _similarity(key: str, other: str) -> float:
    return difflib.SequenceMatcher(None, key, other).ratio()


# ---------------------------------------------------------------------------
# K4: exact, ambiguous or new
# ---------------------------------------------------------------------------


def classify_artist(
    name: str, known: Iterable[KnownArtist], policy: ArtistMatchPolicy = DEFAULT_ARTIST_POLICY
) -> Classification:
    """Exact, ambiguous or new (A8-D8, A8-D12): a three-way answer, not a score with one cut-off."""
    #   "clear matches and clear non-matches resolve automatically; ambiguous matches go through a
    #   review step rather than a fixed rule" (requirements-initial.md, D8, D12). That is a THREE-way answer, not a
    #   similarity score with one cut-off, and the middle band is deliberately where the model is used. A two-way
    #   rule is wrong in one direction either way: too loose merges two acts, too strict duplicates one.
    key = artist_key(name)
    known = list(known)
    exact = sorted(a.id for a in known if artist_key(a.name) == key)
    if exact:
        return Exact(artist_id=exact[0], duplicates=tuple(exact[1:]))
    close = [(a, _similarity(key, artist_key(a.name))) for a in known if _is_close(key, artist_key(a.name), policy)]
    close.sort(key=lambda pair: (-pair[1], pair[0].id))
    return Ambiguous(candidates=tuple(a for a, _ in close[: policy.max_candidates])) if close else New()


# ---------------------------------------------------------------------------
# K5: the model decides the ambiguous case
# ---------------------------------------------------------------------------


class ArtistMatchAnswer(BaseModel):
    """The model's answer about one incoming name."""

    matched_artist_id: int | None = Field(
        default=None,
        description="The id of the listed artist this act is the same as; null if it is a different act or you are unsure",
    )
    confidence: float = Field(ge=0, le=1, description="Your confidence in this answer, from 0 to 1")
    reason: str = Field(description="One sentence saying why")


def ask(
    incoming: str, candidates: Iterable[KnownArtist], *, client: Any, options: RequestOptions, seed: int | None = None
) -> ArtistMatchAnswer:
    """The single model call: is `incoming` one of `candidates`?"""
    offered = [(c.id, c.name) for c in candidates]
    answer: ArtistMatchAnswer = client.chat.completions.create(
        response_model=ArtistMatchAnswer,
        messages=[{"role": "user", "content": prompts.artist_match_instruction(incoming, offered)}],
        **request_kwargs(options, seed),
    )
    return answer


def _resolution(name: str, outcome: Outcome, **fields: Any) -> ArtistResolution:
    return ArtistResolution(name=name, key=artist_key(name), outcome=outcome, **fields)


def _new(
    name: str, options: RequestOptions, candidates: tuple[KnownArtist, ...], *, reason: str,
    answer: ArtistMatchAnswer | None = None,
) -> ArtistResolution:
    """The conservative outcome (D9): a new artist, decided by the model's step, with why."""
    return _resolution(
        name, "new_after_model", artist_id=None, decided_by="model", model_used=options.model,
        confidence=answer.confidence if answer else None, candidates=candidates, reason=reason,
    )


def _matched(
    name: str, options: RequestOptions, candidates: tuple[KnownArtist, ...], answer: ArtistMatchAnswer
) -> ArtistResolution:
    """The model's confident "same act": link the existing artist it named."""
    return _resolution(
        name, "matched_by_model", artist_id=answer.matched_artist_id, decided_by="model", model_used=options.model,
        confidence=answer.confidence, candidates=candidates, reason=answer.reason,
    )


def decide_ambiguous(
    name: str, candidates: tuple[KnownArtist, ...], *, client: Any, options: RequestOptions,
    policy: ArtistMatchPolicy = DEFAULT_ARTIST_POLICY,
) -> ArtistResolution:
    """Ask the model; link only on a confident answer naming an offered artist, else create a new one (D9)."""
    #   This is the one place in the pipeline where a model makes a database decision, so the failure
    #   direction is a design decision, not an accident (A5-D9). A wrong merge is silent and spreads (two acts share one
    #   page); a duplicate artist is visible and revertable. So low confidence, a "different act" answer, an id nobody
    #   offered and a failed call ALL resolve to "new artist", and the resolution records why, which `trace.audited`
    #   turns into the audit row.
    try:
        answer = ask(name, candidates, client=client, options=options)
    except EXTRACTION_ERRORS as err:
        return _new(name, options, candidates, reason=f"model call failed: {type(err).__name__}: {err}")
    if answer.matched_artist_id in {c.id for c in candidates} and answer.confidence >= policy.min_confidence:
        return _matched(name, options, candidates, answer)
    return _new(name, options, candidates, reason=answer.reason, answer=answer)


# ---------------------------------------------------------------------------
# Once per name
# ---------------------------------------------------------------------------


def resolve_artists(
    names: Iterable[str], known: Iterable[KnownArtist], *, client: Any, options: RequestOptions,
    policy: ArtistMatchPolicy = DEFAULT_ARTIST_POLICY,
) -> dict[str, ArtistResolution]:
    """One resolution per distinct `artist_key` among `names`, keyed by it (the first spelling is kept).

    Reconcile runs before commit, so the database can't tell it that an artist it is about to create was
    already created for another show: the same unknown name on three shows must come out as one new artist
    here, and the model is asked about an ambiguous name once, not once per show.
    """
    known = list(known)
    resolved: dict[str, ArtistResolution] = {}
    for name in names:
        key = artist_key(name)
        if key in resolved:
            continue
        found = classify_artist(name, known, policy)
        if isinstance(found, Exact):
            resolved[key] = _resolution(
                name, "exact", artist_id=found.artist_id, decided_by="rule", duplicates=found.duplicates
            )
        elif isinstance(found, Ambiguous):
            resolved[key] = decide_ambiguous(name, found.candidates, client=client, options=options, policy=policy)
        else:
            resolved[key] = _resolution(name, "new", artist_id=None, decided_by="rule")
    return resolved
