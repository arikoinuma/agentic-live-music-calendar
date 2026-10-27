"""Core calendar tables: metro, venue, event, show, artist, show_artist.

HOW THE TABLES RELATE (read this first)
  metro  1 --- *  venue  1 --- *  show  * --- 1  event (optional: festivals)
                                   |
                                   * show_artist *
                                                 |
                                               artist (global, not per-metro)
  A metro is a city region. A venue belongs to one metro and has a calendar
  page the agent reads. A show is one event on one date at one venue. A
  show's lineup is the set of artists linked through show_artist. An event
  groups several shows (a festival) and isn't shown in the v1 UI.

  Each class below is a table; each attribute is a column. `Mapped[X | None]`
  means nullable; plain `Mapped[X]` means NOT NULL.

Columns, types, nullability and defaults follow docs/arch/data-model-initial.md
section 2. Departures from it are listed in
docs/dev/implementations/a1-data-layer.md; the ones that live in this file:

* `Numeric(10, 2)` for prices where the doc says plain `Numeric` — an exact
  money type with a sane scale.
* An extra index on `show (venue_id, date)`, which the doc doesn't list.
* `show.date` keeps its name despite the repo's `_date` suffix rule for
  dates, because the data model and the API contract both call it `date`.
* Four read-only `relationship()`s, added in C2 with their first consumer, the read API
  (`app/queries.py`): `Venue.metro`, `Show.venue`, `Show.event` and `Show.lineup`, plus
  `ShowArtist.artist`. All are `viewonly=True, lazy="raise"` (C2-D4). The product never
  deletes a row (`Show.status` is a soft delete) and the worker writes through explicit
  foreign keys (A6), so a relationship that can only be read cannot change what the worker
  writes, and there is no cascade to choose. `lazy="raise"` turns an implicit lazy load,
  which under asyncio is a `MissingGreenlet` at runtime, into an error naming the attribute
  in the first test: every query says what it loads. The first thing that wants to write
  through the object graph (an admin edit API) revisits both settings.

`import datetime` rather than `from datetime import date`: inside `Show`, the
attribute named `date` would shadow the type in later annotations.
"""

import datetime
import decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import types
from app.db.base import Base, TimestampMixin
from app.enums import (
    AgeRestriction,
    ArtistFormat,
    ArtistRepertoire,
    FetchStrategy,
    Seating,
    Setting,
    ShowStatus,
    VenueType,
)


class Metro(TimestampMixin, Base):
    """A metropolitan area. Venues are scoped to one; artists are not."""

    __tablename__ = "metro"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    # IANA name. Drives the per-metro 4 a.m. agent trigger and the calendar
    # rendering in the metro's zone rather than the browser's.
    timezone: Mapped[str]


class Venue(TimestampMixin, Base):
    """A place that hosts shows, and the page the agent reads to find them.

    `calendar_url` and `fetch_strategy` are what the agent worker uses;
    the rest is display metadata for the venue's page in the UI.
    """

    __tablename__ = "venue"
    __table_args__ = (
        # GIN so `extra_metadata @> '{...}'` filters stay indexed while a
        # speculative field is still living in the JSONB blob, before it
        # graduates to a real column (data-model-initial.md section 1).
        # name=None: the `ix` naming convention names it venue_extra_metadata_idx.
        Index(None, "extra_metadata", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    metro_id: Mapped[int] = mapped_column(ForeignKey("metro.id"))
    name: Mapped[str]
    # The live-music calendar page the agent fetches and extracts from. Required:
    # without it there is nothing for the agent to do for this venue.
    calendar_url: Mapped[str]
    # A link to a photo hosted elsewhere; we don't store images.
    photo_url: Mapped[str | None]
    address: Mapped[str | None] = mapped_column(Text)
    # Plain arrays rather than child tables: entries carry no per-entry metadata.
    phone_numbers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    emails: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    website: Mapped[str | None]
    # Venue-level defaults. A show with NULL here means "inherit"; the read
    # API resolves that server-side (api-contract.md section 5).
    age_restriction: Mapped[AgeRestriction | None] = mapped_column(types.AGE_RESTRICTION)
    serves_alcohol: Mapped[bool | None]
    venue_type: Mapped[VenueType | None] = mapped_column(types.VENUE_TYPE)
    setting: Mapped[Setting | None] = mapped_column(types.SETTING)
    seating: Mapped[Seating | None] = mapped_column(types.SEATING)
    # Server-side default so a raw INSERT (or the seed, or a future admin
    # tool) gets 'http' without having to know about it.
    fetch_strategy: Mapped[FetchStrategy] = mapped_column(
        types.FETCH_STRATEGY, server_default=FetchStrategy.HTTP.value
    )
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Read-only, never lazy (C2-D4, module docstring): the venue detail route names it in its query.
    metro: Mapped[Metro] = relationship(viewonly=True, lazy="raise")


class Artist(TimestampMixin, Base):
    """A performer. Created by the agent as a name-only record when a listing
    mentions someone new, and enriched later."""

    __tablename__ = "artist"
    __table_args__ = (Index(None, "extra_metadata", postgresql_using="gin"),)

    # Global, not metro-scoped: artists tour between markets.
    id: Mapped[int] = mapped_column(primary_key=True)
    # The only required field. Reconcile matches incoming listings to artists
    # by this name (build plan A5).
    name: Mapped[str]
    photo_url: Mapped[str | None]
    website: Mapped[str | None]
    # Free text on purpose — not an FK to `metro`.
    hometown: Mapped[str | None] = mapped_column(Text)
    # solo / duo / trio / band: describes the act itself, not one night's
    # lineup (a solo artist with a backing band is still "solo").
    format: Mapped[ArtistFormat | None] = mapped_column(types.ARTIST_FORMAT)
    # original / cover / both: a fixed list, deliberately not free-form tags.
    repertoire: Mapped[ArtistRepertoire | None] = mapped_column(types.ARTIST_REPERTOIRE)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Event(TimestampMixin, Base):
    """Parent of several shows (a festival). Not a v1 UI surface.

    "Must have more than one show" is an application-layer invariant, not a
    constraint — a CHECK can't express "at least two rows in a child table".
    """

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    # Derived: min/max of the member shows' dates. Recomputed when a member
    # show's date changes; never independently edited.
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)


class Show(TimestampMixin, Base):
    __tablename__ = "show"
    __table_args__ = (
        # data-model-initial.md section 2: mirrors the internal-consistency
        # rule agents validate against. NULL free_admission passes (NOT of
        # NULL is NULL, which a CHECK accepts) — absence of a price does not
        # imply free, and a price doesn't contradict "not stated".
        # `name=` is mandatory under the `ck` naming convention; this one
        # renders as show_free_admission_check.
        CheckConstraint(
            "NOT (free_admission AND (admission_advance IS NOT NULL OR admission_day IS NOT NULL))",
            name="free_admission",
        ),
        # Reconcile's composite-key lookup (venue, date, time) and every
        # calendar range query filter on exactly these two columns. Not
        # speculative: A5 and the read API both consume it. The convention
        # names it show_venue_id_idx, which only mentions the first column.
        Index(None, "venue_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venue.id"))
    # NULL for an ordinary standalone show; set when the show belongs to a
    # festival-style Event.
    event_id: Mapped[int | None] = mapped_column(ForeignKey("event.id"))
    # The only field the spec requires of a show. Start time may be unknown.
    date: Mapped[datetime.date] = mapped_column(Date)
    start_time: Mapped[datetime.time | None] = mapped_column(Time)
    # Left blank if the listing is unclear.
    end_time: Mapped[datetime.time | None] = mapped_column(Time)
    # NULL on these four means "use the venue's value".
    age_restriction: Mapped[AgeRestriction | None] = mapped_column(types.AGE_RESTRICTION)
    serves_alcohol: Mapped[bool | None]
    setting: Mapped[Setting | None] = mapped_column(types.SETTING)
    seating: Mapped[Seating | None] = mapped_column(types.SEATING)
    # Ticket price bought ahead vs. at the door. All-NULL means "not stated",
    # never "free": free is only ever the explicit `free_admission` flag
    # below (api-contract.md section 5).
    admission_advance: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    admission_day: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    # True only if the listing says so explicitly. The CHECK constraint
    # above forbids True together with a price.
    free_admission: Mapped[bool | None]
    # The show's poster image, if the listing has one.
    image_url: Mapped[str | None]
    # The page this show was most recently extracted from; overwritten on
    # each successful reconcile. History lives in audit_log, not here.
    original_url: Mapped[str | None] = mapped_column(Text)
    # Soft delete: a show absent from a later fetch, within the date range
    # that fetch covered, becomes 'removed' — never deleted.
    status: Mapped[ShowStatus] = mapped_column(
        types.SHOW_STATUS, server_default=ShowStatus.ACTIVE.value
    )

    # Read-only, never lazy (C2-D4, module docstring). `lineup` is unordered here on purpose: the
    # read API sorts it in Python (C2-D5), because a database collation is not a rule the tests state.
    venue: Mapped[Venue] = relationship(viewonly=True, lazy="raise")
    event: Mapped[Event | None] = relationship(viewonly=True, lazy="raise")
    lineup: Mapped[list["ShowArtist"]] = relationship(viewonly=True, lazy="raise")


class ShowArtist(Base):
    """A show's lineup. No timestamps: a pure join (data-model-initial.md section 1)."""

    __tablename__ = "show_artist"

    show_id: Mapped[int] = mapped_column(ForeignKey("show.id"), primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artist.id"), primary_key=True)
    # This artist's own set time, distinct from show.start_time.
    start_time: Mapped[datetime.time | None] = mapped_column(Time)
    # Performance order; if the listing doesn't say, the agent infers it from
    # listing order (requirements-initial.md, "Agent Extraction: Fields").
    sequence_number: Mapped[int | None] = mapped_column(Integer)

    artist: Mapped[Artist] = relationship(viewonly=True, lazy="raise")
