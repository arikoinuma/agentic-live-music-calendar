"""Tests for `agent_worker/snapshots.py`: where a fetched page is stored, and what a failed write says (C9).

HOW TO READ THIS
  C9 stores each fetched venue page in a Cloudflare R2 bucket and records the object's key on the fetch row
  (`audit_log.snapshot_key`). `snapshots.py` is the only module that talks to R2, through boto3's `s3` client. None
  of these tests reaches a network:

    * the `s3` adapter is driven through botocore's `Stubber`, which checks every call against the `s3` service model and
      raises `StubAssertionError` when a request does not match the one the test expected (verified in a scratch run on
      November 18, 2026, C9-PR1 Context), so a wrong parameter name, a missing `Bucket` or a different key turns a test
      red without a bucket existing;
    * the one failure family `Stubber` cannot produce, a `BotoCoreError` (the network dropped), is raised from a
      `before-send.s3.PutObject` handler on a client that does not retry (C9-PR1-8), because botocore's standard retry
      mode would otherwise try the call four times, 2.7 seconds, before giving up.

  Expected values are written here by hand (the key strings, the byte lengths from `hashlib`, the classification pairs),
  never read from the function under test, so a function that is wrong cannot also make its own test right.

  The two key points are `C9-K1` (`snapshot_key_for`) and `C9-K2` (the `except` in `S3SnapshotStore.put`). Their tests
  are T1 and the `_raises_snapshot_error` tests, named so a single `-k` selects each one's tests (pytest keeps only
  the LAST `-k`, C9-PR1-9).

docs/dev/implementations/c9-r2-snapshots.md, C9-D1, C9-D4, C9-D5, C9-D6, C9-D7, C9-D8, C9-D14; C9-T1 to C9-T7, C9-T15.
"""

import ast
import datetime
import hashlib
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ParamValidationError,
    ReadTimeoutError,
)
from botocore.stub import Stubber

from agent_worker import snapshots
from agent_worker.snapshots import (
    NoSnapshotStore,
    S3SnapshotStore,
    SnapshotError,
    SnapshotRef,
    classify_snapshot_error,
    make_s3_client,
    snapshot_config_problem,
    snapshot_key_for,
)
from app.config import AppEnv

BUCKET = "pebblebeats-snapshots-staging"
ENDPOINT = "https://0123456789abcdef.r2.cloudflarestorage.com"
SECRET = "super-secret-key-material-9f8e7d"
DAY = datetime.date(2026, 11, 18)
# A page with a non-ASCII character, so the byte length is not the string length (C9-T2).
PAGE = "<html><body>Café Lena: Jazz Night</body></html>"


def build_client(*, retries: int = 0) -> Any:
    """A real boto3 `s3` client pointed at a fake endpoint, which never sends anything.

    Used where a test needs a client it can wrap in a `Stubber` or hang an event handler on. `retries=0` turns
    botocore's retrying off, so a raising handler fails at once instead of four times (C9-PR1-8).
    """
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="auto",
        aws_access_key_id="test-key-id",
        aws_secret_access_key=SECRET,
        config=Config(retries={"max_attempts": retries}),
    )


def stubbed() -> tuple[S3SnapshotStore, Stubber]:
    """An `S3SnapshotStore` over a stubbed client, and the stubber that scripts its answers."""
    client = build_client()
    stubber = Stubber(client)
    return S3SnapshotStore(client, BUCKET), stubber


def a_client_error(code: str, status: int) -> Any:
    """A botocore `ClientError` as R2 would answer it: an error code, a message and an HTTP status."""
    response = {
        "Error": {"Code": code, "Message": "refused"},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }
    return ClientError(response, "PutObject")  # type: ignore[arg-type]  # a plain dict is what botocore builds


# ---------------------------------------------------------------------------
# The key (C9-T1, C9-D5, C9-K1)
# ---------------------------------------------------------------------------


def test_snapshot_key_for_is_the_fetch_rows_identity() -> None:
    # Proves (C9-T1, C9-D5, C9-K1): the key is built from which venue, which date and which run, as
    # `venues/<venue_id>/<date>-run-<run_id>.html`. The expected string is written by hand, so a function that builds
    # a different layout cannot also make this test pass. If it returned a content hash, two unchanged pages would
    # share one object and "one key per fetch row" would break.
    assert snapshot_key_for(3, DAY, 412) == "venues/3/2026-11-18-run-412.html"


def test_snapshot_keys_never_collide_and_sort_by_date_within_a_venue() -> None:
    # Proves (C9-T1, C9-D5): two venues, two dates and two runs each give a different key; the key has no leading slash
    # (a different object that a dashboard shows under an empty folder name) and ends `.html`; and within one venue
    # the keys sort by date, so a listing of the prefix reads as a timeline.
    keys = [
        snapshot_key_for(1, DAY, 5),
        snapshot_key_for(2, DAY, 5),
        snapshot_key_for(1, DAY + datetime.timedelta(days=1), 5),
        snapshot_key_for(1, DAY, 6),
    ]
    assert len(set(keys)) == 4
    assert all(not key.startswith("/") and key.endswith(".html") for key in keys)
    same_venue = [snapshot_key_for(1, DAY + datetime.timedelta(days=n), 9) for n in (2, 0, 1)]
    assert sorted(same_venue) == [
        "venues/1/2026-11-18-run-9.html",
        "venues/1/2026-11-19-run-9.html",
        "venues/1/2026-11-20-run-9.html",
    ]


# ---------------------------------------------------------------------------
# What a successful write sends (C9-T2, C9-D4, C9-D7)
# ---------------------------------------------------------------------------


async def test_put_makes_one_put_object_with_the_page_and_its_hash() -> None:
    # Proves (C9-T2, C9-D4, C9-D7): `put` makes exactly one `put_object` with the bucket, the key, the page as UTF-8
    # bytes, the HTML content type and the SHA-256 as user metadata, and returns the key, the byte length and the
    # hash. The expected values come from this test's own page string and `hashlib`, not from the code under test.
    # The page has a non-ASCII character, so the length asserted is the BYTE length (`len(PAGE)` would be one short).
    store, stubber = stubbed()
    body = PAGE.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    stubber.add_response(
        "put_object",
        {},
        expected_params={
            "Bucket": BUCKET,
            "Key": "venues/3/2026-11-18-run-412.html",
            "Body": body,
            "ContentType": "text/html; charset=utf-8",
            "Metadata": {"sha256": digest},
        },
    )
    with stubber:
        ref = await store.put(venue_id=3, fetched_on=DAY, run_id=412, page=PAGE)
        stubber.assert_no_pending_responses()
    assert ref == SnapshotRef(key="venues/3/2026-11-18-run-412.html", bytes=len(body), sha256=digest)
    assert ref.bytes == len(PAGE) + 1  # "é" is two bytes in UTF-8


async def test_put_with_no_run_id_is_a_bug_not_a_venues_failure() -> None:
    # Proves (C9-T2, C9-D4): a real store given `run_id=None` raises `ValueError`, not `SnapshotError`. A missing run
    # id is a bug in OUR code (every worker fetch has one), and `SnapshotError` would be filed as "the venue failed" and
    # skipped by `main.RUN_ERRORS`, hiding it. No call reaches the client: the stubber has none scripted, so one would fail.
    store, stubber = stubbed()
    with stubber, pytest.raises(ValueError, match="run_id"):
        await store.put(venue_id=3, fetched_on=DAY, run_id=None, page=PAGE)


# ---------------------------------------------------------------------------
# A failed write raises, with its kind (C9-T3, C9-D1, C9-D14, C9-K2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status", "kind"),
    [("AccessDenied", 403, "auth"), ("InternalError", 500, "transient")],
)
async def test_a_refused_put_raises_snapshot_error(code: str, status: int, kind: str) -> None:
    # Proves (C9-T3, C9-K2, C9-D1, C9-D14): a `ClientError` from R2 becomes a `SnapshotError` that names the key, carries
    # the error's code and its kind, and is NEVER swallowed into a `None` return. `None` already means "no store is
    # configured", so a failed put that returned it would leave a fetch row saying a page was fetched with nothing behind
    # it. The message must not hold the secret key (it holds the endpoint, an account identifier, not a credential).
    store, stubber = stubbed()
    stubber.add_client_error("put_object", service_error_code=code, service_message="refused", http_status_code=status)
    with stubber, pytest.raises(SnapshotError) as raised:
        await store.put(venue_id=3, fetched_on=DAY, run_id=412, page=PAGE)
    error = raised.value
    assert "venues/3/2026-11-18-run-412.html" in str(error)
    assert (error.kind, error.code) == (kind, code)
    assert SECRET not in str(error)


async def test_a_dropped_connection_raises_snapshot_error() -> None:
    # Proves (C9-T3, C9-K2, C9-D14): the SECOND failure family, a `BotoCoreError` (the network dropped before R2
    # answered), is caught by the same `except` and raised as a `SnapshotError` of kind `transient` with no code. `Stubber`
    # cannot script one, so a `before-send` handler raises it; the client does not retry, or the test would take 2.7 s.
    client = build_client(retries=0)

    def drop(**_: Any) -> None:
        raise EndpointConnectionError(endpoint_url=ENDPOINT)

    client.meta.events.register("before-send.s3.PutObject", drop)
    store = S3SnapshotStore(client, BUCKET)
    with pytest.raises(SnapshotError) as raised:
        await store.put(venue_id=3, fetched_on=DAY, run_id=412, page=PAGE)
    assert (raised.value.kind, raised.value.code) == ("transient", None)
    assert "venues/3/2026-11-18-run-412.html" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_snapshot_error_describes_itself_for_the_fetch_row() -> None:
    # Proves (C9-D14): the dict the fetch row stores as `detail.snapshot_error` has exactly the keys `kind`, `code` and
    # `message`, which is what `docs/dev/audit-queries.sql` reads. The literal is written here from the plan.
    error = SnapshotError("could not store k", kind="auth", code="AccessDenied")
    assert error.as_detail() == {"kind": "auth", "code": "AccessDenied", "message": "could not store k"}


# ---------------------------------------------------------------------------
# The client main builds (C9-T4, C9-D7, C9-U1)
# ---------------------------------------------------------------------------


def test_the_client_is_built_the_way_c9_d7_says() -> None:
    # Proves (C9-T4, C9-D7, C9-U1): the client has the R2 endpoint, `region_name="auto"`, both checksum options set to
    # `when_required` (boto3's default, `when_supported`, adds a CRC32 header that reports say R2 answered with 501),
    # botocore's standard retry mode reading back as four attempts in all, and the two timeouts. `retries` reads back
    # as botocore's normalized dict, not the one passed in (C9-PR1-7). A stub cannot prove R2 accepts the option; the
    # first hosted write (C9-U1, Step 9) does.
    client = make_s3_client(endpoint_url=ENDPOINT, access_key_id="test-key-id", secret_access_key=SECRET)
    assert client.meta.endpoint_url == ENDPOINT
    assert client.meta.region_name == "auto"
    config = client.meta.config
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"
    assert config.retries == {"mode": "standard", "total_max_attempts": 4}
    assert (config.connect_timeout, config.read_timeout) == (5, 20)


# ---------------------------------------------------------------------------
# The preflight (C9-T5, C9-D8)
# ---------------------------------------------------------------------------


async def test_check_reads_one_key_from_the_bucket() -> None:
    # Proves (C9-T5, C9-D8): the startup preflight is one `list_objects_v2` with `MaxKeys=1` against the bucket, the one
    # call that proves the endpoint, the token and the bucket together (C9-U3). `head_bucket` is not used: R2's docs
    # promise an Object token can list, and say nothing of `HeadBucket`.
    store, stubber = stubbed()
    stubber.add_response("list_objects_v2", {}, expected_params={"Bucket": BUCKET, "MaxKeys": 1})
    with stubber:
        await store.check()
        stubber.assert_no_pending_responses()


async def test_a_refused_check_raises_snapshot_error_with_its_kind() -> None:
    # Proves (C9-T5, C9-D8, C9-D14): a bucket that does not exist makes the preflight raise a `SnapshotError` of kind
    # `config`, so `main` can log WHAT was wrong (a wrong bucket name) and exit 2 before any venue is fetched.
    store, stubber = stubbed()
    stubber.add_client_error(
        "list_objects_v2", service_error_code="NoSuchBucket", service_message="gone", http_status_code=404
    )
    with stubber, pytest.raises(SnapshotError) as raised:
        await store.check()
    assert (raised.value.kind, raised.value.code) == ("config", "NoSuchBucket")


# ---------------------------------------------------------------------------
# The default store (C9-D2, C9-D6)
# ---------------------------------------------------------------------------


async def test_the_default_store_writes_nothing_and_says_so() -> None:
    # Proves (C9-D2, C9-D6): `NoSnapshotStore.put` returns `None` (no store configured: a laptop, the eval harness, the
    # tests) whatever it is given, including a missing run id, and its preflight does nothing. Every existing
    # `WorkerContext` gets this default, which is why no existing test changes.
    store = NoSnapshotStore()
    assert await store.put(venue_id=1, fetched_on=DAY, run_id=None, page=PAGE) is None
    await store.check()  # returns nothing and raises nothing


# ---------------------------------------------------------------------------
# The configuration check (C9-T6, C9-D2, C9-D8)
# ---------------------------------------------------------------------------

# (id, app_env, endpoint, key_id, secret, bucket, expected: None for fine, or the variable the sentence must name)
CONFIG_CASES: list[tuple[str, AppEnv, str | None, str | None, str | None, str | None, str | None]] = [
    ("hosted-with-all-four", "staging", ENDPOINT, "id", "s", BUCKET, None),
    ("hosted-without-an-endpoint", "staging", None, "id", "s", BUCKET, "R2_ENDPOINT_URL"),
    ("hosted-without-a-key-id", "staging", ENDPOINT, None, "s", BUCKET, "R2_ACCESS_KEY_ID"),
    ("hosted-without-a-secret", "prod", ENDPOINT, "id", None, BUCKET, "R2_SECRET_ACCESS_KEY"),
    ("hosted-without-a-bucket", "dev", ENDPOINT, "id", "s", None, "R2_BUCKET"),
    ("hosted-with-none", "staging", None, None, None, None, "R2_"),
    ("hosted-with-a-blank-secret", "staging", ENDPOINT, "id", "  ", BUCKET, "R2_SECRET_ACCESS_KEY"),
    ("local-with-none-is-off", "local", None, None, None, None, None),
    ("local-with-blanks-is-off", "local", "", " ", "", "", None),
    ("local-with-some", "local", ENDPOINT, "id", None, None, "R2_SECRET_ACCESS_KEY"),
    ("local-with-all-four-is-on", "local", ENDPOINT, "id", "s", "pebblebeats-snapshots-local", None),
    ("hosted-with-a-non-https-endpoint", "staging", "http://r2.example", "id", "s", BUCKET, "https"),
    ("hosted-with-a-bare-host-endpoint", "staging", "r2.example.com", "id", "s", BUCKET, "https"),
]


@pytest.mark.parametrize(
    ("app_env", "endpoint", "key_id", "secret", "bucket", "names"),
    [case[1:] for case in CONFIG_CASES],
    ids=[case[0] for case in CONFIG_CASES],
)
def test_snapshot_config_problem(
    app_env: AppEnv,
    endpoint: str | None,
    key_id: str | None,
    secret: str | None,
    bucket: str | None,
    names: str | None,
) -> None:
    # Proves (C9-T6, C9-D2, C9-D8): a hosted worker needs all four R2 settings and says which one is missing; a laptop with
    # none runs with snapshots off, a laptop with some but not all is a mistake (it would silently run off), and with
    # all four it runs on; a blank value counts as unset; and an endpoint that is not `https://…` is refused, because
    # boto3 raises a bare `ValueError` on a malformed URL, outside `RUN_ERRORS` and outside the exit 2 (C9-PR1-11). A row
    # that expects a problem names the variable (or `https`) its sentence must mention, written here from the plan.
    problem = snapshot_config_problem(app_env, endpoint, key_id, secret, bucket)
    if names is None:
        assert problem is None
    else:
        assert problem is not None and names in problem


# ---------------------------------------------------------------------------
# Classifying a failure (C9-T15, C9-D14)
# ---------------------------------------------------------------------------


def classification_cases() -> list[tuple[str, BaseException, tuple[str, str | None]]]:
    """(id, the error, the (kind, code) it must classify as): every pair written by hand from the plan's mapping."""
    endpoint = {"endpoint_url": ENDPOINT}
    return [
        ("access-denied", a_client_error("AccessDenied", 403), ("auth", "AccessDenied")),
        ("invalid-key-id", a_client_error("InvalidAccessKeyId", 403), ("auth", "InvalidAccessKeyId")),
        ("bad-signature", a_client_error("SignatureDoesNotMatch", 403), ("auth", "SignatureDoesNotMatch")),
        ("expired-token-at-400", a_client_error("ExpiredToken", 400), ("auth", "ExpiredToken")),
        ("unknown-code-at-403", a_client_error("SomethingNew", 403), ("auth", "SomethingNew")),
        ("no-such-bucket", a_client_error("NoSuchBucket", 404), ("config", "NoSuchBucket")),
        ("invalid-bucket-name", a_client_error("InvalidBucketName", 400), ("config", "InvalidBucketName")),
        ("internal-error", a_client_error("InternalError", 500), ("transient", "InternalError")),
        ("slow-down", a_client_error("SlowDown", 503), ("transient", "SlowDown")),
        ("unknown-code-at-500", a_client_error("SomethingNew", 500), ("transient", "SomethingNew")),
        ("unknown-code-at-400", a_client_error("SomethingNew", 400), ("other", "SomethingNew")),
        ("endpoint-unreachable", EndpointConnectionError(**endpoint), ("transient", None)),
        ("connect-timeout", ConnectTimeoutError(**endpoint), ("transient", None)),
        ("read-timeout", ReadTimeoutError(**endpoint), ("transient", None)),
        ("connection-closed", ConnectionClosedError(**endpoint), ("transient", None)),
        ("bad-parameters", ParamValidationError(report="bad"), ("other", None)),
    ]


@pytest.mark.parametrize(
    ("error", "expected"),
    [case[1:] for case in classification_cases()],
    ids=[case[0] for case in classification_cases()],
)
def test_classify_snapshot_error(error: BaseException, expected: tuple[str, str | None]) -> None:
    # Proves (C9-T15, C9-D14): the kind and code of each failure follow the plan's mapping, so a later retry policy can
    # tell a transient failure (worth retrying) from an auth one (never). The `other` rows pin the safe direction: an
    # unrecognized code at a 4xx is never read as worth retrying. A real R2 failure that lands in `other` is the signal to
    # refine the table (the mapping is AWS's codes guessed onto R2's).
    assert classify_snapshot_error(error) == expected


# ---------------------------------------------------------------------------
# Layering (C9-T7, C9-D6)
# ---------------------------------------------------------------------------


def test_snapshots_imports_nothing_above_it() -> None:
    # Proves (C9-T7, C9-D6): `snapshots.py` takes plain arguments (a venue id, a date, a run id, the page text) and
    # imports none of `state`, `audit`, `trace`, `context` or `main`, so the import order stays a DAG
    # (`snapshots` <- `audit` <- `context` <- `trace`; apps/api/AGENTS.md). Read from the source with `ast`, so a lazy
    # import inside a function is caught too, which `sys.modules` after an import would miss.
    source = Path(snapshots.__file__).read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    above = {
        "agent_worker.state",
        "agent_worker.audit",
        "agent_worker.trace",
        "agent_worker.context",
        "agent_worker.main",
    }
    assert imported & above == set()


async def test_the_secret_never_reaches_a_check_error() -> None:
    # Proves (C9-D14): the preflight's failure message, like the put's, never contains the secret key. A stubbed
    # `AccessDenied` is raised from `check`, and the text that would reach the log is searched for the secret.
    store, stubber = stubbed()
    stubber.add_client_error("list_objects_v2", service_error_code="AccessDenied", http_status_code=403)
    with stubber, pytest.raises(SnapshotError) as raised:
        await store.check()
    assert SECRET not in str(raised.value)
