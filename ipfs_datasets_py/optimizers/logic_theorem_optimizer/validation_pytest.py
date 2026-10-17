"""Opt-in pytest tmp_path profile for strict owned regular-file inventories.

Use ``-p ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest``.
Unlike pytest's numbered tmp_path helper, this fixture creates no convenience
``...current`` symlink. Every test still receives a unique private directory;
all directories are retained as validation evidence. The factory fixture itself
is unchanged, so suites that require numbered factory aliases need a different
explicitly supported profile. No test assertions or selection rules change.
"""
from __future__ import annotations

from pathlib import Path
import re
import stat
import tempfile

import pytest


@pytest.fixture
def tmp_path(request, tmp_path_factory):
    """A function-scoped private directory below the explicit owned basetemp."""
    configured = request.config.option.basetemp
    if configured is None:
        raise pytest.UsageError('owned validation requires explicit --basetemp')
    base = Path(tmp_path_factory.getbasetemp())
    if not Path(configured).is_absolute() or base != Path(configured):
        raise pytest.UsageError('owned validation requires the exact absolute basetemp')
    for parent in (base, *base.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise pytest.UsageError('owned validation basetemp must be an unaliased directory')
    name = re.sub(r'[^A-Za-z0-9_]', '_', request.node.name)[:48]
    return Path(tempfile.mkdtemp(prefix=name+'-', dir=base))
