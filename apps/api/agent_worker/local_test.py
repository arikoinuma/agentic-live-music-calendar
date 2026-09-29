import json
from pathlib import Path

from agent_worker.graph import compiled_graph
from agent_worker.state import VenueGraphState

result = compiled_graph.invoke(
    VenueGraphState(venue_id=1, calendar_url="agent_worker/eval/fixtures/Archives_ Events - The White Squirrel Bar.html")
)
state = VenueGraphState(**result)

# page_content is only useful to a human when it's text (a cleaned HTML
# page) — for an image fixture it's a giant base64 blob, unreadable and
# not worth dumping in full. Truncate it for the file; everything else
# (extraction, confidence, attempt_count, reconcile_decision) is written
# out completely, since that's what's actually worth inspecting.
dump = state.model_dump()
if dump["page_content"] and len(dump["page_content"]) > 200:
    original_length = len(dump["page_content"])
    dump["page_content"] = dump["page_content"][:200] + f"... (truncated, {original_length} chars total)"

output_path = Path(__file__).parent / "local_test_output.json"
output_path.write_text(json.dumps(dump, indent=2, default=str))
print(f"Wrote result to {output_path}")
