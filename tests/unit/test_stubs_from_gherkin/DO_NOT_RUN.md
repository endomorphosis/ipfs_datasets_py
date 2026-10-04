# Test Stubs Directory - Do Not Run

This directory contains template files that should NOT be collected or run by pytest.

These are stubs for implementing tests with pytest-bdd framework.
They require manual implementation before they can be used.

Pytest is configured to skip this directory via:
- conftest.py in this directory
- norecursedirs in pytest.ini

If you want to use these stubs:
1. Copy the relevant stub file to a different location
2. Install pytest-bdd: `pip install pytest-bdd`
3. Implement the fixture and step definitions
4. Connect to the corresponding .feature file
5. Run the implemented tests
