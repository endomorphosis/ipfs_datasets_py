"""
Pytest configuration and custom exceptions for test stubs from Gherkin.
"""


class FixtureError(Exception):
    """
    Custom exception raised when a fixture fails to be created or initialized.
    
    This exception is used to provide clear error messages when fixture setup fails,
    wrapping the original exception and providing context about which fixture failed.
    """
    pass
