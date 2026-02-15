# System Resource Manager

This module provides a system resource management solution that tracks CPU cores, RAM, VRAM, and disk space. It emits resource availability to other components and handles resource allocation/deallocation while respecting configured limits.

## Class Diagram

```mermaid
classDiagram
    class ResourcePacket {
        +int cpuCores
        +int ramMB
        +int vramMB
        +int diskSpaceGB
        +allocate()
        +deallocate()
    }

    class ResourceConfig {
        +int MAX_CPU_CORES
        +int TOTAL_ALLOCATED_RAM
        +int TOTAL_ALLOCATED_VRAM
        +int TOTAL_ALLOCATED_DISK
        +bool ENABLE_OVERCOMMIT
    }

    class BaseResourceManager {
        #ResourceConfig config
        #ResourcePacket totalResources
        #ResourcePacket availableResources
        +recalculateResources()
        +requestResources(ResourcePacket)
        +releaseResources(ResourcePacket)
        +getAvailableResources()
        #validateRequest(ResourcePacket)
    }

    class SystemResourceManager {
        -detectHardware()
        -monitorResourceUsage()
        +heartbeat()
        +exportToExternalResourceManager()
    }

    class HardwareMonitor {
        +getTotalCpuCores()
        +getFreeCpuCores()
        +getTotalMemory() 
        +getFreeMemory()
        +getTotalVram()
        +getFreeVram()
        +getTotalDiskSpace()
        +getFreeDiskSpace()
    }

    class ResourceEmitter {
        <<interface>>
        +emitResourceUpdate(ResourcePacket)
        +emitResourceWarning(string message)
        +subscribeToResourceUpdates(callback)
    }

    BaseResourceManager <|-- SystemResourceManager
    SystemResourceManager *-- HardwareMonitor
    SystemResourceManager *-- ResourceConfig
    SystemResourceManager ..|> ResourceEmitter
    BaseResourceManager o-- ResourcePacket