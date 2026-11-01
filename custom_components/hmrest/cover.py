"""Rollläden / Jalousien."""

from __future__ import annotations

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .entity import HmEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "cover", lambda hub, spec: HmCover(hub, spec))


def _pct(v) -> int | None:
    try:
        return max(0, min(100, round(float(v) * 100)))
    except (TypeError, ValueError):
        return None


class HmCover(HmEntity, CoverEntity):
    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "cover")
        t = spec.channel.type
        if "BLIND" in t or "LEVEL_2" in spec.channel.params:
            self._attr_device_class = CoverDeviceClass.BLIND
        elif "SHUTTER" in t:
            self._attr_device_class = CoverDeviceClass.SHUTTER
        f = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )
        if "LEVEL_2" in spec.channel.params and spec.channel.params["LEVEL_2"].writable:
            f |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
                | CoverEntityFeature.STOP_TILT
            )
        self._attr_supported_features = f

    @property
    def current_cover_position(self) -> int | None:
        p = self.spec.p("LEVEL")
        return None if p is None else _pct(p.value)

    @property
    def current_cover_tilt_position(self) -> int | None:
        p = self.spec.p("LEVEL_2")
        return None if p is None else _pct(p.value)

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        return None if pos is None else pos == 0

    def _direction(self) -> str | None:
        for name in ("ACTIVITY_STATE", "DIRECTION"):
            p = self.spec.p(name)
            if p is not None and p.value is not None:
                return str(p.enum_label(p.value)).upper()
        return None

    @property
    def is_opening(self) -> bool:
        return self._direction() == "UP"

    @property
    def is_closing(self) -> bool:
        return self._direction() == "DOWN"

    async def async_open_cover(self, **kwargs) -> None:
        await self._put("LEVEL", 1.0)

    async def async_close_cover(self, **kwargs) -> None:
        await self._put("LEVEL", 0.0)

    async def async_stop_cover(self, **kwargs) -> None:
        await self._put("STOP", True)

    async def async_set_cover_position(self, **kwargs) -> None:
        await self._put("LEVEL", kwargs[ATTR_POSITION] / 100)

    async def _tilt(self, value: float) -> None:
        pos = self.current_cover_position
        values = {"LEVEL_2": value}
        if pos is not None:
            values["LEVEL"] = pos / 100
        await self._put_many(values)

    async def async_open_cover_tilt(self, **kwargs) -> None:
        await self._tilt(1.0)

    async def async_close_cover_tilt(self, **kwargs) -> None:
        await self._tilt(0.0)

    async def async_set_cover_tilt_position(self, **kwargs) -> None:
        await self._tilt(kwargs[ATTR_TILT_POSITION] / 100)

    async def async_stop_cover_tilt(self, **kwargs) -> None:
        await self._put("STOP", True)
