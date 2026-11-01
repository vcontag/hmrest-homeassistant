"""Basisklasse und Hilfsfunktionen für alle HM-REST-Entitäten."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import HmDevice, HmParam, HmRestError, HmRestHub
from .mapping import Spec, build_specs

_LOGGER = logging.getLogger(__name__)


def async_setup_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    factory: Callable[[HmRestHub, Spec], Entity | None],
) -> None:
    """Entitäten einer Plattform für alle (auch später neue) Geräte anlegen."""
    hub: HmRestHub = entry.runtime_data

    @callback
    def add_device(dev: HmDevice) -> None:
        ents = []
        for spec in build_specs(dev):
            if spec.platform != platform:
                continue
            ent = factory(hub, spec)
            if ent is not None:
                ents.append(ent)
        if ents:
            async_add_entities(ents)

    for dev in list(hub.devices.values()):
        add_device(dev)
    entry.async_on_unload(hub.register_device_callback(add_device))


def scale(p: HmParam | None) -> float:
    """HomeMatic „100%" = Werte 0…1 -> Faktor 100."""
    return 100.0 if p is not None and p.unit == "100%" else 1.0


class HmEntity(Entity):
    """Gemeinsame Logik: Gerätezuordnung, Verfügbarkeit, Event-Abo."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hub: HmRestHub, spec: Spec, platform: str) -> None:
        self.hub = hub
        self.spec = spec
        dev = spec.device
        self._attr_unique_id = spec.unique_id
        self.entity_id = f"{platform}.{spec.object_id}"
        self._attr_name = spec.name
        self._attr_entity_registry_enabled_default = spec.enabled
        if spec.category == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif spec.category == "config":
            self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev.address)},
            name=dev.title,
            manufacturer="eQ-3",
            model=dev.type,
            sw_version=dev.firmware,
            suggested_area=dev.area,
            serial_number=dev.address,
            configuration_url=hub.api.base,
        )

    # Welche (Kanal, Parameter) beobachtet werden; Unterklassen können erweitern
    def watched(self) -> list[tuple[str, str]]:
        out = []
        for ch in {self.spec.channel.address: self.spec.channel, self.spec.state.address: self.spec.state}.values():
            for name in ch.params:
                out.append((ch.address, name))
        return out

    async def async_added_to_hass(self) -> None:
        for addr, param in self.watched():
            self.async_on_remove(self.hub.subscribe(addr, param, self._updated))
        self.async_on_remove(self.hub.subscribe(f"{self.spec.device.address}:0", "UNREACH", self._updated))
        self.async_on_remove(self.hub.subscribe_connection(self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not self.hub.connected:
            return False
        if self.spec.param in ("UNREACH", "STICKY_UNREACH"):
            return True
        return not self.spec.device.unreach

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {"address": self.spec.channel.address, "interface": self.spec.device.interface}
        if self.spec.param:
            attrs["parameter"] = self.spec.param
        return attrs

    # ---------- Schreiben ----------

    async def _put(self, param: str, value: Any, address: str | None = None) -> None:
        try:
            await self.hub.async_set_value(address or self.spec.channel.address, param, value)
        except HmRestError as err:
            raise HomeAssistantError(f"HomeMatic: {err}") from err

    async def _put_many(self, values: dict[str, Any], address: str | None = None) -> None:
        try:
            await self.hub.async_set_values(address or self.spec.channel.address, values)
        except HmRestError as err:
            raise HomeAssistantError(f"HomeMatic: {err}") from err


class HmParamEntity(HmEntity):
    """Entität für genau einen Datenpunkt."""

    @property
    def param(self) -> HmParam:
        return self.spec.channel.params[self.spec.param]  # type: ignore[index]

    def watched(self) -> list[tuple[str, str]]:
        return [(self.spec.channel.address, self.spec.param)]  # type: ignore[list-item]
