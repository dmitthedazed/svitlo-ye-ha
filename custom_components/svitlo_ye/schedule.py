"""Pure schedule logic: parse API slots, group them into intervals, compute stats.

Mirrors the Android app (ScheduleMapper, ScheduleDomainLogic, StatisticsCalculator):
- the API returns half-hour slots ``{"date": "dd.MM.yyyy", "span": "HH:mm-HH:mm",
  "color": "white|green|red|yellow"}`` in Kyiv time;
- an end of ``24:00`` (or an end not after the start) belongs to the next day;
- consecutive slots with the same status are merged into one interval;
- a repeated slot (same date and span) is counted once.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
import html
from typing import Any

from .const import SCHEDULE_TZ

MINUTES_PER_DAY = 24 * 60


class ScheduleStatus(StrEnum):
    """Status of a schedule interval."""

    AVAILABLE = "available"
    OUTAGE = "outage"
    PROBABLE = "probable"
    UNKNOWN = "unknown"

    @classmethod
    def from_color(cls, color: str | None) -> ScheduleStatus:
        """Map an API color to a status (same mapping as the app)."""
        match (color or "").strip().lower():
            case "white" | "green":
                return cls.AVAILABLE
            case "red":
                return cls.OUTAGE
            case "yellow":
                return cls.PROBABLE
            case _:
                return cls.UNKNOWN

    @property
    def has_power(self) -> bool | None:
        """Return whether power is expected (None when unknown)."""
        if self is ScheduleStatus.UNKNOWN:
            return None
        return self is ScheduleStatus.AVAILABLE


STATUS_OPTIONS: list[str] = [s.value for s in ScheduleStatus]


@dataclass(frozen=True, slots=True)
class Slot:
    """One raw slot of the schedule, converted to absolute UTC times."""

    day: date
    span: str
    start: datetime
    end: datetime
    status: ScheduleStatus
    text: str | None = None

    @property
    def minutes(self) -> int:
        """Return the duration in minutes (real elapsed time)."""
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True, slots=True)
class Interval:
    """Consecutive slots of the same status merged into one block."""

    start: datetime
    end: datetime
    status: ScheduleStatus
    slot_count: int = 1

    @property
    def duration(self) -> timedelta:
        """Return the interval duration."""
        return self.end - self.start

    def contains(self, moment: datetime) -> bool:
        """Return True if ``moment`` falls in [start, end)."""
        return self.start <= moment < self.end

    def as_dict(self) -> dict[str, Any]:
        """Serialize for state attributes (local Kyiv times)."""
        start = self.start.astimezone(SCHEDULE_TZ)
        end = self.end.astimezone(SCHEDULE_TZ)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "start_time": start.strftime("%H:%M"),
            "end_time": _end_label(start, end),
            "status": self.status.value,
            "duration_minutes": int(self.duration.total_seconds() // 60),
        }


@dataclass(frozen=True, slots=True)
class Message:
    """Informational message published next to the schedule."""

    id: int
    text: str


@dataclass(frozen=True, slots=True)
class DayStats:
    """Minutes per status for one schedule day."""

    outage: int = 0
    available: int = 0
    probable: int = 0
    unknown: int = 0

    @property
    def outage_hours(self) -> float:
        """Return the sure outage duration in hours."""
        return round(self.outage / 60, 2)

    @property
    def probable_hours(self) -> float:
        """Return the probable outage duration in hours."""
        return round(self.probable / 60, 2)

    @property
    def available_hours(self) -> float:
        """Return the duration with power in hours."""
        return round(self.available / 60, 2)

    @property
    def unknown_hours(self) -> float:
        """Return the unknown duration in hours."""
        return round(self.unknown / 60, 2)


@dataclass(frozen=True, slots=True)
class ScheduleData:
    """Everything the coordinator knows about one queue."""

    cherga: int
    pidcherga: int
    slots: tuple[Slot, ...] = ()
    intervals: tuple[Interval, ...] = ()
    messages: tuple[Message, ...] = ()
    server_updated: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def queue(self) -> str:
        """Return the queue as ``cherga.pidcherga``."""
        return f"{self.cherga}.{self.pidcherga}"

    @property
    def last_updated(self) -> datetime:
        """Return the server publication time, or the fetch time as a fallback."""
        return self.server_updated or self.fetched_at

    def current(self, now: datetime) -> Interval | None:
        """Return the interval active at ``now``."""
        return next((i for i in self.intervals if i.contains(now)), None)

    def current_status(self, now: datetime) -> ScheduleStatus:
        """Return the status at ``now`` (UNKNOWN outside the published schedule)."""
        interval = self.current(now)
        return interval.status if interval else ScheduleStatus.UNKNOWN

    def next_interval(self, now: datetime) -> Interval | None:
        """Return the next interval with a different status than the current one.

        Returns None when the schedule ends without a known following state.
        """
        current = self.current(now)
        for interval in self.intervals:
            if interval.start <= now:
                continue
            if current is None:
                return interval
            if interval.start != current.end:
                # A gap in the published schedule: the next state is unknown.
                return None
            if interval.status is not current.status:
                return interval
        return None

    def next_change(self, now: datetime) -> datetime | None:
        """Return the moment the status changes next."""
        nxt = self.next_interval(now)
        return nxt.start if nxt else None

    def next_power_change(self, now: datetime) -> tuple[datetime, bool] | None:
        """Return when power appears or disappears next and the new power state.

        Probable outages count as "no power" like in the app (``isLightOn``).
        Consecutive intervals with the same power state are skipped.
        """
        current = self.current(now)
        if current is None:
            first = next((i for i in self.intervals if i.start > now), None)
            if first is None or first.status.has_power is None:
                return None
            return first.start, bool(first.status.has_power)
        state = current.status.has_power
        cursor = current
        for interval in self.intervals:
            if interval.start < cursor.end:
                continue
            if interval.start != cursor.end:
                return None
            new_state = interval.status.has_power
            if new_state is None:
                return None
            if new_state != state:
                return interval.start, new_state
            cursor = interval
        return None

    def next_power_transition(self, now: datetime, power: bool) -> datetime | None:
        """Return the start of the next interval where power becomes ``power``.

        Probable outages count as "no power". Only transitions *into* the requested
        state are reported, so the current interval is never returned.
        """
        current = self.current(now)
        state = current.status.has_power if current else None
        for interval in self.intervals:
            if interval.start <= now:
                continue
            new_state = interval.status.has_power
            if new_state is None:
                state = None
                continue
            if new_state is power and state is not power:
                return interval.start
            state = new_state
        return None

    def day_slots(self, day: date) -> list[Slot]:
        """Return slots published for a Kyiv calendar day."""
        return [s for s in self.slots if s.day == day]

    def day_intervals(self, day: date) -> list[Interval]:
        """Return intervals overlapping a Kyiv calendar day, clipped to it."""
        day_start = datetime.combine(day, time.min, SCHEDULE_TZ).astimezone(UTC)
        day_end = datetime.combine(day + timedelta(days=1), time.min, SCHEDULE_TZ).astimezone(UTC)
        result: list[Interval] = []
        for interval in self.intervals:
            if interval.end <= day_start or interval.start >= day_end:
                continue
            result.append(
                Interval(
                    start=max(interval.start, day_start),
                    end=min(interval.end, day_end),
                    status=interval.status,
                    slot_count=interval.slot_count,
                )
            )
        return result

    def day_stats(self, day: date) -> DayStats | None:
        """Return per-status minutes for a day, or None if it is not published."""
        slots = self.day_slots(day)
        if not slots:
            return None
        totals = dict.fromkeys(ScheduleStatus, 0)
        for slot in slots:
            totals[slot.status] += _span_minutes(slot.span)
        return DayStats(
            outage=totals[ScheduleStatus.OUTAGE],
            available=totals[ScheduleStatus.AVAILABLE],
            probable=totals[ScheduleStatus.PROBABLE],
            unknown=totals[ScheduleStatus.UNKNOWN],
        )

    def outage_intervals(self) -> list[Interval]:
        """Return intervals with a sure or probable outage."""
        return [
            i
            for i in self.intervals
            if i.status in (ScheduleStatus.OUTAGE, ScheduleStatus.PROBABLE)
        ]


def kyiv_today(now: datetime) -> date:
    """Return the schedule day for ``now``."""
    return now.astimezone(SCHEDULE_TZ).date()


def _end_label(start: datetime, end: datetime) -> str:
    """Return "HH:MM" for the end, using "24:00" for the next midnight."""
    if end.time() == time.min and end.date() > start.date():
        return "24:00"
    return end.strftime("%H:%M")


def parse_clock(value: str) -> int | None:
    """Parse ``HH:mm`` to minutes since midnight; ``24:00`` is the end of day."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if hours == 24 and minutes == 0:
        return MINUTES_PER_DAY
    if 0 <= hours <= 23 and 0 <= minutes <= 59:
        return hours * 60 + minutes
    return None


def parse_span(span: str) -> tuple[int, int] | None:
    """Parse ``HH:mm-HH:mm`` into start/end minutes."""
    parts = span.split("-")
    if len(parts) != 2:
        return None
    start = parse_clock(parts[0])
    end = parse_clock(parts[1])
    if start is None or end is None or start == MINUTES_PER_DAY:
        return None
    return start, end


def _span_minutes(span: str) -> int:
    """Wall-clock minutes of a span, as the app counts them."""
    parsed = parse_span(span)
    if parsed is None:
        return 0
    duration = parsed[1] - parsed[0]
    return duration if duration > 0 else duration + MINUTES_PER_DAY


def parse_api_date(value: str) -> date | None:
    """Parse ``dd.MM.yyyy``."""
    try:
        day, month, year = (int(p) for p in value.strip().split("."))
        return date(year, month, day)
    except ValueError:
        return None


def _at(day: date, minutes: int) -> datetime:
    """Kyiv wall-clock time on ``day`` (minutes may be 1440) as UTC."""
    extra_days, minute_of_day = divmod(minutes, MINUTES_PER_DAY)
    local = datetime.combine(
        day + timedelta(days=extra_days),
        time(minute_of_day // 60, minute_of_day % 60),
        SCHEDULE_TZ,
    )
    return local.astimezone(UTC)


def parse_slot(raw: Mapping[str, Any]) -> Slot | None:
    """Convert one API record into a slot; returns None for malformed records."""
    day = parse_api_date(str(raw.get("date", "")))
    span = str(raw.get("span", "")).replace(" ", "")
    parsed = parse_span(span)
    if day is None or parsed is None:
        return None
    start_min, end_min = parsed
    start = _at(day, start_min)
    end = _at(day, end_min)
    if end <= start:
        end = _at(day + timedelta(days=1), end_min)
    text = raw.get("text")
    return Slot(
        day=day,
        span=span,
        start=start,
        end=end,
        status=ScheduleStatus.from_color(raw.get("color")),
        text=str(text) if text else None,
    )


def parse_slots(raw: Iterable[Mapping[str, Any]]) -> list[Slot]:
    """Parse, de-duplicate (date + span) and sort API records."""
    seen: set[tuple[date, str]] = set()
    slots: list[Slot] = []
    for record in raw:
        if not isinstance(record, Mapping):
            continue
        slot = parse_slot(record)
        if slot is None or (slot.day, slot.span) in seen:
            continue
        seen.add((slot.day, slot.span))
        slots.append(slot)
    slots.sort(key=lambda s: s.start)
    return slots


def group_slots(slots: Sequence[Slot]) -> list[Interval]:
    """Merge touching slots with the same status into intervals."""
    intervals: list[Interval] = []
    for slot in slots:
        if intervals:
            last = intervals[-1]
            if last.status is slot.status and last.end == slot.start:
                intervals[-1] = Interval(
                    start=last.start,
                    end=slot.end,
                    status=last.status,
                    slot_count=last.slot_count + 1,
                )
                continue
            if slot.start < last.end:
                # Overlapping record: keep the earlier one.
                continue
        intervals.append(Interval(slot.start, slot.end, slot.status))
    return intervals


def parse_messages(raw: Iterable[Mapping[str, Any]]) -> list[Message]:
    """Parse informational messages, decoding HTML entities."""
    messages: list[Message] = []
    for record in raw:
        if not isinstance(record, Mapping):
            continue
        text = html.unescape(str(record.get("text", ""))).strip()
        if not text:
            continue
        try:
            msg_id = int(record.get("id", 0))
        except (TypeError, ValueError):
            msg_id = 0
        messages.append(Message(msg_id, text))
    messages.sort(key=lambda m: m.id)
    return messages


def parse_server_timestamp(value: str | None) -> datetime | None:
    """Parse ``Last-Modified-Shedules-Date`` (``yyyy.MM.dd HH:mm:ss``, Kyiv time)."""
    if not value:
        return None
    try:
        naive = datetime.strptime(value.strip(), "%Y.%m.%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=SCHEDULE_TZ).astimezone(UTC)


def build_schedule(
    cherga: int,
    pidcherga: int,
    raw_schedule: Iterable[Mapping[str, Any]],
    raw_messages: Iterable[Mapping[str, Any]] = (),
    *,
    server_updated: datetime | None = None,
    fetched_at: datetime | None = None,
) -> ScheduleData:
    """Build ScheduleData from raw API payloads."""
    slots = parse_slots(raw_schedule)
    return ScheduleData(
        cherga=cherga,
        pidcherga=pidcherga,
        slots=tuple(slots),
        intervals=tuple(group_slots(slots)),
        messages=tuple(parse_messages(raw_messages)),
        server_updated=server_updated,
        fetched_at=fetched_at or datetime.now(UTC),
    )
