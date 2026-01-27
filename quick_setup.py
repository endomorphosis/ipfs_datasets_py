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
from pathlib import Path
import importlib.util

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

# Enable auto-installation by setting environment variable
os.environ['IPFS_DATASETS_AUTO_INSTALL'] = 'true'
os.environ['IPFS_INSTALL_VERBOSE'] = 'true'

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
    """Ensure ipfs_kit_py is installed from the known_good branch on Windows."""
    if not IS_WINDOWS:
        return

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
        subprocess.run(['git', '-C', str(repo_path), 'checkout', 'known_good'], check=False, text=True)

        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-e', str(repo_path),
            '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
        ], check=False, text=True)
        if result.returncode == 0:
            marker_file.write_text('known_good', encoding='utf-8')
            os.environ['IPFS_KIT_PY_INSTALLED'] = 'true'
    except Exception as e:
        logger.warning(f"Failed to install known_good ipfs_kit_py: {e}")

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
        'beautifulsoup4>=4.12.0',
        'html2text>=2025.4.15',
        'pillow>=10.0.0,<12.0.0',
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

    ensure_known_good_ipfs_kit_py(logger)
    
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