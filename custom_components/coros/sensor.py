"""Sensor platform for the Coros integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CorosData, CorosDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class CorosSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[CorosData], Any]


def _sleep_phase(data: CorosData, field: str) -> int | None:
    if data.latest_sleep is None or data.latest_sleep.phases is None:
        return None
    return getattr(data.latest_sleep.phases, field)


SENSOR_TYPES: tuple[CorosSensorEntityDescription, ...] = (
    CorosSensorEntityDescription(
        key="hrv",
        translation_key="hrv",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.latest_hrv.avg_sleep_hrv if d.latest_hrv else None,
    ),
    CorosSensorEntityDescription(
        key="resting_heart_rate",
        translation_key="resting_heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.latest_daily.rhr if d.latest_daily else None,
    ),
    CorosSensorEntityDescription(
        key="training_load",
        translation_key="training_load",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.latest_daily.training_load if d.latest_daily else None,
    ),
    CorosSensorEntityDescription(
        key="base_fitness",
        translation_key="base_fitness",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.latest_daily.cti if d.latest_daily else None,
    ),
    CorosSensorEntityDescription(
        key="load_impact",
        translation_key="load_impact",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.latest_daily.ati if d.latest_daily else None,
    ),
    CorosSensorEntityDescription(
        key="fatigue",
        translation_key="fatigue",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.latest_daily.tired_rate if d.latest_daily else None,
    ),
    CorosSensorEntityDescription(
        key="training_load_ratio",
        translation_key="training_load_ratio",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.latest_daily.training_load_ratio if d.latest_daily else None,
    ),
    CorosSensorEntityDescription(
        key="sleep_duration",
        translation_key="sleep_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.latest_sleep.total_duration_minutes if d.latest_sleep else None,
    ),
    CorosSensorEntityDescription(
        key="sleep_deep_minutes",
        translation_key="sleep_deep_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _sleep_phase(d, "deep_minutes"),
    ),
    CorosSensorEntityDescription(
        key="sleep_light_minutes",
        translation_key="sleep_light_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _sleep_phase(d, "light_minutes"),
    ),
    CorosSensorEntityDescription(
        key="sleep_rem_minutes",
        translation_key="sleep_rem_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _sleep_phase(d, "rem_minutes"),
    ),
    CorosSensorEntityDescription(
        key="sleep_awake_minutes",
        translation_key="sleep_awake_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _sleep_phase(d, "awake_minutes"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CorosDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CorosSensor(coordinator, description, entry) for description in SENSOR_TYPES)


class CorosSensor(CoordinatorEntity[CorosDataUpdateCoordinator], SensorEntity):
    """Representation of a single Coros metric."""

    entity_description: CorosSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CorosDataUpdateCoordinator,
        description: CorosSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_EMAIL, "Coros"),
            manufacturer="Coros",
            model="Training Hub",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)
