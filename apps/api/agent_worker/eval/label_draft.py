"""List a captured page's visible lines as candidate `source_line`s for a hand-written label (C5-K1).

What this is: labelling a page means reading it and writing, for each real show, the date, the acts and the line it came from
(`labels.py`). Finding and copying the lines is the tedious part; deciding what is a show and who the acts are is the part that
needs a person. This prints the first and leaves the second alone: the page's visible text (scripts and styles stripped, as the
pipeline cleans a page), one numbered line each, repeated lines once, with the lines that look dated flagged.

It deliberately prints NO act names from structured data: a label is read from the page text, never from JSON-LD or a model's
output (`labels.py` docstring), or the score would measure agreement with the model rather than correctness.

    uv run python -m agent_worker.eval.label_draft agent_worker/eval/fixtures/<capture>.html

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 7 (A2.1-D11 asked for "the page's entry lines pasted as `source_line`
candidates"; this is that as a tool).
"""

import argparse
import re
from pathlib import Path

from agent_worker.extraction import clean_text

# A month name or abbreviation followed by a day number ("Oct 10", "August 17", "AUG 8"), or a numeric month/day ("10/31").
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATED = re.compile(rf"\b{_MONTHS}\s+\d{{1,2}}\b|\b\d{{1,2}}/\d{{1,2}}\b", re.IGNORECASE)


def candidate_lines(html: str) -> list[tuple[int, str, bool]]:
    """`(line number, text, looks dated)` for each distinct visible line of the page, in page order.

    The number is the line's position in the cleaned text (with line breaks kept), so it can be quoted back. A line that
    repeats (a heading and a nav link, say) is listed at its first position only."""
    seen: set[str] = set()
    lines = []
    for number, raw in enumerate(clean_text(html, keep_line_breaks=True).splitlines(), start=1):
        text = raw.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        lines.append((number, text, bool(_DATED.search(text))))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List a captured page's visible lines as candidate source lines for a label.")
    parser.add_argument("fixture", type=Path, help="the captured page (an .html file)")
    args = parser.parse_args(argv)
    for number, text, dated in candidate_lines(args.fixture.read_text()):
        print(f"{number:5d} {'>' if dated else ' '} {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
