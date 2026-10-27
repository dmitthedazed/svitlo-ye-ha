"""Tests for the config and options flows."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.svitlo_ye.const import (
    BASE_URL,
    CONF_CHERGA,
    CONF_CITY_ID,
    CONF_HOUSE,
    CONF_PIDCHERGA,
    CONF_REM_ID,
    CONF_SCAN_INTERVAL,
    CONF_STREET_ID,
    CONF_STREET_SEARCH,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import mock_schedule

HOUSE_KEY = "388680|1|legal"


async def _walk_to_house(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_REM_ID: "7"})
    assert result["step_id"] == "city"
    assert result["description_placeholders"] == {"rem": "Житомирський"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CITY_ID: "16657"}
    )
    assert result["step_id"] == "street"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET_ID: "173934"}
    )
    assert result["step_id"] == "house"
    return result["flow_id"]


async def test_full_flow(hass: HomeAssistant, mock_location_api: AiohttpClientMocker) -> None:
    """REM -> city -> street -> house creates an entry with the queue."""
    mock_schedule(mock_location_api)
    flow_id = await _walk_to_house(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_HOUSE: HOUSE_KEY, CONF_NAME: "Офіс"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Офіс"
    assert result["data"][CONF_CHERGA] == 1
    assert result["data"][CONF_PIDCHERGA] == 2
    assert result["data"][CONF_HOUSE] == "1"
    assert result["result"].unique_id == HOUSE_KEY


async def test_default_title_and_duplicate(
    hass: HomeAssistant, mock_location_api: AiohttpClientMocker
) -> None:
    """Without a name the title is street + house; the same house aborts."""
    mock_schedule(mock_location_api)
    flow_id = await _walk_to_house(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_HOUSE: HOUSE_KEY})
    await hass.async_block_till_done()
    assert result["title"] == "вул. Київська, 1"

    flow_id = await _walk_to_house(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_HOUSE: HOUSE_KEY})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_street_search(hass: HomeAssistant, mock_location_api: AiohttpClientMocker) -> None:
    """Long street lists are narrowed down by a search step."""
    with patch("custom_components.svitlo_ye.config_flow.STREET_SEARCH_THRESHOLD", 5):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REM_ID: "7"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CITY_ID: "16657"}
        )
        assert result["step_id"] == "street_search"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STREET_SEARCH: "неіснуюча"}
        )
        assert result["errors"] == {CONF_STREET_SEARCH: "no_street_match"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STREET_SEARCH: "ВУЛ. київськ"}
        )
        assert result["step_id"] == "street"
        options = result["data_schema"].schema[CONF_STREET_ID].config["options"]
        assert options == [{"value": "173934", "label": "вул. Київська"}]


async def test_cannot_connect_on_start(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """If the REM list cannot be loaded, the flow aborts."""
    aioclient_mock.get(f"{BASE_URL}api-rem.php", exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_cannot_connect_mid_flow_and_recover(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failing step shows an error and can be retried."""
    from .conftest import load_text

    aioclient_mock.get(f"{BASE_URL}api-rem.php", text=load_text("rem.json"))
    aioclient_mock.get(f"{BASE_URL}api-city.php?rem_id=7", status=500)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_REM_ID: "7"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}api-city.php?rem_id=7", text=load_text("city.json"))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_REM_ID: "7"})
    assert result["step_id"] == "city"


async def test_no_houses(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A street without houses shows an error."""
    from .conftest import load_text

    aioclient_mock.get(f"{BASE_URL}api-rem.php", text=load_text("rem.json"))
    aioclient_mock.get(f"{BASE_URL}api-city.php?rem_id=7", text=load_text("city.json"))
    aioclient_mock.get(f"{BASE_URL}api-street.php?city_id=16657", text=load_text("street.json"))
    aioclient_mock.get(f"{BASE_URL}api-address.php?street_id=173934", json=[])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_REM_ID: "7"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CITY_ID: "16657"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET_ID: "173934"}
    )
    assert result["step_id"] == "street"
    assert result["errors"] == {"base": "no_houses"}


async def test_options_flow(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The polling interval is configurable and applied after reload."""
    mock_schedule(aioclient_mock)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 30}
    coordinator = config_entry.runtime_data.coordinator
    assert coordinator.update_interval.total_seconds() == 30 * 60
