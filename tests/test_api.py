"""Tests for the API client and address parsing."""

from __future__ import annotations

from datetime import UTC, datetime
import re

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.svitlo_ye.api import (
    AddressRecord,
    ConsumerCategory,
    SvitloYeApiClient,
    SvitloYeConnectionError,
    SvitloYeResponseError,
    parse_houses,
)
from custom_components.svitlo_ye.const import BASE_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import mock_schedule


@pytest.fixture
async def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> SvitloYeApiClient:
    """Return an API client using the mocked session."""
    return SvitloYeApiClient(async_get_clientsession(hass))


async def test_location_chain(
    client: SvitloYeApiClient, mock_location_api: AiohttpClientMocker
) -> None:
    """REM, settlement, street and address lists are parsed and sorted."""
    rems = await client.async_get_rems()
    assert any(r.id == "7" and r.name == "Житомирський" for r in rems)
    assert [r.name for r in rems] == sorted((r.name for r in rems), key=str.casefold)

    cities = await client.async_get_cities("7")
    assert any(c.id == "16657" and c.name == "місто Житомир" for c in cities)

    streets = await client.async_get_streets("16657")
    assert any(s.id == "173934" and s.name == "вул. Київська" for s in streets)

    records = await client.async_get_addresses("173934")
    assert records
    assert all(isinstance(r.cherga, int) and isinstance(r.pidcherga, int) for r in records)
    first = next(r for r in records if r.id == "388680")
    assert (first.cherga, first.pidcherga, first.sector) == (1, 2, "12")


async def test_schedule_and_messages(
    client: SvitloYeApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Schedule, messages and the publication header are returned together."""
    mock_schedule(aioclient_mock)
    raw = await client.async_get_all(1, 2)
    assert len(raw.slots) == 48
    assert raw.slots[0]["span"] == "00:00-00:30"
    assert raw.messages
    assert raw.messages[0]["id"] == "1"
    assert raw.server_updated == datetime(2026, 10, 26, 22, 16, 59, tzinfo=UTC)


async def test_messages_failure_is_tolerated(
    client: SvitloYeApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failing messages endpoint does not fail the schedule."""
    aioclient_mock.get(f"{BASE_URL}api-schedule.php?cherga_id=1&pidcherga_id=2", json=[])
    aioclient_mock.get(f"{BASE_URL}api-message.php", status=500)
    raw = await client.async_get_all(1, 2)
    assert raw.slots == []
    assert raw.messages is None


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exc": TimeoutError()}, SvitloYeConnectionError),
        ({"exc": aiohttp.ClientConnectionError()}, SvitloYeConnectionError),
        ({"status": 502}, SvitloYeConnectionError),
        ({"text": "<html>maintenance</html>"}, SvitloYeResponseError),
        ({"text": '{"error": "x"}'}, SvitloYeResponseError),
    ],
)
async def test_errors(
    client: SvitloYeApiClient,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    error: type[Exception],
) -> None:
    """Network and format errors are mapped to client errors."""
    aioclient_mock.get(f"{BASE_URL}api-rem.php", **kwargs)
    with pytest.raises(error):
        await client.async_get_rems()


async def test_empty_and_null_body(
    client: SvitloYeApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Empty body and JSON null are treated as an empty list."""
    aioclient_mock.get(f"{BASE_URL}api-city.php?rem_id=1", text="")
    aioclient_mock.get(f"{BASE_URL}api-city.php?rem_id=2", text="null")
    assert await client.async_get_cities("1") == []
    assert await client.async_get_cities("2") == []


def test_parse_houses_real_fixture(mock_location_api: AiohttpClientMocker) -> None:
    """Address records split into houses with categories, sorted numerically."""
    from .conftest import load_json

    records = [
        AddressRecord(
            id=r["id"],
            name=r["name"],
            cherga=int(r["cherga"]),
            pidcherga=int(r["pidcherga"]),
        )
        for r in load_json("address.json")
    ]
    houses = parse_houses(records)
    assert houses
    numbers = [h.number for h in houses]
    assert all("споживачі" not in n for n in numbers)
    keys = [h.key for h in houses]
    assert len(keys) == len(set(keys))
    leading = [int(re.match(r"\d+", n).group()) for n in numbers if n[0].isdigit()]
    assert leading == sorted(leading)


def test_parse_houses_categories() -> None:
    """Household, legal and other suffixes are recognised and stripped."""
    records = [
        AddressRecord(
            id="1",
            name=(
                "25 - побутові споживачі, 27А - побутові споживачі, "
                "3 - непобутові (юридичні) споживачі, 10/2"
            ),
            cherga=3,
            pidcherga=1,
        ),
        AddressRecord(id="2", name="25 - побутові споживачі, ", cherga=3, pidcherga=1),
    ]
    houses = parse_houses(records)
    assert [(h.number, h.category) for h in houses] == [
        ("3", ConsumerCategory.LEGAL),
        ("10/2", ConsumerCategory.OTHER),
        ("25", ConsumerCategory.HOUSEHOLD),
        ("25", ConsumerCategory.HOUSEHOLD),
        ("27А", ConsumerCategory.HOUSEHOLD),
    ]
    # Same house in two records stays distinct by record id.
    assert houses[2].address_id != houses[3].address_id
