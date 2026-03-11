import sys
import requests
import logging
import time

from requests.auth import HTTPBasicAuth

_LOGGER = logging.getLogger(__name__)

# Parameter registry: id -> (type_code, name, read_only)
# Type codes: 1=int8, 2=uint8, 4=uint16, 6=uint32, 7=bool
PARAMETERS = {
    0:   (6, "start_away_time", False),
    1:   (6, "end_away_time", False),
    2:   (2, "mode", False),
    3:   (2, "control_type", False),
    4:   (1, "manual_air_temp", False),
    5:   (1, "manual_floor_temp", False),
    6:   (1, "away_air_temp", False),
    7:   (1, "away_floor_temp", False),
    14:  (2, "min_temp_advanced_mode", False),
    15:  (2, "max_temp_advanced_mode", False),
    17:  (4, "power", True),
    18:  (2, "sensor_type", False),
    19:  (2, "hysteresis", False),
    20:  (1, "air_correction", False),
    21:  (1, "floor_correction", False),
    23:  (2, "brightness", False),
    25:  (2, "prop_koef", False),
    26:  (1, "upper_limit", False),
    27:  (1, "lower_limit", False),
    28:  (2, "max_schedule_period", False),
    29:  (2, "temp_temperature", False),
    31:  (2, "set_temperature", True),
    33:  (1, "upper_air_limit", False),
    34:  (1, "lower_air_limit", False),
    52:  (4, "night_bright_start", False),
    53:  (4, "night_bright_end", False),
    109: (7, "off_button_lock", True),
    114: (7, "local_network_block", False),
    115: (7, "cloud_block", False),
    117: (7, "nc_contact_control", False),
    118: (7, "cooling_control", False),
    120: (7, "use_night_bright", False),
    121: (7, "preheat", False),
    122: (7, "open_window_control", False),
    124: (7, "child_lock", False),
    125: (7, "power_off", False),
}


class Thermostat:
    """
    A class for interacting with the Terneo Thermostat's HTTP API.
    Parameters
    ----------
    serialnumber: `str`
        Serial Number of device
    host : `str`
        Hostname or IP address.
    port : `int` (optional)
        The port of the web server.
    username : `str` (optional)
        The username for HTTP auth.
    password : `str` (optional)
        The password for the HTTP auth.
    """

    def __init__(self, serialnumber, host, port=80, username=None, password=None):
        if username or password and not username and password:
            raise ValueError(
                "Username and Password must both be specified, if either are specified."
            )
        elif username or password:
            self.auth = HTTPBasicAuth(username, password)
        else:
            self.auth = None

        self.sn = serialnumber

        self._base_url = "http://{}:{}/{{endpoint}}.cgi".format(host, port)
        self._setpoint = None
        self._temperature = None
        self._mode = None
        self._state = None

        self._schedule = None
        self._parameters = {}
        self._last_request = time.time()

        try:
            r = requests.get(self._base_url.format(endpoint="api.html")[:-4])
            assert r.status_code == 200
        except Exception as e:
            raise type(e)("Connection to Thermostat failed with: {}".format(str(e))).with_traceback(sys.exc_info()[2])

    def _get_url(self, endpoint):
        return self._base_url.format(endpoint=endpoint)

    def get(self, endpoint, **kwargs):
        """
        Perform a GET request
        Parameters
        ----------
        endpoint : `str`
            The endpoint to send the request to, will have 'cgi' appended to it.
        kwargs : `dict`
            All other kwargs are passed to `requests.get`
        Returns
        -------
        response : `requests.Response`
            The result of the request.
        """
        kwergs = {'auth': self.auth}
        kwergs.update(kwargs)

        r = requests.get(self._get_url(endpoint), **kwergs)
        return r

    def post(self, endpoint='api', **kwargs):
        """
        Perform a POST request
        Parameters
        ----------
        endpoint : `str`
            The endpoint to send the request to, will have 'cgi' appended to it.
        kwargs : `dict`
            All other kwargs are passed to `requests.post`
        Returns
        -------
        response : `requests.Response`
            The result of the request.
        """
        kwergs = {'auth': self.auth}

        kwergs.update(kwargs)

        start_time = time.time()
        if start_time - self._last_request < 1:
            time.sleep(1)

        # _LOGGER.error(f"terneo request start time: {start_time}. cmd - {kwargs['json'].get('cmd')}; pars - {kwargs['json'].get('par')}")
        try:
            r = requests.post(self._get_url(endpoint), timeout=5, **kwergs)
        except Exception as e:
            self._last_request = time.time()
            _LOGGER.error(e)
            return False
        end_time = time.time()
        # _LOGGER.error(f'terneo request end time: {end_time}. diff: {end_time - start_time}')
        self._last_request = end_time
        content = r.json()

        if content.get('status', '') == 'timeout':
            _LOGGER.error(f'terneo timout: {kwargs}')
            return False

        return content

    def status(self):
        """
        Get the status dictionary from the thermostat
        """
        r = self.post(json={"cmd": 4})
        return r

    def is_on(self):
        """
        getting power on/off for firmware 2.3
        :return: bool
        """
        r = self.post(json={"cmd": 1})
        if r and 'par' in r:
            for a in r['par']:
                if a[0] == 125:
                    return a[2] == "0"
        return False

    @property
    def temperature(self):
        """
        Current value of the temperature sensor in C
        """
        if self._temperature is None:
            data = self.status()
            if data:
                self._temperature = self.get_temperature(data)
        return self._temperature

    @staticmethod
    def get_temperature(data):
        return float(data['t.1']) / 16

    @property
    def setpoint(self):
        """
        Current thermostat setpoint in C
        """
        if self._setpoint is None:
            data = self.status()
            if data:
                self._setpoint = self.get_setpoint(data)
        return self._setpoint

    @setpoint.setter
    def setpoint(self, val):
        setpoint = str(val)
        self.post(json=dict(sn=self.sn, par=[[125, 7, "0"], [2, 2, "1"], [5, 1, setpoint]]))

    @staticmethod
    def get_setpoint(data):
        return float(data['t.5']) / 16

    @property
    def mode(self):
        """
        Returns the current mode of the thermostat.
        Returns
        -------
        mode : `int`
            `0` for schedule mode, `3` for manual mode and `4` for away mode.
        """
        if self._mode is None:
            data = self.status()
            if data:
                self._mode = self.get_mode(data)
        return self._mode

    def get_mode(self, data):
        if 'f.16' in data:  # in firmware 2.4 was added new flag for power off/on
            is_on = int(data['f.16']) == 0
        else:
            is_on = self.is_on()

        if not is_on:
            return -1
        else:
            return int(data['m.1'])

    @mode.setter
    def mode(self, val):
        val = int(val)
        if val not in [0, 1]:
            raise ValueError("mode must be either 0,1")

        self.post(json=dict(sn=self.sn, par=[[125, 7, "0"], [2, 2, str(val)]]))

    @property
    def state(self):
        """
        Current state of the relay.
        Returns
        -------
        state : `bool`
            returns `True` if the relay is on and `False` if the relay is off.
        """
        if self._state is None:
            data = self.status()
            if data:
                self._state = self.get_state(data)
        return self._state

    @staticmethod
    def get_state(data):
        return int(data['f.0']) == 1

    def turn_on(self):
        return self.post(json=dict(sn=self.sn, par=[[125, 7, "0"]]))

    def turn_off(self):
        return self.post(json=dict(sn=self.sn, par=[[125, 7, "1"]]))

    def get_parameters(self):
        """
        Get all device parameters via cmd 1.
        Returns a dict mapping parameter name to its value.
        """
        r = self.post(json={"cmd": 1})
        if r and 'par' in r:
            params = {}
            for par_id, par_type, par_value in r['par']:
                if par_id in PARAMETERS:
                    _, name, _ = PARAMETERS[par_id]
                    if par_type == 7:  # bool
                        params[name] = par_value == "1"
                    elif par_type in (1, 2):  # int8, uint8
                        params[name] = int(par_value)
                    elif par_type in (4, 6):  # uint16, uint32
                        params[name] = int(par_value)
                    else:
                        params[name] = par_value
            return params
        return None

    def set_parameter(self, name, value):
        """
        Set a device parameter by name.
        Parameters
        ----------
        name : str
            Parameter name from PARAMETERS registry.
        value : int, bool, or str
            Value to set.
        """
        par_id = None
        for pid, (type_code, pname, read_only) in PARAMETERS.items():
            if pname == name:
                par_id = pid
                break

        if par_id is None:
            raise ValueError(f"Unknown parameter: {name}")

        type_code, _, read_only = PARAMETERS[par_id]
        if read_only:
            raise ValueError(f"Parameter '{name}' is read-only")

        if type_code == 7:  # bool
            str_value = "1" if value else "0"
        else:
            str_value = str(int(value))

        return self.post(json={"sn": self.sn, "par": [[par_id, type_code, str_value]]})

    def get_schedule(self):
        """
        Get the weekly schedule from the thermostat.
        Returns a dict with day keys "0"-"6" (Monday-Sunday),
        each containing a list of [minutes_from_midnight, temp_tenths] pairs.
        """
        r = self.post(json={"cmd": 2})
        if r and 'tt' in r:
            return r['tt']
        return None

    def set_schedule_day(self, day, periods):
        """
        Set the schedule for a single day.
        Parameters
        ----------
        day : int
            Day of week, 0=Monday through 6=Sunday.
        periods : list
            List of [minutes_from_midnight, temperature_in_tenths] pairs.
            Max 16 periods per day.
        """
        if day not in range(7):
            raise ValueError("day must be 0-6 (Monday-Sunday)")
        if len(periods) > 16:
            raise ValueError("Maximum 16 periods per day")
        return self.post(json={"sn": self.sn, "tt": {str(day): periods}})

    def update(self):
        data = self.status()
        if data:
            self._setpoint = self.get_setpoint(data)
            self._temperature = self.get_temperature(data)
            self._mode = self.get_mode(data)
            self._state = self.get_state(data)
            params = self.get_parameters()
            if params:
                self._parameters = params
            schedule = self.get_schedule()
            if schedule:
                self._schedule = schedule
