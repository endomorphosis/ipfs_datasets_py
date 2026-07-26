"""Internal loader for canonical accelerator router aliases."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType


def load_accelerator_router(module_name: str) -> ModuleType:
    """Import a canonical router, including from an enclosing source checkout."""

    qualified_name = f"ipfs_accelerate_py.{module_name}"
    try:
        return importlib.import_module(qualified_name)
    except ModuleNotFoundError as original_error:
        if original_error.name != qualified_name:
            raise
        package = importlib.import_module("ipfs_accelerate_py")
        package_path = getattr(package, "__path__", None)
        if package_path is None:
            raise original_error

        for ancestor in Path(__file__).resolve().parents:
            source_root = ancestor / "ipfs_accelerate_py"
            for candidate in (
                source_root,
                source_root / "ipfs_accelerate_py",
            ):
                if not (
                    (candidate / "__init__.py").is_file()
                    and (candidate / f"{module_name}.py").is_file()
                ):
                    continue
                candidate_text = str(candidate)
                search_path = [
                    candidate_text,
                    *(
                        value
                        for value in package_path
                        if value != candidate_text
                    ),
                ]
                package.__path__ = search_path
                package_spec = getattr(package, "__spec__", None)
                if package_spec is not None:
                    package_spec.submodule_search_locations = search_path
                importlib.invalidate_caches()
                return importlib.import_module(qualified_name)
        raise original_error
