#!/usr/bin/env python3
"""Actual pytest controls with owned tmp_path directories and no current aliases.

The caller supplies the exact selected tests and owned --basetemp. This plugin
changes only tmp_path allocation; it replaces no product or resource hooks.
"""
import hashlib
import json
from pathlib import Path
import sys

import pytest


class OwnedTemporaryPaths:
    def __init__(self):
        self.count = 0
        self.root = None

    @pytest.fixture
    def tmp_path(self, tmp_path_factory, request):
        root = Path(tmp_path_factory.getbasetemp())
        if self.root is None:
            self.root = root
        if root != self.root:
            raise RuntimeError("pytest owned temporary root changed")
        self.count += 1
        if self.count > 4096:
            raise RuntimeError("pytest fixture count exceeds bounded control roster")
        name = "component-" + hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20] + "-" + str(self.count)
        # Real pytest factory; numbered=False omits its automatic *current link.
        path = tmp_path_factory.mktemp(name, numbered=False)
        if path.parent != root or path.is_symlink() or not path.is_dir():
            raise RuntimeError("pytest temporary directory is outside its owned root")
        return path

    def pytest_sessionfinish(self, session, exitstatus):
        print(json.dumps({"schema": "legal-ir-component-controls-fixture-observation/v1",
            "fixture_count": self.count,
            "owned_temporary_root": str(self.root) if self.root is not None else None,
            "pytest_factory_used": True, "numbered": False,
            "automatic_current_aliases_requested": False,
            "product_hooks_replaced": False, "native_resource_hooks_replaced": False}, sort_keys=True), flush=True)


def main():
    return pytest.main(sys.argv[1:], plugins=[OwnedTemporaryPaths()])


if __name__ == "__main__":
    raise SystemExit(main())
