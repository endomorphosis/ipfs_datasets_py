import psutil
import time


class PsUtil:

    def __init__(self, resources=None, configs=None):
        self.configs = configs
        self.resources = resources


    def get_network_bandwidth(self) -> tuple[int, int]:
        """
        Retrieves total network bandwidth usage (sent and received bytes) 
        over a period of time.
        """
        old_value = psutil.net_io_counters()
        time.sleep(1)
        new_value = psutil.net_io_counters()

        sent_bytes = new_value.bytes_sent - old_value.bytes_sent
        received_bytes = new_value.bytes_recv - old_value.bytes_recv

        return sent_bytes, received_bytes

