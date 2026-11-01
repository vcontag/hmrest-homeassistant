"""Heizkörperthermostate und Wandthermostate (HmIP und BidCos)."""

from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_BOOST,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .entity import HmEntity, async_setup_platform

OFF_TEMP = 4.5


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "climate", lambda hub, spec: HmClimate(hub, spec))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class HmClimate(HmEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
    _attr_target_temperature_step = 0.5
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "climate")
        ps = spec.channel.params
        self._ip = "SET_POINT_TEMPERATURE" in ps
        self._sp = "SET_POINT_TEMPERATURE" if self._ip else "SET_TEMPERATURE"
        sp = ps[self._sp]
        self._attr_min_temp = _f(sp.min) or OFF_TEMP
        self._attr_max_temp = _f(sp.max) or 30.5
        f = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if "BOOST_MODE" in ps:
            f |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_NONE, PRESET_BOOST]
        self._attr_supported_features = f
        self._last_target = 20.0

    def _v(self, *names):
        for n in names:
            p = self.spec.p(n)
            if p is not None and p.value is not None:
                return p.value
        return None

    @property
    def current_temperature(self) -> float | None:
        return _f(self._v("ACTUAL_TEMPERATURE"))

    @property
    def current_humidity(self) -> float | None:
        return _f(self._v("HUMIDITY", "ACTUAL_HUMIDITY"))

    @property
    def target_temperature(self) -> float | None:
        t = _f(self._v(self._sp))
        if t is not None and t > self._attr_min_temp + 0.01:
            self._last_target = t
        return t

    def _mode_index(self) -> int | None:
        v = self._v("SET_POINT_MODE") if self._ip else self._v("CONTROL_MODE")
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @property
    def hvac_mode(self) -> HVACMode | None:
        t = self.target_temperature
        if t is not None and t <= max(OFF_TEMP, self._attr_min_temp) + 0.01:
            return HVACMode.OFF
        mode = self._mode_index()
        if mode == 0:
            return HVACMode.AUTO
        if mode is None:
            return None
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        for name in ("LEVEL", "VALVE_STATE"):
            p = self.spec.channel.params.get(name)
            if p is not None and p.type == "FLOAT" and p.value is not None:
                return HVACAction.HEATING if float(p.value) > 0 else HVACAction.IDLE
        return None

    @property
    def preset_mode(self) -> str | None:
        if "BOOST_MODE" not in self.spec.channel.params:
            return None
        if self._ip:
            return PRESET_BOOST if self._v("BOOST_MODE") else PRESET_NONE
        return PRESET_BOOST if self._mode_index() == 3 else PRESET_NONE

    async def async_set_temperature(self, **kwargs) -> None:
        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])
        if (t := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._put(self._sp, float(t))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        ps = self.spec.channel.params
        if hvac_mode == HVACMode.AUTO:
            if self._ip:
                await self._put("CONTROL_MODE", 0)
            elif "AUTO_MODE" in ps:
                await self._put("AUTO_MODE", True)
            return
        temp = OFF_TEMP if hvac_mode == HVACMode.OFF else self._last_target
        if self._ip:
            await self._put_many({"CONTROL_MODE": 1, self._sp: temp})
        elif "MANU_MODE" in ps:
            await self._put("MANU_MODE", temp)
        else:
            await self._put(self._sp, temp)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_BOOST:
            await self._put("BOOST_MODE", True)
        elif self._ip:
            await self._put("BOOST_MODE", False)
        else:
            await self.async_set_hvac_mode(HVACMode.AUTO)
