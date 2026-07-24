"""
Automated Dependency Installation System

Provides cross-platform automated installation of dependencies to replace
mock implementations with full functionality. Supports Linux, macOS, and Windows.
"""
import os
import sys
import platform
import subprocess
import importlib
import importlib.util
import logging
import json
import hashlib
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Set
import warnings

if __package__:
    from .dependency_catalog import (
        COMPONENT_MODULES,
        canonical_distribution_name,
        companion_packages,
        dependencies_for_component,
        dependency_for_distribution,
        dependency_for_import,
        package_candidates,
    )
else:  # pragma: no cover - compatibility for direct script execution.
    from dependency_catalog import (  # type: ignore[no-redef]
        COMPONENT_MODULES,
        canonical_distribution_name,
        companion_packages,
        dependencies_for_component,
        dependency_for_distribution,
        dependency_for_import,
        package_candidates,
    )

logger = logging.getLogger(__name__)

_INSTALL_LOCKS: Dict[str, threading.Lock] = {}
_INSTALL_LOCKS_GUARD = threading.Lock()


def _truthy_env_value(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _runtime_installer_check_enabled() -> bool:
    configured = os.getenv("IPFS_DATASETS_ENSURE_INSTALLER")
    return configured is not None and _truthy_env_value(configured)


def _runtime_installer_marker_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "state" / "runtime_installer_state.json"


def _current_repo_revision() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            if value:
                return value
    except Exception:
        pass

    fallback_paths = [
        repo_root / "setup.py",
        repo_root / "scripts" / "setup" / "install.py",
        repo_root / "ipfs_datasets_py" / "__init__.py",
    ]
    stamp_parts: List[str] = []
    for path in fallback_paths:
        try:
            stat = path.stat()
            stamp_parts.append(f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}")
        except Exception:
            continue
    return "|".join(stamp_parts) or "unknown"


def _load_runtime_installer_state() -> Dict[str, object]:
    marker_path = _runtime_installer_marker_path()
    if not marker_path.exists():
        return {}
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_runtime_installer_state(payload: Dict[str, object]) -> None:
    marker_path = _runtime_installer_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class DependencyInstaller:
    """Cross-platform dependency installer that replaces mock implementations"""
    
    def __init__(self, auto_install: bool = None, verbose: bool = False):
        if auto_install is None:
            auto_install = _truthy_env_value(os.getenv('IPFS_DATASETS_AUTO_INSTALL')) or _truthy_env_value(
                os.getenv('IPFS_AUTO_INSTALL')
            )
        if _truthy_env_value(os.getenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS")) or _truthy_env_value(
            os.getenv("IPFS_DATASETS_PY_BENCHMARK")
        ):
            auto_install = False
        self.auto_install = auto_install
        self.verbose = verbose
        self.system = platform.system().lower()
        self.architecture = platform.machine().lower()
        self.python_version = sys.version_info

        # Resolve project root and local bin/deps directories.
        # Default layout: <repo_root>/bin (repo_root is parent of package folder).
        default_project_root = Path(__file__).resolve().parents[1]
        self.project_root = Path(os.getenv('IPFS_DATASETS_PROJECT_ROOT', str(default_project_root))).resolve()
        self.bin_dir = Path(os.getenv('IPFS_DATASETS_LOCAL_BIN', str(self.project_root / 'bin'))).resolve()
        self.deps_dir = Path(os.getenv('IPFS_DATASETS_LOCAL_DEPS', str(self.bin_dir / '.deps'))).resolve()
        self.npm_prefix_dir = Path(os.getenv('IPFS_DATASETS_NPM_PREFIX', str(self.deps_dir / 'npm'))).resolve()
        self.npm_bin_dir = self.npm_prefix_dir / 'bin'

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.deps_dir.mkdir(parents=True, exist_ok=True)
        self.npm_prefix_dir.mkdir(parents=True, exist_ok=True)
        self.npm_bin_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_bin_on_path()
        
        # Track installed packages to avoid duplicate installations
        self.installed_packages = set()

        # Environment toggles
        self.force_local_system_deps = os.getenv('IPFS_DATASETS_FORCE_LOCAL_SYSTEM_DEPS', 'false').lower() == 'true'
        
        # Package mappings for different systems
        self.system_packages = {
            'linux': {
                'tesseract': 'tesseract-ocr',
                'ffmpeg': 'ffmpeg',
                'opencv': 'libopencv-dev',
                'poppler': 'poppler-utils',
                # Theorem Provers and SAT/SMT Solvers
                'z3': 'z3',
                'cvc4': 'cvc4',
                'cvc5': 'cvc5',
                'lean': 'lean4',
                'coq': 'coq',
                'isabelle': 'isabelle',
                'vampire': 'vampire',
                'eprover': 'eprover',
            },
            'darwin': {  # macOS
                'tesseract': 'tesseract',
                'ffmpeg': 'ffmpeg', 
                'opencv': 'opencv',
                'poppler': 'poppler',
                # Theorem Provers and SAT/SMT Solvers
                'z3': 'z3',
                'cvc4': 'cvc4',
                'cvc5': 'cvc5',
                'lean': 'lean',
                'coq': 'coq',
                'isabelle': 'isabelle',
            },
            'windows': {
                'tesseract': 'UB-Mannheim.TesseractOCR',
                'ffmpeg': 'Gyan.FFmpeg',
                'opencv': 'opencv',
                'poppler': 'oschwartz10612.Poppler',
                # Theorem Provers and SAT/SMT Solvers
                'z3': 'z3',
                'cvc4': 'cvc4',
                'cvc5': 'cvc5',
                'lean': 'lean',
                'coq': 'coq',
            }
        }
        
        # Runtime installation uses the same reviewed specifications for every
        # call site. Import names and distribution names are intentionally
        # separate (for example, ``fitz`` is provided by ``pymupdf``).
        self.python_packages = package_candidates()
        self.python_package_companions = companion_packages()
        self._failed_packages: Dict[str, float] = {}

        # Node CLI packages used by the SyMAI router (npm install -g)
        self.node_cli_packages = {
            'gemini-cli': {
                'package': '@google/gemini-cli',
                'command': 'npx',
            },
            'copilot': {
                'package': '@github/copilot',
                'command': 'copilot',
            },
            'claude-code': {
                'package': '@anthropic-ai/claude-code',
                'command': 'claude',
            },
        }

        # Minimal command mapping used to verify system tools.
        # (This is intentionally small; local installers can extend it.)
        self._system_dep_verify = {
            'ffmpeg': (['ffmpeg', '-version'],),
            'tesseract': (['tesseract', '--version'],),
            'poppler': (['pdfinfo', '-v'], ['pdftoppm', '-v']),
            'z3': (['z3', '--version'],),
            'cvc4': (['cvc4', '--version'],),
            'cvc5': (['cvc5', '--version'],),
        }

    def _ensure_bin_on_path(self) -> None:
        """Prepend local bin directory to PATH for the current process."""
        bin_str = str(self.bin_dir)
        npm_bin = str(self.npm_bin_dir)
        current = os.environ.get('PATH', '')
        parts = current.split(os.pathsep) if current else []
        new_parts = []
        for entry in [bin_str, npm_bin]:
            if entry and entry not in parts and entry not in new_parts:
                new_parts.append(entry)
        if not new_parts:
            return
        os.environ['PATH'] = os.pathsep.join(new_parts + parts)

    def _normalized_arch(self) -> str:
        """Return a normalized architecture label."""
        arch = (self.architecture or '').lower()
        if arch in {'x86_64', 'amd64'}:
            return 'amd64'
        if arch in {'aarch64', 'arm64'}:
            return 'arm64'
        if arch.startswith('armv7') or arch == 'armv7l':
            return 'armv7'
        return arch or 'unknown'

    def _command_exists_path(self, command: str) -> bool:
        """Check if a command exists in PATH (without invoking it)."""
        try:
            from shutil import which
        except Exception:
            return False
        return which(command) is not None

    def _sudo_available(self) -> bool:
        """Return True if passwordless sudo is available (non-interactive)."""
        if self.system not in {'linux', 'darwin'}:
            return False
        if not self._command_exists_path('sudo'):
            return False
        try:
            result = subprocess.run(['sudo', '-n', 'true'], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _system_dep_satisfied(self, package_name: str) -> bool:
        """Check whether a system dependency appears to already be installed."""
        verify_cmds = self._system_dep_verify.get(package_name)
        if not verify_cmds:
            return False
        for cmd in verify_cmds:
            try:
                if not cmd:
                    continue
                if not self._command_exists_path(cmd[0]):
                    continue
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return True
            except Exception:
                continue
        return False

    def _write_executable(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        try:
            os.chmod(path, 0o755)
        except Exception:
            pass

    def _install_ffmpeg_locally(self) -> bool:
        """Install/enable ffmpeg locally in ./bin without sudo.

        Strategy: install `imageio-ffmpeg` and create a wrapper `bin/ffmpeg`
        that execs the platform-appropriate bundled binary.
        """
        if self._system_dep_satisfied('ffmpeg') and not self.force_local_system_deps:
            return True

        # Ensure helper package is available
        if not self.install_python_dependency('imageio-ffmpeg'):
            return False

        wrapper = self.bin_dir / 'ffmpeg'
        wrapper_py = """#!/usr/bin/env python3
import os
import sys

try:
    import imageio_ffmpeg
except Exception as e:
    sys.stderr.write(f"imageio-ffmpeg not available: {e}\\n")
    sys.exit(1)

exe = imageio_ffmpeg.get_ffmpeg_exe()
args = [exe] + sys.argv[1:]
os.execv(exe, args)
"""
        self._write_executable(wrapper, wrapper_py)
        return self._system_dep_satisfied('ffmpeg')

    def _apt_available_for_local_extract(self) -> bool:
        """Check whether Debian/Ubuntu tooling exists for local extraction installs."""
        return self._command_exists_path('apt-get') and self._command_exists_path('apt-cache') and self._command_exists_path('dpkg-deb')

    def _apt_parse_depends(self, package: str) -> List[str]:
        """Parse direct Depends/PreDepends for an apt package."""
        try:
            result = subprocess.run(['apt-cache', 'depends', package], capture_output=True, text=True, timeout=30)
        except Exception:
            return []
        if result.returncode != 0:
            return []
        deps: List[str] = []
        for line in (result.stdout or '').splitlines():
            line = line.strip()
            if not (line.startswith('Depends:') or line.startswith('PreDepends:')):
                continue
            _, dep = line.split(':', 1)
            dep = dep.strip()
            # Ignore virtual/alternative deps in angle brackets
            if dep.startswith('<') and dep.endswith('>'):
                continue
            # apt-cache may prefix with "|" for alternatives
            dep = dep.lstrip('|').strip()
            if not dep or dep.startswith('<'):
                continue
            # Ignore self-references
            if dep == package:
                continue
            deps.append(dep)
        return deps

    def _apt_collect_packages(self, roots: List[str], max_packages: int = 40) -> List[str]:
        """Collect a bounded set of packages (roots + dependencies)."""
        queue: List[str] = list(dict.fromkeys(roots))
        seen: Set[str] = set(queue)
        out: List[str] = []
        while queue and len(out) < max_packages:
            pkg = queue.pop(0)
            out.append(pkg)
            for dep in self._apt_parse_depends(pkg):
                if dep not in seen:
                    seen.add(dep)
                    queue.append(dep)
                if len(seen) >= max_packages:
                    break
        return out

    def _apt_download_and_extract(self, packages: List[str]) -> Optional[Path]:
        """Download and extract apt .debs into a local prefix under ./bin/.deps/apt."""
        if not self._apt_available_for_local_extract():
            return None
        apt_root = self.deps_dir / 'apt'
        apt_root.mkdir(parents=True, exist_ok=True)

        download_dir = self.deps_dir / 'apt_downloads'
        download_dir.mkdir(parents=True, exist_ok=True)

        for pkg in packages:
            try:
                # Download into download_dir (no sudo required)
                result = subprocess.run(
                    ['apt-get', 'download', pkg],
                    cwd=str(download_dir),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode != 0 and self.verbose:
                    logger.warning(f"apt-get download failed for {pkg}: {result.stderr.strip()}")
            except Exception as e:
                if self.verbose:
                    logger.warning(f"apt-get download error for {pkg}: {e}")

        debs = sorted(download_dir.glob('*.deb'))
        if not debs:
            return None

        for deb in debs:
            try:
                subprocess.run(
                    ['dpkg-deb', '-x', str(deb), str(apt_root)],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except Exception as e:
                if self.verbose:
                    logger.warning(f"dpkg-deb extract failed for {deb.name}: {e}")

        return apt_root

    def _install_apt_extracted_binary(self, package: str, binary: str) -> bool:
        """Install a binary via apt download+extract and create a wrapper in ./bin."""
        if self._command_exists_path(binary):
            return True
        if not self._apt_available_for_local_extract():
            return False

        pkgs = self._apt_collect_packages([package])
        apt_root = self._apt_download_and_extract(pkgs)
        if apt_root is None:
            return False

        real_bin = apt_root / 'usr' / 'bin' / binary
        if not real_bin.exists():
            # Some packages install into /bin
            real_bin = apt_root / 'bin' / binary
        if not real_bin.exists():
            return False

        # Conservative LD_LIBRARY_PATH: include common lib dirs under extracted root.
        lib_paths = []
        for p in [
            apt_root / 'usr' / 'lib',
            apt_root / 'lib',
            apt_root / 'usr' / 'lib' / f"{self._normalized_arch()}-linux-gnu",
            apt_root / 'usr' / 'lib' / 'aarch64-linux-gnu',
            apt_root / 'usr' / 'lib' / 'x86_64-linux-gnu',
        ]:
            if p.exists():
                lib_paths.append(str(p))
        ld_path = ':'.join(lib_paths)

        wrapper_path = self.bin_dir / binary
        wrapper_sh = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="{apt_root}"
BIN1="$ROOT/usr/bin/{binary}"
BIN2="$ROOT/bin/{binary}"
if [[ -x "$BIN1" ]]; then
  BIN="$BIN1"
elif [[ -x "$BIN2" ]]; then
  BIN="$BIN2"
else
  echo "Missing extracted binary: {binary}" 1>&2
  exit 1
fi
export LD_LIBRARY_PATH="{ld_path}:$LD_LIBRARY_PATH"
exec "$BIN" "$@"
"""
        self._write_executable(wrapper_path, wrapper_sh)
        return self._command_exists_path(binary)

    def detect_package_manager(self) -> str:
        """Detect system package manager"""
        if self.system == 'linux':
            # Check for various Linux package managers
            if self._command_exists('apt-get'):
                return 'apt'
            elif self._command_exists('yum'):
                return 'yum'
            elif self._command_exists('dnf'):
                return 'dnf'
            elif self._command_exists('pacman'):
                return 'pacman'
            elif self._command_exists('zypper'):
                return 'zypper'
        elif self.system == 'darwin':
            if self._command_exists('brew'):
                return 'brew'
            elif self._command_exists('port'):
                return 'macports'
        elif self.system == 'windows':
            if self._command_exists('choco'):
                return 'chocolatey'
            elif self._command_exists('scoop'):
                return 'scoop'
            elif self._command_exists('winget'):
                return 'winget'
        
        return 'pip-only'

    def _command_exists(self, command: str) -> bool:
        """Check if a command exists in PATH"""
        try:
            subprocess.run([command, '--version'], 
                         capture_output=True, check=False, timeout=5)
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _npm_available(self) -> bool:
        return self._command_exists_path('npm')

    def _node_version_tuple(self, node_cmd: str = 'node') -> Optional[Tuple[int, int, int]]:
        try:
            result = subprocess.run([node_cmd, '--version'], capture_output=True, text=True, timeout=5)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        version_text = (result.stdout or result.stderr or '').strip()
        if not version_text:
            return None
        if version_text.startswith('v'):
            version_text = version_text[1:]
        parts = version_text.split('.')
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            return None
        return (major, minor, patch)

    def _node_dist_target(self) -> Optional[str]:
        arch = self._normalized_arch()
        if self.system == 'linux':
            if arch == 'amd64':
                return 'linux-x64'
            if arch == 'arm64':
                return 'linux-arm64'
        if self.system == 'darwin':
            if arch == 'amd64':
                return 'darwin-x64'
            if arch == 'arm64':
                return 'darwin-arm64'
        return None

    def install_nodejs_local(self, version: str) -> bool:
        target = self._node_dist_target()
        if not target:
            if self.verbose:
                logger.warning("No local Node.js build for %s/%s", self.system, self.architecture)
            return False

        node_dir = self.deps_dir / f"node-v{version}-{target}"
        node_bin = node_dir / 'bin'
        if not node_dir.exists():
            url = f"https://nodejs.org/dist/v{version}/node-v{version}-{target}.tar.xz"
            archive_path = self.deps_dir / f"node-v{version}-{target}.tar.xz"
            if self.verbose:
                logger.info("Downloading Node.js %s from %s", version, url)
            try:
                from urllib.request import urlopen
                with urlopen(url, timeout=120) as response, open(archive_path, 'wb') as archive_file:
                    archive_file.write(response.read())
            except Exception as exc:
                if self.verbose:
                    logger.warning("Failed to download Node.js: %s", exc)
                return False

            try:
                import tarfile
                with tarfile.open(archive_path, 'r:xz') as archive:
                    archive.extractall(self.deps_dir)
            except Exception as exc:
                if self.verbose:
                    logger.warning("Failed to extract Node.js archive: %s", exc)
                return False

        if not node_bin.exists():
            if self.verbose:
                logger.warning("Node.js bin directory missing: %s", node_bin)
            return False

        for binary_name in ('node', 'npm', 'npx'):
            source_path = node_bin / binary_name
            if not source_path.exists():
                continue
            target_path = self.bin_dir / binary_name
            if target_path.exists():
                continue
            try:
                os.symlink(source_path, target_path)
            except Exception:
                try:
                    import shutil
                    shutil.copy2(source_path, target_path)
                except Exception:
                    if self.verbose:
                        logger.warning("Failed to link %s", binary_name)
        self._ensure_bin_on_path()
        return self._node_version_tuple(str(self.bin_dir / 'node')) is not None

    def ensure_nodejs(self, min_major: int = 20) -> bool:
        version = self._node_version_tuple()
        if version and version[0] >= min_major:
            return True
        if not self.auto_install:
            return False
        version_str = os.getenv('IPFS_DATASETS_NODE_VERSION', '20.11.1')
        if not self.install_nodejs_local(version_str):
            return False
        version = self._node_version_tuple(str(self.bin_dir / 'node'))
        return bool(version and version[0] >= min_major)

    def install_node_cli_dependency(self, package_name: str) -> bool:
        if not self.auto_install:
            return False
        if not self._npm_available():
            if not self.ensure_nodejs(min_major=20):
                if self.verbose:
                    logger.warning("Node.js 20+ not available; cannot install %s", package_name)
                return False
        if not self._npm_available():
            if self.verbose:
                logger.warning("npm is not available; cannot install %s", package_name)
            return False

        try:
            cmd = ['npm', 'install', '-g', '--prefix', str(self.npm_prefix_dir), package_name]
            if self.verbose:
                logger.info("Installing Node CLI package %s", package_name)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                return True
            if self.verbose:
                logger.warning("npm install failed for %s: %s", package_name, result.stderr.strip())
            return False
        except Exception as e:
            if self.verbose:
                logger.warning("npm install error for %s: %s", package_name, e)
            return False

    def verify_node_cli(self, command: str) -> bool:
        if not command:
            return False
        if command == 'npx':
            return self._npm_available()
        return self._command_exists_path(command)

    def install_system_dependency(self, package_name: str) -> bool:
        """Install system-level dependency"""
        if self._is_system_dependency_available(package_name):
            if self.verbose:
                logger.info(f"System dependency {package_name} already available")
            return True

        if os.getenv('IPFS_INSTALL_SYSTEM_DEPS', 'true').lower() != 'true':
            if self.verbose:
                logger.info(f"Skipping system dependency {package_name} (IPFS_INSTALL_SYSTEM_DEPS=false)")
            return False

        if not self.auto_install:
            return False

        # Already satisfied?
        # In forced-local mode, still proceed so we can drop a wrapper into ./bin.
        if self._system_dep_satisfied(package_name) and not self.force_local_system_deps:
            return True

        package_manager = self.detect_package_manager()
        
        if package_name not in self.system_packages.get(self.system, {}):
            if self.verbose:
                logger.warning(f"No system package mapping for {package_name} on {self.system}")
            return False
            
        system_package = self.system_packages[self.system][package_name]
        
        winget_command = ['winget', 'install', system_package,
                          '--accept-source-agreements', '--accept-package-agreements',
                          '--silent', '--disable-interactivity']
        if '.' in system_package:
            winget_command = ['winget', 'install', '--id', system_package,
                              '--accept-source-agreements', '--accept-package-agreements',
                              '--silent', '--disable-interactivity']

        def _maybe_sudo(cmd: List[str]) -> List[str]:
            # In many sandbox/CI environments, sudo is unavailable. If we're
            # already root, run without sudo.
            try:
                if hasattr(os, 'geteuid') and os.geteuid() == 0:
                    return cmd
            except Exception:
                pass
            # Use non-interactive sudo so we never prompt ("zero touch").
            return ['sudo', '-n'] + cmd

        commands = {
            'apt': _maybe_sudo(['apt-get', 'install', '-y', system_package]),
            'yum': _maybe_sudo(['yum', 'install', '-y', system_package]),
            'dnf': _maybe_sudo(['dnf', 'install', '-y', system_package]),
            'pacman': _maybe_sudo(['pacman', '-S', '--noconfirm', system_package]),
            'zypper': _maybe_sudo(['zypper', 'install', '-y', system_package]),
            'brew': ['brew', 'install', system_package],
            'macports': _maybe_sudo(['port', 'install', system_package]),
            'chocolatey': ['choco', 'install', system_package, '-y'],
            'scoop': ['scoop', 'install', system_package],
            'winget': winget_command,
        }
        
        if package_manager not in commands:
            if self.verbose:
                logger.warning(f"Unsupported package manager: {package_manager}")
            return False
            
        try:
            cmd = commands[package_manager]
            if self.verbose:
                logger.info(f"Installing system package {system_package} using {package_manager}")
                
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                if self.verbose:
                    logger.info(f"Successfully installed {system_package}")
                return True
            else:
                if self.verbose:
                    logger.warning(f"Failed to install {system_package}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            if self.verbose:
                logger.warning(f"Timeout installing {system_package}")
            return False
        except Exception as e:
            if self.verbose:
                logger.warning(f"Error installing {system_package}: {e}")
            return False

    def _is_system_dependency_available(self, package_name: str) -> bool:
        """Check if a system dependency appears to be installed."""
        checks = {
            'ffmpeg': [['ffmpeg', '-version']],
            'tesseract': [['tesseract', '--version']],
            'poppler': [['pdftotext', '-v'], ['pdfinfo', '-v']],
        }

        if package_name not in checks:
            return False

        for cmd in checks[package_name]:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                continue

        if self.system == 'windows':
            try:
                where_map = {
                    'ffmpeg': ['ffmpeg'],
                    'tesseract': ['tesseract'],
                    'poppler': ['pdftotext', 'pdfinfo'],
                }
                for exe in where_map.get(package_name, []):
                    result = subprocess.run(['where', exe], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return True
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                pass

        return False

    def _ensure_windows_dependency_on_path(self, package_name: str) -> bool:
        """Ensure Windows system dependency is available on PATH."""
        if self.system != 'windows':
            return False

        bins = self._find_windows_dependency_bins(package_name)
        if not bins:
            if self.verbose:
                logger.warning(f"Could not locate install path for {package_name}")
            return False

        return self._add_to_user_path(bins)

    def _find_windows_dependency_bins(self, package_name: str) -> List[str]:
        """Find candidate bin directories for Windows system dependencies."""
        exe_map = {
            'ffmpeg': ['ffmpeg.exe'],
            'tesseract': ['tesseract.exe'],
            'poppler': ['pdftotext.exe', 'pdfinfo.exe'],
        }

        exes = exe_map.get(package_name, [])
        if not exes:
            return []

        found_dirs: List[str] = []

        # First, check current PATH via `where`
        for exe in exes:
            try:
                result = subprocess.run(['where', exe], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line.lower().endswith(exe.lower()):
                            found_dirs.append(str(Path(line).parent))
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                continue

        if found_dirs:
            return sorted(set(found_dirs))

        # Search common install locations
        base_dirs = [
            os.environ.get('ProgramFiles', r'C:\Program Files'),
            os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
            os.environ.get('LOCALAPPDATA'),
        ]

        candidates: List[Path] = []
        for base in filter(None, base_dirs):
            candidates.extend([
                Path(base) / 'ffmpeg' / 'bin',
                Path(base) / 'Gyan' / 'FFmpeg' / 'bin',
                Path(base) / 'Tesseract-OCR',
                Path(base) / 'Poppler' / 'bin',
                Path(base) / 'poppler' / 'Library' / 'bin',
                Path(base) / 'poppler' / 'bin',
                Path(base) / 'Programs' / 'ffmpeg' / 'bin',
                Path(base) / 'Programs' / 'Gyan' / 'FFmpeg' / 'bin',
                Path(base) / 'Programs' / 'Poppler' / 'bin',
                Path(base) / 'Programs' / 'Tesseract-OCR',
            ])

        for candidate in candidates:
            if candidate and candidate.exists():
                found_dirs.append(str(candidate))

        # Search WinGet package cache for executables
        winget_root = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages'
        if winget_root.exists():
            for exe in exes:
                try:
                    for path in winget_root.rglob(exe):
                        found_dirs.append(str(path.parent))
                except Exception:
                    continue

        return sorted(set(found_dirs))

    def _add_to_user_path(self, paths: List[str]) -> bool:
        """Add paths to the current user PATH without admin rights."""
        if not paths:
            return False

        try:
            existing_user_path = os.environ.get('PATH', '')
            try:
                import winreg  # type: ignore
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_READ) as key:
                    existing_user_path = winreg.QueryValueEx(key, 'Path')[0]
            except Exception:
                pass

            current_paths = [p.strip() for p in existing_user_path.split(';') if p.strip()]
            updated = False
            for path in paths:
                if path not in current_paths:
                    current_paths.insert(0, path)
                    updated = True

            if not updated:
                return True

            new_user_path = ';'.join(current_paths)

            try:
                import winreg  # type: ignore
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, 'Path', 0, winreg.REG_EXPAND_SZ, new_user_path)
            except Exception:
                # Fallback to setx if registry update fails
                subprocess.run(['setx', 'PATH', new_user_path], capture_output=True, text=True, timeout=30)

            os.environ['PATH'] = new_user_path
            if self.verbose:
                logger.info(f"Updated user PATH with: {paths}")
            return True
        except Exception as e:
            if self.verbose:
                logger.warning(f"Failed to update user PATH: {e}")
            return False

    @staticmethod
    def _bounded_env_seconds(
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _valid_package_spec(package_spec: str) -> bool:
        """Reject option injection and malformed requirement arguments."""

        candidate = str(package_spec or "").strip()
        return bool(
            candidate
            and not candidate.startswith("-")
            and "\n" not in candidate
            and "\r" not in candidate
            and "\x00" not in candidate
        )

    def _module_is_importable(self, module_name: Optional[str]) -> bool:
        if not module_name:
            return False
        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

    @contextmanager
    def _package_install_lock(self, package_key: str) -> Iterator[bool]:
        """Serialize pip installs across threads and supervisor worker processes."""

        lock_timeout = self._bounded_env_seconds(
            "IPFS_DATASETS_INSTALL_LOCK_TIMEOUT",
            1320.0,
            minimum=1.0,
            maximum=7200.0,
        )
        with _INSTALL_LOCKS_GUARD:
            thread_lock = _INSTALL_LOCKS.setdefault(package_key, threading.Lock())

        if not thread_lock.acquire(timeout=lock_timeout):
            logger.warning("Timed out waiting for dependency lock: %s", package_key)
            yield False
            return

        lock_root = self.deps_dir / "install-locks"
        lock_path = lock_root / f"{package_key}.lock"
        acquired_process_lock = False
        deadline = time.monotonic() + lock_timeout
        stale_after = max(
            lock_timeout * 4.0,
            self._bounded_env_seconds(
                "IPFS_DATASETS_PIP_TIMEOUT",
                600.0,
                minimum=30.0,
                maximum=3600.0,
            )
            * 4.0,
        )

        try:
            lock_root.mkdir(parents=True, exist_ok=True)
            while time.monotonic() < deadline:
                try:
                    lock_path.mkdir()
                    acquired_process_lock = True
                    break
                except FileExistsError:
                    try:
                        age = time.time() - lock_path.stat().st_mtime
                        if age > stale_after:
                            lock_path.rmdir()
                            continue
                    except (FileNotFoundError, OSError):
                        pass
                    time.sleep(0.05)

            if not acquired_process_lock:
                logger.warning("Timed out waiting for process dependency lock: %s", package_key)
            yield acquired_process_lock
        finally:
            if acquired_process_lock:
                try:
                    lock_path.rmdir()
                except OSError:
                    pass
            thread_lock.release()

    def _package_candidates_for(self, package_name: str) -> List[str]:
        dependency = dependency_for_distribution(package_name)
        has_explicit_constraint = bool(re.search(r"[\s\[<>=!~;@]", package_name))
        if dependency is not None and not has_explicit_constraint:
            return list(dependency.requirements)
        return [package_name]

    @staticmethod
    def _package_install_key(package_name: str) -> str:
        identity = canonical_distribution_name(package_name)
        safe_identity = re.sub(r"[^a-z0-9-]+", "-", identity).strip("-")
        digest_source = identity if safe_identity else package_name
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
        prefix = (safe_identity or "dependency")[:80]
        return f"{prefix}-{digest}"

    def install_python_dependency(
        self,
        package_name: str,
        force_reinstall: bool = False,
        *,
        module_name: Optional[str] = None,
    ) -> bool:
        """Install one Python dependency once, with reviewed fallback options."""

        if not self._valid_package_spec(package_name):
            logger.error("Refusing malformed dependency specification: %r", package_name)
            return False

        package_identity = canonical_distribution_name(package_name) or package_name
        package_lock_key = self._package_install_key(package_name)

        if package_identity in self.installed_packages and not force_reinstall:
            return not module_name or self._module_is_importable(module_name)

        retry_after = self._bounded_env_seconds(
            "IPFS_DATASETS_INSTALL_RETRY_SECONDS",
            30.0,
            minimum=0.0,
            maximum=3600.0,
        )
        failed_at = self._failed_packages.get(package_identity)
        if (
            failed_at is not None
            and not force_reinstall
            and time.monotonic() - failed_at < retry_after
        ):
            return False

        with self._package_install_lock(package_lock_key) as acquired:
            if not acquired:
                return False

            if package_identity in self.installed_packages and not force_reinstall:
                return not module_name or self._module_is_importable(module_name)

            failed_at = self._failed_packages.get(package_identity)
            if (
                failed_at is not None
                and not force_reinstall
                and time.monotonic() - failed_at < retry_after
            ):
                return False

            # A sibling worker may have completed the install while this worker
            # was waiting for the process lock.
            importlib.invalidate_caches()
            if not force_reinstall and self._module_is_importable(module_name):
                self.installed_packages.add(package_identity)
                self._failed_packages.pop(package_identity, None)
                return True

            packages_to_try = self._package_candidates_for(package_name)
            for package_spec in packages_to_try:
                if not self._valid_package_spec(package_spec):
                    continue
                installed = (
                    self._pip_install(package_spec, force_reinstall=True)
                    if force_reinstall
                    else self._pip_install(package_spec)
                )
                if not installed:
                    continue

                dependency = dependency_for_distribution(package_name)
                companion_key = dependency.distribution if dependency is not None else package_name
                for companion_package in self.python_package_companions.get(companion_key, []):
                    if not self.install_python_dependency(
                        companion_package,
                        force_reinstall=force_reinstall,
                    ):
                        logger.error(
                            "Failed to install companion dependency %s for %s",
                            companion_package,
                            package_name,
                        )
                        self._failed_packages[package_identity] = time.monotonic()
                        return False

                importlib.invalidate_caches()
                self.installed_packages.add(package_identity)
                self._failed_packages.pop(package_identity, None)
                return True

            self._failed_packages[package_identity] = time.monotonic()
            logger.error("Failed to install any variant of %s", package_name)
            return False

    def _pip_install(self, package_spec: str, *, force_reinstall: bool = False) -> bool:
        """Install package using pip"""
        try:
            if self.verbose:
                logger.info(f"Installing {package_spec} with pip")

            base_cmd = [
                sys.executable, '-m', 'pip', 'install', package_spec,
                '--quiet', '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
            ]
            if force_reinstall:
                base_cmd.append("--force-reinstall")
            if _truthy_env_value(os.getenv("IPFS_DATASETS_AUTO_INSTALL_OFFLINE")):
                base_cmd.append("--no-index")
            wheelhouse = os.getenv("IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE", "").strip()
            if wheelhouse:
                base_cmd.extend(["--find-links", wheelhouse])

            timeout = self._bounded_env_seconds(
                "IPFS_DATASETS_PIP_TIMEOUT",
                600.0,
                minimum=30.0,
                maximum=3600.0,
            )
            result = subprocess.run(base_cmd, capture_output=True, text=True, timeout=timeout)

            # PEP 668 (externally managed environment) is common on Debian/Ubuntu.
            # If we hit it, retry as a user install with the explicit override.
            if result.returncode != 0 and (
                'externally-managed-environment' in (result.stderr or '')
                or 'ExternallyManagedEnvironment' in (result.stderr or '')
            ):
                retry_cmd = base_cmd + ['--user', '--break-system-packages']
                result = subprocess.run(retry_cmd, capture_output=True, text=True, timeout=timeout)
            
            if result.returncode == 0:
                if self.verbose:
                    logger.info(f"Successfully installed {package_spec}")
                return True
            else:
                if self.verbose:
                    logger.warning(
                        "Failed to install %s: %s",
                        package_spec,
                        (result.stderr or "")[-4000:],
                    )
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout installing {package_spec}")
            return False
        except KeyboardInterrupt:
            if self.verbose:
                logger.warning(f"Installation interrupted for {package_spec}")
            return False
        except Exception as e:
            logger.warning(f"Error installing {package_spec}: {e}")
            return False

    def ensure_dependency(self, module_name: str, package_name: Optional[str] = None, 
                         system_deps: Optional[List[str]] = None) -> Tuple[bool, Optional[object]]:
        """
        Ensure a dependency is available, installing if necessary
        
        Args:
            module_name: Python module to import
            package_name: PyPI package name (if different from module_name)
            system_deps: List of system dependencies to install first
            
        Returns:
            Tuple of (success, imported_module)
        """
        dependency = dependency_for_import(module_name)
        if package_name is None and dependency is not None:
            package_name = dependency.distribution
        if system_deps is None and dependency is not None:
            system_deps = list(dependency.system_dependencies)

        # First try to import. Only a missing requested module should trigger
        # pip; an ImportError raised from inside an installed package indicates
        # a broken/incompatible environment and must not create an install loop.
        try:
            module = importlib.import_module(module_name)
            return True, module
        except ModuleNotFoundError as exc:
            requested_root = module_name.split(".", 1)[0]
            missing_root = str(exc.name or "").split(".", 1)[0]
            if missing_root and missing_root != requested_root:
                logger.warning(
                    "Module %s is installed but its dependency %s failed to import",
                    module_name,
                    exc.name,
                )
                return False, None
            if not self.auto_install:
                logger.warning(f"Module {module_name} not available and auto_install disabled")
                return False, None
        except ImportError as exc:
            logger.warning("Module %s failed to import: %s", module_name, exc)
            return False, None
        except Exception as exc:
            logger.warning("Module %s raised during import: %s", module_name, exc)
            return False, None

        if self.verbose:
            logger.info("Module %s not found, attempting lazy installation", module_name)

        if system_deps:
            for system_dependency in system_deps:
                self.install_system_dependency(system_dependency)

        package_name = package_name or module_name
        if not self.install_python_dependency(package_name, module_name=module_name):
            logger.error("Failed to install %s", package_name)
            return False, None

        importlib.invalidate_caches()
        try:
            module = importlib.import_module(module_name)
            if self.verbose:
                logger.info("Successfully installed and imported %s", module_name)
            return True, module
        except (ImportError, OSError) as exc:
            logger.error("Failed to import %s after installation: %s", module_name, exc)
            return False, None
        except Exception as exc:
            logger.error("Module %s raised after installation: %s", module_name, exc)
            return False, None

    def install_graphrag_dependencies(self) -> bool:
        """Install all dependencies needed for GraphRAG PDF processing"""
        if self.verbose:
            logger.info("Installing GraphRAG PDF processing dependencies...")

        return self.install_component_dependencies(
            "graphrag",
            minimum_success_ratio=0.8,
        )

    def install_component_dependencies(
        self,
        component: str,
        *,
        minimum_success_ratio: float = 1.0,
    ) -> bool:
        """Resolve a catalog component and install only its missing imports."""

        dependencies = dependencies_for_component(component)
        if not dependencies:
            return False

        success_count = 0
        for dependency in dependencies:
            success, _ = self.ensure_dependency(
                dependency.import_name,
                dependency.distribution,
                list(dependency.system_dependencies),
            )
            if success:
                success_count += 1

        if self.verbose:
            logger.info(
                "Installed %s/%s dependencies for %s",
                success_count,
                len(dependencies),
                component,
            )
        return success_count >= len(dependencies) * minimum_success_ratio

    def install_theorem_provers(self) -> Dict[str, bool]:
        """Install multiple theorem provers and return status"""
        if self.verbose:
            logger.info("Installing theorem provers and SAT/SMT solvers...")
            
        provers = ['z3', 'cvc5', 'lean', 'coq']
        results = {}
        
        for prover in provers:
            if self.verbose:
                logger.info(f"Installing theorem prover: {prover}")
            success = True
            
            # Special handling for Lean 4
            if prover == 'lean':
                success = self.install_lean_elan()
            else:
                # Install system package
                if not self.install_system_dependency(prover):
                    success = False
            
            # Install Python binding if available
            python_packages = {
                'z3': 'z3-solver',
                'cvc5': 'cvc5',
                'lean': None,    # No Python binding, system only
                'coq': None      # No Python binding, system only
            }
            
            if python_packages.get(prover):
                if not self.install_python_dependency(python_packages[prover]):
                    success = False
            
            # Verify installation
            if success:
                success = self.verify_theorem_prover_installation(prover)
            
            results[prover] = success
            
            if self.verbose:
                status = "✓" if success else "✗"
                logger.info(f"{status} {prover}: {'Success' if success else 'Failed'}")
            
        return results

    def verify_theorem_prover_installation(self, prover: str) -> bool:
        """Verify that a theorem prover is properly installed"""
        verification_commands = {
            'z3': ['z3', '--version'],
            'cvc4': ['cvc4', '--version'],
            'cvc5': ['cvc5', '--version'],
            'lean': ['lean', '--version'],
            'coq': ['coqc', '--version'],
            'isabelle': ['isabelle', 'version'],
            'vampire': ['vampire', '--version'],
            'eprover': ['eprover', '--version']
        }
        
        if prover not in verification_commands:
            return False
            
        try:
            result = subprocess.run(
                verification_commands[prover],
                capture_output=True,
                text=True,
                timeout=30
            )
            if self.verbose and result.returncode == 0:
                logger.info(f"{prover} version: {result.stdout.strip()}")
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            return False

    def install_lean_elan(self) -> bool:
        """Install Lean 4 using elan (recommended approach)"""
        try:
            # Check if elan is already installed
            result = subprocess.run(['elan', '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                if self.verbose:
                    logger.info("elan already installed")
                # Install latest Lean 4
                subprocess.run(['elan', 'toolchain', 'install', 'leanprover/lean4:stable'], 
                             capture_output=True, timeout=300)
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        
        # Install elan first
        if self.verbose:
            logger.info("Installing elan (Lean toolchain manager)...")
            
        if self.system in ['linux', 'darwin']:
            # Unix-like systems
            try:
                # Download and run elan installer
                curl_cmd = [
                    'curl', '-sSf', 'https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh'
                ]
                sh_cmd = ['sh', '-s', '--', '-y']
                
                curl_process = subprocess.Popen(curl_cmd, stdout=subprocess.PIPE)
                sh_process = subprocess.Popen(sh_cmd, stdin=curl_process.stdout, 
                                            capture_output=True, text=True)
                curl_process.stdout.close()
                
                output, error = sh_process.communicate(timeout=600)
                
                if sh_process.returncode == 0:
                    # Add to PATH for current session
                    home = os.path.expanduser("~")
                    elan_bin = os.path.join(home, ".elan", "bin")
                    if elan_bin not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = f"{elan_bin}:{os.environ.get('PATH', '')}"
                    
                    if self.verbose:
                        logger.info("elan installed successfully")
                    return True
                else:
                    if self.verbose:
                        logger.error(f"Failed to install elan: {error}")
                    return False
                    
            except Exception as e:
                if self.verbose:
                    logger.error(f"Error installing elan: {e}")
                return False
        else:
            # Windows - would need PowerShell script
            if self.verbose:
                logger.warning("Lean 4 installation on Windows requires manual setup")
            return False


# Global installer instance
_installer = None


def _load_setup_install_module():
    """Best-effort load of scripts/setup/install.py as a module."""
    try:
        repo_root = Path(__file__).resolve().parents[1]
        install_path = repo_root / "scripts" / "setup" / "install.py"
        if not install_path.exists():
            return None
        spec = importlib.util.spec_from_file_location("ipfs_datasets_setup_install", install_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def ensure_main_ipfs_kit_py() -> bool:
    """Best-effort install/bootstrap of ``ipfs_kit_py`` from the repo setup helper."""
    module = _load_setup_install_module()
    if module is None:
        return False
    helper = getattr(module, "ensure_main_ipfs_kit_py", None)
    if not callable(helper):
        return False
    try:
        os.environ.setdefault("IPFS_KIT_PY_USE_GIT", "true")
        os.environ["IPFS_DATASETS_PY_ENABLE_IPFS_KIT"] = "1"
        helper()
        importlib.import_module("ipfs_kit_py.ipfs_kit")
        return True
    except Exception:
        return False


def ensure_repo_installer_current(force: bool = False) -> bool:
    """Ensure installer bootstrap has run for the current checkout revision.

    This keeps runtime behavior aligned with the currently checked-out repo
    version instead of relying on a one-time manual setup.
    """
    if not _runtime_installer_check_enabled() and not force:
        return False

    current_revision = _current_repo_revision()
    state = _load_runtime_installer_state()
    if (
        not force
        and state.get("status") == "success"
        and str(state.get("repo_revision") or "") == current_revision
    ):
        return False

    module = _load_setup_install_module()
    if module is None:
        return False

    helper_names = [
        "ensure_main_ipfs_kit_py",
        "ensure_libp2p_main",
        "ensure_ipfs_accelerate_py",
    ]
    completed: List[str] = []
    failures: List[str] = []

    for helper_name in helper_names:
        helper = getattr(module, helper_name, None)
        if not callable(helper):
            continue
        try:
            helper()
            completed.append(helper_name)
        except Exception as exc:
            failures.append(f"{helper_name}: {exc}")

    status = "success" if not failures else "partial"
    _save_runtime_installer_state(
        {
            "completed_helpers": completed,
            "failures": failures,
            "repo_revision": current_revision,
            "status": status,
        }
    )
    return True

def get_installer() -> DependencyInstaller:
    """Get global installer instance"""
    global _installer
    if _installer is None:
        auto_install = _truthy_env_value(os.getenv('IPFS_DATASETS_AUTO_INSTALL')) or _truthy_env_value(
            os.getenv('IPFS_AUTO_INSTALL')
        )
        verbose = _truthy_env_value(os.getenv('IPFS_INSTALL_VERBOSE'))
        _installer = DependencyInstaller(auto_install=auto_install, verbose=verbose)
    return _installer


def ensure_module(module_name: str, package_name: Optional[str] = None, 
                  system_deps: Optional[List[str]] = None, 
                  fallback_mock: Optional[object] = None, 
                  required: bool = False) -> object:
    """
    Ensure a module is available, installing if necessary, with optional fallback
    
    Args:
        module_name: Python module to import
        package_name: PyPI package name (if different from module_name)  
        system_deps: List of system dependencies to install first
        fallback_mock: Mock object to return if installation fails
        required: If True, raise ImportError on failure. If False, return None.
        
    Returns:
        Imported module, fallback mock, or None
    """
    installer = get_installer()
    success, module = installer.ensure_dependency(module_name, package_name, system_deps)
    
    if success:
        return module
    elif fallback_mock is not None:
        if installer.verbose:
            warnings.warn(f"Using mock implementation for {module_name} - install failed")
        return fallback_mock
    elif required:
        raise ImportError(f"Failed to install and import {module_name}")
    else:
        return None


def lazy_import(module_name: str, package_name: Optional[str] = None, **kwargs: object) -> object:
    """Import a supported dependency on demand, installing it when configured."""

    return ensure_module(module_name, package_name, **kwargs)


def install_for_component(component: str) -> bool:
    """Install missing dependencies for a catalog feature component."""

    installer = get_installer()

    if component == 'graphrag':
        return installer.install_graphrag_dependencies()
    if component == 'ipfs':
        return ensure_main_ipfs_kit_py()
    if component == 'theorem_provers':
        return installer.install_theorem_provers()
    if component == 'lean':
        return installer.install_system_dependency('lean')
    if component == 'coq':
        return installer.install_system_dependency('coq')

    if component == 'symai_router':
        if not installer.ensure_nodejs(min_major=20):
            if installer.verbose:
                logger.warning("Node.js 20+ not available; CLI installs may fail")
            return False
        cli_success = 0
        cli_total = 0
        for cli_info in installer.node_cli_packages.values():
            cli_total += 1
            command = cli_info.get('command', '')
            if installer.verify_node_cli(command):
                cli_success += 1
                continue
            if installer.install_node_cli_dependency(cli_info.get('package', '')):
                if installer.verify_node_cli(command):
                    cli_success += 1
        return installer.install_component_dependencies(component) and cli_success == cli_total

    if component not in COMPONENT_MODULES:
        logger.warning("Unknown component: %s", component)
        return False
    return installer.install_component_dependencies(component)


if __name__ == '__main__':
    # CLI for testing dependency installation
    import argparse

    available_components = sorted(
        set(COMPONENT_MODULES)
        | {"ipfs", "theorem_provers", "lean", "coq"}
    )
    parser = argparse.ArgumentParser(description='Install dependencies for IPFS datasets')
    parser.add_argument('component', nargs='?', default='graphrag',
                       choices=available_components,
                       help='Feature component to provision eagerly')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--no-auto-install', action='store_true', 
                       help='Disable auto installation')
    
    args = parser.parse_args()
    
    # Configure installer
    installer = DependencyInstaller(
        auto_install=not args.no_auto_install,
        verbose=args.verbose
    )
    
    # Set global installer
    _installer = installer
    
    # Install for component
    success = install_for_component(args.component)
    
    if success:
        print(f"✅ Successfully installed dependencies for {args.component}")
        sys.exit(0)
    else:
        print(f"❌ Failed to install some dependencies for {args.component}")
        sys.exit(1)
