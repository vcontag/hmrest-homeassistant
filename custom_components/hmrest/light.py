"""Dimmer als Licht-Entität."""

from __future__ import annotations

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity

from .entity import HmEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "light", lambda hub, spec: HmLight(hub, spec))


class HmLight(HmEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "light")

    def _level(self) -> float | None:
        p = self.spec.p("LEVEL")
        if p is None or p.value is None:
            return None
        try:
            return max(0.0, min(1.0, float(p.value)))
        except (TypeError, ValueError):
            return None

    @property
    def is_on(self) -> bool | None:
        lv = self._level()
        return None if lv is None else lv > 0

    @property
    def brightness(self) -> int | None:
        lv = self._level()
        return None if lv is None else round(lv * 255)

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            await self._put("LEVEL", round(kwargs[ATTR_BRIGHTNESS] / 255, 3))
        elif "OLD_LEVEL" in self.spec.channel.params:
            await self._put("OLD_LEVEL", True)
        else:
            await self._put("LEVEL", 1.0)

    async def async_turn_off(self, **kwargs) -> None:
        await self._put("LEVEL", 0.0)
