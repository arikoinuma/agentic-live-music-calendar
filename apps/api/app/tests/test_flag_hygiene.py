"""Tests that the code's flag reads and the registry cannot drift apart (C3.1-T12).

HOW TO READ THIS
  `scripts.flags.hygiene_problems` checks three things (C3.1-D18): every `is_enabled(...)` / `isEnabled(...)` call
  names a registered flag with a string literal, on a surface that flag declares; every flag is read on each
  surface it declares; and `docs/dev/environments.md`'s inventory block lists exactly the registered variables.

  Two kinds of test, because a checker that finds nothing passes by accident:
    * the REAL repository passes (the checker run over `app/`, `agent_worker/`, `apps/calendar` and the real
      document), and
    * a SYNTHETIC tree built in `tmp_path` that breaks each rule on purpose produces exactly those problems, and
      the same tree without the bad lines produces none.
  The synthetic tree is checked against a registry taken from the shared case table (`flag-cases.json`), so it can
  hold a web-only flag and an unread one that the real registry does not. Expected problems are written out here, not
  computed by the checker.
"""

import dataclasses
from pathlib import Path

from app.flags import FLAGS, build_registry
from app.tests.test_flags import CASE_FLAGS
from scripts.flags import API_ROOT, ENVIRONMENTS_DOC, WEB_ROOT, hygiene_problems, inventory_variables

# The synthetic registry: one flag Python reads, one the web reads, one nothing reads.
REGISTRY = build_registry([CASE_FLAGS["demo.python_only"], CASE_FLAGS["demo.web_only"]])
# The case table's unread flag declares both surfaces, which would be two problems; narrowed to Python it is one.
UNREAD = dataclasses.replace(CASE_FLAGS["demo.unread"], surfaces=("python",))
REGISTRY_WITH_AN_UNREAD_FLAG = build_registry([CASE_FLAGS["demo.python_only"], CASE_FLAGS["demo.web_only"], UNREAD])


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def tree(tmp_path: Path, *, bad: bool) -> tuple[Path, Path]:
    """A synthetic `apps/api` and `apps/calendar`. With `bad=False` every read is clean; with `bad=True` the same
    tree also holds one unregistered read, one non-literal read and one read on the wrong surface."""
    api, web = tmp_path / "api", tmp_path / "web"
    clean_py = "from app.flags import is_enabled\n\nON = is_enabled('demo.python_only')\n"
    bad_py = "NOPE = is_enabled('demo.nope')\nname = 'demo.python_only'\nDYNAMIC = is_enabled(name)\n"
    bad_py += "WRONG = is_enabled('demo.web_only')\n"
    write(api, "app/routes.py", clean_py + (bad_py if bad else ""))
    # Everything below must be ignored by the scan: a test, the testing package, the flags module itself.
    write(api, "app/tests/test_routes.py", "is_enabled('demo.ignored')\n")
    write(api, "app/testing/sample.py", "is_enabled('demo.ignored')\n")
    write(api, "app/flags.py", "def is_enabled(name):\n    return is_enabled('demo.ignored')\n")
    write(web, "app/page.tsx", 'const on = isEnabled("demo.web_only");\n')
    write(web, "lib/flags.ts", "export function isEnabled(name: string) { return isEnabled(name); }\n")
    write(web, "lib/flags.test.ts", 'isEnabled("demo.ignored");\n')
    write(web, "node_modules/pkg/index.ts", 'isEnabled("demo.ignored");\n')
    return api, web


def test_the_real_repository_passes_the_checks() -> None:
    # Proves (C3.1-T12, C3.1-D18): every flag read in `app/`, `agent_worker/` and `apps/calendar` is a literal naming a
    # registered flag on a surface it declares, every registered flag is read on each of its surfaces, and
    # `environments.md`'s inventory lists exactly the registered variables. This is the guard that keeps a typo'd or
    # forgotten flag from shipping.
    assert hygiene_problems(FLAGS, api_root=API_ROOT, web_root=WEB_ROOT, environments_doc=ENVIRONMENTS_DOC) == []


def test_a_clean_synthetic_tree_has_no_problems(tmp_path: Path) -> None:
    # Proves (C3.1-T12): the control for the next test. The same tree minus the three bad reads passes, and the
    # ignored files (tests, `app/testing`, the flags module, `node_modules`) are really ignored: they all read a
    # name that is registered nowhere.
    api, web = tree(tmp_path, bad=False)
    assert hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=None) == []


def test_every_kind_of_problem_is_found_and_only_those(tmp_path: Path) -> None:
    # Proves (C3.1-T12, C3.1-D18): a tree with one unregistered read, one non-literal read, one read on the wrong
    # surface and one registered flag that nothing reads yields exactly those four problems, each naming its
    # location or flag. A checker that scanned nothing would return an empty list and fail this.
    api, web = tree(tmp_path, bad=True)
    problems = hygiene_problems(REGISTRY_WITH_AN_UNREAD_FLAG, api_root=api, web_root=web, environments_doc=None)
    assert len(problems) == 4, problems
    # Line numbers are those of the synthetic `app/routes.py` built in `tree`: 4 unregistered, 6 non-literal, 7 wrong surface.
    (unregistered,) = [p for p in problems if "app/routes.py:4" in p]
    (non_literal,) = [p for p in problems if "app/routes.py:6" in p]
    (wrong_surface,) = [p for p in problems if "app/routes.py:7" in p]
    (unread,) = [p for p in problems if "'demo.unread'" in p and "routes.py" not in p]
    assert "'demo.nope'" in unregistered and "not a registered" in unregistered
    assert "string literal" in non_literal
    assert "'demo.web_only'" in wrong_surface and "python" in wrong_surface
    assert "nothing on that surface reads it" in unread


def test_a_web_read_of_a_python_only_flag_is_a_problem(tmp_path: Path) -> None:
    # Proves (C3.1-T12, C3.1-D8): the web scan applies the surface rule too, with the file and line, and finds a
    # non-literal argument. This is the checker's half of "a flag only Python reads must not become callable from the web".
    api, web = tree(tmp_path, bad=False)
    write(web, "app/other.tsx", 'const a = isEnabled("demo.python_only");\nconst b = isEnabled(someName, { metro });\n')
    problems = hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=None)
    assert len(problems) == 2, problems
    assert any("app/other.tsx:1" in p and "web" in p for p in problems)
    assert any("app/other.tsx:2" in p and "string literal" in p for p in problems)


def test_a_read_split_over_several_lines_is_still_seen(tmp_path: Path) -> None:
    # Proves (C3.1-T12, C3.1-D18, C3.1-CR1-1): the web scan matches the whole file, not one line at a time, so a call that
    # a formatter wrapped (C4's caller passes `{ metro }`) is counted and checked. A wrapped literal naming an
    # unregistered flag and a wrapped non-literal are both found, each at the line its `isEnabled(` starts on; a wrapped
    # valid read still counts as the read that a registered web flag needs. Line 2 and line 6 are those of the file
    # written below. A line-by-line scan returns nothing for these and reports the web flag as unread instead.
    api, web = tree(tmp_path, bad=False)
    (web / "app" / "page.tsx").unlink()
    write(
        web,
        "app/wrapped.tsx",
        'const ok = isEnabled(\n  "demo.web_only",\n  { metro },\n);\n'
        'const bad = isEnabled(\n  "demo.nope",\n  { metro },\n);\n'
        "const dynamic = isEnabled(\n  someName,\n);\n",
    )
    problems = hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=None)
    assert len(problems) == 2, problems
    assert any("app/wrapped.tsx:5" in p and "'demo.nope'" in p for p in problems)
    assert any("app/wrapped.tsx:9" in p and "string literal" in p for p in problems)


def test_a_flag_read_that_bypasses_is_enabled_is_a_problem(tmp_path: Path) -> None:
    # Proves (C3.1-T12, C3.1-D18, C3.1-CR1-2): `is_enabled("<literal>")` is the only read the scan can check, so
    # the other ways to read a flag are reported rather than missed: `read_flag` and `resolve_value` called outside
    # `app/flags.py`, and `is_enabled` imported under another name. The control line (a plain `is_enabled` read of a
    # registered flag) is not reported.
    api, web = tree(tmp_path, bad=False)
    write(
        api,
        "app/sneaky.py",
        "from app.flags import is_enabled as on\n"
        "A = on('demo.python_only')\n"
        "B = read_flag('demo.python_only', FLAGS, os.environ)\n"
        "C = flags.resolve_value(flag, os.environ, None)\n",
    )
    problems = hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=None)
    assert len(problems) == 3, problems
    assert any("app/sneaky.py:1" in p and "alias" in p for p in problems)
    assert any("app/sneaky.py:3" in p and "read_flag" in p for p in problems)
    assert any("app/sneaky.py:4" in p and "resolve_value" in p for p in problems)


# --- The inventory in environments.md ------------------------------------------------------------------------------


def doc(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "environments.md"
    path.write_text(body)
    return path


def test_the_inventory_must_list_exactly_the_registered_variables(tmp_path: Path) -> None:
    # Proves (C3.1-T12, C3.1-D18): the inventory block is compared both ways. A registered variable missing from the
    # document (it would be set in a dashboard from memory) and a variable listed for no flag (it would be set and do
    # nothing) are each a problem; an exact match is not. Variable names are derived by hand from the two flag names.
    api, web = tree(tmp_path, bad=False)
    start, end = "<!-- flags-inventory:start -->", "<!-- flags-inventory:end -->"
    exact = doc(tmp_path, f"{start}\n| `FLAG_DEMO_PYTHON_ONLY` | x |\n| `FLAG_DEMO_WEB_ONLY` | x |\n{end}\n")
    assert hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=exact) == []
    missing = doc(tmp_path, f"{start}\n| `FLAG_DEMO_PYTHON_ONLY` | x |\n{end}\n")
    problems = hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=missing)
    assert len(problems) == 1 and "FLAG_DEMO_WEB_ONLY" in problems[0] and "missing" in problems[0]
    extra = doc(
        tmp_path, f"{start}\n| `FLAG_DEMO_PYTHON_ONLY` |\n| `FLAG_DEMO_WEB_ONLY` |\n| `FLAG_OLD_ONE` |\n{end}\n"
    )
    problems = hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=extra)
    assert len(problems) == 1 and "FLAG_OLD_ONE" in problems[0]


def test_a_document_without_the_markers_is_a_problem(tmp_path: Path) -> None:
    # Proves (C3.1-T12): deleting the markers cannot silence the inventory check; it becomes its own problem.
    api, web = tree(tmp_path, bad=False)
    problems = hygiene_problems(REGISTRY, api_root=api, web_root=web, environments_doc=doc(tmp_path, "no markers"))
    assert len(problems) == 1 and "markers" in problems[0]


def test_the_real_inventory_lists_the_first_flag() -> None:
    # Proves (C3.1-D18): the real document's block lists the one registered variable, spelled as the plan gives it.
    assert inventory_variables(ENVIRONMENTS_DOC) == {"FLAG_WORKER_SCHEDULED_RUNS"}
