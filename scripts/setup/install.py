#!/usr/bin/env python3
"""
Unified IPFS Datasets Dependency Installer
One-stop solution for installing and managing dependencies.
"""

import os
import sys
import subprocess
import argparse
import json
import platform
from pathlib import Path
import importlib.util
import importlib.metadata
import tempfile

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

_VENV_SYNC_MARKER = ".ipfs_datasets_py_venv_sync.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _setup_scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _venv_python(venv_dir: Path) -> Path:
    if IS_WINDOWS:
        return venv_dir / 'Scripts' / 'python.exe'
    return venv_dir / 'bin' / 'python'


def _venv_marker_payload(repo_root: Path) -> dict:
    tracked_files = [
        repo_root / 'requirements.txt',
        repo_root / 'pyproject.toml',
        repo_root / 'setup.py',
        repo_root / 'scripts' / 'setup' / 'install.py',
    ]
    return {
        'tracked_files': {
            str(path.relative_to(repo_root)): path.stat().st_mtime_ns
            for path in tracked_files
            if path.exists()
        },
        'python': f'{sys.version_info.major}.{sys.version_info.minor}',
    }


def _needs_venv_sync(repo_root: Path, venv_dir: Path) -> bool:
    marker_path = venv_dir / _VENV_SYNC_MARKER
    if not marker_path.exists():
        return True
    try:
        current = _venv_marker_payload(repo_root)
        previous = json.loads(marker_path.read_text(encoding='utf-8'))
        return previous != current
    except Exception:
        return True


def _write_venv_sync_marker(repo_root: Path, venv_dir: Path) -> None:
    marker_path = venv_dir / _VENV_SYNC_MARKER
    marker_path.write_text(json.dumps(_venv_marker_payload(repo_root), indent=2, sort_keys=True), encoding='utf-8')


def _create_or_reuse_venv(venv_dir: Path) -> Path:
    python_path = _venv_python(venv_dir)
    if python_path.exists():
        return python_path

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"📦 Creating virtual environment at {venv_dir}...")
    subprocess.run([sys.executable, '-m', 'venv', str(venv_dir)], check=True, text=True)
    return python_path


def _local_requirement_overrides(repo_root: Path) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    candidate_paths = {
        'ipfs_kit_py': repo_root / 'ipfs_kit_py',
        'ipfs_accelerate_py': repo_root / 'ipfs_accelerate_py',
    }
    for package_name, package_path in candidate_paths.items():
        if not package_path.is_dir():
            continue
        if (package_path / 'pyproject.toml').exists() or (package_path / 'setup.py').exists():
            overrides[package_name] = package_path
    return overrides


def _is_local_package_installed(package_name: str, package_path: Path) -> bool:
    try:
        spec = importlib.util.find_spec(package_name)
        if not spec or not spec.origin:
            return False
        origin_path = Path(spec.origin).resolve()
        return str(package_path.resolve()).lower() in str(origin_path).lower()
    except Exception:
        return False


def _install_requirements_with_local_overrides(python_path: Path, repo_root: Path, requirements_path: Path) -> None:
    overrides = _local_requirement_overrides(repo_root)
    filtered_lines: list[str] = []
    for raw_line in requirements_path.read_text(encoding='utf-8').splitlines():
        stripped = raw_line.strip()
        if overrides.get('ipfs_kit_py') and 'github.com/endomorphosis/ipfs_kit_py.git' in stripped:
            continue
        if overrides.get('ipfs_accelerate_py') and 'github.com/endomorphosis/ipfs_accelerate_py.git' in stripped:
            continue
        filtered_lines.append(raw_line)

    with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='-requirements.txt', delete=False) as handle:
        handle.write('\n'.join(filtered_lines) + '\n')
        temp_requirements_path = Path(handle.name)

    try:
        subprocess.run([str(python_path), '-m', 'pip', 'install', '-r', str(temp_requirements_path)], check=True, text=True)
        for package_name, package_path in overrides.items():
            print(f"📦 Installing local {package_name} from {package_path}...")
            subprocess.run([str(python_path), '-m', 'pip', 'install', '-e', str(package_path)], check=True, text=True)
    finally:
        temp_requirements_path.unlink(missing_ok=True)


def _prune_stale_torch_cuda_packages(python_path: Path) -> None:
    script = r'''
import importlib.metadata as md
import json
import platform
from packaging.requirements import Requirement

installed_nvidia = {}
for dist in md.distributions():
    name = dist.metadata.get('Name', '')
    if name.lower().startswith('nvidia-'):
        installed_nvidia[name] = dist.version

required = set()
try:
    torch = md.distribution('torch')
except Exception:
    torch = None

if torch is not None:
    for raw in torch.requires or []:
        try:
            requirement = Requirement(raw)
        except Exception:
            continue
        if not requirement.name.lower().startswith('nvidia-'):
            continue
        marker = requirement.marker
        if marker is not None and not marker.evaluate():
            continue
        required.add(requirement.name)

stale = sorted(name for name in installed_nvidia if name not in required)
print(json.dumps({'stale': stale}))
'''
    result = subprocess.run([str(python_path), '-c', script], check=True, text=True, capture_output=True)
    payload = json.loads(result.stdout.strip() or '{}')
    stale_packages = list(payload.get('stale') or [])
    if not stale_packages:
        return
    print(f"🧹 Removing stale Torch/CUDA packages: {', '.join(stale_packages)}")
    subprocess.run([str(python_path), '-m', 'pip', 'uninstall', '-y', *stale_packages], check=True, text=True)


def _sync_venv_dependencies(repo_root: Path, venv_dir: Path) -> None:
    python_path = _create_or_reuse_venv(venv_dir)
    needs_sync = _needs_venv_sync(repo_root, venv_dir)
    if not needs_sync:
        _prune_stale_torch_cuda_packages(python_path)
        return

    requirements_path = repo_root / 'requirements.txt'
    editable_target = repo_root
    print(f"📦 Syncing dependencies into {venv_dir}...")
    subprocess.run([str(python_path), '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'], check=True, text=True)
    _install_requirements_with_local_overrides(python_path, repo_root, requirements_path)
    subprocess.run([str(python_path), '-m', 'pip', 'install', '-e', str(editable_target), '--no-deps'], check=True, text=True)
    _prune_stale_torch_cuda_packages(python_path)
    _write_venv_sync_marker(repo_root, venv_dir)


def ensure_project_venv(original_argv: list[str], *, venv_dir: Path, disable_bootstrap: bool) -> None:
    if disable_bootstrap:
        return

    repo_root = _repo_root()
    target_python = _venv_python(venv_dir)
    running_in_target_venv = False
    try:
        running_in_target_venv = Path(sys.prefix).resolve() == venv_dir.resolve()
    except Exception:
        running_in_target_venv = False

    if running_in_target_venv:
        _sync_venv_dependencies(repo_root, venv_dir)
        return

    _sync_venv_dependencies(repo_root, venv_dir)
    print(f"✅ Re-running setup inside {venv_dir}...")
    os.execv(str(target_python), [str(target_python), __file__, '--no-venv-bootstrap', *original_argv])


def ensure_logic_provers() -> None:
    """Best-effort install of external provers (Z3/CVC5/Lean/Coq).

    This script is what users commonly run for setup; setup.py hooks do not run
    in all pip install modes (e.g. wheels/PEP517), so we also run the installer here.

    Controlled via env vars (defaults ON):
    - IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS
    - IPFS_DATASETS_PY_AUTO_INSTALL_Z3
    - IPFS_DATASETS_PY_AUTO_INSTALL_CVC5
    - IPFS_DATASETS_PY_AUTO_INSTALL_LEAN
    - IPFS_DATASETS_PY_AUTO_INSTALL_COQ
    """

    def env_truthy(name: str, default: str = "1") -> bool:
        value = os.environ.get(name, default)
        return str(value).strip().lower() not in {"0", "false", "no", "off", ""}

    if not env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS", "1"):
        return

    repo_root = Path(__file__).resolve().parents[2]
    installer = repo_root / "ipfs_prover_installer.py"
    if not installer.exists():
        return

    args = [sys.executable, str(installer), "--yes"]
    if env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_Z3", "1"):
        args.append("--z3")
    if env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_CVC5", "1"):
        args.append("--cvc5")
    if env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_LEAN", "1"):
        args.append("--lean")
    if env_truthy("IPFS_DATASETS_PY_AUTO_INSTALL_COQ", "1"):
        args.append("--coq")

    print("\n🧠 Installing theorem provers (best-effort)...")
    subprocess.run(args, check=False, text=True)

def _is_main_ipfs_kit_py_installed(repo_path: Path) -> bool:
    """Check whether ipfs_kit_py is installed from the main repo path."""
    try:
        spec = importlib.util.find_spec('ipfs_kit_py')
        if not spec or not spec.origin:
            return False
        origin_path = Path(spec.origin).resolve()
        repo_resolved = repo_path.resolve()
        return str(repo_resolved).lower() in str(origin_path).lower()
    except Exception:
        return False

def ensure_main_ipfs_kit_py() -> None:
    """Ensure ipfs_kit_py is installed from the main branch."""

    os.environ.setdefault('IPFS_KIT_PY_USE_GIT', 'true')

    repo_root = Path(__file__).resolve().parents[2]
    repo_path = repo_root / '.tools' / 'ipfs_kit_py'
    marker_file = repo_path / '.main_installed'

    if marker_file.exists():
        os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
        return

    if _is_main_ipfs_kit_py_installed(repo_path):
        os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
        return

    try:
        subprocess.run(['git', '--version'], check=True, capture_output=True, text=True)
    except Exception as e:
        print(f"⚠️ Git not available; skipping main ipfs_kit_py install: {e}")
        return

    try:
        repo_path.parent.mkdir(parents=True, exist_ok=True)

        if not (repo_path / '.git').exists():
            subprocess.run([
                'git', 'clone', '--filter=blob:none',
                'https://github.com/endomorphosis/ipfs_kit_py.git',
                str(repo_path)
            ], check=False, text=True)

        subprocess.run(['git', '-C', str(repo_path), 'fetch', '--all', '--prune'], check=False, text=True)
        subprocess.run(['git', '-C', str(repo_path), 'checkout', 'main'], check=False, text=True)

        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-e', str(repo_path),
            '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
        ], check=False, text=True)
        if result.returncode == 0:
            marker_file.write_text('main', encoding='utf-8')
            os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
    except Exception as e:
        print(f"⚠️ Failed to install main ipfs_kit_py: {e}")


def ensure_libp2p_main() -> None:
    """Ensure libp2p is installed from the git main branch."""
    if importlib.util.find_spec('libp2p') is not None:
        print("✅ libp2p already installed")
        return
    try:
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'pip',
                'install',
                '--upgrade',
                '--no-deps',
                'libp2p @ git+https://github.com/libp2p/py-libp2p.git@main',
                '--disable-pip-version-check',
                '--no-input',
                '--progress-bar',
                'off',
            ],
            check=False,
            text=True,
        )
        if result.returncode == 0:
            print("✅ Installed libp2p from git main branch")
        else:
            print(f"⚠️ Failed to install libp2p from git main: {result.stderr.strip()}")
    except Exception as e:
        print(f"⚠️ Failed to install libp2p from git main: {e}")


def ensure_ipfs_accelerate_py() -> None:
    """Ensure ipfs_accelerate_py is installed from the main branch."""
    repo_root = _repo_root()
    local_path = repo_root / 'ipfs_accelerate_py'

    if local_path.is_dir() and ((local_path / 'pyproject.toml').exists() or (local_path / 'setup.py').exists()):
        if _is_local_package_installed('ipfs_accelerate_py', local_path):
            print("✅ ipfs_accelerate_py already installed from local checkout")
            return
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'pip',
                    'install',
                    '-e',
                    str(local_path),
                    '--disable-pip-version-check',
                    '--no-input',
                    '--progress-bar',
                    'off',
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("✅ Installed ipfs_accelerate_py from local checkout")
                return
            error_msg = result.stderr or result.stdout or "No error details available"
            print(f"⚠️ Failed to install ipfs_accelerate_py from local checkout: {error_msg.strip()}")
        except Exception as e:
            print(f"⚠️ Failed to install ipfs_accelerate_py from local checkout: {e}")

    try:
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'pip',
                'install',
                '--upgrade',
                'ipfs_accelerate_py @ git+https://github.com/endomorphosis/ipfs_accelerate_py.git@main',
                '--disable-pip-version-check',
                '--no-input',
                '--progress-bar',
                'off',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("✅ Installed ipfs_accelerate_py from git main branch")
        else:
            error_msg = result.stderr or result.stdout or "No error details available"
            print(f"⚠️ Failed to install ipfs_accelerate_py from git main: {error_msg.strip()}")
    except Exception as e:
        print(f"⚠️ Failed to install ipfs_accelerate_py from git main: {e}")

def run_setup_wizard():
    """Run the interactive setup wizard"""
    print("🧙 IPFS Datasets Setup Wizard")
    print("=" * 40)
    
    print("\nChoose your installation type:")
    print("1. Quick Setup (core dependencies for CLI)")
    print("2. Interactive Setup (custom selection)")
    print("3. Profile-based (specific features)")
    print("4. Health Check (diagnose issues)")
    print("5. Full Analysis (comprehensive scan)")
    
    while True:
        try:
            choice = input("\nSelect option (1-5): ").strip()
            
            if choice == "1":
                return quick_setup()
            elif choice == "2":
                return interactive_setup()
            elif choice == "3":
                return profile_setup()
            elif choice == "4":
                return health_check()
            elif choice == "5":
                return full_analysis()
            else:
                print("Invalid choice, please select 1-5")
                
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            return 1

def quick_setup():
    """Run quick setup for core dependencies"""
    print("\n🚀 Running Quick Setup...")
    
    try:
        quick_setup_path = Path(__file__).resolve().with_name('quick_setup.py')
        result = subprocess.run([sys.executable, str(quick_setup_path)], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Quick setup failed: {e}")
        return 1

def interactive_setup():
    """Run interactive dependency manager setup"""
    print("\n🎛️ Running Interactive Setup...")
    
    try:
        result = subprocess.run([sys.executable, str(_setup_scripts_dir() / 'dependency_manager.py'), 'setup'], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Interactive setup failed: {e}")
        return 1

def profile_setup():
    """Install specific dependency profiles"""
    print("\n📦 Profile-based Installation")
    
    profiles = {
        'minimal': 'Basic functionality only',
        'cli': 'CLI tools functionality', 
        'pdf': 'PDF processing capabilities',
        'ml': 'Machine learning and AI features',
        'vectors': 'Vector storage and search',
        'web': 'Web scraping and archiving',
        'media': 'Media processing (audio/video)',
        'api': 'FastAPI web services',
        'dev': 'Development and testing',
        'full': 'All functionality (everything)'
    }
    
    print("\nAvailable profiles:")
    for i, (name, desc) in enumerate(profiles.items(), 1):
        print(f"{i:2d}. {name:8s} - {desc}")
    
    try:
        choice = input(f"\nSelect profile (1-{len(profiles)}): ").strip()
        profile_idx = int(choice) - 1
        profile_names = list(profiles.keys())
        
        if 0 <= profile_idx < len(profile_names):
            profile_name = profile_names[profile_idx]
            print(f"\n📦 Installing {profile_name} profile...")
            
            result = subprocess.run([
                sys.executable, str(_setup_scripts_dir() / 'dependency_manager.py'), 'install', 
                '--profile', profile_name
            ], check=False, text=True)
            
            return result.returncode
        else:
            print("Invalid selection")
            return 1
            
    except (ValueError, KeyboardInterrupt):
        print("Installation cancelled")
        return 1

def health_check():
    """Run dependency health check"""
    print("\n🏥 Running Health Check...")
    
    try:
        result = subprocess.run([sys.executable, str(_setup_scripts_dir() / 'dependency_health_checker.py'), 'check'], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return 1

def full_analysis():
    """Run comprehensive dependency analysis"""
    print("\n📊 Running Full Analysis...")
    
    try:
        result = subprocess.run([sys.executable, str(_setup_scripts_dir() / 'dependency_manager.py'), 'analyze'], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        return 1

def test_installation():
    """Test CLI functionality after installation"""
    print("\n🧪 Testing CLI Functionality...")
    
    try:
        result = subprocess.run([sys.executable, str(_setup_scripts_dir() / 'comprehensive_cli_test.py')], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Testing failed: {e}")
        return 1

def show_status():
    """Show current dependency status"""
    print("\n📋 Current Dependency Status")
    print("=" * 35)
    
    # Quick check of critical dependencies
    critical_deps = [
        ('numpy', 'numpy'),
        ('pandas', 'pandas'),
        ('requests', 'requests'),
        ('pyyaml', 'yaml'),
        ('tqdm', 'tqdm'),
    ]
    
    for label, module_name in critical_deps:
        try:
            __import__(module_name)
            print(f"✅ {label:12s} - Available")
        except ImportError:
            print(f"❌ {label:12s} - Missing")
    
    print(f"\nFor detailed status, run: python {_setup_scripts_dir() / 'dependency_health_checker.py'} check")

def main():
    """Main CLI interface"""
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description='IPFS Datasets Unified Dependency Installer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install.py                    # Interactive wizard
  python install.py --quick           # Quick setup
  python install.py --profile ml      # Install ML profile  
  python install.py --health          # Health check
  python install.py --test            # Test CLI tools
  python install.py --status          # Show status
        """
    )
    
    parser.add_argument('--quick', action='store_true',
                       help='Run quick setup (core dependencies)')
    parser.add_argument('--profile', 
                       choices=['minimal', 'cli', 'pdf', 'ml', 'vectors', 
                               'web', 'media', 'api', 'dev', 'full'],
                       help='Install specific dependency profile')
    parser.add_argument('--health', action='store_true',
                       help='Run dependency health check')
    parser.add_argument('--analyze', action='store_true',
                       help='Run comprehensive dependency analysis')
    parser.add_argument('--test', action='store_true',
                       help='Test CLI functionality')
    parser.add_argument('--status', action='store_true',
                       help='Show current dependency status')
    parser.add_argument('--enable-auto-install', action='store_true',
                       help='Enable automatic dependency installation')
    parser.add_argument('--venv-dir', default=str(repo_root / '.venv'),
                       help='Virtual environment path to create/sync before running setup')
    parser.add_argument('--no-venv-bootstrap', action='store_true',
                       help='Skip automatic .venv creation and dependency sync')
    
    args = parser.parse_args()

    ensure_project_venv(
        sys.argv[1:],
        venv_dir=Path(args.venv_dir).resolve(),
        disable_bootstrap=bool(args.no_venv_bootstrap),
    )

    ensure_main_ipfs_kit_py()
    ensure_libp2p_main()
    ensure_ipfs_accelerate_py()
    ensure_logic_provers()
    
    # Enable auto-installation if requested
    if args.enable_auto_install:
        os.environ['IPFS_DATASETS_AUTO_INSTALL'] = 'true'
        print("✅ Auto-installation enabled")
    
    # Handle specific commands
    if args.quick:
        return quick_setup()
    elif args.profile:
        print(f"📦 Installing {args.profile} profile...")
        try:
            result = subprocess.run([
                sys.executable, str(_setup_scripts_dir() / 'dependency_manager.py'), 'install',
                '--profile', args.profile
            ], check=False, text=True)
            return result.returncode
        except Exception as e:
            print(f"❌ Profile installation failed: {e}")
            return 1
    elif args.health:
        return health_check()
    elif args.analyze:
        return full_analysis()
    elif args.test:
        return test_installation()
    elif args.status:
        show_status()
        return 0
    else:
        # Run interactive wizard
        return run_setup_wizard()

if __name__ == '__main__':
    sys.exit(main())