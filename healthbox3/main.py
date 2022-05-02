"""
A Healthbox 3 plugin, for reading and controlling your Renson Healthbox 3
"""
"""
structuur:

3 threads:
    device discovery
    device data pulling
    cloud data syncing

local caching:
    dict with as key the reg_key of the device and value? (dict voor de variabele maar ook object voor status etc?)
"""

import six
import requests
import simplejson as json
import time
from socket import *
from threading import Thread
from plugins.base import om_expose, output_status, OMPluginBase, PluginConfigChecker, background_task, om_metric_data
from .api_handler import ApiHandler
from .healtbox3 import HealthBox3Manager, HealthBox3Driver

class HealthboxPlugin(OMPluginBase):
    """
    A Healthbox 3 plugin, for reading and controlling your Renson Healthbox 3
    """

    name = 'Healthbox3'
    version = '1.0.1'
    interfaces = [('config', '1.0'),
                  ('metrics', '1.0')]

    def __init__(self, webinterface, logger):
        super(HealthboxPlugin, self).__init__(webinterface, logger)

        self.api_handler = ApiHandler(self.logger)
        self.discovered_devices = {}  # dict of all the endura delta drivers mapped with register key as key
        self.reg_key_to_gateway_id = {}  # mapping of register key to gateway id (for api calls)

        self.healtbox_manager = HealthBox3Manager()
        self.healtbox_manager.set_discovery_callback(self.discover_callback)
        self.healtbox_manager.start_discovery()

    def discover_callback(self, ip):
        # type: (str) -> None
        """ callback for when a new device has been discovered """
        reg_key = self.healtbox_manager.get_registration_key(ip)
        if reg_key is not None:
            try:
                self.discovered_devices[reg_key] = EnduraDeltaDriver(ip=ip)
                self.logger('Found Endura Delta device @ ip: {} with registration key: {}'.format(ip, reg_key))
                self.register_ventilation_config(reg_key)
            except Exception as ex:
                self.logger("Discovered device @ {}, but could not connect to the device... {}".format(ip, ex))

    def register_ventilation_config(self, reg_key): #TODO does the healthbox have a reg_key?
        # type: (str) -> None
        """ Registers a new device to the gateway """
        if reg_key not in self.discovered_devices:
            self.logger('Could not register new ventilation device, registration key is not known to the plugin')
            return
        hbd = self.discovered_devices[reg_key]
        if hbd is None:
            self.logger('Could not register new ventilation device, driver is not working properly to request data')
            return
        registration_key = hbd.get_variable('Registration key') #TODO does the heathbox have a reg_key?
        config = {
            "external_id": registration_key,
            "source": {"type": "plugin", "name": HealthboxPlugin.name},
            "name": hbd.get_variable('Device name'), #TODO does the healthbox have a device name?
            "amount_of_levels": 4,
            "device": {"type": "Healthbox 3",
                       "vendor": "Renson",
                       "serial": registration_key
            }
        }
        self.api_handler.add_request(self.webinterface.set_ventilation_configuration, {'config': json.dumps(config)}, self.handle_register_response)

    def handle_register_response(self, data):
        # type: (str) -> bool
        """ handles the response received from the register request """
        data_dict = json.loads(data)
        if data_dict is None or 'success' not in data_dict:
            self.logger('Could not register new ventilation device, API endpoint did not respond with valid answer')
            return False
        if not data_dict['success']:
            self.logger('Could not register new ventilation device, registration failed trough API')
            return False

        if 'config' not in data_dict:
            self.logger('Could not register new ventilation device, API endpoint did not respond with valid answer')
            return False
        gateway_id = data_dict['config']['id']
        reg_key = data_dict['config']['external_id']
        self.reg_key_to_gateway_id[reg_key] = gateway_id
        self.logger('Successfully registered new ventilation device @ gateway id: {}'.format(gateway_id))
        if not self._is_collecting_metrics:
            self.start_metric_collection()
        return True




























# original code below




    config_description = [{'name': 'serial',
                           'type': 'str',
                           'description': 'The serial of the Healthbox 3. E.g. 250424P0031'}]

    metric_definitions = [{'type': 'aqi',
                           'tags': ['type', 'description', 'serial'],
                           'metrics': [{'name': 'aqi',
                                        'description': 'Global air quality index',
                                        'type': 'gauge',
                                        'unit': 'aqi'}]}]

    default_config = {'serial': ''}

    def __init__(self, webinterface, logger):
        super(Healthbox, self).__init__(webinterface, logger)
        self.logger('Starting Healthbox plugin...')

        self._config = self.read_config(Healthbox.default_config)
        self._config_checker = PluginConfigChecker(Healthbox.config_description)

        self._read_config()

        self._previous_output_state = {}
        self.logger("Started Healthbox plugin")

    def _read_config(self):
        self._serial = self._config['serial']
        self._sensor_mapping = self._config.get('sensor_mapping', [])

        self._endpoint = 'http://{0}/v2/api/data/current'
        self._headers = {'X-Requested-With': 'OpenMotics plugin: Healthbox',
                         'X-Healthbox-Version': '2'}

        self._ip = self._discover_ip_for_serial(self._serial)
        if self._ip:
            self.logger("Healthbox found with serial {0}and ip address {1}".format(self._serial, self._ip))
        else:
            self.logger("Healthbox  with serial {0} not found!".format(self._serial))
        self._enabled = (self._ip != '' and self._serial != '')
        self.logger('Healthbox is {0}'.format('enabled' if self._enabled else 'disabled'))

    def _byteify(self, input):
        if isinstance(input, dict):
            return {self._byteify(key): self._byteify(value)
                    for key, value in input.items()}
        elif isinstance(input, list):
            return [self._byteify(element) for element in input]
        elif isinstance(input, six.text_type):
            return input.encode('utf-8')
        else:
            return input

    def _discover_ip_for_serial(self, serial):
        hb3Ip = ''
        # Create a UDP socket for devices discovery
        sock = socket(AF_INET, SOCK_DGRAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
        sock.settimeout(5)

        server_address = ('255.255.255.255', 49152)
        message = 'RENSON_DEVICE/JSON?'

        discovered_devices = []
        try:
            sent = sock.sendto(message.encode(), server_address)
            while True:
                data, server = sock.recvfrom(4096)
                if data.decode('UTF-8'):
                    discovered_devices.append(json.loads(data))
                else:
                    print('Verification failed')
                print('Trying again...')

        except Exception as ex:
            if len(discovered_devices) == 0:
                self.logger('Error during discovery for serial: {0}'.format(ex))

        finally:
            sock.close()

        for device in discovered_devices:
            if device.get('serial') == serial:
                hb3Ip = device.get('IP')

        if hb3Ip == '':
            self.logger('Error during discovery for serial: {0}'.format(serial))
        return hb3Ip


    @background_task
    def run(self):
        while True:
            if not self._enabled:
                start = time.time()
                try:
                    self._ip = self._discover_ip_for_serial(self._serial)
                    if self._ip:
                        self._enabled = True
                        self.logger('Healthbox is {0}'.format('enabled' if self._enabled else 'disabled'))
                except Exception as ex:
                    self.logger('Error while fetching ip address: {0}'.format(ex))
                # This loop should run approx. every 60 seconds
                sleep = 60 - (time.time() - start)
                if sleep < 0:
                    sleep = 1
                time.sleep(sleep)
            else:
                time.sleep(60)

    @om_metric_data(interval=15)
    def get_metric_data(self):
        if self._enabled:
            now = time.time()
            try:
                response = requests.get(url=self._endpoint.format(self._ip))
                if response.status_code != 200:
                    self.logger('Failed to load healthbox data')
                    return
                result = response.json()
                serial = result.get('serial')
                sensors = result.get('sensor')
                description = result.get('description')
                if serial and sensors and description:
                    for sensor in result['sensor']:
                        if sensor['type'] == 'global air quality index':
                            yield {'type': 'aqi',
                                'timestamp': now,
                                'tags': {'type': 'Healthbox',
                                            'description':description,
                                            'serial': serial},
                                'values': {'aqi': float(sensor['parameter']['index']['value'])}
                            }
            except Exception as ex:
                self.logger("Error while fetching metric date from healthbox: {0}".format(ex))
                self._enabled = False
                self.logger('Healthbox is {0}'.format('enabled' if self._enabled else 'disabled'))
                return

    @om_expose
    def get_config_description(self):
        return json.dumps(Healthbox.config_description)

    @om_expose
    def get_config(self):
        return json.dumps(self._config)

    @om_expose
    def set_config(self, config):
        config = json.loads(config)
        for key in config:
            if isinstance(config[key], six.string_types):
                config[key] = str(config[key])
        self._config_checker.check_config(config)
        self._config = config
        self._read_config()
        self.write_config(config)
        return json.dumps({'success': True})

