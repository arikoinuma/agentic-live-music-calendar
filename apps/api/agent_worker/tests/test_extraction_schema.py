"""Tests for the extraction schema (`agent_worker/schemas.py`) and its time normalizer.

The schema is what the model is asked to fill in, so these tests pin two things at once:
what Pydantic will *accept* from a model (the validation behaviour), and what the model is
*told* (the JSON schema and field descriptions `instructor` sends in the request). Neither
needs a model: nothing here makes a network call, so the file is fast and runs in CI.

Where the expected values come from: the field list and its rules are taken from
docs/arch/requirements-initial.md "Agent Extraction: Fields" and the design in
docs/dev/implementations/a2-extraction-schema.md (Design, Test approach) — not read back
from the schema under test, so a schema that drifts from the requirements fails here.

How to read it: sections run schema shape -> optionality -> admission -> acts ->
descriptions -> time normalizer -> round trips.
"""

import datetime
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from agent_worker.schemas import ActExtraction, ShowExtraction, VenuePageExtraction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def minimal_show(**overrides: Any) -> dict[str, Any]:
    """The smallest payload a model could send for one show: only the required fields.

    Overrides replace or add fields. Used wherever a test needs a valid show and only
    cares about one field of it.
    """
    show: dict[str, Any] = {
        "venue": "The Test Room",
        "date": "2026-08-17",
        "acts": [{"name": "Band A"}],
        "is_ambiguous": False,
        "confidence": 0.9,
    }
    show.update(overrides)
    return show


def validate_field(model: type[BaseModel], name: str, value: Any) -> Any:
    """Validate `value` through ONE field of `model`, alone — its type, its
    `BeforeValidator`s and its constraints — without building the whole model.

    Why not just construct the model: a model needs valid `acts` etc. around the field
    under test, so a failure in an unrelated field (e.g. a TODO still open) would make
    this field's test fail for the wrong reason. Rebuilding the field's own
    `Annotated[type, *metadata]` isolates it, and lets one parametrized table of time
    spellings run against all three time fields.
    """
    info = model.model_fields[name]
    # `Annotated[T]` with no metadata is itself an error, so a field with no constraints
    # or validators (the old, pre-A2 `time`) is validated by its bare type.
    field_type: Any = Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation
    return TypeAdapter(field_type).validate_python(value)


# The three fields that hold a clock time: when the music starts, when it ends, and one
# act's own set time. The normalizer must apply to all of them (a lenient field next to
# a strict one is the bug this guards).
TIME_FIELDS = [
    pytest.param(ShowExtraction, "time", id="show.time"),
    pytest.param(ShowExtraction, "end_time", id="show.end_time"),
    pytest.param(ActExtraction, "start_time", id="act.start_time"),
]

# ---------------------------------------------------------------------------
# Schema shape: what the model is told is required
# ---------------------------------------------------------------------------


def test_required_fields_are_exactly_the_five_the_requirements_demand() -> None:
    # Proves: the JSON schema `instructor` sends lists exactly these as required — the
    # strongest single guard for v0.1-G8 (a required `time` forces the model to invent one
    # when a page states none). Catches the Pydantic v2 trap where `X | None` with no
    # `= None` is *still required*.
    required = set(ShowExtraction.model_json_schema()["required"])
    assert required == {"venue", "date", "acts", "is_ambiguous", "confidence"}


def test_the_old_ticket_info_field_is_gone() -> None:
    # Proves: `ticket_info` really was replaced by the typed admission fields. Pydantic
    # ignores unknown input fields by default, so a leftover field would go unnoticed
    # and keep tempting the model to fill a string nothing reads.
    assert "ticket_info" not in ShowExtraction.model_json_schema()["properties"]


def test_page_level_schema_still_requires_page_readable() -> None:
    # Proves: A2 didn't regress the page_readable signal that tells an empty page from
    # a broken one (VenuePageExtraction's own docstring explains why it matters).
    assert "page_readable" in VenuePageExtraction.model_json_schema()["required"]


# ---------------------------------------------------------------------------
# Optionality: "not stated" is representable
# ---------------------------------------------------------------------------

OPTIONAL_SHOW_FIELDS = [
    "time", "end_time", "admission_advance", "admission_day", "free_admission", "image_url",
]
OPTIONAL_ACT_FIELDS = ["start_time", "sequence_number"]


@pytest.mark.parametrize(
    ("model", "name"),
    [(ShowExtraction, f) for f in OPTIONAL_SHOW_FIELDS]
    + [(ActExtraction, f) for f in OPTIONAL_ACT_FIELDS],
)
def test_optional_fields_default_to_none(model: type[BaseModel], name: str) -> None:
    # Proves: every optional field has an explicit default of None, so a model that
    # omits it is fine. `free_admission` defaulting to None (not False) is what keeps
    # "the page said nothing" from reading as "not free" — requirements: "it's ok for
    # neither prices nor free admission to be empty".
    info = model.model_fields[name]
    assert not info.is_required()
    assert info.default is None


def test_a_minimal_show_validates_with_everything_optional_none() -> None:
    # Proves: a show carrying only the required fields is accepted and every optional
    # field comes back None — the "page states nothing else" case is representable end
    # to end, including inside an act.
    show = ShowExtraction.model_validate(minimal_show())
    assert show.time is None
    assert show.end_time is None
    assert show.admission_advance is None
    assert show.admission_day is None
    assert show.free_admission is None
    assert show.image_url is None
    assert show.acts[0].start_time is None
    assert show.acts[0].sequence_number is None


def test_free_admission_false_becomes_not_stated() -> None:
    # Proves: A2-F1 of the A2 eval — the model wrote `free_admission: false` on 56 shows whose
    # pages state no admission at all. `false` carries no meaning downstream (absence of a
    # price never means "not free"), so the schema turns it into None; `true` is kept. The
    # JSON schema the model sees is unchanged (`boolean | null`), as with the time
    # normalizer. A2.1-D6.
    assert validate_field(ShowExtraction, "free_admission", False) is None
    assert validate_field(ShowExtraction, "free_admission", True) is True
    prop = ShowExtraction.model_json_schema()["properties"]["free_admission"]
    assert prop["anyOf"] == [{"type": "boolean"}, {"type": "null"}]


# ---------------------------------------------------------------------------
# Admission prices
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["admission_advance", "admission_day"])
def test_negative_prices_are_rejected(name: str) -> None:
    # Proves: `ge=0` is in force, so a model that reads "-5" gets re-asked instead of
    # writing a negative price. (Plausibility beyond this is A3's job.)
    with pytest.raises(ValidationError):
        validate_field(ShowExtraction, name, -5)


@pytest.mark.parametrize("raw", ["15.00", 15, 15.0])
def test_prices_accept_the_shapes_a_model_emits(raw: Any) -> None:
    # Proves: both `"15.00"` (a string) and `15` (an int) land as the float 15.0.
    # Prices are floats in extraction on purpose (Decimal would put a regex-string
    # branch in the schema the model sees, twice per show); A6 converts at the write.
    assert validate_field(ShowExtraction, "admission_day", raw) == 15.0


# ---------------------------------------------------------------------------
# Acts: structured objects, not bare names
# ---------------------------------------------------------------------------


def test_acts_must_be_objects() -> None:
    # Proves: `acts` is a list of ActExtraction objects, so a bare
    # string act is rejected. This is the shape change that lets an act carry its own
    # start time and order. Validated through the `acts` field alone (`validate_field`),
    # so a failure here points at `acts` and not at some other required field.
    with pytest.raises(ValidationError):
        validate_field(ShowExtraction, "acts", ["Band A"])
    assert validate_field(ShowExtraction, "acts", [{"name": "Band A"}])[0].name == "Band A"


def test_sequence_number_is_one_based_and_optional() -> None:
    # Proves: a *stated* performance order is 1-based (0 is rejected), and None is fine
    # because most pages state no order — A5 derives it from list position then
    # (requirements: "make an assumption … based on the order in which the artists are
    # listed"). Making it required would turn every unnumbered page into a re-ask.
    with pytest.raises(ValidationError):
        ActExtraction.model_validate({"name": "Band A", "sequence_number": 0})
    assert ActExtraction.model_validate({"name": "Band A", "sequence_number": 1}).sequence_number == 1
    assert ActExtraction.model_validate({"name": "Band A"}).sequence_number is None


def test_an_empty_acts_list_is_deliberately_valid() -> None:
    # Proves (pins a decision): the schema does NOT enforce "one or more artists".
    # That check is A3's completeness validation. Enforcing it here would turn one
    # leaked "Karaoke" entry (which the model emits with no artists) into a full-page
    # `instructor` re-ask instead of a single dropped show. (The baseline already
    # produced two such empty-acts shows on its own.)
    assert validate_field(ShowExtraction, "acts", []) == []


# ---------------------------------------------------------------------------
# Descriptions: they are instructions to the model, so the conventions are tested
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "name"),
    [(ShowExtraction, f) for f in OPTIONAL_SHOW_FIELDS]
    + [(ActExtraction, f) for f in OPTIONAL_ACT_FIELDS],
)
def test_every_optional_field_tells_the_model_how_to_say_not_stated(
    model: type[BaseModel], name: str
) -> None:
    # Proves: each optional field's description ends the model's instructions with the
    # fixed phrase "otherwise null". The description is part of the request `instructor`
    # sends, so this is an instruction, not a comment — and the exact phrase (not just
    # the word "null", which "nullable" would also satisfy) is what makes the convention
    # checkable.
    description = model.model_fields[name].description or ""
    assert "otherwise null" in description


@pytest.mark.parametrize(("model", "name"), TIME_FIELDS)
def test_every_time_field_asks_for_24_hour_hh_mm(model: type[BaseModel], name: str) -> None:
    # Proves: the format instruction ("HH:MM") can't be silently dropped from a time
    # field. The normalizer rescues sloppy output, but asking for the right format is
    # still what keeps most of it clean.
    assert "HH:MM" in (model.model_fields[name].description or "")


@pytest.mark.parametrize(("model", "name"), TIME_FIELDS)
def test_every_time_field_tells_the_model_to_assume_pm(model: type[BaseModel], name: str) -> None:
    # Proves: the "no AM/PM means PM" rule (Ari, October 10, 2026; a2-extraction-schema.md
    # A2-D2) reaches the model, not just the normalizer. The model is asked
    # for 24-hour HH:MM, so it does the 12-to-24 conversion itself: a page's bare "10:30"
    # comes back as "10:30" or "22:30" depending on what the model assumed, and the
    # normalizer can't tell which (two-digit HH:MM is the format we asked for). Only the
    # instruction can settle that case.
    assert "assume PM" in (model.model_fields[name].description or "")


def test_show_time_means_when_the_music_starts_not_doors() -> None:
    # Proves: `time`'s description settles the "Doors 7 / Show 8" ambiguity. Left
    # undecided it flips between runs, which reconcile would read as a time change
    # (remove + insert) rather than the same show.
    assert "doors" in (ShowExtraction.model_fields["time"].description or "").lower()


# ---------------------------------------------------------------------------
# Time normalizer (agent_worker/normalize.py): convert the recoverable, refuse the rest
# ---------------------------------------------------------------------------
# Expected values come from the plan's normalizer table (Design › Time normalizer), i.e.
# from what a 12-hour clock means — not from the normalizer's own code.


@pytest.mark.parametrize(("model", "name"), TIME_FIELDS)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("19:30", datetime.time(19, 30)),
        ("19:30:00", datetime.time(19, 30)),
        ("07:30", datetime.time(7, 30)),  # zero-padded: clearly 24-hour
        ("7pm", datetime.time(19, 0)),
        ("7 PM", datetime.time(19, 0)),
        ("7:30pm", datetime.time(19, 30)),
        ("7:30 PM", datetime.time(19, 30)),
        ("7:30 p.m.", datetime.time(19, 30)),
        ("8:00pm", datetime.time(20, 0)),
        (" 7pm ", datetime.time(19, 0)),  # surrounding whitespace
        ("12am", datetime.time(0, 0)),  # midnight
        ("12pm", datetime.time(12, 0)),  # noon
        ("12:15am", datetime.time(0, 15)),
        # Bare "p"/"a" is an explicit meridiem too — it is how the Midway page itself
        # writes times ("7p", "8p"), so a model copying the page must not be re-asked.
        ("7p", datetime.time(19, 0)),
        ("8:30p", datetime.time(20, 30)),
        ("7P", datetime.time(19, 0)),
        ("11a", datetime.time(11, 0)),
        # ISO with fractional seconds is valid to plain Pydantic, so the normalizer must
        # not make it worse than having no normalizer at all.
        ("19:30:00.000", datetime.time(19, 30)),
        ("19:30:00.500", datetime.time(19, 30, 0, 500000)),
        # No AM/PM and not zero-padded: assume PM (Ari, October 10, 2026 — live music is
        # overwhelmingly afternoon/evening, and a listing that really is in the morning
        # says AM). A2-D2 in the A2 plan; this reverses the original
        # "reject and re-ask" choice.
        ("7:30", datetime.time(19, 30)),
        ("7", datetime.time(19, 0)),
        ("9:45", datetime.time(21, 45)),
        ("1:00", datetime.time(13, 0)),
        ("10", datetime.time(22, 0)),  # no colon, so not the HH:MM we asked for
        ("12:30", datetime.time(12, 30)),  # 12 PM is noon: unchanged either way
        # The limit of the rule: a two-digit HH:MM is the 24-hour format the description
        # asks for, so it is trusted as written. "10:30" stays morning; whether the model
        # should have written "22:30" is the description's job (assume-PM test above).
        ("10:30", datetime.time(10, 30)),
        ("11:00", datetime.time(11, 0)),
    ],
)
def test_normalizer_converts_unambiguous_spellings(
    model: type[BaseModel], name: str, raw: str, expected: datetime.time
) -> None:
    # Proves: the sloppy-but-unambiguous formats a model actually emits are converted,
    # not rejected — a rejected time fails the whole page and costs a full re-ask.
    # Run against all three time fields.
    assert validate_field(model, name, raw) == expected


@pytest.mark.parametrize(("model", "name"), TIME_FIELDS)
@pytest.mark.parametrize("raw", ["", "null", "None", "N/A", "na", "TBD", "tba", "Unknown"])
def test_normalizer_reads_the_word_for_not_stated_as_none(
    model: type[BaseModel], name: str, raw: str
) -> None:
    # Proves: a model told "otherwise null" that writes the *word* gets None, not a
    # validation error — the word means "the page doesn't state a time".
    assert validate_field(model, name, raw) is None


@pytest.mark.parametrize(("model", "name"), TIME_FIELDS)
@pytest.mark.parametrize("raw", ["19:30:00Z", "19:30-05:00"])
def test_normalizer_drops_the_timezone_without_converting(
    model: type[BaseModel], name: str, raw: str
) -> None:
    # Proves: a zone suffix is noise, not information — the wall-clock 19:30 is kept
    # (not shifted) and the result is naive. An aware time would later fail to compare
    # equal to the database's naive `time` column (A5's reconcile key).
    result = validate_field(model, name, raw)
    assert result == datetime.time(19, 30)
    assert result.tzinfo is None


@pytest.mark.parametrize(("model", "name"), TIME_FIELDS)
@pytest.mark.parametrize(
    "raw", ["24:00", "25:00", "13pm", "0pm", "0:30", "13", "after dark", 68400, 19.5, True]
)
def test_normalizer_refuses_non_times(model: type[BaseModel], name: str, raw: Any) -> None:
    # Proves: impossible times and free text are refused, not coerced; a bare hour
    # outside 1-12 ("0:30", "13") isn't a 12-hour reading, so assume-PM doesn't apply;
    # and integers specifically are refused, because plain Pydantic would accept 68400 as
    # a timezone-AWARE 19:00. Each failure must be a `value_error` — the kind
    # `instructor` retries on.
    with pytest.raises(ValidationError) as excinfo:
        validate_field(model, name, raw)
    assert excinfo.value.errors()[0]["type"] == "value_error"


def test_normalizer_leaves_the_json_schema_the_model_sees_unchanged() -> None:
    # Proves: leniency is invisible to the model. The schema sent in the request still
    # says "a time string, or null" — the model is told nothing about our tolerance, so
    # it isn't encouraged to be sloppy.
    expected = [{"format": "time", "type": "string"}, {"type": "null"}]
    props = ShowExtraction.model_json_schema()["properties"]
    assert props["time"]["anyOf"] == expected
    assert props["end_time"]["anyOf"] == expected
    act_props = ShowExtraction.model_json_schema()["$defs"]["ActExtraction"]["properties"]
    assert act_props["start_time"]["anyOf"] == expected


# ---------------------------------------------------------------------------
# Round trips: realistic payloads parse as a model would emit them
# ---------------------------------------------------------------------------


def test_a_realistic_multi_act_payload_round_trips() -> None:
    # Proves: a payload shaped like what a model plausibly returns for a priced
    # multi-act show parses with every field landing where it should — advance and
    # day prices as floats, per-act start times and a stated order, an end time.
    payload = """{
      "page_readable": true,
      "shows": [{
        "venue": "The Test Room", "date": "2026-08-22",
        "time": "7:30 PM", "end_time": "23:00",
        "acts": [
          {"name": "Opener", "start_time": "7:30pm", "sequence_number": 1},
          {"name": "Headliner", "start_time": "9:00pm", "sequence_number": 2}
        ],
        "is_ambiguous": false,
        "admission_advance": 12, "admission_day": "15.00",
        "free_admission": null, "image_url": null, "confidence": 0.8
      }]
    }"""
    page = VenuePageExtraction.model_validate_json(payload)
    show = page.shows[0]
    assert show.time == datetime.time(19, 30)
    assert show.end_time == datetime.time(23, 0)
    assert [a.name for a in show.acts] == ["Opener", "Headliner"]
    assert show.acts[1].start_time == datetime.time(21, 0)
    assert show.acts[1].sequence_number == 2
    assert (show.admission_advance, show.admission_day) == (12.0, 15.0)
    assert show.free_admission is None


def test_a_minimal_payload_round_trips() -> None:
    # Proves: the other extreme — a date and one act, everything else null/omitted —
    # is accepted as a whole page, which is the Terminal Bar case (dates and names, no
    # times or prices).
    payload = (
        '{"page_readable": true, "shows": [{"venue": "Terminal Bar", "date": "2026-08-07",'
        ' "acts": [{"name": "Envies"}], "is_ambiguous": false, "confidence": 0.7}]}'
    )
    show = VenuePageExtraction.model_validate_json(payload).shows[0]
    assert show.time is None
    assert show.acts[0].name == "Envies"
