import sys
import pkg_resources

print(f"Python version: {sys.version}")
print(f"Executable: {sys.executable}")

print("\nInspecting sys.path:")
for path in sys.path:
    print(f"  {path}")

print("\nInstalled packages:")
for pkg in pkg_resources.working_set:
    print(f"  {pkg.project_name}=={pkg.version}")

print("\nAttempting to import modelcontextprotocol:")
try:
    import modelcontextprotocol
    print(f"Success! Version: {getattr(modelcontextprotocol, '__version__', 'unknown')}")
except ImportError as e:
    print(f"Failed: {e}")
