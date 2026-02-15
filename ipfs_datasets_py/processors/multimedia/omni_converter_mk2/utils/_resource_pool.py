
from multiprocessing import Manager, Lock
from multiprocessing.managers import SyncManager


from external_programs import ExternalPrograms
from types_ import Configs


class ProcessSafeCounter(object):
    def __init__(self, manager: SyncManager, init_val: int = 0):
        self.val = manager.Value('i', init_val)
        self.lock = manager.Lock()

    def increment(self):
        with self.lock:
            self.val.value += 1

    def value(self):
        with self.lock:
            return self.val.value


class ProcessSafeDict(object):
    def __init__(self, manager: SyncManager):
        self.dict = manager.dict()
        self.lock = manager.Lock()

    def set(self, key, value):
        with self.lock:
            self.dict[key] = value

    def get(self, key):
        with self.lock:
            return self.dict.get(key)

    def remove(self, key):
        with self.lock:
            if key in self.dict:
                del self.dict[key]

    def __getitem__(self, key):
        return self.get(key)



class ExternalProgramDict(ProcessSafeDict):
    """A dictionary to manage external programs with process-safe access."""

    def __init__(self, manager: SyncManager):
        super().__init__(manager)
        self._EXTERNAL_PROGRAMS = {**ExternalPrograms.items()}
        for program in self._EXTERNAL_PROGRAMS:
            self.set(program, self._EXTERNAL_PROGRAMS[program])

try:
    from pydantic import BaseModel, UrlConstraints
except ImportError:
    raise ImportError("pydantic is not installed. Please install it using 'pip install pydantic'.")



class ExternalService:
    def __init__(self, service_a, service_b, service_c) -> None:
        self._service_a = service_a
        self._service_b = service_b
        self._service_c = service_c
        # service_d, ... etc

    def get_cluster_info(self, name: str):
        """Useful for things like Runpod, AWS, or other cloud providers."""
        self._service_a.send_something_to_somewhere(name)
        data = {
            'name': name,
            'free_resources': self._service_b.get_free_resources(),
            'current_price': self._service_c.get_price(name),
        }

        return ' ,'.join([
            ': '.join(['Service name', name]),
            ': '.join(['CPU', str(data['free_resources']['cpu'])]),
            ': '.join(['RAM', str(data['free_resources']['ram'])]),
            ': '.join(['Price', '{} $'.format(round(data['current_price']['usd'], 2))]),
        ])


# class TestClusterService(TestCase):
#     def test_get_cluster_info(self):
#         cluster = ClusterService(
#             service_a=Mock(),
#             service_b=Mock(get_free_resources=Mock(return_value={'cpu': 100, 'ram': 200})),
#             service_c=Mock(get_price=Mock(return_value={'usd': 101.4999})),
#         )

#         self.assertEqual(
#             cluster.get_cluster_info('best name'),
#             'Cluster name: best name ,CPU: 100 ,RAM: 200 ,Price: 101.5 $'
#         )




class ResourcePool:

    def __init__(self, configs: Configs):
        self._system_resources = {}
        self._api_resources = {}
        self._external_programs = ExternalProgramDict(Manager())

    def add_resource(self, name, resource):
        """Add a resource to the pool."""
        self._resources[name] = resource

    def get_resource(self, name):
        """Retrieve a resource from the pool."""
        return self._resources.get(name)

    def remove_resource(self, name):
        """Remove a resource from the pool."""
        if name in self._resources:
            del self._resources[name]



