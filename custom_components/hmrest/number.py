"""Number-Entitäten für beschreibbare FLOAT/INTEGER-Datenpunkte."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode

from .sysvar import HmSysVarNumber, async_setup_sysvar_platform
from .entity import HmParamEntity, async_setup_platform, scale
from .sensor import UNITS


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "number", lambda hub, spec: HmNumber(hub, spec))
    async_setup_sysvar_platform(hass, entry, async_add_entities, "number", HmSysVarNumber)


def _f(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class HmNumber(HmParamEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "number")
        p = self.param
        k = scale(p)
        self._attr_native_min_value = _f(p.min, 0.0) * k
        self._attr_native_max_value = _f(p.max, 100.0) * k
        if p.type == "INTEGER" or k != 1:
            self._attr_native_step = 1.0
        elif p.unit in ("°C", "°F"):
            self._attr_native_step = 0.5
        else:
            self._attr_native_step = 0.1
        if p.unit:
            self._attr_native_unit_of_measurement = UNITS.get(p.unit, p.unit)

    @property
    def native_value(self) -> float | None:
        p = self.param
        if p.value is None:
            return None
        try:
            return round(float(p.value) * scale(p), 2)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        p = self.param
        v = value / scale(p)
        await self._put(p.name, int(round(v)) if p.type == "INTEGER" else v)
