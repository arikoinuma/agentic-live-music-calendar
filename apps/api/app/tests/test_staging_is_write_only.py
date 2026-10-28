"""Nothing in production code reads an `extraction_staging` document back (C3-D10).

HOW TO READ THIS
  A copy of production's Postgres (Neon's "reset from parent") carries `audit_log.detail` values that name MongoDB
  staging documents. Those documents live only in production's Atlas database, so in a lower environment the ids
  dangle. That is harmless exactly as long as nothing dereferences them, and C3-D10 says to check that instead of
  assuming it. This test is the check: it parses the production modules and fails on any MongoDB read method, and
  on any `Stager` method other than `stage`. If a later milestone legitimately reads staging (a replay tool, an
  admin view), this test should fail, and its author must then decide what a dangling id means there.

  No database. The method names are MongoDB's own read API (pymongo), written out here, not read from the code.
"""

import ast
from pathlib import Path

from agent_worker.staging import Stager

API_DIR = Path(__file__).resolve().parents[2]
PACKAGES = ("app", "agent_worker")
NOT_PRODUCTION_DIRS = {"tests", "testing", "__pycache__", "eval"}
NOT_PRODUCTION_FILES = {"local_test.py"}

# pymongo collection methods that return documents or counts of them. `find` is separate (below), because
# `str.find` is everywhere.
MONGO_READS = {"find_one", "find_one_and_update", "find_one_and_delete", "find_one_and_replace",
               "aggregate", "count_documents", "estimated_document_count", "distinct", "watch"}


def mongo_reads(source: str) -> list[tuple[int, str]]:
    """(line, method) for every call in `source` that reads MongoDB documents.

    `find` is read as a collection call when its arguments look like a query: none at all, a dict literal, or any
    keyword argument (`filter=`, `projection=`, `sort=`, `limit=`). `text.find(key)` passes a plain name and is
    not flagged. That is a heuristic, and `test_the_matcher_catches_find_on_a_collection` pins what it does catch
    (C3-CR1-2).
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        query_shaped = not node.args or isinstance(node.args[0], ast.Dict) or bool(node.keywords)
        if name in MONGO_READS or (name == "find" and query_shaped):
            found.append((node.lineno, name))
    return found


def _production_modules() -> list[Path]:
    found = []
    for package in PACKAGES:
        for path in (API_DIR / package).rglob("*.py"):
            relative = path.relative_to(API_DIR / package)
            if NOT_PRODUCTION_DIRS & set(relative.parts) or path.name in NOT_PRODUCTION_FILES:
                continue
            found.append(path)
    return found


def test_no_production_module_calls_a_mongodb_read_method() -> None:
    # Proves (C3-D10): no production module calls a method that reads documents from MongoDB, so a dangling
    # staging id in a copied `audit_log.detail` is never dereferenced. The eval harness and `local_test.py` are
    # manual tools and are excluded by name, as in `test_no_testing_imports.py`.
    offenders = [
        f"{path.relative_to(API_DIR)}:{line} .{name}()"
        for path in _production_modules()
        for line, name in mongo_reads(path.read_text())
    ]
    assert offenders == []


def test_the_matcher_catches_find_on_a_collection() -> None:
    # Proves (C3-CR1-2): the scan flags the read a replay tool would most likely write, `find` on the staging
    # collection, in the shapes pymongo accepts (a filter dict, keyword arguments, an async cursor), and leaves
    # `str.find` alone. Without this, a guard that never fires would look the same as a guard that works.
    reads = [
        'cursor = collection.find({"_id": staged_id})',
        'docs = await mongo[db]["extraction_staging"].find({"_id": sid}).to_list(1)',
        'collection.find(filter={"_id": 1}, limit=1)',
        "everything = collection.find()",
        "one = await collection.find_one({})",
    ]
    for source in reads:
        assert mongo_reads(source), source
    assert mongo_reads("at = text.find(key)") == []
    assert mongo_reads("nxt = text.find(other_key, at + len(key))") == []


def test_the_stager_interface_can_only_write() -> None:
    # Proves (C3-D10): the interface the graph holds for MongoDB has one method, `stage`, so a node cannot read
    # a staging document back through it. Adding a getter to `Stager` turns this red and forces the question.
    methods = {name for name in vars(Stager) if not name.startswith("_")}
    assert methods == {"stage"}
