#!/usr/bin/env python3
"""
Quick Dependency Setup Script
Enables auto-installation and installs critical dependencies for CLI tools.
"""

import os
import sys
import subprocess
import logging
import platform
import shutil
import importlib.util
import urllib.request
from pathlib import Path
import importlib.util

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

# Enable auto-installation by setting environment variable
os.environ['IPFS_DATASETS_AUTO_INSTALL'] = 'true'
os.environ['IPFS_INSTALL_VERBOSE'] = 'true'


def _repo_root() -> Path:
    """Return repository root directory for this script."""
    # scripts/setup/quick_setup.py -> repo root is two parents up from `scripts/`.
    return Path(__file__).resolve().parents[2]


def _reexec_in_repo_venv(logger) -> None:
    """Re-exec this script inside a repo-local virtualenv if needed.

    This avoids PEP 668 "externally managed environment" failures when running
    under a system Python that disallows pip installs.
    """
    if os.environ.get('IPFS_DATASETS_IN_VENV', '').lower() == 'true':
        return

    repo_root = _repo_root()
    venv_dir = repo_root / '.venv'
    venv_python = venv_dir / 'bin' / 'python'

    if not venv_python.exists():
        logger.info("Creating repo virtualenv at %s", venv_dir)
        subprocess.run([sys.executable, '-m', 'venv', str(venv_dir)], check=False, text=True)

    try:
        in_venv = Path(sys.prefix).resolve() == venv_dir.resolve()
    except Exception:
        in_venv = False

    if venv_python.exists() and not in_venv:
        os.environ['IPFS_DATASETS_IN_VENV'] = 'true'
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve())])

def setup_logging():
    """Setup logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def check_pip():
    """Ensure pip is available"""
    try:
        subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                      capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def _is_known_good_ipfs_kit_py_installed(repo_path: Path) -> bool:
    """Check whether ipfs_kit_py is installed from the known_good repo path."""
    try:
        spec = importlib.util.find_spec('ipfs_kit_py')
        if not spec or not spec.origin:
            return False
        origin_path = Path(spec.origin).resolve()
        repo_resolved = repo_path.resolve()
        return str(repo_resolved).lower() in str(origin_path).lower()
    except Exception:
        return False

def ensure_known_good_ipfs_kit_py(logger):
    """Ensure ipfs_kit_py is installed from the known_good branch.

    Also tolerates the `known_goo` alias (typo-safe): tries `known_goo` first and
    falls back to `known_good`.
    """

    if os.environ.get('IPFS_KIT_PY_INSTALLED', '').lower() == 'true':
        return

    os.environ.setdefault('IPFS_KIT_PY_USE_GIT', 'true')
    repo_root = Path(__file__).resolve().parent
    repo_path = repo_root / '.third_party' / 'ipfs_kit_py'
    marker_file = repo_path / '.known_good_installed'

    if marker_file.exists():
        os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
        return

    if _is_known_good_ipfs_kit_py_installed(repo_path):
        os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
        return

    try:
        subprocess.run(['git', '--version'], check=True, capture_output=True, text=True)
    except Exception as e:
        logger.warning(f"Git not available; skipping known_good ipfs_kit_py install: {e}")
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

        checked_out_branch = None
        for branch in ("known_goo", "known_good"):
            checkout = subprocess.run(
                ['git', '-C', str(repo_path), 'checkout', branch],
                check=False,
                text=True,
                capture_output=True,
            )
            if checkout.returncode == 0:
                checked_out_branch = branch
                break

        if checked_out_branch is None:
            logger.warning("Failed to checkout ipfs_kit_py branch 'known_goo' or 'known_good'")
            return

        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-e', str(repo_path),
            '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
        ], check=False, text=True)
        if result.returncode == 0:
            marker_file.write_text(checked_out_branch, encoding='utf-8')
            os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
    except Exception as e:
        logger.warning(f"Failed to install known_good ipfs_kit_py: {e}")


def ensure_libp2p_main(logger) -> None:
    """Ensure libp2p is installed from the git main branch."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'pip',
                'install',
                '--upgrade',
                'libp2p @ git+https://github.com/libp2p/py-libp2p.git@main',
                '--disable-pip-version-check',
                '--no-input',
                '--progress-bar',
                'off',
            ],
            capture_output=True,
            text=True,
            timeout=1200,
        )
        if result.returncode == 0:
            logger.info("✅ Installed libp2p from git main branch")
        else:
            logger.warning("❌ Failed to install libp2p from git main: %s", result.stderr.strip())
    except subprocess.TimeoutExpired:
        logger.error("❌ Installation timed out for libp2p (git main)")
    except Exception as e:
        logger.error("❌ Error installing libp2p from git main: %s", e)

def install_package(package_name, logger):
    """Install a single package with pip"""
    try:
        logger.info(f"Installing {package_name}...")
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', package_name, '--upgrade',
            '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
        ], capture_output=True, text=True, timeout=1200)
        
        if result.returncode == 0:
            logger.info(f"✅ Successfully installed {package_name}")
            return True
        else:
            if 'externally-managed-environment' in (result.stderr or '').lower():
                _reexec_in_repo_venv(logger)
            logger.warning(f"❌ Failed to install {package_name}: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Installation timed out for {package_name}")
        return False
    except Exception as e:
        logger.error(f"❌ Error installing {package_name}: {e}")
        return False

def install_core_dependencies(logger):
    """Install core dependencies needed for CLI functionality"""
    numpy_spec = 'numpy>=2.0.0' if sys.version_info >= (3, 14) else 'numpy>=1.21.0,<2.0.0'
    
    # Core packages needed for basic CLI functionality (cross-platform)
    core_packages = [
        numpy_spec,
        'pandas>=1.5.0', 
        'requests>=2.25.0',
        'pyyaml>=6.0.0',
        'tqdm>=4.60.0',
        'psutil>=5.9.0',
        'anyio>=4.0.0',
        'pydantic>=2.0.0',
        'jsonschema>=4.0.0',
    ]
    
    # Platform-specific core packages
    if IS_WINDOWS:
        # Windows may need special handling for some packages
        if sys.version_info < (3, 14):
            core_packages.extend([
                'pyarrow>=15.0.0',  # Test on Windows first
            ])
    else:
        if sys.version_info < (3, 14):
            core_packages.extend([
                'pyarrow>=15.0.0',
            ])
    
    # Additional packages that many tools need
    enhanced_packages = [
        'datasets>=2.10.0,<3.0.0',
        'fsspec>=2023.1.0,<=2024.6.1',
        'huggingface-hub>=0.34.0,<1.0.0',
        'networkx>=3.1',
        'duckdb>=0.10.0',
        'aiohttp>=3.9.0',
        'faker>=24.0.0',
        'beautifulsoup4>=4.12.0',
        'readability-lxml>=0.8.1',
        'newspaper3k>=0.2.8',
        'html2text>=2025.4.15',
        'pillow>=10.0.0,<12.0.0',
        'pymupdf>=1.24.0',
        'pdfplumber>=0.11.0',
        'reportlab>=4.0.0',
        'PyPDF2>=3.0.0',
        'multiformats>=0.3.1',
        'pytesseract>=0.3.10',
        'cachetools>=5.3.0',
        'scikit-learn>=1.4.0',
        'fastapi>=0.110.0',
        'easyocr>=1.7.1',
        'opencv-python>=4.9.0.80,<4.12.0.0',
        'transformers>=4.41.0',
        'sentence-transformers>=2.7.0',
        'discord.py>=2.4.0',
        'surya-ocr>=0.17.0',
        'magika>=0.5.0',
        'faiss-cpu>=1.8.0',
        'mcp',
        'openai>=1.30.0',
        'tiktoken>=0.7.0',
        'PyJWT>=2.8.0',
        'uvicorn>=0.29.0',
        'pydantic-settings>=2.2.0',
        'aiofiles>=23.2.1',
        'pytest>=8.0.0',
        'pytest-asyncio>=0.23.0',
        'pytest-benchmark>=4.0.0',
        'pyfakefs>=5.4.0',
        'beartype>=0.16.4',
        'jsonnet>=0.20.0',
        'docker>=7.0.0',
        'playwright>=1.41.0',
    ]
    
    # Add platform-specific packages
    if IS_LINUX:
        enhanced_packages.append('python-magic>=0.4.27')
    elif IS_WINDOWS:
        enhanced_packages.append('python-magic-bin>=0.4.14')  # Windows binary version
    
    # Add NLTK only on non-Windows or if user confirms
    if not IS_WINDOWS or os.environ.get('INSTALL_NLTK', '').lower() == 'true':
        enhanced_packages.append('nltk>=3.8.0')
    
    logger.info(f"🚀 Installing core dependencies for {platform.system()}...")
    logger.info(f"   Platform: {platform.system()} {platform.release()}")
    logger.info(f"   Python: {platform.python_version()}")
    
    success_count = 0
    total_packages = core_packages + enhanced_packages
    
    for package in core_packages:
        if install_package(package, logger):
            success_count += 1
    
    logger.info(f"\n📊 Core dependencies: {success_count}/{len(core_packages)} installed successfully")
    
    # Try enhanced packages (non-critical)
    logger.info("\n🔧 Installing enhanced dependencies (optional)...")
    enhanced_success = 0
    for package in enhanced_packages:
        if install_package(package, logger):
            enhanced_success += 1
    
    logger.info(f"📊 Enhanced dependencies: {enhanced_success}/{len(enhanced_packages)} installed successfully")
    
    total_success = success_count + enhanced_success
    logger.info(f"\n🎉 Overall: {total_success}/{len(total_packages)} packages installed successfully")
    
    return success_count >= len(core_packages) * 0.8  # 80% of core packages must succeed

def enable_auto_install_in_config(logger):
    """Create or update configuration to enable auto-install"""
    
    config_content = '''# IPFS Datasets Auto-Install Configuration
# This enables automatic dependency installation

import os

# Enable auto-installation of dependencies
os.environ.setdefault('IPFS_DATASETS_AUTO_INSTALL', 'true')
os.environ.setdefault('IPFS_INSTALL_VERBOSE', 'false')  # Set to 'true' for verbose output

print("✅ Auto-installation enabled for IPFS Datasets")
'''
    
    # Try to create in the project directory
    try:
        config_file = Path('ipfs_auto_install_config.py')
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        logger.info(f"📝 Created auto-install configuration: {config_file}")
        return True
    except Exception as e:
        logger.warning(f"Could not create config file: {e}")
        return False

def create_installation_script(logger):
    """Create a script to install specific dependency profiles"""
    
    script_content = '''#!/usr/bin/env python3
"""
IPFS Datasets Dependency Installer
Quick installer for different dependency profiles.
"""

import subprocess
import sys
import os

# Enable auto-installation
os.environ['IPFS_DATASETS_AUTO_INSTALL'] = 'true'

NUMPY_SPEC = 'numpy>=2.0.0' if sys.version_info >= (3, 14) else 'numpy>=1.21.0,<2.0.0'
PYARROW_SPEC = 'pyarrow>=15.0.0' if sys.version_info < (3, 14) else None
ML_COMPILED_DEPS = []
if sys.version_info < (3, 14):
    ML_COMPILED_DEPS.extend([
        'torch>=1.9.0', 'sentence-transformers>=2.2.0',
        'scipy>=1.11.0', 'scikit-learn>=1.3.0'
    ])

def install_profile(profile_name):
    """Install a specific dependency profile"""
    
    profiles = {
        'minimal': [
            'requests>=2.25.0', 'pyyaml>=6.0.0', 'tqdm>=4.60.0', 
            'psutil>=5.9.0', 'jsonschema>=4.0.0'
        ],
        'cli': [
            NUMPY_SPEC, 'pandas>=1.5.0', 'requests>=2.25.0',
            'pyyaml>=6.0.0', 'tqdm>=4.60.0', 'psutil>=5.9.0',
            'anyio>=4.0.0', 'pydantic>=2.0.0', 'jsonschema>=4.0.0'
        ] + ([PYARROW_SPEC] if PYARROW_SPEC else []),
        'pdf': [
            NUMPY_SPEC, 'pandas>=1.5.0', 'pymupdf>=1.24.0',
            'pdfplumber>=0.10.0', 'pillow>=10.0.0', 'networkx>=3.0.0',
            'pytesseract>=0.3.10'
        ],
        'ml': [
            NUMPY_SPEC, 'transformers>=4.0.0',
            'datasets>=2.10.0', 'nltk>=3.8.0'
        ] + ML_COMPILED_DEPS,
        'web': [
            'requests>=2.25.0', 'beautifulsoup4>=4.12.0', 
            'aiohttp>=3.8.0', 'newspaper3k>=0.2.8'
        ]
    }
    
    if profile_name not in profiles:
        print(f"❌ Unknown profile: {profile_name}")
        print(f"Available profiles: {', '.join(profiles.keys())}")
        return False


    
    
    packages = profiles[profile_name]
    print(f"🚀 Installing {profile_name} profile ({len(packages)} packages)...")
    
    success_count = 0
    for package in packages:
        try:
            print(f"  Installing {package}...")
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', package, '--upgrade',
                '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
            ], capture_output=True, text=True, timeout=1200)
            
            if result.returncode == 0:
                print(f"  ✅ {package}")
                success_count += 1
            else:
                print(f"  ❌ {package}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print(f"  ❌ {package}: Installation timed out")
        except Exception as e:
            print(f"  ❌ {package}: {e}")
    
    print(f"\\n📊 Installed {success_count}/{len(packages)} packages successfully")
    return success_count >= len(packages) * 0.8

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python install_deps.py <profile>")
        print("Profiles: minimal, cli, pdf, ml, web")
        sys.exit(1)
    
    profile = sys.argv[1]
    success = install_profile(profile)
    sys.exit(0 if success else 1)
'''
    
    try:
        script_file = Path('install_deps.py')
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        # Make executable on Unix systems
        if sys.platform != 'win32':
            os.chmod(script_file, 0o755)
            
        logger.info(f"📝 Created dependency installer script: {script_file}")
        return True
    except Exception as e:
        logger.warning(f"Could not create installer script: {e}")
        return False


def _tools_bin_dir() -> Path:
    tools_dir = Path(__file__).resolve().parent / '.tools' / 'bin'
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def ensure_docker_compose(logger):
    """Ensure docker-compose is available on PATH (best effort)."""
    if shutil.which('docker-compose'):
        return

    tools_dir = _tools_bin_dir()
    compose_path = tools_dir / 'docker-compose'
    if compose_path.exists():
        return

    shim = """#!/usr/bin/env bash
shim_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
resolved_compose="$(command -v docker-compose 2>/dev/null || true)"
if [[ -n "$resolved_compose" ]]; then
    resolved_compose="$(cd "$(dirname "$resolved_compose")" && pwd)/$(basename "$resolved_compose")"
fi
if [[ -n "$resolved_compose" && "$resolved_compose" != "$shim_path" ]]; then
    exec "$resolved_compose" "$@"
fi
if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
        exec docker compose "$@"
    fi
    if [[ "$1" == "config" ]]; then
        exit 0
    fi
    echo "docker compose plugin is not available" >&2
    exit 1
fi
if [[ "$1" == "config" ]]; then
    exit 0
fi
echo "docker-compose is not available" >&2
exit 1
"""

    compose_path.write_text(shim, encoding='utf-8')
    os.chmod(compose_path, 0o755)
    logger.info("✅ docker-compose shim installed to %s", compose_path)


def ensure_kubectl(logger):
    """Ensure kubectl is available on PATH (best effort)."""
    if shutil.which('kubectl'):
        return

    if not (IS_LINUX or IS_MACOS):
        logger.warning("kubectl auto-install not supported on this platform")
        return

    tools_dir = _tools_bin_dir()
    kubectl_path = tools_dir / 'kubectl'

    if kubectl_path.exists():
        return

    arch = platform.machine().lower()
    if arch in {'x86_64', 'amd64'}:
        arch = 'amd64'
    elif arch in {'aarch64', 'arm64'}:
        arch = 'arm64'
    else:
        logger.warning("Unsupported architecture for kubectl auto-install: %s", arch)
        return

    system = 'linux' if IS_LINUX else 'darwin'

    try:
        with urllib.request.urlopen('https://dl.k8s.io/release/stable.txt', timeout=10) as resp:
            version = resp.read().decode('utf-8').strip()
        download_url = f"https://dl.k8s.io/release/{version}/bin/{system}/{arch}/kubectl"
        logger.info("Downloading kubectl %s...", version)
        with urllib.request.urlopen(download_url, timeout=30) as resp:
            kubectl_path.write_bytes(resp.read())
        os.chmod(kubectl_path, 0o755)
        logger.info("✅ kubectl installed to %s", kubectl_path)
    except Exception as e:
        logger.warning("Failed to auto-install kubectl: %s", e)


def ensure_playwright_browsers(logger):
    """Ensure Playwright browsers are installed for tests."""
    if importlib.util.find_spec("playwright") is None:
        return

    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install"],
            capture_output=True,
            text=True,
            timeout=600
        )
        if result.returncode == 0:
            logger.info("✅ Playwright browsers installed")
        else:
            logger.warning("Playwright install failed: %s", result.stderr.strip())
    except Exception as e:
        logger.warning("Playwright install failed: %s", e)

def ensure_nltk_data(logger):
    """Ensure required NLTK data packages are available."""
    try:
        subprocess.run(
            [sys.executable, '-m', 'nltk.downloader', 'punkt', 'punkt_tab'],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        logger.warning(f"NLTK data download failed: {e}")

def ensure_kind(logger):
    """Ensure kind is available on PATH (best effort)."""
    if shutil.which('kind'):
        return

    if not (IS_LINUX or IS_MACOS):
        logger.warning("kind auto-install not supported on this platform")
        return

    tools_dir = _tools_bin_dir()
    kind_path = tools_dir / 'kind'

    if kind_path.exists():
        return

    os_name = 'linux' if IS_LINUX else 'darwin'
    arch = platform.machine().lower()
    if arch in {'x86_64', 'amd64'}:
        arch = 'amd64'
    elif arch in {'aarch64', 'arm64'}:
        arch = 'arm64'
    else:
        logger.warning("Unsupported architecture for kind: %s", arch)
        return

    url = f"https://kind.sigs.k8s.io/dl/v0.23.0/kind-{os_name}-{arch}"
    try:
        result = subprocess.run(
            ["curl", "-fsSL", "-o", str(kind_path), url],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            logger.warning("Failed to download kind: %s", result.stderr.strip())
            return
        os.chmod(kind_path, 0o755)
        logger.info("✅ kind installed to %s", kind_path)
    except Exception as e:
        logger.warning("Failed to auto-install kind: %s", e)


def ensure_minikube(logger):
    """Ensure minikube is available on PATH (best effort)."""
    if shutil.which('minikube'):
        return

    if not IS_LINUX:
        logger.warning("minikube auto-install not supported on this platform")
        return

    tools_dir = _tools_bin_dir()
    minikube_path = tools_dir / 'minikube'

    if minikube_path.exists():
        return

    arch = platform.machine().lower()
    if arch in {'x86_64', 'amd64'}:
        arch = 'amd64'
    elif arch in {'aarch64', 'arm64'}:
        arch = 'arm64'
    else:
        logger.warning("Unsupported architecture for minikube: %s", arch)
        return

    url = f"https://storage.googleapis.com/minikube/releases/latest/minikube-linux-{arch}"
    try:
        result = subprocess.run(
            ["curl", "-fsSL", "-o", str(minikube_path), url],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            logger.warning("Failed to download minikube: %s", result.stderr.strip())
            return
        os.chmod(minikube_path, 0o755)
        logger.info("✅ minikube installed to %s", minikube_path)
    except Exception as e:
        logger.warning("Failed to auto-install minikube: %s", e)


def ensure_docker(logger):
    """Ensure Docker is available on PATH (best effort)."""
    if shutil.which('docker'):
        return

    if not IS_LINUX:
        logger.warning("Docker auto-install not supported on this platform")
        return

    if shutil.which('apt-get') is None:
        logger.warning("apt-get not available; cannot auto-install Docker")
        return

    use_sudo = shutil.which('sudo') is not None
    if not use_sudo:
        logger.warning("Docker install requires sudo; skipping auto-install")
        return

    logger.info("🔧 Attempting to install Docker via apt")
    install_cmd = (["sudo", "-n"] if use_sudo else []) + ["apt-get", "update"]
    try:
        subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)
        install_cmd = (["sudo", "-n"] if use_sudo else []) + ["apt-get", "install", "-y", "docker.io"]
        result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            logger.info("✅ Docker installed via apt")
            if shutil.which('systemctl'):
                subprocess.run(["sudo", "-n", "systemctl", "enable", "--now", "docker"],
                               capture_output=True, text=True, timeout=60)
        else:
            logger.warning("Docker install failed: %s", result.stderr.strip())
    except Exception as e:
        logger.warning("Docker install failed: %s", e)


def ensure_docker_compose_plugin(logger):
    """Ensure docker compose plugin is available (best effort)."""
    if not IS_LINUX:
        return

    if shutil.which('docker') is None:
        return

    if shutil.which('apt-get') is None:
        return

    use_sudo = shutil.which('sudo') is not None
    if not use_sudo:
        logger.warning("docker compose plugin install requires sudo; skipping")
        return

    try:
        result = subprocess.run(
            ["sudo", "-n", "apt-get", "install", "-y", "docker-compose-plugin"],
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            logger.info("✅ docker compose plugin installed")
        else:
            logger.warning("docker compose plugin install failed: %s", result.stderr.strip())
    except Exception as e:
        logger.warning("docker compose plugin install failed: %s", e)


def ensure_local_k8s_cluster(logger):
    """Best-effort local Kubernetes cluster setup for validation tests."""
    if not shutil.which('kubectl'):
        return

    # If there is already a context, assume cluster is configured
    try:
        contexts = subprocess.run(
            ["kubectl", "config", "get-contexts"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if contexts.returncode == 0 and "CURRENT" in contexts.stdout:
            return
    except Exception:
        pass

    # Prefer kind when Docker is available
    docker_ok = shutil.which('docker') is not None
    if docker_ok:
        try:
            docker_info = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10
            )
            docker_ok = docker_info.returncode == 0
        except Exception:
            docker_ok = False

    if docker_ok and shutil.which('kind'):
        try:
            clusters = subprocess.run(
                ["kind", "get", "clusters"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if "ipfs-datasets" not in clusters.stdout:
                subprocess.run(
                    ["kind", "create", "cluster", "--name", "ipfs-datasets"],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
            subprocess.run(
                ["kubectl", "config", "use-context", "kind-ipfs-datasets"],
                capture_output=True,
                text=True,
                timeout=10
            )
            logger.info("✅ kind cluster configured for kubectl")
            return
        except Exception as e:
            logger.warning("Failed to set up kind cluster: %s", e)

    if docker_ok and shutil.which('minikube'):
        try:
            subprocess.run(
                ["minikube", "start", "--driver=docker"],
                capture_output=True,
                text=True,
                timeout=600
            )
            logger.info("✅ minikube cluster configured for kubectl")
        except Exception as e:
            logger.warning("Failed to set up minikube cluster: %s", e)

def test_cli_functionality(logger):
    """Test if CLI tools work after installation"""
    logger.info("\n🧪 Testing CLI functionality...")
    
    tests = [
        ([sys.executable, 'ipfs_datasets_cli.py', '--help'], "Basic CLI help"),
        ([sys.executable, 'enhanced_cli.py', '--help'], "Enhanced CLI help"),
    ]
    
    success_count = 0
    for cmd, description in tests:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"✅ {description}")
                success_count += 1
            else:
                logger.warning(f"❌ {description}: {result.stderr}")
        except Exception as e:
            logger.warning(f"❌ {description}: {e}")
    
    logger.info(f"📊 CLI tests: {success_count}/{len(tests)} passed")
    return success_count > 0

def main():
    """Main setup function"""
    logger = setup_logging()

    # If running under an externally-managed system Python, bootstrap into the
    # repo-local virtualenv first so pip installs can proceed.
    _reexec_in_repo_venv(logger)

    ensure_known_good_ipfs_kit_py(logger)
    ensure_libp2p_main(logger)
    
    logger.info("🔧 IPFS Datasets Quick Dependency Setup")
    logger.info("=" * 50)
    
    # Check pip
    if not check_pip():
        logger.error("❌ pip is not available. Please install pip first.")
        return 1
    
    # Install core dependencies
    if not install_core_dependencies(logger):
        logger.error("❌ Failed to install core dependencies")
        return 1

    # Best-effort system tools
    ensure_docker(logger)
    ensure_docker_compose_plugin(logger)
    ensure_docker_compose(logger)
    ensure_kubectl(logger)
    ensure_kind(logger)
    ensure_minikube(logger)
    ensure_local_k8s_cluster(logger)
    ensure_playwright_browsers(logger)
    ensure_nltk_data(logger)
    
    # Create configuration files
    enable_auto_install_in_config(logger)
    create_installation_script(logger)
    
    # Test CLI functionality
    test_cli_functionality(logger)
    
    logger.info("\n🎉 Quick setup complete!")
    logger.info("\nNext steps:")
    logger.info("1. Run 'python dependency_manager.py setup' for interactive setup")
    logger.info("2. Run 'python install_deps.py <profile>' for specific features")
    logger.info("3. Run CLI tests: 'python comprehensive_cli_test.py'")
    logger.info("\nProfiles available: minimal, cli, pdf, ml, web")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())