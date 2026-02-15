from dataclasses import dataclass
from typing import Any, Generator, TypeVar, Literal, Dict, Optional

from configs.configs import Configs


from pydantic import BaseModel


from config_parser.config_parser import ConfigParser
from file_paths_manager.file_paths_manager import FilePathsManager
from non_system_resource_manager.non_system_resource_manager import NonSystemResourceManager
from system_resource_manager.system_resource_manager import SystemResourceManager


Injectable = TypeVar('Injectable', bound=Any)


@dataclass
class ResourceBreakdown:
    are_available: bool = False
    available_ram: int = 0
    available_vram: int = 0
    available_cpu_cores: int = 0
    available_disk_space: int = 0
    available_network_bandwidth: int = 0
    available_gpu_processing_time: int = 0
    available_io_operations: int = 0
    message: str = ""


resources = {
    'config_parser': ConfigParser,
    'file_paths_manager': FilePathsManager,
    'non_system_resource_manager': NonSystemResourceManager,
    'resource_emitter': SystemResourceManager
}


class ExternalResourceManager():
    """
        Orchestrate and manage external resources for the program.

        This includes:
        - Allocating finite hardware resources to different parts of the program.
            This includes:
            - RAM
            - VRAM
            - CPU Cores
            - Disk Space
            - Network Bandwidth
            - GPU Processing Time
            - I/O Operations
        - Allocating finite non-system resources to different parts of the program.
            This includes:
            - Paths to files that need to be converted.
            - External APIs (e.g. Anthropic, HuggingFace, etc.).
            - Access to external databases.
            - Monetary costs associated with resource access and usage.
            - Rate limits for API calls
            - Authentication tokens and credentials
            - Caching mechanisms
            - Temporary storage locations
        - Managing the lifecycle of external resources.
        - Monitoring and reporting resource usage to the User and other parts of the program.
        - Implement resource prioritization strategies.
        - Handling resource contention and throttling.
        - Managing fallback mechanisms for resource unavailability.

        Attributes:
        - configs: Configs
            The configuration settings for the external resource manager.
        - resources: Injectable
            Dependency-injected modules and functions available to the external resource manager.
    """
    def __init__(self, resources: Injectable, configs: Configs):

        self.configs = configs
        self.resources = resources
        assert isinstance(self.configs, BaseModel)
        assert isinstance(self.resources, dict)


        # Modules
        self.config_parser:               ConfigParser             = self.resources['config_parser']()
        self.file_paths_manager:          FilePathsManager         = self.resources['file_paths_manager']()
        self.non_system_resource_manager: NonSystemResourceManager = self.resources['non_system_resource_manager']()
        self.system_resource_manager:     SystemResourceManager    = self.resources['resource_emitter']()


        # User-imposed Resource Constraints
        self.total_allocated_ram = self.configs.TOTAL_ALLOCATED_RAM
        self.total_allocated_vram = self.configs.TOTAL_ALLOCATED_VRAM
        self.total_allocated_cpu_cores = self.configs.TOTAL_ALLOCATED_CPU_CORES
        self.total_allocated_disk_space = self.configs.TOTAL_ALLOCATED_DISK_SPACE
        self.total_allocated_network_bandwidth = self.configs.TOTAL_ALLOCATED_NETWORK_BANDWIDTH
        self.total_allocated_gpu_processing_time = self.configs.TOTAL_ALLOCATED_GPU_PROCESSING_TIME
        self.total_allocated_io_operations = self.configs.TOTAL_ALLOCATED_IO_OPERATIONS

        # Internal attributes
        self.current_used_ram = 0
        self.current_used_vram = 0
        self.current_used_cpu_cores = 0
        self.current_used_disk_space = 0
        self.current_used_network_bandwidth = 0
        self.current_used_gpu_processing_time = 0
        self.current_used_io_operations = 0

        # Non-system resource tracking
        self.api_call_counts = {}
        self.api_rate_limits = {}
        self.active_file_paths = set()
        self.debug_mode = self.configs.DEBUG_MODE if hasattr(self.configs, 'DEBUG_MODE') else False

    def check_resource_availability(self, resource_type: Literal["system", "non_system"]) -> ResourceBreakdown:
        """
        Check if specified resources are available.
        
        Args:
            resource_type: The type of resources to check (system or non_system)
            
        Returns:
            ResourceBreakdown: Details of available resources
        """
        breakdown = ResourceBreakdown()
        
        if resource_type == "system":
            # Check system resources availability
            breakdown.available_ram = self.total_allocated_ram - self.current_used_ram
            breakdown.available_vram = self.total_allocated_vram - self.current_used_vram
            breakdown.available_cpu_cores = self.total_allocated_cpu_cores - self.current_used_cpu_cores
            breakdown.available_disk_space = self.total_allocated_disk_space - self.current_used_disk_space
            breakdown.available_network_bandwidth = self.total_allocated_network_bandwidth - self.current_used_network_bandwidth
            breakdown.available_gpu_processing_time = self.total_allocated_gpu_processing_time - self.current_used_gpu_processing_time
            breakdown.available_io_operations = self.total_allocated_io_operations - self.current_used_io_operations
            
            # Determine if resources are available
            breakdown.are_available = (
                breakdown.available_ram > 0 or
                breakdown.available_vram > 0 or
                breakdown.available_cpu_cores > 0 or
                breakdown.available_disk_space > 0 or
                breakdown.available_network_bandwidth > 0 or
                breakdown.available_gpu_processing_time > 0 or
                breakdown.available_io_operations > 0
            )
            breakdown.message = f"System resources {'available' if breakdown.are_available else 'unavailable'}"
        
        elif resource_type == "non_system":
            # Check if file paths are available
            file_paths_available = len(self.file_paths_manager.get_unprocessed_file_paths()) > 0
            
            # Check API rate limits
            api_limits_ok = all(self.api_call_counts.get(api, 0) < self.api_rate_limits.get(api, float('inf')) 
                                for api in self.api_call_counts)
            
            breakdown.are_available = file_paths_available and api_limits_ok
            breakdown.message = f"Non-system resources {'available' if breakdown.are_available else 'unavailable'}"
        
        return breakdown

    def allocate_free_resources(self, resource_type: Literal["system", "non_system"]) -> None:
        """
        Allocate free resources of the specified type.
        
        Args:
            resource_type: The type of resources to allocate (system or non_system)
        """
        if resource_type == "system":
            # Generate system resource allocation tasks
            for resource in self.allocate_system_resources():
                # Process each allocation
                self.manage_resource_lifecycle()
        else:
            # Generate non-system resource allocation tasks
            for resource in self.allocate_non_system_resources():
                # Process each allocation
                self.manage_resource_lifecycle()
        
    def heartbeat(self) -> None:
        """
        Periodic function that organizes the external resource manager methods.
        """
        while True:
            system_resources: ResourceBreakdown = self.check_resource_availability("system")
            non_system_resources: ResourceBreakdown = self.check_resource_availability("non_system")

            if system_resources.are_available:
                self.allocate_free_resources("system")

            if non_system_resources.are_available:
                self.allocate_free_resources("non_system")

            # Monitor current resource usage
            self.monitor_resource_usage()
            
            # Handle any resource prioritization
            self.prioritize_resources()
            
            # Handle any resource contention
            self.handle_resource_contention()
            
            # Check for fallback mechanisms if needed
            self.manage_fallback_mechanisms()

            self.update_the_user_on_heartbeat_actions(mode=self.debug_mode)


    def allocate_system_resources(self) -> Generator:
        """
        Allocate system resources to the program.

        This method allocates system resources like RAM, VRAM, CPU Cores, Disk Space, etc.
        to different parts of the program according to the configuration settings.
        """
        # Check each resource category and yield allocations
        if self.total_allocated_ram - self.current_used_ram > 0:
            ram_to_allocate = min(self.configs.RAM_ALLOCATION_CHUNK, 
                                self.total_allocated_ram - self.current_used_ram)
            self.current_used_ram += ram_to_allocate
            yield {"type": "ram", "amount": ram_to_allocate}
        
        if self.total_allocated_vram - self.current_used_vram > 0:
            vram_to_allocate = min(self.configs.VRAM_ALLOCATION_CHUNK, 
                                 self.total_allocated_vram - self.current_used_vram)
            self.current_used_vram += vram_to_allocate
            yield {"type": "vram", "amount": vram_to_allocate}
        
        if self.total_allocated_cpu_cores - self.current_used_cpu_cores > 0:
            cpu_cores_to_allocate = min(self.configs.CPU_CORES_ALLOCATION_CHUNK, 
                                      self.total_allocated_cpu_cores - self.current_used_cpu_cores)
            self.current_used_cpu_cores += cpu_cores_to_allocate
            yield {"type": "cpu_cores", "amount": cpu_cores_to_allocate}
        
        # Similar for other resources
        for resource_type in ["disk_space", "network_bandwidth", "gpu_processing_time", "io_operations"]:
            attr_name = f"total_allocated_{resource_type}"
            current_attr_name = f"current_used_{resource_type}"
            config_chunk_name = f"{resource_type.upper()}_ALLOCATION_CHUNK"
            
            total = getattr(self, attr_name)
            current = getattr(self, current_attr_name)
            chunk = getattr(self.configs, config_chunk_name, 1)  # Default to 1 if not defined
            
            if total - current > 0:
                to_allocate = min(chunk, total - current)
                setattr(self, current_attr_name, current + to_allocate)
                yield {"type": resource_type, "amount": to_allocate}

    def allocate_non_system_resources(self) -> Generator:
        """
        Allocate non-system resources to the program.

        This method allocates non-system resources like file paths, external APIs, databases, etc.
        to different parts of the program according to the configuration settings.
        """
        # Allocate file paths
        unprocessed_paths = self.file_paths_manager.get_unprocessed_file_paths()
        max_paths_per_allocation = getattr(self.configs, 'MAX_PATHS_PER_ALLOCATION', 10)
        
        for i, file_path in enumerate(unprocessed_paths[:max_paths_per_allocation]):
            self.active_file_paths.add(file_path)
            yield {"type": "file_path", "path": file_path}
        
        # Allocate API tokens if needed
        for api_name, current_count in self.api_call_counts.items():
            limit = self.api_rate_limits.get(api_name, float('inf'))
            if current_count < limit:
                calls_to_allocate = min(getattr(self.configs, f"{api_name.upper()}_API_CHUNK", 1), limit - current_count)
                self.api_call_counts[api_name] = current_count + calls_to_allocate
                yield {"type": "api_calls", "api": api_name, "amount": calls_to_allocate}

    def manage_resource_lifecycle(self) -> None:
        """
        Manage the lifecycle of allocated resources.

        This method handles the lifecycle of allocated resources, including
        monitoring, releasing, and renewing resources as needed.
        """
        # Check for completed file processing
        completed_paths = []
        for path in self.active_file_paths:
            if self.file_paths_manager.is_file_processed(path):
                completed_paths.append(path)
        
        # Release completed file paths
        for path in completed_paths:
            self.active_file_paths.remove(path)
        
        # Release system resources that are no longer in use
        # This would typically involve tracking resource usage by task and releasing when tasks complete
        # For demonstration purposes, we'll use a simple decay mechanism
        decay_rate = getattr(self.configs, 'RESOURCE_DECAY_RATE', 0.05)  # 5% decay by default
        
        self.current_used_ram = max(0, self.current_used_ram - int(self.total_allocated_ram * decay_rate))
        self.current_used_vram = max(0, self.current_used_vram - int(self.total_allocated_vram * decay_rate))
        self.current_used_cpu_cores = max(0, self.current_used_cpu_cores - int(self.total_allocated_cpu_cores * decay_rate))
        self.current_used_disk_space = max(0, self.current_used_disk_space - int(self.total_allocated_disk_space * decay_rate))
        self.current_used_network_bandwidth = max(0, self.current_used_network_bandwidth - int(self.total_allocated_network_bandwidth * decay_rate))
        self.current_used_gpu_processing_time = max(0, self.current_used_gpu_processing_time - int(self.total_allocated_gpu_processing_time * decay_rate))
        self.current_used_io_operations = max(0, self.current_used_io_operations - int(self.total_allocated_io_operations * decay_rate))
        
        # Refresh API call counts periodically
        api_refresh_interval = getattr(self.configs, 'API_REFRESH_INTERVAL', 3600)  # Default 1 hour in seconds
        # In a real implementation, you would check if enough time has passed since the last refresh
        # For demonstration purposes, we'll reset a portion of the API calls on each lifecycle management
        for api in self.api_call_counts:
            self.api_call_counts[api] = max(0, self.api_call_counts[api] - int(self.api_rate_limits.get(api, 100) * 0.01))

    def monitor_resource_usage(self) -> None:
        """
        Monitor resource usage and report statistics.

        This method monitors the usage of allocated resources and reports
        usage statistics to the user and other parts of the program.
        """
        # Calculate usage percentages
        system_resource_usage = {
            "ram": (self.current_used_ram / self.total_allocated_ram) if self.total_allocated_ram > 0 else 0,
            "vram": (self.current_used_vram / self.total_allocated_vram) if self.total_allocated_vram > 0 else 0,
            "cpu_cores": (self.current_used_cpu_cores / self.total_allocated_cpu_cores) if self.total_allocated_cpu_cores > 0 else 0,
            "disk_space": (self.current_used_disk_space / self.total_allocated_disk_space) if self.total_allocated_disk_space > 0 else 0,
            "network_bandwidth": (self.current_used_network_bandwidth / self.total_allocated_network_bandwidth) if self.total_allocated_network_bandwidth > 0 else 0,
            "gpu_processing_time": (self.current_used_gpu_processing_time / self.total_allocated_gpu_processing_time) if self.total_allocated_gpu_processing_time > 0 else 0,
            "io_operations": (self.current_used_io_operations / self.total_allocated_io_operations) if self.total_allocated_io_operations > 0 else 0
        }
        
        # Check for high usage thresholds
        high_usage_threshold = getattr(self.configs, 'HIGH_USAGE_THRESHOLD', 0.8)  # 80% by default
        high_usage_resources = [res for res, usage in system_resource_usage.items() if usage > high_usage_threshold]
        
        if high_usage_resources and hasattr(self.resources, 'logger'):
            self.resources['logger'].warning(f"High resource usage detected for: {', '.join(high_usage_resources)}")
        
        # Report API usage
        for api, count in self.api_call_counts.items():
            limit = self.api_rate_limits.get(api, float('inf'))
            if limit < float('inf') and count / limit > high_usage_threshold:
                if hasattr(self.resources, 'logger'):
                    self.resources['logger'].warning(f"High API usage for {api}: {count}/{limit}")
        
        # Store usage statistics for reporting
        self.resource_usage_stats = {
            "system": system_resource_usage,
            "non_system": {
                "active_file_paths": len(self.active_file_paths),
                "api_usage": {api: count / limit if limit < float('inf') else 0 
                              for api, count in self.api_call_counts.items() 
                              for limit in [self.api_rate_limits.get(api, float('inf'))]}
            }
        }

    def prioritize_resources(self) -> None:
        """
        Implement resource prioritization strategies.

        Priorities are determined by the following:
        - File type prioritization for pending files
        - Whether larger or smaller file sizes take precendence.

        """
        # Define priority strategies based on configuration
        file_type_priority = getattr(self.configs, 'FILE_TYPE_PRIORITY_MOST_TO_LEAST', [])
        prioritize_larger_files = getattr(self.configs, 'LARGER_FILES_FIRST', False)
        prioritize_api_calls = getattr(self.configs, 'PRIORITIZE_API_CALLS', {})
        resource_priority_rules = getattr(self.configs, 'RESOURCE_PRIORITY_RULES', {})
        task_completion_priority = getattr(self.configs, 'TASK_COMPLETION_PRIORITY', True)
        
        # File type prioritization for pending files
        if file_type_priority:
            pending_files = list(self.active_file_paths)
            prioritized_files = []
            
            # Sort files by type priority
            for file_type in file_type_priority:
                matching_files = [f for f in pending_files if f.lower().endswith(f".{file_type.lower()}")]
                prioritized_files.extend(matching_files)
                pending_files = [f for f in pending_files if f not in matching_files]
            
            # Add any files with non-prioritized types at the end
            prioritized_files.extend(pending_files)
            
            # Further sort by file size if configured
            if prioritize_larger_files and hasattr(self.resources, 'file_system'):
                fs = self.resources['file_system']
                prioritized_files.sort(key=lambda f: fs.get_file_size(f), reverse=True)
            
            # Update the active file paths with the new priority order
            self.active_file_paths = set(prioritized_files)
        
        # Get priority settings from configuration for system resources
        resource_priorities = getattr(self.configs, 'RESOURCE_PRIORITIES', {})
        
        # By default, if a component has higher priority, it gets more resources
        if not resource_priorities:
            return
        
        # Prioritize components based on their priority values
        components_by_priority = sorted(resource_priorities.items(), key=lambda x: x[1], reverse=True)
        
        # Allocate resources based on priority
        for resource_type in ["ram", "vram", "cpu_cores", "disk_space", "network_bandwidth", "gpu_processing_time"]:
            available_resource = getattr(self, f"total_allocated_{resource_type}") - getattr(self, f"current_used_{resource_type}")
            
            if available_resource <= 0:
                continue
            
            total_priority = sum(priority for _, priority in components_by_priority)
            if total_priority <= 0:
                continue
            
            # Apply resource-specific rules if defined
            if resource_type in resource_priority_rules:
                # Custom prioritization rules for this resource
                custom_priorities = resource_priority_rules[resource_type]
                components_by_priority = sorted(custom_priorities.items(), key=lambda x: x[1], reverse=True)
                total_priority = sum(priority for _, priority in components_by_priority if priority > 0)
            
            # Allocate based on priority ratio
            for component, priority in components_by_priority:
                if priority <= 0:
                    continue
                    
            resource_to_allocate = int((priority / total_priority) * available_resource)
            if resource_to_allocate > 0 and hasattr(self.resources, component):
                # Apply the allocation
                setattr(self, f"current_used_{resource_type}", 
                   getattr(self, f"current_used_{resource_type}") + resource_to_allocate)
                
                # Notify component (would be implemented in a real system)
                if hasattr(self.resources, 'resource_notifier'):
                    self.resources['resource_notifier'].allocate(
                        component=component, 
                        resource_type=resource_type, 
                        amount=resource_to_allocate
                    )

        # Prioritize API calls if configured
        if prioritize_api_calls and self.api_call_counts:
            for api, priority in prioritize_api_calls.items():
                if api in self.api_call_counts and priority > 0:
                    # Higher priority APIs get more call allocation when rate limited
                    pass  # Implementation would depend on how API calls are managed

        # Task completion priority - allocate more resources to tasks close to completion
        if task_completion_priority and hasattr(self.resources, 'task_manager'):
            task_manager = self.resources['task_manager']
            near_completion_tasks = task_manager.get_tasks_near_completion()
            
            # Boost resources for nearly complete tasks # TODO
            for task in near_completion_tasks: 
            # Implementation would allocate additional resources to these tasks
                pass


        # Get priority settings from configuration
        resource_priorities = getattr(self.configs, 'RESOURCE_PRIORITIES', {})
        
        # By default, if a component has higher priority, it gets more resources
        # This is a simple implementation; in reality, this would be more complex
        if not resource_priorities:
            return
        
        # Example of prioritizing CPU cores based on components' priorities
        components_by_priority = sorted(resource_priorities.items(), key=lambda x: x[1], reverse=True)
        
        # Allocate available CPU cores based on priority
        available_cores = self.total_allocated_cpu_cores - self.current_used_cpu_cores
        if available_cores <= 0:
            return
        
        total_priority = sum(priority for _, priority in components_by_priority)
        for component, priority in components_by_priority:
            # Skip components with zero priority
            if priority <= 0:
                continue
                
            # Calculate cores to allocate based on priority
            cores_to_allocate = int((priority / total_priority) * available_cores)
            if cores_to_allocate > 0 and hasattr(self.resources, component):
                # In a real implementation, you would have a way to inform the component about its allocated resources
                # For demonstration purposes, we'll just update our tracking
                self.current_used_cpu_cores += cores_to_allocate

    def handle_resource_contention(self) -> None:
        """
        Handle resource contention and throttling.

        This method handles resource contention and throttling by implementing
        strategies to resolve conflicts and ensure fair resource allocation.
        """
        # Check if any resource is over-allocated
        resources_over_allocated = []
        
        if self.current_used_ram > self.total_allocated_ram:
            resources_over_allocated.append(("ram", self.current_used_ram - self.total_allocated_ram))
            
        if self.current_used_vram > self.total_allocated_vram:
            resources_over_allocated.append(("vram", self.current_used_vram - self.total_allocated_vram))
            
        if self.current_used_cpu_cores > self.total_allocated_cpu_cores:
            resources_over_allocated.append(("cpu_cores", self.current_used_cpu_cores - self.total_allocated_cpu_cores))
        
        # Handle other resources similarly
        
        if not resources_over_allocated:
            return
            
        # Log the contention
        if hasattr(self.resources, 'logger'):
            self.resources['logger'].warning(f"Resource contention detected: {resources_over_allocated}")
            
        # Implement throttling for over-allocated resources
        # For demonstration purposes, we'll just cap the usage at the maximum
        self.current_used_ram = min(self.current_used_ram, self.total_allocated_ram)
        self.current_used_vram = min(self.current_used_vram, self.total_allocated_vram)
        self.current_used_cpu_cores = min(self.current_used_cpu_cores, self.total_allocated_cpu_cores)
        self.current_used_disk_space = min(self.current_used_disk_space, self.total_allocated_disk_space)
        self.current_used_network_bandwidth = min(self.current_used_network_bandwidth, self.total_allocated_network_bandwidth)
        self.current_used_gpu_processing_time = min(self.current_used_gpu_processing_time, self.total_allocated_gpu_processing_time)
        self.current_used_io_operations = min(self.current_used_io_operations, self.total_allocated_io_operations)

    def manage_fallback_mechanisms(self) -> None:
        """
        Manage fallback mechanisms for resource unavailability.

        This method implements fallback mechanisms to handle cases where
        resources are unavailable or exhausted.
        """
        # Check if any resource is critically low
        critical_threshold = getattr(self.configs, 'CRITICAL_RESOURCE_THRESHOLD', 0.05)  # 5% by default
        
        critical_resources = []
        if self.total_allocated_ram > 0 and (self.total_allocated_ram - self.current_used_ram) / self.total_allocated_ram < critical_threshold:
            critical_resources.append("ram")
            
        if self.total_allocated_vram > 0 and (self.total_allocated_vram - self.current_used_vram) / self.total_allocated_vram < critical_threshold:
            critical_resources.append("vram")
            
        # Check other resources similarly
        
        if not critical_resources:
            return
            
        # Log the critical resource status
        if hasattr(self.resources, 'logger'):
            self.resources['logger'].warning(f"Critical resource levels for: {', '.join(critical_resources)}")
            
        # Implement fallback strategies
        for resource in critical_resources:
            if resource == "ram" and hasattr(self.configs, 'USE_DISK_SWAP') and self.configs.USE_DISK_SWAP:
                # Enable disk swapping as a fallback for low RAM
                if hasattr(self.resources, 'logger'):
                    self.resources['logger'].info("Enabling disk swapping as RAM fallback")
                    
            elif resource == "vram" and hasattr(self.configs, 'USE_CPU_FALLBACK') and self.configs.USE_CPU_FALLBACK:
                # Use CPU as fallback for GPU operations
                if hasattr(self.resources, 'logger'):
                    self.resources['logger'].info("Switching to CPU processing as VRAM fallback")
            
            # Add fallback mechanisms for other resources as needed

    def update_the_user_on_heartbeat_actions(self, mode: bool = False) -> None:
        """
        Update the user on actions taken during the heartbeat.
        
        Args:
            mode: Debug mode flag. If True, more detailed information will be provided.
        """
        if not mode:
            return
            
        # Create a summary of resource usage
        system_usage_summary = {
            "ram": f"{self.current_used_ram}/{self.total_allocated_ram} ({int(self.current_used_ram/self.total_allocated_ram*100 if self.total_allocated_ram > 0 else 0)}%)",
            "vram": f"{self.current_used_vram}/{self.total_allocated_vram} ({int(self.current_used_vram/self.total_allocated_vram*100 if self.total_allocated_vram > 0 else 0)}%)",
            "cpu_cores": f"{self.current_used_cpu_cores}/{self.total_allocated_cpu_cores} ({int(self.current_used_cpu_cores/self.total_allocated_cpu_cores*100 if self.total_allocated_cpu_cores > 0 else 0)}%)",
            "active_file_paths": len(self.active_file_paths),
            "api_usage": {api: f"{count}/{self.api_rate_limits.get(api, 'unlimited')}" for api, count in self.api_call_counts.items()}
        }
        
        if hasattr(self.resources, 'logger'):
            self.resources['logger'].debug(f"Resource usage summary: {system_usage_summary}")
            
        # In a real implementation, this could also update a UI or send notifications
        # depending on the application's requirements

