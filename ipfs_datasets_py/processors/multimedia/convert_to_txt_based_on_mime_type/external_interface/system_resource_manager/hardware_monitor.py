from typing import Dict, Any, Callable, Coroutine, Optional


from pydantic import BaseModel


class HardwareMonitor:
    """
    Hardware monitoring component that detects and tracks system resources.
    
    This class is responsible for interfacing with the operating system and
    hardware to detect available resources and monitor their usage.
    """

    def __init__(self, resources: dict[str, Callable|Coroutine] = None, configs: BaseModel = None):
        """
        Initialize hardware monitoring capabilities.
        
        Sets up connections to system monitoring APIs and prepares for hardware detection.
        """
        self.configs = configs
        self.resources = resources
        assert isinstance(self.configs, BaseModel)
        assert isinstance(self.resources, dict)
        assert hasattr(self.configs, 'hardware')

        self.output_directory = self.configs.output_directory

        # Implementation would initialize hardware detection mechanisms
        self._get_total_cpu_cores = resources['_get_total_cpu_cores']
        self._get_cpu_utilization_as_percentage = resources['_get_cpu_utilization_as_percentage']
        #self._get_free_cpu_cores = resources['_get_free_cpu_cores']
        self._get_total_memory = resources['_get_total_memory']
        self._get_free_memory = resources['_get_free_memory']
        self._get_total_vram = resources['_get_total_vram']
        self._get_free_vram = resources['_get_free_vram']
        self._get_total_disk_space = resources['_get_total_disk_space']
        self._get_free_disk_space = resources['_get_free_disk_space']


    def get_total_cpu_cores(self) -> int:
        """
        Get the total number of physical CPU cores available on the system.
        
        Returns:
            int: The total number of CPU cores
        """
        self._get_total_cpu_cores()


    def get_cpu_utilization_as_percentage(self) -> float:
        """
        Get the current CPU utilization as a percentage.
        
        Returns:
            float: The CPU utilization percentage (0-100)
        """
        self._get_cpu_utilization_as_percentage()


    def get_free_cpu_cores(self) -> int:
        """
        Estimate the number of physical CPU cores that are currently unused.
        
        Returns:
            int: The estimated number of free CPU cores
        """
        # Get total CPU cores
        total_cores = self.get_total_cpu_cores()
        
        # Get current CPU utilization as a percentage (0-100)
        cpu_usage_percent = self.get_cpu_utilization_as_percentage()
        
        # Calculate estimated free cores
        # If CPU is 75% utilized, then 25% of cores are estimated to be free
        free_cores = int(total_cores * (1 - cpu_usage_percent / 100))
        
        # Ensure we always return at least one free core
        return max(1, free_cores)


    def get_total_memory(self) -> int:
        """
        Get the total system RAM in megabytes.
        
        Returns:
            int: Total RAM in MB
        """
        return self._get_total_memory()


    def get_free_memory(self) -> int:
        """
        Get the current free system RAM in megabytes.
        
        Returns:
            int: Free RAM in MB
        """
        return self._get_free_memory()


    def get_total_vram(self) -> int:
        """
        Get the total VRAM across all GPUs in megabytes.
        
        Returns:
            int: Total VRAM in MB, or 0 if no GPU is available
        """
        # Implementation would use GPU-specific libraries like torch, pycuda, etc.
        self._get_total_vram()


    def get_free_vram(self) -> int:
        """
        Get the current free VRAM across all GPUs in megabytes.
        
        Returns:
            int: Free VRAM in MB, or 0 if no GPU is available
        """
        # Implementation would use GPU-specific libraries
        self._get_free_vram()


    def get_total_disk_space(self) -> int:
        """
        Get the total disk space in gigabytes.
        
        Returns:
            int: Total disk space in GB
        """
        # Implementation would check specified disk paths
        pass


    def get_free_disk_space(self) -> int:
        """
        Get the current free disk space in gigabytes.
        
        Returns:
            int: Free disk space in GB
        """
        # Implementation would check specified disk paths
        pass