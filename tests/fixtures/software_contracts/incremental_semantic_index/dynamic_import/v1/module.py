import importlib


def load(name: str):
    return importlib.import_module(name)
