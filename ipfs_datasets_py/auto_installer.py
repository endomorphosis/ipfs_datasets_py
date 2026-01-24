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
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
import warnings

logger = logging.getLogger(__name__)


class DependencyInstaller:
    """Cross-platform dependency installer that replaces mock implementations"""
    
    def __init__(self, auto_install: bool = None, verbose: bool = False):
        # Check environment variable first, then parameter, default to False
        if auto_install is None:
            auto_install = os.environ.get('IPFS_DATASETS_AUTO_INSTALL', 'false').lower() == 'true'
        self.auto_install = auto_install
        self.verbose = verbose
        self.system = platform.system().lower()
        self.architecture = platform.machine().lower()
        self.python_version = sys.version_info
        
        # Track installed packages to avoid duplicate installations
        self.installed_packages = set()
        
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
        
        # Python package specifications with fallbacks
        numpy_specs = ['numpy>=2.0.0'] if self.python_version >= (3, 14) else ['numpy>=1.21.0,<2.0.0']

        self.python_packages = {
            # Core ML/AI packages
            'numpy': numpy_specs,
            'pandas': ['pandas>=1.5.0,<3.0.0'],
            'torch': ['torch>=1.9.0,<3.0.0', 'torch-cpu>=1.9.0'],
            'transformers': ['transformers>=4.0.0,<5.0.0'],
            'sentence-transformers': ['sentence-transformers>=2.2.0,<3.0.0'],
            'datasets': ['datasets>=2.10.0,<3.0.0'],
            
            # PDF processing
            'pymupdf': ['pymupdf>=1.24.0,<2.0.0', 'PyMuPDF>=1.24.0'],
            'pdfplumber': ['pdfplumber>=0.10.0,<1.0.0'],
            'pytesseract': ['pytesseract>=0.3.10,<1.0.0'],
            'pillow': ['pillow>=10.0.0', 'PIL>=10.0.0'],
            
            # OCR and vision
            'opencv-python': ['opencv-python>=4.5.0', 'opencv-contrib-python>=4.5.0'],
            'surya-ocr': ['surya-ocr>=0.14.0'],
            'easyocr': ['easyocr>=1.6.0'],
            
            # NLP
            'nltk': ['nltk>=3.8.0,<4.0.0'],
            'spacy': ['spacy>=3.4.0,<4.0.0'],
            
            # Vector stores
            'faiss-cpu': ['faiss-cpu>=1.7.4,<2.0.0', 'faiss>=1.7.4'],
            'qdrant-client': ['qdrant-client>=1.0.0'],
            'elasticsearch': ['elasticsearch>=8.0.0,<9.0.0'],
            
            # Scientific computing
            'scipy': ['scipy>=1.11.0,<2.0.0'],
            'scikit-learn': ['scikit-learn>=1.3.0,<2.0.0'],
            'networkx': ['networkx>=3.0.0,<4.0.0'],
            
            # LLM APIs
            'openai': ['openai>=1.0.0,<2.0.0'],
            'anthropic': ['anthropic>=0.50.0,<1.0.0'],
            
            # Web and API
            'fastapi': ['fastapi>=0.100.0,<1.0.0'],
            'uvicorn': ['uvicorn>=0.20.0,<1.0.0'],
            'requests': ['requests>=2.25.0,<3.0.0'],
            
            # Data formats
            'pyarrow': ['pyarrow>=15.0.0,<21.0.0'],
            
            # Theorem Provers and SAT/SMT Solvers (Python bindings)
            'z3-solver': ['z3-solver>=4.12.0,<5.0.0'],
            'pysmt': ['pysmt>=0.9.5,<1.0.0'],
            'cvc5': ['cvc5>=1.0.0,<2.0.0'], 
            'mathsat': ['mathsat>=5.6.0'],
            'beartype': ['beartype>=0.15.0,<1.0.0'],
            'pydantic': ['pydantic>=2.0.0,<3.0.0'],
            'jsonschema': ['jsonschema>=4.0.0,<5.0.0'],
            
            # Media processing
            'ffmpeg-python': ['ffmpeg-python>=0.2.0'],
            'moviepy': ['moviepy>=1.0.0'],
            
            # Web scraping
            'requests': ['requests>=2.25.0,<3.0.0'],
            'beautifulsoup4': ['beautifulsoup4>=4.10.0,<5.0.0'],
            'newspaper3k': ['newspaper3k>=0.2.8,<1.0.0'],
            'readability-lxml': ['readability-lxml>=0.8.0,<1.0.0'],
            
            # Development
            'pytest': ['pytest>=8.0.0,<9.0.0'],
            'coverage': ['coverage>=7.0.0,<8.0.0'],
        }

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

    def install_system_dependency(self, package_name: str) -> bool:
        """Install system-level dependency"""
        # Skip system dependency installation in sandboxed environments
        if os.getenv('IPFS_INSTALL_SYSTEM_DEPS', 'true').lower() != 'true':
            if self.verbose:
                logger.info(f"Skipping system dependency {package_name} (IPFS_INSTALL_SYSTEM_DEPS=false)")
            return False

        if not self.auto_install or os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
            if self.verbose:
                logger.info(f"Skipping system dependency {package_name} in CI/sandbox environment")
            return False
            
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

        commands = {
            'apt': ['sudo', 'apt-get', 'install', '-y', system_package],
            'yum': ['sudo', 'yum', 'install', '-y', system_package],
            'dnf': ['sudo', 'dnf', 'install', '-y', system_package],
            'pacman': ['sudo', 'pacman', '-S', '--noconfirm', system_package],
            'zypper': ['sudo', 'zypper', 'install', '-y', system_package],
            'brew': ['brew', 'install', system_package],
            'macports': ['sudo', 'port', 'install', system_package],
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
                
            timeout = 120 if package_manager == 'winget' else 300
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            
            if result.returncode == 0:
                if self.verbose:
                    logger.info(f"Successfully installed {system_package}")
                return True
            else:
                if self.verbose:
                    logger.warning(f"Failed to install {system_package}: {result.stderr}")
                if package_manager == 'winget':
                    fallback_name = package_name if '.' in system_package else system_package
                    if self._command_exists('choco'):
                        choco_cmd = ['choco', 'install', fallback_name, '-y']
                        if self.verbose:
                            logger.info(f"Retrying {fallback_name} using chocolatey")
                        choco_result = subprocess.run(choco_cmd, capture_output=True, text=True, timeout=300)
                        if choco_result.returncode == 0:
                            if self.verbose:
                                logger.info(f"Successfully installed {fallback_name} with chocolatey")
                            return True
                    if self._command_exists('scoop'):
                        scoop_cmd = ['scoop', 'install', fallback_name]
                        if self.verbose:
                            logger.info(f"Retrying {fallback_name} using scoop")
                        scoop_result = subprocess.run(scoop_cmd, capture_output=True, text=True, timeout=300)
                        if scoop_result.returncode == 0:
                            if self.verbose:
                                logger.info(f"Successfully installed {fallback_name} with scoop")
                            return True
                return False
                
        except subprocess.TimeoutExpired:
            if self.verbose:
                logger.warning(f"Timeout installing {system_package}")
            return False
        except Exception as e:
            if self.verbose:
                logger.warning(f"Error installing {system_package}: {e}")
            return False

    def install_python_dependency(self, package_name: str, force_reinstall: bool = False) -> bool:
        """Install Python dependency with fallback options"""
        if package_name in self.installed_packages and not force_reinstall:
            return True
            
        if package_name not in self.python_packages:
            # Try direct pip install
            return self._pip_install(package_name)
            
        packages_to_try = self.python_packages[package_name]
        
        for package_spec in packages_to_try:
            if self._pip_install(package_spec):
                self.installed_packages.add(package_name)
                return True
                
        logger.error(f"Failed to install any variant of {package_name}")
        return False

    def _pip_install(self, package_spec: str) -> bool:
        """Install package using pip"""
        try:
            if self.verbose:
                logger.info(f"Installing {package_spec} with pip")
                
            result = subprocess.run([
                sys.executable, '-m', 'pip', 'install', package_spec, '--quiet',
                '--disable-pip-version-check', '--no-input', '--progress-bar', 'off'
            ], capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                if self.verbose:
                    logger.info(f"Successfully installed {package_spec}")
                return True
            else:
                if self.verbose:
                    logger.warning(f"Failed to install {package_spec}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout installing {package_spec}")
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
        # First try to import
        try:
            module = importlib.import_module(module_name)
            return True, module
        except ImportError as e:
            if not self.auto_install:
                logger.warning(f"Module {module_name} not available and auto_install disabled")
                return False, None
                
            if self.verbose:
                logger.info(f"Module {module_name} not found, attempting to install")
            
            # Install system dependencies first
            if system_deps:
                for sys_dep in system_deps:
                    self.install_system_dependency(sys_dep)
            
            # Install Python package
            pkg_name = package_name or module_name
            if self.install_python_dependency(pkg_name):
                # Try importing again
                try:
                    module = importlib.import_module(module_name)
                    if self.verbose:
                        logger.info(f"Successfully installed and imported {module_name}")
                    return True, module
                except ImportError:
                    logger.error(f"Failed to import {module_name} after installation")
                    return False, None
            else:
                logger.error(f"Failed to install {pkg_name}")
                return False, None

    def install_graphrag_dependencies(self) -> bool:
        """Install all dependencies needed for GraphRAG PDF processing"""
        if self.verbose:
            logger.info("Installing GraphRAG PDF processing dependencies...")
            
        # Core dependencies for GraphRAG
        dependencies = [
            # Core ML
            ('numpy', 'numpy'),
            ('pandas', 'pandas'), 
            ('torch', 'torch'),
            ('transformers', 'transformers'),
            ('sentence_transformers', 'sentence-transformers'),
            ('datasets', 'datasets'),
            
            # PDF processing
            ('fitz', 'pymupdf', ['poppler']),  # PyMuPDF imports as 'fitz'
            ('pdfplumber', 'pdfplumber'),
            ('pytesseract', 'pytesseract', ['tesseract']),
            ('PIL', 'pillow'),
            
            # OCR and vision
            ('cv2', 'opencv-python'),
            ('surya', 'surya-ocr'),
            ('easyocr', 'easyocr'),
            
            # NLP
            ('nltk', 'nltk'),
            
            # Vector stores
            ('faiss', 'faiss-cpu'),
            ('qdrant_client', 'qdrant-client'),
            ('elasticsearch', 'elasticsearch'),
            
            # Scientific
            ('scipy', 'scipy'),
            ('sklearn', 'scikit-learn'),
            ('networkx', 'networkx'),
            
            # LLM APIs
            ('openai', 'openai'),
            
            # Data
            ('pyarrow', 'pyarrow'),
            ('pydantic', 'pydantic'),
        ]
        
        success_count = 0
        total_count = len(dependencies)
        
        for dep_info in dependencies:
            module_name = dep_info[0]
            package_name = dep_info[1] if len(dep_info) > 1 else module_name
            system_deps = dep_info[2] if len(dep_info) > 2 else None
            
            success, _ = self.ensure_dependency(module_name, package_name, system_deps)
            if success:
                success_count += 1
            
        if self.verbose:
            logger.info(f"Installed {success_count}/{total_count} GraphRAG dependencies")
            
        return success_count >= (total_count * 0.8)  # 80% success rate

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

def get_installer() -> DependencyInstaller:
    """Get global installer instance"""
    global _installer
    if _installer is None:
        # Check environment variables for configuration - use consistent variable names
        auto_install = os.getenv('IPFS_DATASETS_AUTO_INSTALL', 
                               os.getenv('IPFS_AUTO_INSTALL', 'false')).lower() == 'true'
        verbose = os.getenv('IPFS_INSTALL_VERBOSE', 'false').lower() == 'true'
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


def install_for_component(component: str) -> bool:
    """Install dependencies for a specific component"""
    installer = get_installer()
    
    if component == 'graphrag':
        return installer.install_graphrag_dependencies()
    elif component == 'pdf':
        dependencies = [
            ('fitz', 'pymupdf', ['poppler']),
            ('pdfplumber', 'pdfplumber'),
            ('pytesseract', 'pytesseract', ['tesseract']),
            ('PIL', 'pillow'),
        ]
    elif component == 'ocr':
        dependencies = [
            ('cv2', 'opencv-python'),
            ('surya', 'surya-ocr'),
            ('easyocr', 'easyocr'),
            ('pytesseract', 'pytesseract', ['tesseract']),
        ]
    elif component == 'ml':
        dependencies = [
            ('numpy', 'numpy'),
            ('torch', 'torch'),
            ('transformers', 'transformers'),
            ('sentence_transformers', 'sentence-transformers'),
        ]
    elif component == 'vectors':
        dependencies = [
            ('faiss', 'faiss-cpu'),
            ('qdrant_client', 'qdrant-client'),
            ('elasticsearch', 'elasticsearch'),
        ]
    elif component == 'theorem_provers':
        # Install theorem provers and SAT/SMT solvers
        return installer.install_theorem_provers()
    elif component == 'z3':
        dependencies = [
            ('z3', 'z3-solver', ['z3']),
        ]
    elif component == 'lean':
        dependencies = [
            # Lean 4 is system-only, no Python binding
        ]
        # Install system dependency only
        return installer.install_system_dependency('lean')
    elif component == 'coq':
        dependencies = [
            # Coq is system-only, no Python binding
        ]
        # Install system dependency only
        return installer.install_system_dependency('coq')
    elif component == 'cvc5':
        dependencies = [
            ('cvc5', 'cvc5', ['cvc5']),
        ]
    elif component == 'smt_solvers':
        dependencies = [
            ('z3', 'z3-solver', ['z3']),
            ('cvc5', 'cvc5', ['cvc5']),
            ('pysmt', 'pysmt'),
        ]
    elif component == 'web':
        dependencies = [
            ('requests', 'requests'),
            ('bs4', 'beautifulsoup4'),
            ('newspaper', 'newspaper3k'),
            ('readability', 'readability-lxml'),
        ]
    else:
        logger.warning(f"Unknown component: {component}")
        return False
    
    success_count = 0
    for dep_info in dependencies:
        module_name = dep_info[0]
        package_name = dep_info[1] if len(dep_info) > 1 else module_name
        system_deps = dep_info[2] if len(dep_info) > 2 else None
        
        success, _ = installer.ensure_dependency(module_name, package_name, system_deps)
        if success:
            success_count += 1
    
    return success_count >= len(dependencies)


if __name__ == '__main__':
    # CLI for testing dependency installation
    import argparse
    
    parser = argparse.ArgumentParser(description='Install dependencies for IPFS datasets')
    parser.add_argument('component', nargs='?', default='graphrag',
                       help='Component to install deps for (graphrag, pdf, ocr, ml, vectors, theorem_provers, z3, lean, coq, cvc5, smt_solvers, web)')
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