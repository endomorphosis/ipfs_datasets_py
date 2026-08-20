"""Static-analysis fixture: never import or execute this module."""
from typing import Protocol

class Interface(Protocol):
    def run(self) -> None: ...

class Base:
    pass

class Component:
    pass

class Concrete(Base, Interface):
    component: Component

    def run(self) -> None:
        return None
