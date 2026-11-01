"""Schalter: Schaltaktoren (STATE) und beschreibbare BOOL-Datenpunkte."""

from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

from .sysvar import HmSysVarSwitch, async_setup_sysvar_platform
from .entity import HmEntity, HmParamEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(hub, spec):
        if spec.kind == "switch":
            return HmSwitch(hub, spec)
        return HmBoolSwitch(hub, spec)

    async_setup_platform(hass, entry, async_add_entities, "switch", factory)
    async_setup_sysvar_platform(hass, entry, async_add_entities, "switch", HmSysVarSwitch)


class HmSwitch(HmEntity, SwitchEntity):
    """Schaltaktor-Kanal (bei HmIP: Status aus dem Senderkanal)."""

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "switch")
        self._attr_device_class = SwitchDeviceClass.OUTLET if "PS" in spec.device.type else SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        p = self.spec.p("STATE")
        return None if p is None or p.value is None else bool(p.value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._put("STATE", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._put("STATE", False)


class HmBoolSwitch(HmParamEntity, SwitchEntity):
    """Beliebiger beschreibbarer BOOL-Datenpunkt."""

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "switch")

    @property
    def is_on(self) -> bool | None:
        v = self.param.value
        return None if v is None else bool(v)

    async def async_turn_on(self, **kwargs) -> None:
        await self._put(self.param.name, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._put(self.param.name, False)
