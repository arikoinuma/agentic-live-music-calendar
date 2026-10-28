"""Re-create a Neon environment's login role after a "reset from parent" (C3-D9).

Run: `uv run python -m scripts.restore_neon_role staging [--set-password]` (from apps/api), with `NEON_OWNER_URL` set in the shell
to the branch's OWNER connection (`neondb_owner`, `postgresql+asyncpg://`, direct host, no `sslmode`). The helper
`neon_restore_role <env>` in the local, uncommitted `.hosted-env.sh` sets it for you.

Restoring and changing a password are separate. Without the flag, the script asks for a password ONLY when the
role is missing (after a reset), and then it must be the SAME password the environment's `DATABASE_URL` already
holds, so Railway's variable stays valid. A role that exists keeps its password. `--set-password` is the
explicit, separate way to change one (then update that environment's `DATABASE_URL` to match). The sequence and
the reasons for its order are in `app/db/neon_roles.py`; this file only supplies the real connection and the
guard rails.

Guard rails, because this edits a hosted database from a laptop: the URL must come from the shell (never `.env`),
must log in as `neondb_owner`, and the person must type the environment name after reading the host and database
that are about to change.
"""

import asyncio
import getpass
import os
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.neon_roles import ROLE_FOR_ENV, restore_role, role_exists, set_role_password


async def main(env: str, set_password: bool) -> None:
    if env not in ROLE_FOR_ENV:
        sys.exit(f"Usage: restore_neon_role {{{'|'.join(ROLE_FOR_ENV)}}} [--set-password]")
    role = ROLE_FOR_ENV[env]

    owner_url = os.environ.get("NEON_OWNER_URL")
    if not owner_url:
        sys.exit("NEON_OWNER_URL is not set in this shell (the branch's neondb_owner connection).")
    url = make_url(owner_url)
    if url.username != "neondb_owner":
        sys.exit(f"NEON_OWNER_URL logs in as {url.username!r}; it must be the branch owner, 'neondb_owner'.")

    # Show where this will act and make the person type the environment, so a URL left over from another branch
    # is caught by a human before anything changes.
    action = "change the password of" if set_password else "restore"
    print(f"About to {action} role {role!r} on host {url.host}, database {url.database}.")
    if input(f"Type the environment name ({env}) to continue: ").strip() != env:
        sys.exit("Not confirmed; nothing changed.")

    engine = create_async_engine(url)
    try:
        # One transaction: either everything below happens or nothing changed.
        async with engine.begin() as conn:
            exists = await role_exists(conn, role)
            if set_password:
                if not exists:
                    sys.exit(f"{role} does not exist on this branch; run without --set-password to create it.")
                password = _ask_password(f"NEW password for {role}")
                await set_role_password(conn, role, password)
                print(f"Changed the password of {role}. Update {env}'s DATABASE_URL to match.")
                return
            # Only a missing role needs a password; an existing one keeps the one its DATABASE_URL holds.
            password = None if exists else _ask_password(f"Password for {role} (the one its DATABASE_URL uses)")
            created = await restore_role(conn, role, password)
    finally:
        await engine.dispose()
    what = "Created the role and" if created else "The role already existed (password untouched);"
    print(f"{what} handed it the tables. Verify with: neon_{env} && neon_probe {env.upper()}_URL")


def _ask_password(prompt: str) -> str:
    """Read a password with no echo; an empty one is refused rather than stored."""
    password = getpass.getpass(f"{prompt}: ")
    if not password:
        sys.exit("An empty password was given; nothing changed.")
    return password


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(args[0] if args else "", "--set-password" in sys.argv))
