"""Split event titles into performing acts — the JSON-LD route's one model call.

On the JSON-LD route (sources/jsonld.py), dates, times and prices come from the venue's own
structured data. What JSON-LD doesn't say is which performing acts a title like "Lent w.
Gills, Boomdagger" names, or whether "Open Jam" is a music show at all. That one judgement
goes to the model here, as a deliberately narrow task: one call per page, all titles at once,
answer "which acts, or none" per title (A2.1-D4, A2.1-D5 of
docs/dev/implementations/a2.1-extraction-reliability.md).

How to read it: the response models (`ActSplitItem`, `ActSplitAnswer`) are what the model
fills in; `_act_split_instruction` is the instruction (A2.1-K4); `split_titles` numbers
the titles, makes the call, and aligns the answer back to the titles **by id**, so a dropped or
reordered item can never put one show's acts on another.

Known limit: this splitter makes the remaining act errors that keep A2.1 short of the accuracy
standard (56 of 60 on the gated venues: ambiguous names cut, dropped or misread). The fix is a larger
model for this one call, which only fits on hosted inference. It is milestone H1 of
docs/dev/alpha-deployment-plan.md (A2.1-E1–A2.1-E3).
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from agent_worker import prompts
from agent_worker.llm import RequestOptions, request_kwargs
from agent_worker.normalize import fold_text


class ActSplitItem(BaseModel):
    """The model's answer for one numbered title."""

    id: int = Field(description="The number the title was given")
    title: str = Field(description="The title, exactly as given")
    acts: list[str] = Field(
        description="The performing acts the title names, in order; an empty list if it is not a music show"
    )


class ActSplitAnswer(BaseModel):
    """The model's whole answer: one item per title it was given."""

    items: list[ActSplitItem] = Field(description="One entry for every numbered title")


@dataclass
class SplitResult:
    """Acts per input title, in input order, plus what didn't line up (recorded, not hidden)."""

    acts: list[list[str]]
    missing_ids: list[int] = field(default_factory=list)  # titles the answer left out
    title_mismatches: list[int] = field(default_factory=list)  # ids whose echoed title differs


def _act_split_instruction() -> str:
    """The narrow instruction for splitting titles into acts."""
    # Narrow the task. arch-initial.md §7's escalation order starts with "narrow the task": a model
    # asked only "which acts does this title name, and is it a music show at all?" has one judgement
    # to make per title, not a whole page's worth (dates, times, prices are already exact from
    # JSON-LD). The conventions it must follow are A2.1-D5's, in ONE shared text (`prompts._act_conventions()`)
    # that the full-page model route also gets, so the two routes can't disagree (A2.1-PR2-2). Keep the rules there rather than writing them here, or the splitter and the model route
    # drift apart. The exclusion rule is the same one the model route uses, because JSON-LD lists
    # every event on the calendar, karaoke included. Ask for every id back, with an empty list for a
    # non-music title, so a dropped title is visible rather than silent.
    return (
        "You are given numbered event titles from a live-music venue's calendar. For "
        "each id, list the performing acts the title names, in the order they appear, "
        "copying each name exactly as written. For a title that isn't a music show under "
        "the rule below, return its id with an empty acts list. Return every id you were "
        "given, with its title.\n"
        + prompts._act_conventions()
        + prompts._non_music_rule()
    )


# What a retry's splitter hint is introduced with (A3). Fixed text; an empty hint adds nothing.
_HINT_INTRO = "Problems found in an earlier attempt; fix them this time:\n"


def split_titles(
    titles: list[str], *, client: Any, options: RequestOptions, seed: int | None = None, hint: str = ""
) -> SplitResult:
    """Ask the model which acts each title names; return them aligned to `titles`. `hint` is a
    retry's note about what went wrong with the splitter's earlier answer (policy.retry_hint); empty
    on a first attempt, which leaves the request byte-identical."""
    if not titles:  # nothing to split: no model call
        return SplitResult(acts=[])
    numbered = "\n".join(f"{i}: {title}" for i, title in enumerate(titles))
    instruction = _act_split_instruction()
    if hint:
        instruction += "\n" + _HINT_INTRO + hint + "\n"
    answer: ActSplitAnswer = client.chat.completions.create(
        response_model=ActSplitAnswer,
        messages=[{"role": "user", "content": instruction + "\n" + numbered}],
        **request_kwargs(options, seed),
    )

    # Align by id. The first answer for an id wins; ids outside the range are ignored. The
    # echoed title is only a cross-check, compared after folding, since a model may re-quote
    # an apostrophe or re-escape an "&" without changing the title (A2.1-PR1-10).
    by_id: dict[int, ActSplitItem] = {}
    for item in answer.items:
        if 0 <= item.id < len(titles) and item.id not in by_id:
            by_id[item.id] = item

    result = SplitResult(acts=[])
    for i, title in enumerate(titles):
        item = by_id.get(i)
        if item is None:
            result.acts.append([])
            result.missing_ids.append(i)
            continue
        if fold_text(item.title) != fold_text(title):
            result.title_mismatches.append(i)
        result.acts.append([a.strip() for a in item.acts if a.strip()])
    return result
