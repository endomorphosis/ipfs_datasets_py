
from .resources.psutil import PsUtil


class NetworkBandwidthMonitor:


    def __init__(self, resources=None, configs=None):
        self.configs = configs
        self.resources = resources

        self._get_network_bandwidth = self.resources['get_network_bandwidth']


    def convert_to_gigabytes(self, bits: int):
        bytes_ = bits / 8
        return  bytes_ / (1024 ^ 3)


    def get_network_bandwidth(self):
        """
        Retrieves total network bandwidth usage (sent and received bytes)
        over a period of time.
        """
        self._get_network_bandwidth()


    def format_decimal_places(self, value) -> None:
        print ("%0.3f" % self.convert_to_gigabytes(value))


    def print_network_bandwidth(self):
        while True:
            sent, received = self.get_network_bandwidth()
            print(f"Bytes Sent: {self.format_decimal_places(sent)} gigabits")
            print(f"Bytes Received: {self.format_decimal_places(received)} gigabits")

