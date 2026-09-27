"""Pin the declared dependency before executing either unchanged smoke lane."""
import argparse
import importlib.abc
import importlib.machinery
from pathlib import Path
import runpy
import sys

from dependency_binding import ROOT, read_binding, require, verify_binding

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane', choices=('training', 'conversion'), required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--start-token', required=True)
    args = parser.parse_args()
    binding = read_binding(HERE / 'frozen-config.json')
    verify_binding(binding)
    accelerate = Path(binding['root'])
    roots = {'ipfs_accelerate_py': accelerate / 'ipfs_accelerate_py',
             'ipfs_datasets_py': ROOT / 'ipfs_datasets_py'}

    def reject_foreign_loaded_modules():
        for name, module in list(sys.modules.items()):
            package = name.split('.')[0]
            if package not in roots or module is None:
                continue
            origin = getattr(module, '__file__', None)
            if origin is not None:
                require(Path(origin).resolve().is_relative_to(roots[package]),
                        'foreign project module already loaded: ' + name)
            for location in getattr(module, '__path__', ()):
                require(Path(location).resolve().is_relative_to(roots[package]),
                        'foreign project package path: ' + name)

    class ProjectRoots(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            package = fullname.split('.')[0]
            if package not in roots:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None:
                raise ModuleNotFoundError('No module named ' + repr(fullname), name=fullname)
            if spec.origin is None:
                locations = spec.submodule_search_locations or ()
                require(bool(locations) and all(Path(value).resolve().is_relative_to(roots[package])
                                               for value in locations), 'foreign namespace package: ' + fullname)
            else:
                require(Path(spec.origin).resolve().is_relative_to(roots[package]),
                        'foreign project import: ' + fullname)
            return spec

    reject_foreign_loaded_modules()
    sys.meta_path.insert(0, ProjectRoots())
    sys.path[:0] = [str(accelerate), str(ROOT), str(ROOT / 'scripts/ops/legal_ir')]
    from run_autoformal_supervisor import pin_accelerate
    pin_accelerate(accelerate)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    reject_foreign_loaded_modules()
    lane = HERE / (args.lane + '_lane.py')
    require(lane.resolve(strict=True) == lane, 'aliased lane script')
    sys.argv = [str(lane), '--runtime-root', str(args.runtime_root), '--start-token', args.start_token]
    try:
        runpy.run_path(str(lane), run_name='__main__')
    finally:
        reject_foreign_loaded_modules()
        verify_binding(binding)


if __name__ == '__main__':
    main()
