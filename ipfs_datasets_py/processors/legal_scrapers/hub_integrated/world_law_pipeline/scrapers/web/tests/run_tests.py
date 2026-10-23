"""Run the tests without pytest (not installed on the box)."""
import inspect, sys, tempfile, traceback
from pathlib import Path
sys.argv = [sys.argv[0]]
sys.path.insert(0, str(Path(__file__).parent))
import importlib
fails = 0
mods = [importlib.import_module(m.stem) for m in sorted(Path(__file__).parent.glob("test_*.py"))]
for n, fn in sorted(((k, v) for m in mods for k, v in vars(m).items() if k.startswith("test_")), key=lambda kv: kv[0]):
    if n.startswith("test_") and callable(fn):
        try:
            if "tmp_path" in inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print("PASS", n)
        except Exception:
            fails += 1
            print("FAIL", n); traceback.print_exc()
sys.exit(1 if fails else 0)
