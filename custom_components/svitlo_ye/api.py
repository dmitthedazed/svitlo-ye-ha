"""Async client for the public ZTOE GPV API (https://www.ztoe.com.ua/gpv/api/).

Endpoints (all GET, JSON arrays, Kyiv time):
- ``api-rem.php``                                  -> [{"id", "name"}]
- ``api-city.php?rem_id=<id>``                     -> [{"id", "name"}]
- ``api-street.php?city_id=<id>``                  -> [{"id", "name"}]
- ``api-address.php?street_id=<id>``
  -> [{"id", "name", "sector", "cherga", "pidcherga"}] (queues come as strings)
- ``api-schedule.php?cherga_id=<n>&pidcherga_id=<n>``
  -> [{"cherga", "pidcherga", "date", "span", "color"}] (half-hour slots)
- ``api-message.php``                              -> [{"id", "text"}]; its response carries the
  ``Last-Modified-Shedules-Date`` header (``yyyy.MM.dd HH:mm:ss``, Kyiv time).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import json
import re
from typing import Any

import aiohttp

from .const import BASE_URL, LOGGER, REQUEST_TIMEOUT
from .schedule import parse_server_timestamp

SCHEDULE_UPDATED_HEADER = "Last-Modified-Shedules-Date"
ADDRESSES_UPDATED_HEADER = "Last-Modified-Adresses-Date"


class SvitloYeError(Exception):
    """Base error of the API client."""


class SvitloYeConnectionError(SvitloYeError):
    """The API could not be reached (network error, timeout, HTTP error)."""


class SvitloYeResponseError(SvitloYeError):
    """The API answered with something that is not the expected JSON."""


@dataclass(frozen=True, slots=True)
class Named:
    """An entity with id and name (REM, city or street)."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class AddressRecord:
    """One API address record; it usually covers several houses."""

    id: str
    name: str
    cherga: int
    pidcherga: int
    sector: str | None = None


class ConsumerCategory(StrEnum):
    """Consumer category parsed from the address name."""

    HOUSEHOLD = "household"
    LEGAL = "legal"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class House:
    """A single house parsed from an address record."""

    number: str
    category: ConsumerCategory
    address_id: str
    cherga: int
    pidcherga: int

    @property
    def key(self) -> str:
        """Return a stable key for selectors and unique ids."""
        return f"{self.address_id}|{self.number}|{self.category.value}"


@dataclass(frozen=True, slots=True)
class RawSchedule:
    """Raw schedule payload plus metadata."""

    slots: list[dict[str, Any]]
    messages: list[dict[str, Any]] | None
    server_updated: Any = None


_SUFFIXES = [
    re.compile(r"\s*-\s*побутові споживачі\s*", re.IGNORECASE),
    re.compile(r"\s*-\s*непобутові\s*\(юридичні\)\s*споживачі\s*", re.IGNORECASE),
    re.compile(r"\s*-\s*юридичні споживачі\s*", re.IGNORECASE),
    re.compile(r"\s*-\s*фізичні особи\s*-\s*підприємці\s*", re.IGNORECASE),
    re.compile(r"\s*-\s*\w+\s+споживачі\s*", re.IGNORECASE),
]
_LEGAL_MARKERS = (
    "юридичні",
    "непобутові",
    "фізичні особи",
    "фоп",
    "підприємство",
    "установа",
    "промислові",
)
_HOUSE_SORT = re.compile(r"(\d+)(.*)")


def _category(entry: str) -> ConsumerCategory:
    lowered = entry.lower()
    if "побутові" in lowered and "непобутові" not in lowered:
        return ConsumerCategory.HOUSEHOLD
    if any(marker in lowered for marker in _LEGAL_MARKERS):
        return ConsumerCategory.LEGAL
    return ConsumerCategory.OTHER


def parse_houses(records: list[AddressRecord]) -> list[House]:
    """Split address records into houses, like the app's address picker.

    Example: ``"25 - побутові споживачі, 27А - побутові споживачі"`` -> ``25``, ``27А``.
    """
    houses: dict[str, House] = {}
    for record in records:
        for raw_entry in record.name.split(","):
            entry = raw_entry.strip()
            category = _category(entry)
            cleaned = entry
            for pattern in _SUFFIXES:
                cleaned = pattern.sub("", cleaned)
            cleaned = cleaned.strip()
            if not cleaned:
                continue
            house = House(cleaned, category, record.id, record.cherga, record.pidcherga)
            houses.setdefault(house.key, house)

    def sort_key(house: House) -> tuple[int, int, str, str]:
        match = _HOUSE_SORT.match(house.number)
        if match:
            return (0, int(match.group(1)), match.group(2), house.category.value)
        return (1, 0, house.number, house.category.value)

    return sorted(houses.values(), key=sort_key)


def _to_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except ValueError:
        return 0


class SvitloYeApiClient:
    """Thin async wrapper around the GPV API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = BASE_URL,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the client with a shared aiohttp session."""
        self._session = session
        self._base_url = base_url
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        url = f"{self._base_url}{endpoint}"
        try:
            async with self._session.get(
                url,
                params=params,
                timeout=self._timeout,
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status != 200:
                    raise SvitloYeConnectionError(f"{endpoint} returned HTTP {resp.status}")
                body = await resp.read()
                headers = {k: v for k, v in resp.headers.items()}
        except TimeoutError as err:
            raise SvitloYeConnectionError(f"Timeout calling {endpoint}") from err
        except aiohttp.ClientError as err:
            raise SvitloYeConnectionError(f"Error calling {endpoint}: {err}") from err

        text = body.decode("utf-8-sig", errors="replace").strip()
        if not text:
            return [], headers
        try:
            data = json.loads(text)
        except ValueError as err:
            raise SvitloYeResponseError(f"{endpoint} did not return JSON") from err
        if data is None:
            return [], headers
        if not isinstance(data, list):
            raise SvitloYeResponseError(f"{endpoint} returned {type(data).__name__}")
        return [item for item in data if isinstance(item, dict)], headers

    @staticmethod
    def _named(items: list[dict[str, Any]]) -> list[Named]:
        result = [
            Named(str(item["id"]), str(item.get("name", "")).strip())
            for item in items
            if item.get("id") not in (None, "")
        ]
        return sorted(result, key=lambda n: n.name.casefold())

    async def async_get_rems(self) -> list[Named]:
        """Return regional power grid units (REM)."""
        items, _ = await self._request("api-rem.php")
        return self._named(items)

    async def async_get_cities(self, rem_id: str) -> list[Named]:
        """Return settlements of a REM."""
        items, _ = await self._request("api-city.php", {"rem_id": rem_id})
        return self._named(items)

    async def async_get_streets(self, city_id: str) -> list[Named]:
        """Return streets of a settlement."""
        items, _ = await self._request("api-street.php", {"city_id": city_id})
        return self._named(items)

    async def async_get_addresses(self, street_id: str) -> list[AddressRecord]:
        """Return address records (with queues) of a street."""
        items, _ = await self._request("api-address.php", {"street_id": street_id})
        return [
            AddressRecord(
                id=str(item["id"]),
                name=str(item.get("name", "")),
                cherga=_to_int(item.get("cherga")),
                pidcherga=_to_int(item.get("pidcherga")),
                sector=str(item["sector"]) if item.get("sector") else None,
            )
            for item in items
            if item.get("id") not in (None, "")
        ]

    async def async_get_schedule(self, cherga: int, pidcherga: int) -> list[dict[str, Any]]:
        """Return the raw half-hour slots for a queue."""
        items, _ = await self._request(
            "api-schedule.php", {"cherga_id": cherga, "pidcherga_id": pidcherga}
        )
        return items

    async def async_get_messages(self) -> tuple[list[dict[str, Any]], Any]:
        """Return the raw messages and the schedule publication time."""
        items, headers = await self._request("api-message.php")
        updated = parse_server_timestamp(_header(headers, SCHEDULE_UPDATED_HEADER))
        return items, updated

    async def async_get_all(self, cherga: int, pidcherga: int) -> RawSchedule:
        """Fetch schedule and messages in parallel.

        A failing schedule request raises; failing messages are tolerated.
        """
        schedule_res, messages_res = await asyncio.gather(
            self.async_get_schedule(cherga, pidcherga),
            self.async_get_messages(),
            return_exceptions=True,
        )
        if isinstance(schedule_res, BaseException):
            raise schedule_res
        if isinstance(messages_res, BaseException):
            if not isinstance(messages_res, SvitloYeError):
                raise messages_res
            LOGGER.debug("Messages request failed: %s", messages_res)
            return RawSchedule(schedule_res, None, None)
        messages, updated = messages_res
        return RawSchedule(schedule_res, messages, updated)


def _header(headers: dict[str, str], name: str) -> str | None:
    lowered = name.lower()
    return next((v for k, v in headers.items() if k.lower() == lowered), None)
