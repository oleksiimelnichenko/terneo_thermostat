"""Terneo Thermostat Switch Support."""
import logging

import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DOMAIN = "terneo"
CONF_SERIAL = "serial"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SERIAL): cv.string,
        vol.Optional(CONF_NAME, default="Terneo"): cv.string,
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up Terneo switch entities."""
    serialnumber = config.get(CONF_SERIAL)
    name = config.get(CONF_NAME)

    devices = hass.data.get(DOMAIN, {})
    climate_device = devices.get(serialnumber)

    if climate_device is None:
        _LOGGER.error(
            "Terneo climate entity with serial '%s' not found. "
            "Make sure the climate platform is configured first.",
            serialnumber,
        )
        return False

    thermostat = climate_device.thermostat

    add_entities([
        TerneoLocalNetworkBlockSwitch(thermostat, name),
    ], True)


class TerneoLocalNetworkBlockSwitch(SwitchEntity):
    """Switch to control local network blocking (androidBlock, par 114)."""

    def __init__(self, thermostat, name):
        self.thermostat = thermostat
        self._name = f"{name} Local Network Block"
        self._is_on = None

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return f"{self.thermostat.sn}_local_network_block"

    @property
    def is_on(self):
        return self._is_on

    @property
    def icon(self):
        return "mdi:network-off" if self._is_on else "mdi:network"

    def turn_on(self, **kwargs):
        """Block local network control."""
        self.thermostat.set_parameter("local_network_block", True)
        self._is_on = True

    def turn_off(self, **kwargs):
        """Allow local network control."""
        self.thermostat.set_parameter("local_network_block", False)
        self._is_on = False

    def update(self):
        """Update state from device parameters."""
        params = self.thermostat._parameters
        if params:
            self._is_on = params.get("local_network_block")
