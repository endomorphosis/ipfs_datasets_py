

import asyncio
from threading import RLock, Lock
from typing import Final

from pydantic_models.resource.resource import Resource
from pydantic_models.configs import Configs


class ResourceError(Exception):
    pass


class SystemResourcesPoolTemplate():
    """
    Attributes:
    - amount_available (int): The amount of resources available in the pool.
    - max_value (asyncio.Semaphore): The maximum number of the resources a pool can have.
    - min_value (asyncio.Semaphore): The minimum number of the resources a pool can have.
    - resource_type (Resource): The type of resource the pool manages.
    """

    def __init__(self, configs: Configs):
        self.timeout: Final[float] = configs.RESOURCE_TIMEOUT or 30.0
        self.max_value = Lock()
        self.min_value = Lock()
        self.amount_available: int = 0

        self._amount_lock = Lock()
        self._resource_available = asyncio.Condition(self._amount_lock)


    async def add_value_to_resource(self, resource: Resource) -> Resource:
        """
        Add a specified amount of resources to a Resource object.

        This method will block until the resource is available if the class' counter 
        is at its minimum value. Thread-safe and handles concurrent access.

        Args:
            resource (Resource): The resource object to modify.

        Returns:
            Resource: The updated resource object.

        Raises:
            ValueError: If the specified amount is less than or equal to zero.
            TypeError: If the specified amount is not an integer.
            ResourceError: If the resource is already at maximum or not available.
            TimeoutError: If the resource is not available within timeout (seconds).

        Example:
            >>> async with ResourceManager() as rm:
            >>>     resource = await rm.add_value_to_resource(my_resource)
        """
        async with asyncio.timeout(self.timeout):
            async with self.max_value:
                try:
                    return await self._add_value_implementation(resource)
                except Exception as e:
                    raise ResourceError(f"Failed to add resource: {e}")


    async def _add_value_implementation(self, resource: Resource) -> Resource:
        amount_requested = resource.request_this(self.resource_type)

        if amount_requested >= 0:
            async with self._amount_lock:
                while amount_requested > self.amount_available:
                    await self._resource_available.wait()
                    
                for _ in range(amount_requested):
                    await self.min_value.acquire()
                    resource.acquire(self.resource_type)
                    self.amount_available -= 1
        return resource


    async def remove_value_from_resource(self, resource: Resource) -> Resource:
        """
        Release resources from a Resource object back to the pool.

        This method removes the specified amount of resources from the Resource object
        and returns them to the pool. It also notifies any waiting tasks that resources
        are now available.

        Args:
            resource (Resource): The resource object to modify.

        Returns:
            Resource: The updated resource object.

        Raises:
            ValueError: If the specified amount is less than or equal to zero.
            ResourceError: If there's an error during the resource removal process.
        """
        async with asyncio.timeout(self.timeout):
            try:
                return await self._remove_value_implementation(resource)
            except Exception as e:
                raise ResourceError(f"Failed to return resource: {e}")

    async def _remove_value_implementation(self, resource: Resource) -> Resource:
        amount = resource.release(self.resource_type)

        if amount >= 0:
            async with self._amount_lock:
                self.amount_available += amount
                for _ in range(amount):
                    self.min_value.release()
                self._resource_available.notify_all()
        return resource



















                await self._resource_available.wait()  # Add condition variable
                
            for _ in range(amount_requested):
                await self.min_value.acquire()
                resource.add(1)
                self.amount_available -= 1
                
            return resource



    async def add_value_to_resource(self, resource: Resource) -> Resource:
        """
        Add a specified amount of resources to the Resource object.

        This method will block until the resource is available if the class' counter is at its minimum value.
        Once the resource is successfully added, the class' resource_counter will be decremented by the specified amount.

        Args:
            resource (Resource): The resource object to modify.

        Returns:
            Resource: The updated resource object.

        Raises:
            ValueError: If the specified amount is less than or equal to zero.
            TypeError: If the specified amount is not an integer.
            ResourceError: If the resource is already at its maximum value or not available.
            asyncio.TimeoutError: If the resource is not available within the specified timeout.
        """
        try:
            await asyncio.wait_for(self.max_value.acquire(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError("Resource not available within the specified timeout.")

        try:
            amount_requested = resource.request(self.resource_type)

            if amount_requested <= 0:
                raise ValueError("Requested amount must be greater than zero.")

            while amount_requested > self.amount_available:
                # Wait for resources to become available.
                pass

            for _ in range(amount_requested):
                await self.min_value.acquire()
                resource.add(1)
                self.amount_available -= 1

            return resource
        except Exception as e:
            self.max_value.release()
            raise ResourceError(f"Failed to add resource: {e}")
        finally:
            self.max_value.release()

    def remove_value_from_resource(self, resource: Resource, timeout: float = None) -> Resource:
        """
        Subtract a specified amount of resources from the Resource object.

        This method will block until the resource is available if the class' counter is at its maximum value.
        Once the resource is successfully removed, the class' resource_counter will be incremented by the specified amount.
        """
        while self.resource_counter <= self.min_value:
            # Wait for resources to become available
            pass
        resource.request()
        self.resource_counter -= 1






