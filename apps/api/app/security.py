"""The shared secret between the Next.js server and this API: the guard, its comparison and its start-up rule (C10).

WHAT THIS IS FOR
  The API has no users. Its one caller is the Next.js server, and everything it serves is public calendar data, but
  the API is reachable from the whole internet once it is hosted (a Railway URL), so without a check anyone could read
  it directly, bypass the staging gate (C4-D6) and wake the database. The check is one shared secret, sent by the Next.js
  server in a header and compared here (docs/dev/implementations/c10-wiring-and-guard-rails.md, C10-D6 to C10-D9;
  arch-initial.md section 5).

HOW TO READ IT
  1. `require_shared_secret` is the FastAPI dependency. `app/main.py` attaches it to one router that holds every data
     router (guard by default, C10-D6), and to `/health/db`, which sits on the app itself. It reads `Request`
     directly rather than `Header()` or `APIKeyHeader`, so it adds nothing to `/openapi.json` and the generated
     frontend types do not change (C10-D8).
  2. `check_shared_secret` (C10-K1) is the comparison: constant-time, on bytes.
  3. `shared_secret_problem` (C10-K2) is the rule the API's lifespan applies on a hosted environment: no secret, or a
     short one, is a start-up failure, so a forgotten variable cannot become a public API with a green deploy.
  4. `openapi_url_for` decides where the API serves its own schema (C10-D2): `/docs`, `/redoc` and `/openapi.json` are
     plain Starlette routes that no dependency covers, so they are switched off on staging and production instead.

  This module imports `app.config` only, so it sits below `app/main.py`.
"""

import secrets
from typing import Final

from fastapi import HTTPException, Request, status

from app.config import AppEnv, settings

# The header the Next.js server sends. The raw secret, not `Authorization: Bearer ...` (C10-D7): this is a shared
# secret between two of our own services, not a token a client presents, and a custom header cannot be mistaken for
# a user's credentials by a proxy or a log scrubber. Starlette's header lookup is case-insensitive.
SHARED_SECRET_HEADER: Final = "X-Api-Secret"  # noqa: S105 - the header's NAME, not a secret

# A hosted secret must be at least this long (C10-D9). `openssl rand -hex 32` gives 64; 32 is the floor that turns a
# pasted placeholder ("changeme") into a start-up failure instead of a guessable production secret.
MIN_SECRET_LENGTH: Final = 32


def _refusal() -> HTTPException:
    """The one 401 every refusal is: no header, a wrong one and an unreadable one all get this exact response.

    The same status and body for every cause (C10-D7), so a caller cannot tell "absent" from "wrong" from the
    response, and the body says nothing about the secret (not its length, not a hint).
    """
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API secret")


def check_shared_secret(supplied: str | None, expected: str) -> bool:
    """Does the header value the caller sent equal the configured secret? `None` means no header was sent.

    Returns a plain `bool` and never raises, whatever `supplied` holds: the caller turns `False` into the 401.
    """
    # A missing header (`None`) is a plain `False`, so "absent" and "wrong" are the same refusal (C10-D7). The compare is
    # `secrets.compare_digest`, which takes the same time wherever two values first differ, so a caller cannot learn the
    # secret one character at a time from response times (C10-K1). It is given BYTES, because `compare_digest` on `str`
    # raises `TypeError` for any non-ASCII text, and an attacker-chosen header can be non-ASCII (Starlette decodes headers
    # as latin-1): a `str` compare would turn that into a 500, a visible difference from the 401 every other wrong value
    # gets. This differs from C4-D6's compare on purpose (C10-PR1-8): that one hashes both sides first because a
    # human-chosen gate password can be any length; here the value is machine-generated and `shared_secret_problem`'s
    # floor keeps it long, `compare_digest` on raw bytes reveals only the secret's length, and a 64-character length is
    # not worth hiding.
    if supplied is None:
        return False
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def shared_secret_problem(app_env: AppEnv, secret: str | None) -> str | None:
    """What is wrong with the API's secret for a HOSTED environment, as a sentence, or `None` when it is good.

    Pure, so a table can drive it. It is only called for a hosted `app_env`: the lifespan skips `local`, because a
    laptop's API is open by design (C10-D9, C10-PR1-7), so this function carries no `local` branch.
    """
    # Fail closed (C10-K2, C10-D9): on any hosted `APP_ENV` a missing or short secret is a start-up failure, because the
    # alternative ("enforce when it is set") makes a forgotten variable a public API with a green deploy. The `local`
    # exemption is decided once, in the lifespan, and tested there, not here. The 32-character floor turns a pasted
    # placeholder into a refusal at deploy time rather than a guessable secret in production. The rule is in the API's
    # own lifespan and not in `Settings`, so the worker, which builds `Settings` and never reads this variable, is
    # unaffected. The sentence names the variable and never contains the value.
    if secret is None:
        return f"APP_ENV={app_env} but API_SHARED_SECRET is not set: a hosted API would answer anyone"
    if len(secret) < MIN_SECRET_LENGTH:
        return f"API_SHARED_SECRET is shorter than {MIN_SECRET_LENGTH} characters"
    return None


def openapi_url_for(app_env: AppEnv) -> str | None:
    """Where this environment serves its own schema: `/openapi.json` on a laptop and in dev, nowhere on staging or prod.

    FastAPI serves `/docs`, `/redoc` and `/openapi.json` as plain routes, outside every router, so the guard never
    runs on them. Passing `None` as `openapi_url` removes all three (the docs pages are built from it), which closes the
    gap for the two environments the public can reach, while a developer still reads them locally (C10-D2, PQR1-12).
    """
    return "/openapi.json" if app_env in ("local", "dev") else None


async def require_shared_secret(request: Request) -> None:
    """The dependency: let the request through only if it carries the configured secret, else raise the 401.

    Runs before the route's own parameters are validated and before `get_db` is resolved, so a refused request learns
    nothing about the routes (no 422 for a bad parameter) and never opens a database session (C10-D6). The secret is
    read from `settings` per request, and only here does its value leave its `SecretStr` (C10-D8).
    """
    secret = settings.api_shared_secret
    if secret is None:
        # No secret configured. A laptop serves openly, so `make dev` and every route test work as they always did
        # (C10-D9). A hosted process with no secret should never have started (the lifespan refuses it), but if one
        # got here anyway it fails closed: only `local` may be open.
        if settings.app_env == "local":
            return
        raise _refusal()
    if not check_shared_secret(request.headers.get(SHARED_SECRET_HEADER), secret.get_secret_value()):
        raise _refusal()
