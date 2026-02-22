import anyio
from threading import Lock
from typing import Final

from pydantic_models.resource.resource import Resource
from pydantic_models.configs import Configs


class ResourceError(Exception):
    pass


class _AnyioCondition:
    """Minimal anyio-compatible condition variable.

    Provides ``wait()`` / ``notify_all()`` semantics using a list of
    ``anyio.Event`` instances.  The caller must hold ``lock`` before calling
    either method and release it before ``await``-ing a waiter event.
    """

    def __init__(self) -> None:
        self._waiters: list[anyio.Event] = []

    async def wait(self, lock: anyio.Lock) -> None:
        """Release *lock*, wait for a notification, then re-acquire *lock*."""
        ev = anyio.Event()
        self._waiters.append(ev)
        lock.release()           # type: ignore[attr-defined]
        try:
            await ev.wait()
        finally:
            await lock.acquire()  # type: ignore[attr-defined]

    def notify_all(self) -> None:
        """Wake all tasks waiting via ``wait()``."""
        for ev in self._waiters:
            ev.set()
        self._waiters.clear()


class SystemResourcesPoolTemplate():
    """
    Attributes:
    - amount_available (int): The amount of resources available in the pool.
    - max_value (Lock): Guards the maximum number of resources.
    - min_value (Lock): Guards the minimum number of resources.
    - resource_type (Resource): The type of resource the pool manages.
    """

    def __init__(self, configs: Configs):
        self.timeout: Final[float] = configs.RESOURCE_TIMEOUT or 30.0
        self.max_value = Lock()
        self.min_value = Lock()
        self.amount_available: int = 0

        self._amount_lock = anyio.Lock()
        self._resource_available = _AnyioCondition()


    async def add_value_to_resource(self, resource: Resource) -> Resource:
        """
        Add a specified amount of resources to a Resource object.

        This method will block until the resource is available if the class\'
        counter is at its minimum value.

        Args:
            resource (Resource): The resource object to modify.

        Returns:
            Resource: The updated resource object.

        Raises:
            ValueError: If the specified amount is less than or equal to zero.
            TypeError: If the specified amount is not an integer.
            ResourceError: If the resource is already at maximum or not available.
            TimeoutError: If the resource is not available within timeout (seconds).
        """
        with anyio.fail_after(self.timeout):
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
                    await self._resource_available.wait(self._amount_lock)

                for _ in range(amount_requested):
                    await self.min_value.acquire()
                    resource.acquire(self.resource_type)
                    self.amount_available -= 1
        return resource


    async def remove_value_from_resource(self, resource: Resource) -> Resource:
        """
        Release resources from a Resource object back to the pool.

        Args:
            resource (Resource): The resource object to modify.

        Returns:
            Resource: The updated resource object.

        Raises:
            ValueError: If the specified amount is less than or equal to zero.
            ResourceError: If there is an error during the resource removal process.
        """
        with anyio.fail_after(self.timeout):
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
