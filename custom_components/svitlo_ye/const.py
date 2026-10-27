"""Constants for the SvitloYE (Zhytomyroblenergo outage schedule) integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "svitlo_ye"
LOGGER = logging.getLogger(__package__)

BASE_URL: Final = "https://www.ztoe.com.ua/gpv/api/"
REQUEST_TIMEOUT: Final = 30

# The schedule (dates, spans and server headers) is published in Kyiv time.
SCHEDULE_TZ: Final = ZoneInfo("Europe/Kyiv")

CONF_REM_ID: Final = "rem_id"
CONF_REM_NAME: Final = "rem_name"
CONF_CITY_ID: Final = "city_id"
CONF_CITY_NAME: Final = "city_name"
CONF_STREET_ID: Final = "street_id"
CONF_STREET_NAME: Final = "street_name"
CONF_STREET_SEARCH: Final = "street_search"
CONF_ADDRESS_ID: Final = "address_id"
CONF_HOUSE: Final = "house"
CONF_HOUSE_CATEGORY: Final = "house_category"
CONF_CHERGA: Final = "cherga"
CONF_PIDCHERGA: Final = "pidcherga"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL_MIN: Final = 15
MIN_SCAN_INTERVAL_MIN: Final = 5
MAX_SCAN_INTERVAL_MIN: Final = 180

# Above this number of streets the config flow asks for a search string first.
STREET_SEARCH_THRESHOLD: Final = 60

MANUFACTURER: Final = "АТ «Житомиробленерго»"
CONFIGURATION_URL: Final = "https://www.ztoe.com.ua/"


def default_scan_interval() -> timedelta:
    """Return the default polling interval."""
    return timedelta(minutes=DEFAULT_SCAN_INTERVAL_MIN)


# Consecutive failed polls before a repair issue is raised (~3 h at the default interval).
FAILURES_BEFORE_ISSUE: Final = 12
ISSUE_API_UNAVAILABLE: Final = "api_unavailable"
