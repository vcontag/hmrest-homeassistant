"""Text-Entitäten für beschreibbare STRING-Datenpunkte (z.B. Display-Texte)."""

from __future__ import annotations

from homeassistant.components.text import TextEntity

from .sysvar import HmSysVarText, async_setup_sysvar_platform
from .entity import HmParamEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "text", lambda hub, spec: HmText(hub, spec))
    async_setup_sysvar_platform(hass, entry, async_add_entities, "text", HmSysVarText)


class HmText(HmParamEntity, TextEntity):
    _attr_native_max = 255

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "text")

    @property
    def native_value(self) -> str | None:
        v = self.param.value
        return None if v is None else str(v)

    async def async_set_value(self, value: str) -> None:
        await self._put(self.param.name, value)
