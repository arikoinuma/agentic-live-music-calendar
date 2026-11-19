"""Page snapshots: the HTML of each fetched venue page, stored in Cloudflare R2, and what a failed write says (C9).

HOW TO READ THIS
  The fetch step reads a venue's page and keeps it in memory (`state.page_html`). Without a snapshot the page is gone
  the moment the process exits, and for a show read straight from the page's structured data the model is sent almost
  nothing, so nothing else records what the page said. C9 writes the page to an R2 bucket and records the object's key
  on the fetch row (`audit_log.snapshot_key`), so a person can go from a calendar row to its audit rows to the page
  they came from (docs/dev/implementations/c9-r2-snapshots.md, Context).

  The module is small, in this order:

    * `SnapshotRef` is what a successful write returns: the key, the byte length and the SHA-256 of exactly the bytes
      uploaded. The fetch row records all three, so "this row resolves to the page it fetched" is checkable by
      re-hashing the downloaded object, without trusting the filename (C9-D4).
    * `SnapshotError` is the ONE exception a failed write raises, with a `kind` and a `code` (C9-D14), so the rest of
      the worker never imports botocore: `main.RUN_ERRORS` can treat it as "this venue failed" and not a crash.
      `classify_snapshot_error` decides the kind, as a pure function.
    * `SnapshotStore` is the interface the graph writes through (`trace.audited`, C9-D6); `NoSnapshotStore` is the
      default that writes nothing (a laptop, the eval harness, almost every test); `S3SnapshotStore` is the real one.
    * `snapshot_key_for` (C9-K1) is the key. `make_s3_client` builds the boto3 client; the options
      are C9-D7's. `snapshot_config_problem` is the pure check `main` runs before anything connects (C9-D8).

  **This module imports none of `state`, `audit`, `trace`, `context` or `main`** (a test enforces it, C9-T7): the store
  takes plain arguments, so `audit.py` can import `SnapshotRef` from here and the import order stays one-way
  (`snapshots` <- `audit` <- `context` <- `trace`).

  boto3 is synchronous, so each call runs in `asyncio.to_thread`, off the event loop the database and MongoDB
  clients live on (C9-D7; A4-D1).

docs/dev/implementations/c9-r2-snapshots.md, C9-D1, C9-D4, C9-D5, C9-D6, C9-D7, C9-D8, C9-D13, C9-D14.
"""

import asyncio
import datetime
import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from app.config import AppEnv

# ---------------------------------------------------------------------------
# What a write returns, and what a failed one raises
# ---------------------------------------------------------------------------

# What kind of failure a write was (C9-D14). Nothing acts on the kind yet (C9-D1: every kind stops that venue's run);
# it is recorded so a later retry policy (C9-DF1) can retry a `transient` one and never an `auth` one, and so the audit
# queries can group failures by it.
SnapshotErrorKind = Literal["transient", "auth", "config", "other"]


@dataclass(frozen=True)
class SnapshotRef:
    """A stored page: the object's key, and the length and SHA-256 of the bytes that were uploaded (C9-D4)."""

    key: str
    bytes: int
    sha256: str


class SnapshotError(Exception):
    """The page could not be stored (or the bucket could not be reached): what failed, and what kind of failure.

    Raised in place of botocore's errors so that `trace.audited` and `main` never import botocore (A4-D3 made the same
    call for MongoDB). `main.RUN_ERRORS` includes it, so a venue whose page cannot be stored fails that venue and not
    the process (C9-D1).
    """

    def __init__(self, message: str, *, kind: SnapshotErrorKind, code: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code

    def as_detail(self) -> dict[str, Any]:
        """The failure as the fetch row stores it, `detail.snapshot_error`: its kind, its code and its message (C9-D14).

        The message holds the endpoint URL (which carries Cloudflare's account id, an identifier and not a
        credential) and never the secret key; `test_snapshots.py` asserts the stubbed secret is absent.
        """
        return {"kind": self.kind, "code": self.code, "message": str(self)}


# The error codes the classification below keys on. They are the AWS object API's, guessed onto R2's (C9-D14): an unknown code falls
# to `other` and is never read as transient, and the first real failure refines the table.
_AUTH_CODES = {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"}
_CONFIG_CODES = {"NoSuchBucket", "InvalidBucketName"}
_TRANSIENT_CODES = {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable"}
# botocore's connection-level failures: the network, not R2's answer. The same family `retries` already retried.
_TRANSIENT_BOTOCORE = (ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError)


def classify_snapshot_error(err: BaseException) -> tuple[SnapshotErrorKind, str | None]:
    """The `(kind, code)` of a botocore failure (C9-D14). Pure: it reads the error and nothing else.

    * `transient`: a connection or timeout error (no code), or R2 answering 500 or above, or a code that means "try
      again" (`SlowDown`, `RequestTimeout`, `InternalError`, `ServiceUnavailable`). Worth retrying.
    * `auth`: a 401 or 403, or a code that means the credential is not accepted. Never worth retrying: it needs a person.
    * `config`: the bucket does not exist or its name is invalid. Also needs a person.
    * `other`: anything else, including an error of ours (`ParamValidationError`). Not read as retryable.
    The checks run `config`, `auth`, `transient` in that order, so `NoSuchBucket` (a 404) is `config` and a 403 with a code we
    do not know is `auth`.
    """
    if isinstance(err, ClientError):
        error = err.response.get("Error", {})
        code = error.get("Code")
        status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in _CONFIG_CODES:
            return "config", code
        if code in _AUTH_CODES or status in (401, 403):
            return "auth", code
        if code in _TRANSIENT_CODES or (status is not None and status >= 500):
            return "transient", code
        return "other", code
    if isinstance(err, _TRANSIENT_BOTOCORE):
        return "transient", None
    return "other", None


# ---------------------------------------------------------------------------
# The key (C9-K1)
# ---------------------------------------------------------------------------


def snapshot_key_for(venue_id: int, fetched_on: datetime.date, run_id: int) -> str:
    """The object key for one fetch row: `venues/<venue_id>/<date>-run-<run_id>.html` (C9-D5).

    Built from the fetch row's own identity (which venue, which date, which run), never from the page's content, so
    it is recomputable from the row. The bucket is already per environment (Dep-D10), so the key carries no environment.
    """
    # The key is the fetch row's identity (which venue, which date, which run) and never the page's content (C9-D5,
    # C9-K1). A content hash would collapse an unchanged page's snapshots into one object, so "one key per fetch row"
    # would break and a future age-based expiry rule could not work; the identity also lets the key be recomputed from
    # the row alone. No leading slash (that would be a different object, shown under an empty folder name), and an
    # explicit `.isoformat()` so the date's format is what a reader sees, not a `str()` default.
    return f"venues/{venue_id}/{fetched_on.isoformat()}-run-{run_id}.html"


# ---------------------------------------------------------------------------
# The stores
# ---------------------------------------------------------------------------


class SnapshotStore(Protocol):
    """Where fetched pages are stored. The graph depends on this, not on R2 (the same shape as `Stager`)."""

    async def put(
        self, *, venue_id: int, fetched_on: datetime.date, run_id: int | None, page: str
    ) -> SnapshotRef | None:
        """Store `page` and return its reference, or `None` when no store is configured. A failure raises `SnapshotError`."""
        ...

    async def check(self) -> None:
        """Prove the store can be reached and used, or raise `SnapshotError`. Run once at start-up (C9-D8)."""
        ...


class NoSnapshotStore:
    """The store that writes nothing: a laptop with no R2 settings, the eval harness, and every test that builds a
    `WorkerContext` without one (C9-D2, C9-D6). It ignores its arguments, a missing run id included."""

    async def put(
        self, *, venue_id: int, fetched_on: datetime.date, run_id: int | None, page: str
    ) -> SnapshotRef | None:
        return None

    async def check(self) -> None:
        return None


class S3SnapshotStore:
    """The real store: one boto3 `s3` client pointed at an R2 bucket. Both calls run off the event loop (C9-D7)."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def put(
        self, *, venue_id: int, fetched_on: datetime.date, run_id: int | None, page: str
    ) -> SnapshotRef | None:
        """Upload `page` as UTF-8 HTML under `snapshot_key_for(...)` and return its reference.

        What is stored is `page` itself, the text the extractor and validator read, so a snapshot can be dropped into
        `captured_pages/` and replayed (C9-D4). The SHA-256 of the uploaded bytes goes in the returned reference and in
        the object's own metadata.
        """
        if run_id is None:
            # A bug in OUR code (every worker fetch has a run id), not a venue's failure: a `ValueError` stays outside
            # `RUN_ERRORS`, so it stops the process with a traceback instead of being filed as "the venue failed" (C9-D4).
            raise ValueError("a snapshot needs the run_id of the fetch it belongs to")
        key = snapshot_key_for(venue_id, fetched_on, run_id)
        body = page.encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType="text/html; charset=utf-8",
                Metadata={"sha256": digest},
            )
        except (BotoCoreError, ClientError) as err:
            # A failed write RAISES; it never returns `None` (C9-D1, C9-D14, C9-K2). `None` already means "no store is
            # configured", so a failed put that returned it would leave a fetch row saying a page was fetched with
            # nothing behind it. Turning botocore's two failure families (`BotoCoreError`, `ClientError`) into one
            # `SnapshotError` is also what lets `main.RUN_ERRORS` file it as a venue's failure while `trace.audited`
            # and `main` never import botocore (A4-D3 made the same call for MongoDB). The kind is read here, in the
            # same `except`, while botocore's types are still in hand. The `except` names the two families and not
            # `Exception`, so a bug in our own code is not hidden as a storage failure (apps/api/AGENTS.md).
            kind, code = classify_snapshot_error(err)
            raise SnapshotError(f"could not store {key}: {err}", kind=kind, code=code) from err
        return SnapshotRef(key=key, bytes=len(body), sha256=digest)

    async def check(self) -> None:
        """One `list_objects_v2` with `MaxKeys=1`: proves the endpoint, the token and the bucket together (C9-D8, C9-U3).

        It is `list_objects_v2` and not `head_bucket` because R2's docs promise that an Object token can list objects
        and say nothing of `HeadBucket`.
        """
        try:
            await asyncio.to_thread(self._client.list_objects_v2, Bucket=self._bucket, MaxKeys=1)
        except (BotoCoreError, ClientError) as err:
            kind, code = classify_snapshot_error(err)
            raise SnapshotError(f"could not reach bucket {self._bucket}: {err}", kind=kind, code=code) from err


def make_s3_client(*, endpoint_url: str, access_key_id: str, secret_access_key: str) -> Any:
    """The boto3 `s3` client for an R2 bucket, built once in `main` (C9-D7).

    The options, and why:
      * `region_name="auto"`: R2 has one region, spelled that way.
      * both checksum options `when_required`: boto3 1.36 and later add a CRC32 checksum header by default, which reports
        say R2 answered with `501 NotImplemented`; the option makes the client send one only when an operation requires it
        (C9-U1: harmless if R2 accepts the default, needed if it does not; the first hosted write is the check).
      * botocore's `standard` retry mode with `max_attempts=3`, which reads back as FOUR attempts in all: the call
        retries a transient error inside itself, so no `tenacity` wrapper is added. With the timeouts below the worst
        case per venue when R2 hangs is about 100 seconds, and then C9-D1's failure.
      * `connect_timeout=5`, `read_timeout=20`: an R2 that stops answering does not hold a venue's run open forever.
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=20,
        ),
    )


# ---------------------------------------------------------------------------
# The configuration check (no I/O)
# ---------------------------------------------------------------------------

_R2_NAMES = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


def snapshot_config_problem(
    app_env: AppEnv,
    endpoint_url: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    bucket: str | None,
) -> str | None:
    """What is wrong with the R2 settings, as a sentence, or `None` when snapshots can run or are deliberately off (C9-D8).

    Pure, so `main` can run it before anything connects (with the model-endpoint and MongoDB checks, before the
    scheduled-run gate: a skipped run then still proves the service is configured completely, C8-D6) and
    `test_snapshots.py` can drive it as a table. The rules:
      * a HOSTED environment needs all four, and the sentence names the missing ones;
      * a laptop (`local`) with none runs with snapshots off (C9-D2); with some but not all it is a mistake, because it
        would silently run off; with all four it runs on;
      * a blank value counts as unset;
      * the endpoint must be `https://…`: boto3 raises a bare `ValueError` on a malformed URL, outside `RUN_ERRORS` and
        outside the exit 2 (C9-PR1-11).
    The bucket NAME rule (a hosted bucket ends `-<app_env>`) is `config.environment_problem`'s (C9-D9), at `Settings` build.
    """
    values = (endpoint_url, access_key_id, secret_access_key, bucket)
    missing = [name for name, value in zip(_R2_NAMES, values, strict=True) if not value or not value.strip()]
    if len(missing) == len(_R2_NAMES) and app_env == "local":
        return None  # snapshots off on a laptop
    if missing:
        names = ", ".join(missing)
        verb = "is" if len(missing) == 1 else "are"
        if app_env == "local":
            return f"{names} {verb} not set: set all four R2 settings to store page snapshots here, or none to leave them off"
        return (
            f"APP_ENV={app_env} but {names} {verb} not set: page snapshots need all four R2 settings (see .env.example)"
        )
    if endpoint_url is not None and not endpoint_url.strip().lower().startswith("https://"):
        return "R2_ENDPOINT_URL must start with https:// (it is https://<account id>.r2.cloudflarestorage.com)"
    return None
