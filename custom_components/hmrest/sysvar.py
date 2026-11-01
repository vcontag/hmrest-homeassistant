"""Systemvariablen der CCU als Entitäten.

Die CCU meldet Systemvariablen nicht per Event; sie werden zyklisch über
/api/sysvars abgefragt und nach jedem Schreiben aus HA sofort aktualisiert.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN, ENTITY_PREFIX
from .hub import HmRestError, HmRestHub, HmSysVar

PLATFORM_BY_TYPE = {
    "bool": "switch",
    "alarm": "switch",
    "float": "number",
    "integer": "number",
    "enum": "select",
    "string": "text",
}


def sysvar_platform(sv: HmSysVar) -> str:
    if sv.type == "enum" and not sv.value_list:
        return "number"
    return PLATFORM_BY_TYPE.get(sv.type, "text")


def async_setup_sysvar_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    factory: Callable[[HmRestHub, HmSysVar], Entity],
) -> None:
    hub: HmRestHub = entry.runtime_data
    if not hub.sysvars_enabled:
        return

    @callback
    def add(sv: HmSysVar) -> None:
        if sysvar_platform(sv) == platform:
            async_add_entities([factory(hub, sv)])

    for sv in list(hub.sysvars.values()):
        add(sv)
    entry.async_on_unload(hub.register_sysvar_callback(add))


class HmSysVarEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hub: HmRestHub, sv: HmSysVar, platform: str) -> None:
        self.hub = hub
        self.sv = sv
        self._attr_unique_id = f"{hub.entry.entry_id}:sysvar:{sv.id}"
        self.entity_id = f"{platform}.{ENTITY_PREFIX}_sysvar_{slugify(sv.name) or sv.id}"
        self._attr_name = sv.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{hub.entry.entry_id}_sysvars")},
            name="CCU Systemvariablen",
            manufacturer="eQ-3",
            model="Systemvariablen (ReGaHss)",
            configuration_url=hub.api.base,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.subscribe_sysvar(self.sv.id, self._updated))
        self.async_on_remove(self.hub.subscribe_connection(self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.hub.sysvars_ok and not self.sv.removed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"sysvar_id": self.sv.id, "sysvar_type": self.sv.type}
        if self.sv.timestamp:
            attrs["last_change_ccu"] = self.sv.timestamp
        return attrs

    async def _set(self, value: Any) -> None:
        try:
            await self.hub.async_set_sysvar(self.sv.id, value)
        except HmRestError as err:
            raise HomeAssistantError(f"Systemvariable {self.sv.name}: {err}") from err


class HmSysVarSwitch(HmSysVarEntity, SwitchEntity):
    def __init__(self, hub, sv) -> None:
        super().__init__(hub, sv, "switch")
        self._attr_icon = "mdi:alarm-light" if sv.type == "alarm" else "mdi:variable"

    @property
    def is_on(self) -> bool | None:
        v = self.sv.value
        if v is None:
            return None
        if isinstance(v, str):
            return v.lower() in ("true", "1", "on")
        return bool(v)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        text = self.sv.name1 if self.is_on else self.sv.name0
        if text:
            attrs["anzeige"] = text
        return attrs

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class HmSysVarNumber(HmSysVarEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:variable"

    def __init__(self, hub, sv) -> None:
        super().__init__(hub, sv, "number")
        lo, hi = _f(sv.min), _f(sv.max)
        if lo is None or hi is None or lo >= hi:
            lo, hi = -1_000_000.0, 1_000_000.0
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = 0.01 if sv.type == "float" else 1.0
        if sv.unit:
            self._attr_native_unit_of_measurement = sv.unit

    @property
    def native_value(self) -> float | None:
        v = _f(self.sv.value)
        if v is None:
            return None
        return v if self.sv.type == "float" else int(v)

    async def async_set_native_value(self, value: float) -> None:
        await self._set(value if self.sv.type == "float" else int(round(value)))


class HmSysVarSelect(HmSysVarEntity, SelectEntity):
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, hub, sv) -> None:
        super().__init__(hub, sv, "select")

    @property
    def options(self) -> list[str]:
        return list(self.sv.value_list or [])

    @property
    def current_option(self) -> str | None:
        try:
            return self.options[int(self.sv.value)]
        except (TypeError, ValueError, IndexError):
            return None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise HomeAssistantError(f"Unbekannte Option {option}")
        await self._set(self.options.index(option))


class HmSysVarText(HmSysVarEntity, TextEntity):
    _attr_native_max = 255
    _attr_icon = "mdi:form-textbox"

    def __init__(self, hub, sv) -> None:
        super().__init__(hub, sv, "text")

    @property
    def native_value(self) -> str | None:
        v = self.sv.value
        if v is None:
            return None
        return str(v)[:255]

    async def async_set_value(self, value: str) -> None:
        if '"' in value or "\\" in value:
            raise HomeAssistantError('Die Zeichen " und \\ sind in Systemvariablen nicht erlaubt')
        await self._set(value)
