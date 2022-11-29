"""Support for Big Ass Fans number."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional, cast

from homeassistant import config_entries
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode, DOMAIN as NUMBER_DOMAIN

from homeassistant.const import (
    PERCENTAGE,
    ELECTRIC_POTENTIAL_VOLT,
    UnitOfPower,
    ELECTRIC_CURRENT_AMPERE
)

import math

from homeassistant.const import TIME_SECONDS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import victronEnergyDeviceUpdateCoordinator
from .const import DOMAIN, register_info_dict, SliderWriteType, CONF_ADVANCED_OPTIONS

from homeassistant.helpers.typing import StateType
from homeassistant.helpers import entity

import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up victron switch devices."""
    victron_coordinator: victronEnergyDeviceUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("attempting to setup number entities")
    descriptions = []
    _LOGGER.debug(config_entry)
    #TODO cleanup
    if config_entry.options[CONF_ADVANCED_OPTIONS]:
        register_set = victron_coordinator.processed_data()["register_set"]
        for unit, registerLedger in register_set.items():
            for name in registerLedger:
                for register_name, registerInfo in register_info_dict[name].items():
                    # _LOGGER.debug("unit == " + str(unit) + " registerLedger == " + str(registerLedger) + " registerInfo ")
                    # _LOGGER.debug(str(registerInfo.unit))
                    # _LOGGER.debug("register_name")
                    # _LOGGER.debug(register_name)
                    if isinstance(registerInfo.writeType, SliderWriteType):
                        descriptions.append(VictronEntityDescription(
                            key=register_name,
                            name=register_name.replace('_', ' '),
                            value_fn=lambda data, unit, key: data["data"][str(unit) + "." + str(key)],
                            slave=unit,
                            native_unit_of_measurement=registerInfo.unit,
                            register_ledger_key=name,
                            # native_min_value=registerInfo.writeType.lowerLimit,
                            # native_max_value=registerInfo.writeType.upperLimit,
                            native_min_value=determine_min_value(registerInfo.unit, victron_coordinator),
                            native_max_value=determine_max_value(registerInfo.unit, victron_coordinator),
                            entity_category=EntityCategory.CONFIG,
                            address=registerInfo.register
                        ))

    entities = []
    entity = {}
    for description in descriptions:
        entity = description
        entities.append(
            VictronNumber(
                victron_coordinator,
                entity
                ))
    _LOGGER.debug("adding number")
    async_add_entities(entities)
    _LOGGER.debug("adding numbering")


def determine_min_value(unit, coordinator: victronEnergyDeviceUpdateCoordinator) -> int:
    if unit == PERCENTAGE:
        return 0
    elif unit == ELECTRIC_POTENTIAL_VOLT:
        series_type = coordinator.dc_voltage / 3 #statically based on lifepo4 cells
        min_value = series_type * 2.5 #statically based on lifepo4 cells
        return min_value
    elif unit == UnitOfPower.WATT:
        min_value = -(coordinator.ac_voltage * coordinator.ac_current)
        rounded_min = round(min_value/100)*100
        return rounded_min
    elif unit == ELECTRIC_CURRENT_AMPERE:
        return 0
    else:
        return 0

#TODO determine if AC or DC min/max is applicable
#TODO perhaps remove min / max base data from coordinator
def determine_max_value(unit, coordinator) -> int:
    if unit == PERCENTAGE:
        return 100
    elif unit == ELECTRIC_POTENTIAL_VOLT:
        series_type = coordinator.dc_voltage / 3 #statically based on lifepo4 cells
        max_value = series_type * 3.65 #statically based on lifepo4 cells
        return max_value
    elif unit == UnitOfPower.WATT:
        max_value = (coordinator.ac_voltage * coordinator.ac_current)
        rounded_max = round(max_value/100)*100
        return rounded_max
    elif unit == ELECTRIC_CURRENT_AMPERE:
        return coordinator.ac_current
    else:
        return 0


@dataclass
class VictronNumberMixin:
    """A class that describes number entities."""
    slave: int
    value_fn: Callable[[dict], StateType]
    register_ledger_key: str
    address: int

@dataclass
class VictronEntityDescription(NumberEntityDescription, VictronNumberMixin):
    """Describes victron number entity."""
    #TODO write unit references into this class and convert to base for all entity types


class VictronNumber(NumberEntity):
    """Victron number."""

    entity_description: VictronEntityDescription

    def __init__(self, coordinator: victronEnergyDeviceUpdateCoordinator, description: VictronEntityDescription) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self.entity_description = description
        #this needs to be changed to allow multiple of the same type
        self._attr_name = f"{description.name}"

        self.data_key = str(self.entity_description.slave) + "." + str(self.entity_description.key)

        self._attr_native_value = self.entity_description.value_fn(self.coordinator.processed_data(), self.entity_description.slave, self.entity_description.key)

        self._attr_unique_id = f"{self.entity_description.slave}_{self.entity_description.key}"
        if self.entity_description.slave not in (100, 225):
            self.entity_id = f"{NUMBER_DOMAIN}.{DOMAIN}_{self.entity_description.key}_{self.entity_description.slave}"
        else:
            self.entity_id = f"{NUMBER_DOMAIN}.{DOMAIN}_{self.entity_description.key}"

        self._attr_mode = NumberMode.SLIDER
  


    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        #TODO convert float to int again with scale respected
        if value < 0:
            value = 65535 + value
        self.coordinator.write_register(unit=self.entity_description.slave, address=self.entity_description.address, value=int(value))
        await self.coordinator.async_update_local_entry(self.data_key, int(value))


    @property
    def native_value(self) -> int:
        """Return the state of the entity."""
        value = self.entity_description.value_fn(data=self.coordinator.processed_data(), unit=self.entity_description.slave, key=self.entity_description.key)
        _LOGGER.debug(value)
        if value > 32767:
            #TODO remove magic numbers
            value = value - 65535
        return value

    @property
    def native_step(self) -> float | None:
        max = self.native_max_value
        min = self.native_min_value
        gap = len(list(range(int(min), int(max), 1)))
        if gap >= 3000:
            return 100
        elif gap < 3000 and gap > 100:
            return 10
        else:
            return 1

    @property
    def native_min_value(self) -> float:
        return self.entity_description.native_min_value

    @property
    def native_max_value(self) -> float:
        return self.entity_description.native_max_value

    @property
    def device_info(self) -> entity.DeviceInfo:
        """Return the device info."""
        return entity.DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.unique_id.split('_')[0])
            },
            name=self.unique_id.split('_')[1],
            model=self.unique_id.split('_')[0],
            manufacturer="victron", # to be dynamically set for gavazzi and redflow
        )