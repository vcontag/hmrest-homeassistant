"""Select-Entitäten für beschreibbare ENUM-Datenpunkte."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .sysvar import HmSysVarSelect, async_setup_sysvar_platform
from .entity import HmParamEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(hub, spec):
        p = spec.channel.params[spec.param]
        return HmSelect(hub, spec) if p.value_list else None

    async_setup_platform(hass, entry, async_add_entities, "select", factory)
    async_setup_sysvar_platform(hass, entry, async_add_entities, "select", HmSysVarSelect)


class HmSelect(HmParamEntity, SelectEntity):
    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "select")
        self._attr_options = [str(v) for v in self.param.value_list or []]

    @property
    def current_option(self) -> str | None:
        label = self.param.enum_label(self.param.value)
        return label if label in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError(f"Unbekannte Option {option}")
        await self._put(self.param.name, self.param.enum_offset + self._attr_options.index(option))
