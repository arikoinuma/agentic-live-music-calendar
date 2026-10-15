import datetime
import json
from pathlib import Path

from agent_worker.graph import compiled_graph
from agent_worker.state import VenueGraphState

# venue_name and metro_timezone are what the venue's database row will supply once the worker
# reads the database (A4/A5); until then they are passed here. Values from app/db/seed.py
# (venue 1, The White Squirrel Bar) and the seeded metro's zone.
result = compiled_graph.invoke(
    VenueGraphState(
        venue_id=1,
        calendar_url="agent_worker/eval/fixtures/Archives_ Events - The White Squirrel Bar.html",
        venue_name="The White Squirrel Bar",
        metro_timezone="America/Chicago",
        # The fixture was saved on August 17, 2026; the year rule (A2.1-D13) reads this date,
        # and today's would put its August shows a year ahead.
        fetched_on=datetime.date(2026, 8, 17),
    )
)
state = VenueGraphState(**result)

# page_content is only useful to a human when it's text (a cleaned HTML
# page) — for an image fixture it's a giant base64 blob, unreadable and
# not worth dumping in full. Truncate it for the file; everything else
# (extraction, confidence, attempt_count, reconcile_decision) is written
# out completely, since that's what's actually worth inspecting.
dump = state.model_dump()
for key in ("page_content", "page_html"):
    if dump[key] and len(dump[key]) > 200:
        original_length = len(dump[key])
        dump[key] = dump[key][:200] + f"... (truncated, {original_length} chars total)"

output_path = Path(__file__).parent / "local_test_output.json"
output_path.write_text(json.dumps(dump, indent=2, default=str))
print(f"Wrote result to {output_path}")

# A3: what validation decided, and what each attempt did. The same fields are in the JSON above
# (`validation`, `attempt_history`); this is the part worth reading first.
verdict = state.validation.verdict.value if state.validation and state.validation.verdict else "none"
print(f"verdict: {verdict} after {state.attempt_count} attempt(s); source: {state.extraction_source}")
for record in state.attempt_history:
    print(
        f"  attempt {record.attempt} [{record.tier}, {record.route}, {record.model}]: {record.verdict.value}"
        f"{' — ' + ', '.join(r.value for r in record.reasons) if record.reasons else ''}"
    )
if state.escalation_reason:
    print(f"escalated: {state.escalation_reason}")
