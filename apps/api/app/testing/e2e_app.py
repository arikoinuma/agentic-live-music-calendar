"""The real API for the end-to-end job: the production app, with its clock frozen (C2-D2).

Uvicorn starts this instead of `app.main` (`apps/calendar/playwright.config.ts`). Nothing about the
production app changes: the pin is a dependency override applied here, in a module production never imports
(a test enforces it), so no environment variable can freeze a real server's clock.

It refuses to start unless it has a pin (`E2E_API_FROZEN_NOW`, the instant in `e2e/support/clock.ts`) and its
`DATABASE_URL` is the throwaway `calendar_e2e` database (`app/testing/e2e_database.py`). The checks run before
the app is imported, so a refusal leaves nothing half-configured.
"""

import os

from sqlalchemy.engine import make_url

from app.config import settings
from app.testing.e2e_database import check_e2e_database_url, frozen_now_from

_frozen_now = frozen_now_from(os.environ.get("E2E_API_FROZEN_NOW"))
check_e2e_database_url(make_url(settings.database_url))

# Imported after the checks on purpose: a refusal must not have touched the app.
from app.clock import get_now
from app.main import app

app.dependency_overrides[get_now] = lambda: _frozen_now

__all__ = ["app"]
