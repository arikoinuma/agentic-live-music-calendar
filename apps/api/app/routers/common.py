"""Shared pieces for the route modules."""

from typing import Any

# FastAPI documents a 422 for any route with a typed path parameter on
# its own, but it has no way to know which routes can 404. Declaring it
# puts the possibility in /openapi.json, which means the generated
# TypeScript knows a miss is a real outcome rather than something the
# frontend discovers in production.
#
# The annotation isn't decoration: inferred from the literal alone this
# is dict[int, dict[str, str]], and FastAPI's parameter is typed
# dict[int | str, dict[str, Any]] — a stricter key and value type than
# it accepts, which mypy rejects. Worth knowing as a general Python
# point: a dict literal's inferred type is often narrower than what you
# want to pass it to.
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Not found"}}
