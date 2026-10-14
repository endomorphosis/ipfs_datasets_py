"""Explicit resource namespace shells; native package initializers never execute.

This is a qualified alternative bootstrap, not native-package-init equivalence.
Only the unchanged telemetry/proof/scheduler snapshot files may be imported.
"""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
from pathlib import Path
import stat
import sys
import types

SOURCE = Path(__file__).resolve().parent / 'resource-source-v01'
SOURCE_PINS = {
    'ipfs_datasets_py/__init__.py': (56829, 'f258f8eada774251feacd8e2ee2048efe56c89a8ee88efd50e4271ea41d43dc9'),
    'ipfs_datasets_py/optimizers/__init__.py': (957, 'a12bab3724da07be67b447719ace42fc1f480cb5635581f320a99a372f02f450'),
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/__init__.py': (69336, '9d693fa576f00dc36899faad75ef3044c437e2bfec5c62306f7031236725bb0e'),
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py': (53075, '542f705867b93fcb138a117e1f5c97a144ad6635dc92c37bc5034eee5065ef63'),
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py': (15543, '3655923785cb99409171caaba8c523354f03dbe8d82b6deb45a7b46db8394633'),
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py': (111009, '75fc31a79031ba941fb81570419e0c630c67363d77aafc97979a156cd02248a4'),
}
PACKAGES = ('ipfs_datasets_py', 'ipfs_datasets_py.optimizers', 'ipfs_datasets_py.optimizers.logic_theorem_optimizer')
MODULES = {PACKAGES[-1] + '.' + name: 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/' + name + '.py'
           for name in ('runtime_telemetry', 'proof_resource_safety', 'resource_scheduler')}


def require(value, message):
    if not value:
        raise ValueError(message)


def checked_source(relative):
    require(relative in SOURCE_PINS, 'closed resource source roster required')
    path = SOURCE / relative
    info = path.lstat()
    require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode) and not path.is_symlink(),
            'physical resource snapshot source required')
    raw = path.read_bytes(); after = path.stat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(info) == identity(after) and (len(raw), hashlib.sha256(raw).hexdigest()) == SOURCE_PINS[relative],
            'exact resource snapshot source required')
    return path, raw


class CheckedSourceLoader(importlib.abc.Loader):
    """Execute the authenticated source bytes; never consult a bytecode cache."""
    def __init__(self, fullname, relative):
        self.fullname, self.relative = fullname, relative

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        require(module.__name__ == self.fullname and MODULES.get(self.fullname) == self.relative,
                'exact resource source-loader identity required')
        path, raw = checked_source(self.relative)
        module.__file__ = str(path)
        module.__package__ = self.fullname.rpartition('.')[0]
        exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
        _, after_raw = checked_source(self.relative)
        require(after_raw == raw, 'executed resource source changed')


class ResourceOnlyFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        require(fullname.split('.')[0] not in {'torch','numpy','transformers','sentence_transformers','huggingface_hub'},
                'numerical or SDK imports forbidden in resource bootstrap')
        if fullname == 'ipfs_datasets_py' or fullname.startswith('ipfs_datasets_py.'):
            require(fullname in MODULES, 'unqualified resource-package import refused')
            origin, _ = checked_source(MODULES[fullname])
            return importlib.util.spec_from_loader(fullname, CheckedSourceLoader(fullname, MODULES[fullname]), origin=str(origin))
        return None


def bootstrap():
    require(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
            'fresh process required for explicit resource namespace shells')
    require(not any(name.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','huggingface_hub'} for name in sys.modules),
            'fresh resource process may not preload numerical or SDK modules')
    for relative in SOURCE_PINS:
        checked_source(relative)
    sys.dont_write_bytecode = True
    finder = ResourceOnlyFinder()
    sys.meta_path.insert(0, finder)
    for name in PACKAGES:
        relative = name.replace('.', '/') + '/__init__.py'
        origin, _ = checked_source(relative)
        shell = types.ModuleType(name)
        shell.__file__ = str(origin)
        shell.__package__ = name
        shell.__path__ = [str(origin.parent)]
        shell.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
        shell.__spec__.origin = 'explicit-inert-resource-namespace-shell'
        shell.__spec__.submodule_search_locations = list(shell.__path__)
        shell.__resource_namespace_shell__ = True
        sys.modules[name] = shell
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(sys.modules[parent], child, shell)
    for name in MODULES:
        module = importlib.import_module(name)
        require(Path(module.__file__).resolve() == checked_source(MODULES[name])[0], 'resource module origin changed')
    allowed = set(PACKAGES) | set(MODULES)
    require({name for name in sys.modules if name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.')} == allowed,
            'resource namespace imported unqualified modules')
    for relative in SOURCE_PINS:
        checked_source(relative)
    package = sys.modules[PACKAGES[-1]]
    scheduler = sys.modules[PACKAGES[-1] + '.resource_scheduler']
    report = dict(schema='actor-context-ranking-resource-namespace-bootstrap/v1',
                  package_initializers_executed=False, package_initializer_files_custody_pinned=3,
                  native_package_init_equivalence_claimed=False, router_deps_imported=False,
                  exact_source_bytes_compiled_directly=True, bytecode_cache_reads_by_resource_loader=False,
                  canonical_inert_package_shell_count=3, executed_unchanged_resource_source_count=3,
                  resource_source_root=str(SOURCE), sys_path_source_root_added=False,
                  model_calls=0, scheduler_client_constructed=False, shared_state_read_by_bootstrap=False)
    return package, scheduler, report
