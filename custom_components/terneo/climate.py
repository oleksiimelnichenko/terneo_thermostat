"""Terneo Thermostat Support."""
import logging

from .thermostat import Thermostat, PARAMETERS
import requests
import voluptuous as vol
from typing import Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    UnitOfTemperature,
)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DOMAIN = "terneo"
CONF_SERIAL = "serial"

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SET_PARAMETER = "set_parameter"
ATTR_DAY = "day"
ATTR_PERIODS = "periods"
ATTR_TIME = "time"
ATTR_PARAMETER = "parameter"
ATTR_VALUE = "value"

WRITABLE_PARAMS = [name for _, (_, name, ro) in PARAMETERS.items() if not ro]

SERVICE_SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_DAY): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
        vol.Required(ATTR_PERIODS): vol.All(
            cv.ensure_list,
            vol.Length(max=16),
            [
                vol.Schema(
                    {
                        vol.Required(ATTR_TIME): cv.string,
                        vol.Required(ATTR_TEMPERATURE): vol.All(
                            vol.Coerce(float), vol.Range(min=5, max=45)
                        ),
                    }
                )
            ],
        ),
    }
)

SERVICE_SET_PARAMETER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_PARAMETER): vol.In(WRITABLE_PARAMS),
        vol.Required(ATTR_VALUE): vol.Any(bool, int, float),
    }
)

CONF_TOTP_KEY = "totp_key"

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SERIAL): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default="Terneo"): cv.string,
        vol.Optional(CONF_PORT, default=80): cv.port,
        vol.Inclusive(CONF_USERNAME, "authentication"): cv.string,
        vol.Inclusive(CONF_PASSWORD, "authentication"): cv.string,
        vol.Optional(CONF_TOTP_KEY): cv.string,
    }
)

SUPPORT_FLAGS = ClimateEntityFeature.TARGET_TEMPERATURE
SUPPORT_HVAC = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Terneo platform."""
    serialnumber = config.get(CONF_SERIAL)
    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    totp_key = config.get(CONF_TOTP_KEY)

    try:
        therm = Thermostat(serialnumber, host, port=port, username=username, password=password, totp_key=totp_key)
    except (ValueError, AssertionError, requests.RequestException):
        return False

    device = ThermostatDevice(therm, name)
    hass.data.setdefault(DOMAIN, {})[serialnumber] = device
    add_entities((device,), True)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        def handle_set_schedule(call):
            """Handle the set_schedule service call."""
            entity_id = call.data[ATTR_ENTITY_ID]
            day = call.data[ATTR_DAY]
            periods_raw = call.data[ATTR_PERIODS]

            target = None
            for dev in hass.data[DOMAIN].values():
                if dev.entity_id == entity_id:
                    target = dev
                    break

            if target is None:
                _LOGGER.error("Entity %s not found", entity_id)
                return

            periods = []
            for p in periods_raw:
                parts = p[ATTR_TIME].split(":")
                minutes = int(parts[0]) * 60 + int(parts[1])
                temp_tenths = int(p[ATTR_TEMPERATURE] * 10)
                periods.append([minutes, temp_tenths])

            result = target.thermostat.set_schedule_day(day, periods)
            if result:
                target.schedule_update_ha_state(True)
            else:
                _LOGGER.error("Failed to set schedule for day %d on %s", day, entity_id)

        hass.services.register(
            DOMAIN, SERVICE_SET_SCHEDULE, handle_set_schedule,
            schema=SERVICE_SET_SCHEDULE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_PARAMETER):
        def handle_set_parameter(call):
            """Handle the set_parameter service call."""
            entity_id = call.data[ATTR_ENTITY_ID]
            param_name = call.data[ATTR_PARAMETER]
            value = call.data[ATTR_VALUE]

            target = None
            for dev in hass.data[DOMAIN].values():
                if dev.entity_id == entity_id:
                    target = dev
                    break

            if target is None:
                _LOGGER.error("Entity %s not found", entity_id)
                return

            result = target.thermostat.set_parameter(param_name, value)
            if result:
                target.schedule_update_ha_state(True)
            else:
                _LOGGER.error(
                    "Failed to set parameter '%s' to '%s' on %s",
                    param_name, value, entity_id,
                )

        hass.services.register(
            DOMAIN, SERVICE_SET_PARAMETER, handle_set_parameter,
            schema=SERVICE_SET_PARAMETER_SCHEMA,
        )


class ThermostatDevice(ClimateEntity):
    """Interface class for the thermostat module."""

    def __init__(self, thermostat, name):
        """Initialize the device."""
        self._name = name
        self.thermostat = thermostat

        # set up internal state vars
        self._state = None
        self._temperature = None
        self._setpoint = None
        self._mode = None
        self._schedule = None
        self._parameters = {}

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.
        Need to be one of HVAC_MODE_*.
        """

        if self._mode == -1:
            return HVACMode.OFF
        if self._mode == 3:
            return HVACMode.HEAT
        return HVACMode.AUTO

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes.
        Need to be a subset of HVAC_MODES.
        """
        return SUPPORT_HVAC

    @property
    def name(self):
        """Return the name of this Thermostat."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement used by the platform."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_action(self):
        """Return current hvac i.e. heat, cool, idle."""
        if self._mode == -1:
            return HVACAction.OFF
        if self._state:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._setpoint

    @property
    def target_temperature_step(self) -> Optional[float]:
        """Return the supported step of target temperature."""
        return 1.0

    @property
    def unique_id(self):
        """Return unique ID based on Terneo serial number."""
        return self.thermostat.sn

    @property
    def extra_state_attributes(self):
        """Return device state attributes including schedule and settings."""
        attrs = {}
        if self._schedule is not None:
            attrs["schedule"] = self._format_schedule(self._schedule)
        if self._parameters:
            attrs.update(self._parameters)
        return attrs if attrs else None

    @staticmethod
    def _format_schedule(raw_schedule):
        """Convert raw schedule to human-readable format."""
        formatted = {}
        for day_num, day_name in enumerate(DAY_NAMES):
            key = str(day_num)
            if key in raw_schedule:
                periods = []
                for minutes, temp_tenths in raw_schedule[key]:
                    hours = minutes // 60
                    mins = minutes % 60
                    periods.append({
                        "time": f"{hours:02d}:{mins:02d}",
                        "temperature": temp_tenths / 10,
                    })
                formatted[day_name] = periods
        return formatted

    def set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.AUTO:
            self.thermostat.mode = 0
            self._mode = 0
        elif hvac_mode == HVACMode.HEAT:
            self.thermostat.mode = 1
            self._mode = 3
        elif hvac_mode == HVACMode.OFF:
            self.thermostat.turn_off()
            self._mode = -1

    def set_temperature(self, **kwargs):
        """Set the temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            self.thermostat.setpoint = temp
            self._setpoint = temp

    def update(self):
        """Update local state."""
        self.thermostat.update()
        self._setpoint = self.thermostat.setpoint
        self._temperature = self.thermostat.temperature
        self._state = self.thermostat.state
        self._mode = self.thermostat.mode
        if self.thermostat._parameters:
            self._parameters = self.thermostat._parameters
        if self.thermostat._schedule is not None:
            self._schedule = self.thermostat._schedule
