"""Seed the local database with the metro and the four starting venues.

Run: `uv run python -m scripts.seed` (from apps/api), or `make seed`.
Safe to run repeatedly — see app/db/seed.py.

The logic is in app/db/seed.py so it can be tested against a session the
test controls; this file only supplies the real one.
"""

import asyncio

from app.db.seed import seed
from app.db.session import SessionFactory, engine


async def main() -> None:
    # One session for the whole seed: open it, let seed() add rows, commit.
    async with SessionFactory() as session:
        await seed(session)
        # seed() only flushes; committing is the caller's call.
        await session.commit()
    # Close pooled connections so the process exits cleanly.
    await engine.dispose()
    print("Seeded.")


# Only runs when invoked as a script (`python -m scripts.seed`), not when this
# module is merely imported. asyncio.run drives the async main() to completion.
if __name__ == "__main__":
    asyncio.run(main())
