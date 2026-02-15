




from typing import Callable, Coroutine


class Resource:
    pass


class FileLoader():

    def __init__(self):
        self.monad = None
        self.func: Callable | Coroutine = None

    async def load(resource: Resource) -> Resource:
        """
        
        
        """

