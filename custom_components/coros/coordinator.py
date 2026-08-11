"""DataUpdateCoordinator for the Coros integration.

Auth/fetch layer adapted from cygnusb/coros-mcp (MIT) - see README Credits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import api
from .const import DOMAIN, UPDATE_INTERVAL_MINUTES
from .models import DailyRecord, HRVRecord, SleepRecord, StoredAuth

_LOGGER = logging.getLogger(__name__)

# Result codes Coros returns for an invalid/expired web token - these
# trigger Home Assistant's reauth flow rather than a plain retry.
_AUTH_ERROR_CODES = {"1019", "1020"}


@dataclass
class CorosData:
    """Latest fetched Coros data for one account."""

    latest_daily: DailyRecord | None
    latest_hrv: HRVRecord | None
    latest_sleep: SleepRecord | None


class CorosDataUpdateCoordinator(DataUpdateCoordinator[CorosData]):
    """Fetch Coros data on a fixed interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.entry = entry
        self.auth = StoredAuth.from_dict(entry.data["auth"])

    async def _async_update_data(self) -> CorosData:
        today = datetime.now(UTC)
        start = (today - timedelta(days=7)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")

        try:
            hrv_records = await api.fetch_hrv(self.auth)
            daily_records = await api.fetch_daily_records(self.auth, start, end)
        except api.CorosAPIError as err:
            if err.code in _AUTH_ERROR_CODES:
                raise ConfigEntryAuthFailed("Coros session expired") from err
            raise UpdateFailed(f"Coros API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Coros: {err}") from err

        sleep_records: list[SleepRecord] = []
        try:
            sleep_records = await api.fetch_sleep(self.auth, start, end)
        except Exception:
            # Sleep uses a separate mobile-API session that can go stale
            # independently of the web token - don't fail the whole update
            # over it, just skip sleep sensors this cycle.
            _LOGGER.debug("Coros sleep fetch failed this cycle", exc_info=True)

        self._persist_refreshed_mobile_token()

        return CorosData(
            latest_daily=daily_records[-1] if daily_records else None,
            latest_hrv=hrv_records[-1] if hrv_records else None,
            latest_sleep=sleep_records[-1] if sleep_records else None,
        )

    def _persist_refreshed_mobile_token(self) -> None:
        """Write back a refreshed mobile token if fetch_sleep minted one."""
        stored = self.entry.data.get("auth", {})
        if self.auth.mobile_access_token != stored.get("mobile_access_token"):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, "auth": self.auth.as_dict()},
            )
