"""Sensoren für lesbare HomeMatic-Datenpunkte."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    DEGREE,
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfLength,
    UnitOfPower,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)

from .entity import HmParamEntity, async_setup_platform, scale

UNITS = {
    "°C": UnitOfTemperature.CELSIUS,
    "°F": UnitOfTemperature.FAHRENHEIT,
    "%": PERCENTAGE,
    "100%": PERCENTAGE,
    "W": UnitOfPower.WATT,
    "kW": UnitOfPower.KILO_WATT,
    "V": UnitOfElectricPotential.VOLT,
    "mV": UnitOfElectricPotential.MILLIVOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "mA": UnitOfElectricCurrent.MILLIAMPERE,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "Hz": UnitOfFrequency.HERTZ,
    "Lux": LIGHT_LUX,
    "lux": LIGHT_LUX,
    "lx": LIGHT_LUX,
    "dBm": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    "km/h": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "m/s": UnitOfSpeed.METERS_PER_SECOND,
    "mm": UnitOfPrecipitationDepth.MILLIMETERS,
    "hPa": UnitOfPressure.HPA,
    "s": UnitOfTime.SECONDS,
    "min": UnitOfTime.MINUTES,
    "h": UnitOfTime.HOURS,
    "m3": UnitOfVolume.CUBIC_METERS,
    "m³": UnitOfVolume.CUBIC_METERS,
    "m": UnitOfLength.METERS,
    "°": DEGREE,
}

DEVICE_CLASS_BY_UNIT = {
    "°C": SensorDeviceClass.TEMPERATURE,
    "°F": SensorDeviceClass.TEMPERATURE,
    "W": SensorDeviceClass.POWER,
    "kW": SensorDeviceClass.POWER,
    "V": SensorDeviceClass.VOLTAGE,
    "mV": SensorDeviceClass.VOLTAGE,
    "A": SensorDeviceClass.CURRENT,
    "mA": SensorDeviceClass.CURRENT,
    "Wh": SensorDeviceClass.ENERGY,
    "kWh": SensorDeviceClass.ENERGY,
    "Hz": SensorDeviceClass.FREQUENCY,
    "Lux": SensorDeviceClass.ILLUMINANCE,
    "lux": SensorDeviceClass.ILLUMINANCE,
    "lx": SensorDeviceClass.ILLUMINANCE,
    "dBm": SensorDeviceClass.SIGNAL_STRENGTH,
    "km/h": SensorDeviceClass.WIND_SPEED,
    "m/s": SensorDeviceClass.WIND_SPEED,
    "hPa": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
}

DEVICE_CLASS_BY_PARAM = {
    "ACTUAL_TEMPERATURE": SensorDeviceClass.TEMPERATURE,
    "TEMPERATURE": SensorDeviceClass.TEMPERATURE,
    "HUMIDITY": SensorDeviceClass.HUMIDITY,
    "ACTUAL_HUMIDITY": SensorDeviceClass.HUMIDITY,
    "RAIN_COUNTER": SensorDeviceClass.PRECIPITATION,
    "GAS_ENERGY_COUNTER": SensorDeviceClass.GAS,
}

# Parameter, deren Einheit die CCU nicht (korrekt) liefert
UNIT_BY_PARAM = {
    "HUMIDITY": "%",
    "ACTUAL_HUMIDITY": "%",
    "RSSI_DEVICE": "dBm",
    "RSSI_PEER": "dBm",
    "ACTUAL_TEMPERATURE": "°C",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "sensor", lambda hub, spec: HmSensor(hub, spec))


class HmSensor(HmParamEntity, SensorEntity):
    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "sensor")
        p = self.param
        name = p.name
        unit = UNIT_BY_PARAM.get(name) or p.unit
        if p.type == "ENUM":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = [str(v) for v in (p.value_list or [])] or None
            if not self._attr_options:
                self._attr_device_class = None
            return
        if p.type == "STRING":
            return
        self._attr_native_unit_of_measurement = UNITS.get(unit or "", unit or None)
        dc = DEVICE_CLASS_BY_PARAM.get(name) or DEVICE_CLASS_BY_UNIT.get(unit or "")
        if name.startswith("RSSI_"):
            dc = SensorDeviceClass.SIGNAL_STRENGTH
        if dc is SensorDeviceClass.ENERGY or name.endswith("_COUNTER"):
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if dc is not None and self._attr_native_unit_of_measurement is None and dc is not SensorDeviceClass.ENUM:
            dc = None
        self._attr_device_class = dc

    @property
    def native_value(self):
        p = self.param
        v = p.value
        if v is None:
            return None
        if p.type == "ENUM":
            return p.enum_label(v)
        if p.type in ("FLOAT", "INTEGER"):
            try:
                f = float(v) * scale(p)
            except (TypeError, ValueError):
                return None
            if p.type == "INTEGER" and scale(p) == 1:
                return int(f)
            return round(f, 2)
        return str(v)
