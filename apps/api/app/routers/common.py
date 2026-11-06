"""Shared pieces for the route modules."""

from typing import Any

# FastAPI documents a 422 for any route with a typed path parameter on
# its own, but it has no way to know which routes can 404. Declaring it
# puts the possibility in /openapi.json, which means the generated
# TypeScript knows a miss is a real outcome rather than something the
# frontend discovers in production.
#
# The annotation is required, not decoration: inferred from the literal alone this is
# dict[int, dict[str, str]], narrower than FastAPI's dict[int | str, dict[str, Any]] parameter, and mypy rejects
# passing it (dict is invariant in its key and value types).
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Not found"}}
