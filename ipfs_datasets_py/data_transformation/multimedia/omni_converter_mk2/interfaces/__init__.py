"""
Interfaces package for the Omni-Converter.

This package contains the interfaces used by the Omni-Converter, including:
- Python API for programmatic access
- CLI for command-line interaction
- GUI for graphical user interface # TODO: Implement GUI
"""
from interfaces.interfaces_factory import make_cli, make_api, make_gui

__all__ = [
    "make_cli",
    "make_api",
    "make_gui",
]
