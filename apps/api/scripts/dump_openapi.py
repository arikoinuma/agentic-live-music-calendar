"""Write the OpenAPI document to a file, without starting a server.

Run: `uv run python -m scripts.dump_openapi` (from apps/api)

FastAPI builds this document from the route signatures and their
response models, and serves it at GET /openapi.json. `app.openapi()`
returns the same dict directly, which means type generation doesn't need
a running API, a free port, or a health-check wait loop — it just needs
the code to import. That matters most in CI.

The output file is git-ignored: it's derived, and the generated
TypeScript is the artifact anyone actually reads.
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> None:
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
