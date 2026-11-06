"""Shared pieces for the route modules: the 404 declaration and the one way a route refuses a request with a 422."""

from typing import Any

from fastapi.exceptions import RequestValidationError

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


def unprocessable(param: str, message: str, value: object) -> RequestValidationError:
    """A 422 for a rule the router checks itself (a range, a combination), in the same body FastAPI uses for its own.

    FastAPI answers a bad query value with `{"detail": [{"type", "loc", "msg", "input"}]}`, and the OpenAPI document
    and the generated TypeScript (`HTTPValidationError`) promise exactly that for every 422. A plain
    `HTTPException(422, detail="...")` would put a string there instead, so a client would have to handle two shapes
    under one status (PQR1-11). Raising `RequestValidationError` with one item hands the body to FastAPI's own handler,
    and `loc` names the parameter the rule is about, which a global handler wrapping a string could not do
    (PQR1-5-D1). `value` is the offending input, echoed as FastAPI does; it is JSON-encoded on the way out, so a date
    becomes `"2025-01-01"` and `True` becomes `true`.

    Usage: `raise unprocessable("end", "`end` must be on or after `start`", end)`.
    """
    return RequestValidationError([{"type": "value_error", "loc": ("query", param), "msg": message, "input": value}])
