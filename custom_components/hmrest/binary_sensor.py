"""Binärsensoren für BOOL-Datenpunkte und Fensterkontakte."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import HmParamEntity, async_setup_platform

DEVICE_CLASS = {
    "LOW_BAT": BinarySensorDeviceClass.BATTERY,
    "LOWBAT": BinarySensorDeviceClass.BATTERY,
    "UNREACH": BinarySensorDeviceClass.PROBLEM,
    "STICKY_UNREACH": BinarySensorDeviceClass.PROBLEM,
    "MOTION": BinarySensorDeviceClass.MOTION,
    "PRESENCE_DETECTION_STATE": BinarySensorDeviceClass.PRESENCE,
    "RAINING": BinarySensorDeviceClass.MOISTURE,
    "MOISTURE_DETECTED": BinarySensorDeviceClass.MOISTURE,
    "WATERLEVEL_DETECTED": BinarySensorDeviceClass.MOISTURE,
    "SABOTAGE": BinarySensorDeviceClass.TAMPER,
    "ERROR_SABOTAGE": BinarySensorDeviceClass.TAMPER,
    "DUTY_CYCLE": BinarySensorDeviceClass.PROBLEM,
    "UPDATE_PENDING": BinarySensorDeviceClass.UPDATE,
    "WINDOW_STATE": BinarySensorDeviceClass.WINDOW,
    "SMOKE_ALARM": BinarySensorDeviceClass.SMOKE,
    "ALARMSTATE": BinarySensorDeviceClass.SAFETY,
    "DEW_POINT_ALARM": BinarySensorDeviceClass.MOISTURE,
}

CONTACT_TYPES = ("SHUTTER_CONTACT", "ROTARY_HANDLE", "CONTACT")


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "binary_sensor", lambda hub, spec: HmBinarySensor(hub, spec))


class HmBinarySensor(HmParamEntity, BinarySensorEntity):
    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "binary_sensor")
        name = self.param.name
        dc = DEVICE_CLASS.get(name)
        if dc is None and self.param.name == "STATE" and any(t in spec.channel.type for t in CONTACT_TYPES):
            dc = BinarySensorDeviceClass.OPENING
        if dc is None and name.startswith("ERROR_"):
            dc = BinarySensorDeviceClass.PROBLEM
        self._attr_device_class = dc

    @property
    def is_on(self) -> bool | None:
        p = self.param
        v = p.value
        if v is None:
            return None
        if p.type == "ENUM":
            return str(p.enum_label(v)).upper() == "OPEN"
        if isinstance(v, str):
            return v.lower() in ("1", "true", "on", "yes")
        return bool(v)
