"""Config flow for SvitloYE: REM -> settlement -> street -> house, like the app."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import (
    ConsumerCategory,
    House,
    Named,
    SvitloYeApiClient,
    SvitloYeError,
    parse_houses,
)
from .const import (
    CONF_ADDRESS_ID,
    CONF_CHERGA,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_HOUSE,
    CONF_HOUSE_CATEGORY,
    CONF_PIDCHERGA,
    CONF_REM_ID,
    CONF_REM_NAME,
    CONF_SCAN_INTERVAL,
    CONF_STREET_ID,
    CONF_STREET_NAME,
    CONF_STREET_SEARCH,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL_MIN,
    MIN_SCAN_INTERVAL_MIN,
    STREET_SEARCH_THRESHOLD,
)

_CATEGORY_LABEL = {
    ConsumerCategory.HOUSEHOLD: "",
    ConsumerCategory.LEGAL: " (юридичні)",
    ConsumerCategory.OTHER: " (інше)",
}


def _select(items: list[Named]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=i.id, label=i.name) for i in items],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _house_label(house: House) -> str:
    queue = f"черга {house.cherga}.{house.pidcherga}" if house.cherga > 0 else "черга не визначена"
    return f"{house.number}{_CATEGORY_LABEL[house.category]} — {queue}"


def _name_of(items: list[Named], item_id: str) -> str:
    return next((i.name for i in items if i.id == item_id), item_id)


class SvitloYeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SvitloYE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._client: SvitloYeApiClient | None = None
        self._data: dict[str, Any] = {}
        self._rems: list[Named] = []
        self._cities: list[Named] = []
        self._streets: list[Named] = []
        self._street_options: list[Named] = []
        self._houses: list[House] = []

    @property
    def client(self) -> SvitloYeApiClient:
        """Return the API client."""
        if self._client is None:
            self._client = SvitloYeApiClient(async_get_clientsession(self.hass))
        return self._client

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SvitloYeOptionsFlow:
        """Return the options flow."""
        return SvitloYeOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick another address for an existing entry."""
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the REM (regional unit)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            rem_id = user_input[CONF_REM_ID]
            try:
                self._cities = await self.client.async_get_cities(rem_id)
            except SvitloYeError as err:
                LOGGER.debug("Cannot load cities: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not self._cities:
                    errors["base"] = "no_cities"
                else:
                    self._data[CONF_REM_ID] = rem_id
                    self._data[CONF_REM_NAME] = _name_of(self._rems, rem_id)
                    return await self.async_step_city()

        if not self._rems:
            try:
                self._rems = await self.client.async_get_rems()
            except SvitloYeError as err:
                LOGGER.debug("Cannot load REMs: %s", err)
                return self.async_abort(reason="cannot_connect")
            if not self._rems:
                return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_REM_ID): _select(self._rems)}),
            errors=errors,
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the settlement."""
        errors: dict[str, str] = {}
        if user_input is not None:
            city_id = user_input[CONF_CITY_ID]
            try:
                self._streets = await self.client.async_get_streets(city_id)
            except SvitloYeError as err:
                LOGGER.debug("Cannot load streets: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not self._streets:
                    errors["base"] = "no_streets"
                else:
                    self._data[CONF_CITY_ID] = city_id
                    self._data[CONF_CITY_NAME] = _name_of(self._cities, city_id)
                    if len(self._streets) > STREET_SEARCH_THRESHOLD:
                        return await self.async_step_street_search()
                    self._street_options = self._streets
                    return await self.async_step_street()

        return self.async_show_form(
            step_id="city",
            data_schema=vol.Schema({vol.Required(CONF_CITY_ID): _select(self._cities)}),
            errors=errors,
            description_placeholders={"rem": self._data.get(CONF_REM_NAME, "")},
        )

    async def async_step_street_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Narrow down a long list of streets by a part of the name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input.get(CONF_STREET_SEARCH, "")).strip().casefold()
            matches = [s for s in self._streets if query in s.name.casefold()]
            if matches:
                self._street_options = matches
                return await self.async_step_street()
            errors[CONF_STREET_SEARCH] = "no_street_match"

        return self.async_show_form(
            step_id="street_search",
            data_schema=vol.Schema({vol.Optional(CONF_STREET_SEARCH, default=""): TextSelector()}),
            errors=errors,
            description_placeholders={
                "city": self._data.get(CONF_CITY_NAME, ""),
                "count": str(len(self._streets)),
            },
        )

    async def async_step_street(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the street."""
        errors: dict[str, str] = {}
        if user_input is not None:
            street_id = user_input[CONF_STREET_ID]
            try:
                records = await self.client.async_get_addresses(street_id)
            except SvitloYeError as err:
                LOGGER.debug("Cannot load addresses: %s", err)
                errors["base"] = "cannot_connect"
            else:
                self._houses = parse_houses(records)
                if not self._houses:
                    errors["base"] = "no_houses"
                else:
                    self._data[CONF_STREET_ID] = street_id
                    self._data[CONF_STREET_NAME] = _name_of(self._streets, street_id)
                    return await self.async_step_house()

        return self.async_show_form(
            step_id="street",
            data_schema=vol.Schema({vol.Required(CONF_STREET_ID): _select(self._street_options)}),
            errors=errors,
            description_placeholders={"city": self._data.get(CONF_CITY_NAME, "")},
        )

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the house and an optional name."""
        if user_input is not None:
            house = next(h for h in self._houses if h.key == user_input[CONF_HOUSE])
            if self.source != SOURCE_RECONFIGURE:
                await self.async_set_unique_id(house.key.casefold())
                self._abort_if_unique_id_configured()
            else:
                entry = self._get_reconfigure_entry()
                if any(
                    other.unique_id == house.key.casefold()
                    for other in self._async_current_entries()
                    if other.entry_id != entry.entry_id
                ):
                    return self.async_abort(reason="already_configured")
            data = {
                **self._data,
                CONF_ADDRESS_ID: house.address_id,
                CONF_HOUSE: house.number,
                CONF_HOUSE_CATEGORY: house.category.value,
                CONF_CHERGA: house.cherga,
                CONF_PIDCHERGA: house.pidcherga,
            }
            title = str(user_input.get(CONF_NAME) or "").strip() or (
                f"{self._data[CONF_STREET_NAME]}, {house.number}"
            )
            if self.source == SOURCE_RECONFIGURE:
                # unique_id stays the same so entity and device ids remain stable.
                return self.async_update_reload_and_abort(entry, title=title, data=data)
            return self.async_create_entry(title=title, data=data)

        options = [SelectOptionDict(value=h.key, label=_house_label(h)) for h in self._houses]
        return self.async_show_form(
            step_id="house",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOUSE): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Optional(CONF_NAME): TextSelector(),
                }
            ),
            description_placeholders={"street": self._data.get(CONF_STREET_NAME, "")},
        )


class SvitloYeOptionsFlow(OptionsFlow):
    """Options: polling interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MIN,
                            max=MAX_SCAN_INTERVAL_MIN,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    )
                }
            ),
        )
