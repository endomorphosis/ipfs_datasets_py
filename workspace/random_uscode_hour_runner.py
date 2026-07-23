"""Workspace compatibility wrapper for the packaged guarded U.S. Code runner."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (  # noqa: E402
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())
