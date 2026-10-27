"""Tests for the pure schedule logic (parsing, grouping, boundaries)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from custom_components.svitlo_ye.const import SCHEDULE_TZ
from custom_components.svitlo_ye.schedule import (
    ScheduleStatus,
    build_schedule,
    parse_clock,
    parse_messages,
    parse_server_timestamp,
    parse_slots,
)

from .conftest import load_json


def kyiv(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    """Kyiv wall clock -> UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=SCHEDULE_TZ).astimezone(UTC)


def slot(day: str, span: str, color: str) -> dict[str, Any]:
    """Build a raw API slot."""
    return {"cherga": "1", "pidcherga": "1", "date": day, "span": span, "color": color}


def half_hours(day: str, colors: dict[tuple[int, int], str], default: str = "white") -> list:
    """Build a full day of half-hour slots; ``colors`` maps (start_h, end_h) to a color."""
    result = []
    for i in range(48):
        start = i * 30
        end = start + 30
        color = default
        for (from_h, to_h), c in colors.items():
            if from_h * 60 <= start < to_h * 60:
                color = c
        end_label = "24:00" if end == 1440 else f"{end // 60:02d}:{end % 60:02d}"
        result.append(slot(day, f"{start // 60:02d}:{start % 60:02d}-{end_label}", color))
    return result


def test_status_from_color() -> None:
    """Colors map exactly like in the app."""
    assert ScheduleStatus.from_color("white") is ScheduleStatus.AVAILABLE
    assert ScheduleStatus.from_color("GREEN") is ScheduleStatus.AVAILABLE
    assert ScheduleStatus.from_color("red") is ScheduleStatus.OUTAGE
    assert ScheduleStatus.from_color("yellow") is ScheduleStatus.PROBABLE
    assert ScheduleStatus.from_color("blue") is ScheduleStatus.UNKNOWN
    assert ScheduleStatus.from_color(None) is ScheduleStatus.UNKNOWN
    assert ScheduleStatus.UNKNOWN.has_power is None
    assert ScheduleStatus.PROBABLE.has_power is False


def test_parse_clock() -> None:
    """24:00 is the end of the day; invalid values are rejected."""
    assert parse_clock("00:00") == 0
    assert parse_clock("23:30") == 1410
    assert parse_clock("24:00") == 1440
    assert parse_clock("24:30") is None
    assert parse_clock("ab:cd") is None
    assert parse_clock("12") is None


def test_real_fixture_grouping() -> None:
    """The captured response of queue 1.2 groups into 7 intervals."""
    data = build_schedule(1, 2, load_json("schedule_1_2.json"))
    assert len(data.slots) == 48
    spans = [(i.as_dict()["start_time"], i.as_dict()["end_time"], i.status) for i in data.intervals]
    assert spans == [
        ("00:00", "08:00", ScheduleStatus.AVAILABLE),
        ("08:00", "10:00", ScheduleStatus.OUTAGE),
        ("10:00", "13:00", ScheduleStatus.AVAILABLE),
        ("13:00", "16:00", ScheduleStatus.OUTAGE),
        ("16:00", "19:00", ScheduleStatus.AVAILABLE),
        ("19:00", "21:00", ScheduleStatus.OUTAGE),
        ("21:00", "24:00", ScheduleStatus.AVAILABLE),
    ]
    stats = data.day_stats(date(2026, 10, 27))
    assert stats is not None
    assert stats.outage_hours == 7.0
    assert stats.available_hours == 17.0
    # The last interval ends at the next Kyiv midnight.
    assert data.intervals[-1].end == kyiv(2026, 10, 28)


def test_end_2400_and_midnight_merge() -> None:
    """An outage 22:00-24:00 continuing 00:00-02:00 next day is one interval."""
    raw = half_hours("27.10.2026", {(22, 24): "red"}) + half_hours("28.10.2026", {(0, 2): "red"})
    data = build_schedule(1, 1, raw)
    outage = [i for i in data.intervals if i.status is ScheduleStatus.OUTAGE]
    assert len(outage) == 1
    assert outage[0].start == kyiv(2026, 10, 27, 22)
    assert outage[0].end == kyiv(2026, 10, 28, 2)
    assert outage[0].slot_count == 8

    # Around midnight the binary state stays "off" and the next change is 02:00.
    now = kyiv(2026, 10, 27, 23, 50)
    assert data.current_status(now) is ScheduleStatus.OUTAGE
    assert data.next_power_change(now) == (kyiv(2026, 10, 28, 2), True)

    # Clipping per day keeps each day's part.
    today = data.day_intervals(date(2026, 10, 27))
    assert today[-1].as_dict()["end_time"] == "24:00"
    tomorrow = data.day_intervals(date(2026, 10, 28))
    assert tomorrow[0].as_dict()["start_time"] == "00:00"
    assert tomorrow[0].end == kyiv(2026, 10, 28, 2)

    # Stats are per published day.
    assert data.day_stats(date(2026, 10, 27)).outage == 120
    assert data.day_stats(date(2026, 10, 28)).outage == 120
    assert data.day_stats(date(2026, 10, 29)) is None


def test_span_crossing_midnight_inside_one_record() -> None:
    """A single span like 23:00-01:00 ends on the next day."""
    data = build_schedule(1, 1, [slot("27.10.2026", "23:00-01:00", "red")])
    assert data.intervals[0].end == kyiv(2026, 10, 28, 1)
    assert data.day_stats(date(2026, 10, 27)).outage == 120


def test_whole_day_span() -> None:
    """00:00-00:00 is a whole day, like the app counts it."""
    data = build_schedule(1, 1, [slot("27.10.2026", "00:00-00:00", "white")])
    assert data.intervals[0].duration == timedelta(hours=24)
    assert data.day_stats(date(2026, 10, 27)).available == 1440


def test_empty_schedule() -> None:
    """No data -> unknown everywhere."""
    data = build_schedule(9, 9, load_json("schedule_9_9.json"))
    now = kyiv(2026, 10, 27, 12)
    assert data.slots == ()
    assert data.current(now) is None
    assert data.current_status(now) is ScheduleStatus.UNKNOWN
    assert data.next_power_change(now) is None
    assert data.next_change(now) is None
    assert data.day_stats(date(2026, 10, 27)) is None


def test_unknown_color_breaks_power_prediction() -> None:
    """An unknown slot is a state of its own and stops the power-change search."""
    raw = [
        slot("27.10.2026", "10:00-11:00", "white"),
        slot("27.10.2026", "11:00-12:00", "black"),
        slot("27.10.2026", "12:00-13:00", "red"),
    ]
    data = build_schedule(1, 1, raw)
    now = kyiv(2026, 10, 27, 10, 15)
    assert data.next_power_change(now) is None
    assert data.next_change(now) == kyiv(2026, 10, 27, 11)
    assert data.current_status(kyiv(2026, 10, 27, 11, 30)) is ScheduleStatus.UNKNOWN
    assert data.day_stats(date(2026, 10, 27)).unknown == 60


def test_probable_counts_as_no_power() -> None:
    """Outage followed by probable outage: power returns only after both."""
    raw = [
        slot("27.10.2026", "10:00-11:00", "red"),
        slot("27.10.2026", "11:00-12:00", "yellow"),
        slot("27.10.2026", "12:00-13:00", "white"),
    ]
    data = build_schedule(1, 1, raw)
    now = kyiv(2026, 10, 27, 10, 30)
    assert data.next_change(now) == kyiv(2026, 10, 27, 11)
    assert data.next_power_change(now) == (kyiv(2026, 10, 27, 12), True)
    assert [i.status for i in data.outage_intervals()] == [
        ScheduleStatus.OUTAGE,
        ScheduleStatus.PROBABLE,
    ]
    assert data.day_stats(date(2026, 10, 27)).probable == 60


def test_gap_in_schedule() -> None:
    """Between published slots the state is unknown; the next one is predicted."""
    raw = [slot("27.10.2026", "10:00-11:00", "white"), slot("27.10.2026", "12:00-13:00", "red")]
    data = build_schedule(1, 1, raw)
    assert data.next_power_change(kyiv(2026, 10, 27, 10, 30)) is None
    gap = kyiv(2026, 10, 27, 11, 30)
    assert data.current(gap) is None
    assert data.next_power_change(gap) == (kyiv(2026, 10, 27, 12), False)


def test_before_schedule_and_after_end() -> None:
    """Before the first slot the first state is predicted; after the last, nothing."""
    data = build_schedule(1, 2, load_json("schedule_1_2.json"))
    assert data.next_power_change(kyiv(2026, 10, 26, 23)) == (kyiv(2026, 10, 27), True)
    # 21:00-24:00 is the last published interval: no known change after it.
    assert data.next_power_change(kyiv(2026, 10, 27, 22)) is None
    assert data.current_status(kyiv(2026, 10, 28, 0, 1)) is ScheduleStatus.UNKNOWN


def test_duplicates_and_malformed_records() -> None:
    """Repeated spans are counted once; malformed records are skipped."""
    raw = [
        slot("27.10.2026", "10:00-10:30", "red"),
        slot("27.10.2026", "10:00-10:30", "red"),
        slot("27.10.2026", "bad", "red"),
        slot("xx.10.2026", "10:30-11:00", "red"),
        {"date": "27.10.2026"},
        "not a dict",
    ]
    slots = parse_slots(raw)  # type: ignore[arg-type]
    assert len(slots) == 1
    data = build_schedule(1, 1, raw)  # type: ignore[arg-type]
    assert data.day_stats(date(2026, 10, 27)).outage == 30


def test_dst_end_day() -> None:
    """On 25.10.2026 clocks go back: 02:00-04:00 wall time lasts three real hours."""
    raw = [
        slot("25.10.2026", "02:00-03:00", "red"),
        slot("25.10.2026", "03:00-04:00", "red"),
    ]
    data = build_schedule(1, 1, raw)
    interval = data.intervals[0]
    assert interval.start == datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    assert interval.end == datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    # Day statistics count wall-clock minutes, like the app.
    assert data.day_stats(date(2026, 10, 25)).outage == 120


def test_messages_and_server_timestamp() -> None:
    """HTML entities are decoded and the header is parsed in Kyiv time."""
    messages = parse_messages(load_json("messages.json"))
    assert messages[0].text == "УВАГА! ВАЖЛИВА ІНФОРМАЦІЯ!"
    assert '"Укренерго"' in messages[1].text
    assert parse_server_timestamp("2026.10.27 00:16:59") == datetime(
        2026, 10, 26, 22, 16, 59, tzinfo=UTC
    )
    assert parse_server_timestamp("garbage") is None
    assert parse_server_timestamp(None) is None
