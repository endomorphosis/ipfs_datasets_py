"""Static-analysis fixture: never import or execute this module."""
import importlib as loader
import types as runtime_types
from builtins import __import__ as import_builtin
from builtins import setattr as assign_attribute
from ctypes import CDLL as NativeLoader
from importlib.metadata import entry_points as discover_plugins

def aliased_dynamic(name):
    return loader.import_module(name)

def aliased_builtin(name):
    return import_builtin(name)

def native(path):
    return NativeLoader(path)

def plugins():
    return discover_plugins()

def runtime_type(name):
    return type(name, (), {})

def runtime_new(name):
    return runtime_types.new_class(name)

def constructed_attribute(subject, name, value):
    return assign_attribute(subject, name, value)

def import_module():
    return None

def entry_points():
    return ()

class CDLL:
    pass

@framework.hook
def decorated():
    return None

class Meta(type):
    pass

class Generated(metaclass=Meta):
    pass

class Target:
    pass

registry.Target.method = replacement

def factory():
    class Target:
        pass

    return Target
