"""Tastendrücke als Event-Entität (und zusätzlich als Bus-Event homematic_keypress)."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import callback

from .const import KEYPRESS_EVENT
from .entity import HmEntity, async_setup_platform


async def async_setup_entry(hass, entry, async_add_entities):
    async_setup_platform(hass, entry, async_add_entities, "event", lambda hub, spec: HmKeyEvent(hub, spec))


class HmKeyEvent(HmEntity, EventEntity):
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, hub, spec) -> None:
        super().__init__(hub, spec, "event")
        self._types: list[str] = spec.extra["types"]
        self._attr_event_types = [t.lower() for t in self._types]

    def watched(self):
        return []  # Tastendrücke werden in async_added_to_hass separat abonniert

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for t in self._types:
            self.async_on_remove(
                self.hub.subscribe(self.spec.channel.address, t, lambda t=t: self._pressed(t))
            )

    @callback
    def _pressed(self, param: str) -> None:
        p = self.spec.channel.params.get(param)
        if p is not None and p.value is False:
            return
        self._trigger_event(param.lower(), {"address": self.spec.channel.address})
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            KEYPRESS_EVENT,
            {
                "device": self.spec.device.title,
                "channel": self.spec.channel.index,
                "address": self.spec.channel.address,
                "param": param,
                "entity_id": self.entity_id,
            },
        )
