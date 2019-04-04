"""
Get sensor values form modbus
"""

import sys
import time
import struct
import simplejson as json
from plugins.base import om_expose, OMPluginBase, PluginConfigChecker, background_task


class modbusTCPSensor(OMPluginBase):
    """
    Get sensor values form modbus
    """

    name = 'modbusTCPSensor'
    version = '1.0.7'
    interfaces = [('config', '1.0')]

    config_description = [{'name': 'modbus_server_ip',
                           'type': 'str',
                           'description': 'IP or hostname of the ModBus server.'},
                          {'name': 'modbus_port',
                           'type': 'int',
                           'description': 'Port of the ModBus server. Default: 502'},
                          {'name': 'debug',
                           'type': 'int',
                           'description': 'Turn on debugging (0 = off, 1 = on)'},
                          {'name': 'sample_rate',
                           'type': 'int',
                           'description': 'How frequent (every x seconds) to fetch the sensor data, Default: 60'},
                          {'name': 'sensors',
                           'type': 'section',
                           'description': 'OM sensor ID (e.g. 4), a sensor type and a Modbus Address',
                           'repeat': True,
                           'min': 0,
                           'content': [{'name': 'sensor_id', 'type': 'int'},
                                       {'name': 'sensor_type', 'type': 'enum', 'choices': ['temperature', 'humidity', 'brightness']},
                                       {'name': 'modbus_address', 'type': 'int'},
                                       {'name': 'modbus_register_length', 'type': 'int'}]}]

    default_config = {'modbus_port': 502}

    def __init__(self, webinterface, logger):
        super(modbusTCPSensor, self).__init__(webinterface, logger)
        self.logger('Starting modbusTCPSensor plugin...')

        self._config = self.read_config(modbusTCPSensor.default_config)
        self._config_checker = PluginConfigChecker(modbusTCPSensor.config_description)

        py_modbus_tcp_egg = '/opt/openmotics/python/plugins/modbusTCPSensor/pyModbusTCP-0.1.7-py2.7.egg'
        if py_modbus_tcp_egg not in sys.path:
            sys.path.insert(0, py_modbus_tcp_egg)

        self._client = None
        self._samples = []
        self._save_times = {}
        self._read_config()

        self.logger("Started modbusTCPSensor plugin")

    def _read_config(self):
        self._ip = self._config.get('modbus_server_ip')
        self._port = self._config.get('modbus_port', modbusTCPSensor.default_config['modbus_port'])
        self._amount_samples = max(1, min(100, self._config.get('samples', 20)))
        self._debug = self._config.get('debug', 0) == 1
        self._sample_rate = self._config.get('sample_rate', 60)
        self._sensors = []
        for sensor in self._config.get('sensors', []):
            if 0 <= sensor['sensor_id'] < 32:
                self._sensors.append(sensor)
        self._enabled = len(self._sensors) > 0

        try:
            from pyModbusTCP.client import ModbusClient
            self._client = ModbusClient(self._ip, self._port, auto_open=True, auto_close=True)
            self._client.open()
            self._enabled = self._enabled & True
        except Exception as ex:
            self.logger('Error connecting to Modbus server: {0}'.format(ex))

        self.logger('modbusTCPSensor is {0}'.format('enabled' if self._enabled else 'disabled'))

    def clamp_sensor(self, value, sensor_type):
        clamping = {'temperature': [-32, 95.5, 1],
                    'humidity': [0, 100, 1],
                    'brightness': [0, 100, 0]}
        return round(max(clamping[sensor_type][0], min(value, clamping[sensor_type][1])), clamping[sensor_type][2])

    @background_task
    def run(self):
        while True:
            try:
                if not self._enabled or self._client is None:
                    time.sleep(5)
                    continue
                om_sensors = {}
                for sensor in self._sensors:
                    registers = self._client.read_holding_registers(sensor['modbus_address'],
                                                                    sensor['modbus_register_length'])
                    if registers is None:
                        continue
                    sensor_value = struct.unpack('>f', struct.pack('BBBB',
                                                                   registers[1] >> 8, registers[1] & 255,
                                                                   registers[0] >> 8, registers[0] & 255))[0]
                    if not om_sensors.get(sensor['sensor_id']):
                        om_sensors[sensor['sensor_id']] = {'temperature': None, 'humidity': None, 'brightness': None}

                    sensor_value = self.clamp_sensor(sensor_value, sensor['sensor_type'])

                    om_sensors[sensor['sensor_id']][sensor['sensor_type']] = sensor_value
                self.logger('The sensors dict is: {0}'.format(om_sensors))

                for sensor_id, values in om_sensors.iteritems():
                    result = json.loads(self.webinterface.set_virtual_sensor(sensor_id, **values))
                    if result['success'] is False:
                        self.logger('Error when updating virtual sensor {0}: {1}'.format(sensor_id, result['msg']))

                time.sleep(self._sample_rate)
            except Exception as ex:
                self.logger('Could not process sensor values: {0}'.format(ex))
                time.sleep(15)

    @om_expose
    def get_config_description(self):
        return json.dumps(modbusTCPSensor.config_description)

    @om_expose
    def get_config(self):
        return json.dumps(self._config)

    @om_expose
    def set_config(self, config):
        config = json.loads(config)
        for key in config:
            if isinstance(config[key], basestring):
                config[key] = str(config[key])
        self._config_checker.check_config(config)
        self.write_config(config)
        self._config = config
        self._read_config()
        return json.dumps({'success': True})
