"""Data update coordinator for SvitloYE."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SvitloYeApiClient, SvitloYeConnectionError, SvitloYeError
from .const import (
    CONF_CHERGA,
    CONF_PIDCHERGA,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
    FAILURES_BEFORE_ISSUE,
    ISSUE_API_UNAVAILABLE,
    LOGGER,
)
from .schedule import ScheduleData, build_schedule

type SvitloYeConfigEntry = ConfigEntry[SvitloYeRuntimeData]


@dataclass(slots=True)
class SvitloYeRuntimeData:
    """Runtime data stored on the config entry."""

    client: SvitloYeApiClient
    coordinator: SvitloYeCoordinator


class SvitloYeCoordinator(DataUpdateCoordinator[ScheduleData]):
    """Polls the schedule of one queue and ticks entities every minute."""

    config_entry: SvitloYeConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SvitloYeConfigEntry,
        client: SvitloYeApiClient,
    ) -> None:
        """Initialize the coordinator."""
        minutes = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN))
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self.cherga = int(entry.data[CONF_CHERGA])
        self.pidcherga = int(entry.data[CONF_PIDCHERGA])
        self.last_fetch_success: datetime | None = None
        self._failures = 0

    @property
    def _issue_id(self) -> str:
        return f"{ISSUE_API_UNAVAILABLE}_{self.config_entry.entry_id}"

    @callback
    def _record_failure(self) -> None:
        """Count a failed poll and raise a repair issue when it keeps failing."""
        self._failures += 1
        if self._failures >= FAILURES_BEFORE_ISSUE:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_API_UNAVAILABLE,
                translation_placeholders={"title": self.config_entry.title},
            )

    @callback
    def async_clear_issue(self) -> None:
        """Drop the repair issue and the failure counter."""
        self._failures = 0
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    async def _async_update_data(self) -> ScheduleData:
        try:
            data = await self._async_fetch()
        except UpdateFailed:
            self._record_failure()
            raise
        self.async_clear_issue()
        return data

    async def _async_fetch(self) -> ScheduleData:
        try:
            raw = await self.client.async_get_all(self.cherga, self.pidcherga)
        except SvitloYeConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except SvitloYeError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_response",
                translation_placeholders={"error": str(err)},
            ) from err

        now = dt_util.utcnow()
        previous = self.data
        fresh = build_schedule(
            self.cherga,
            self.pidcherga,
            raw.slots,
            raw.messages or (),
            server_updated=raw.server_updated,
            fetched_at=now,
        )
        self.last_fetch_success = now
        if previous is None:
            return fresh

        # An empty answer next to a non-empty schedule is almost always an API hiccup
        # (the app keeps its cache in this case); keep the known schedule.
        if not fresh.slots and previous.slots:
            LOGGER.debug("Empty schedule received, keeping the previous one")
            fresh = replace(
                fresh,
                slots=previous.slots,
                intervals=previous.intervals,
                server_updated=previous.server_updated,
                fetched_at=previous.fetched_at,
            )
        if raw.messages is None:
            fresh = replace(fresh, messages=previous.messages)
        if fresh.server_updated is None:
            fresh = replace(fresh, server_updated=previous.server_updated)
        return fresh

    @callback
    def async_start_ticker(self) -> None:
        """Re-evaluate time based entities at the start of every minute."""

        @callback
        def _tick(_now: datetime) -> None:
            if self.data is not None:
                self.async_update_listeners()

        self.config_entry.async_on_unload(async_track_time_change(self.hass, _tick, second=0))
