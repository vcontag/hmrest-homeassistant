"""Buttons für ACTION-Datenpunkte (z.B. STOP, Tastendruck an der CCU)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import HmParamEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "button", lambda hub, spec: HmButton(hub, spec))


class HmButton(HmParamEntity, ButtonEntity):
    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "button")

    async def async_press(self) -> None:
        await self._put(self.param.name, True)
