#!/usr/bin/env python3
"""
IPFS Datasets Python - Comprehensive Dependency Checker
Validates and installs missing dependencies for full functionality.
"""

import subprocess
import sys
import importlib
import os
from typing import List, Tuple, Dict

class DependencyChecker:
    """Comprehensive dependency checker and installer."""
    
    def __init__(self):
        self.missing_packages = []
        self.dependency_map = {
            # Core web framework
            'flask': 'flask',
            'dash': 'dash',
            'dash_bootstrap_components': 'dash-bootstrap-components',
            'plotly': 'plotly',
            'fastapi': 'fastapi[all]',
            'uvicorn': 'uvicorn[standard]',
            
            # Data processing
            'pydantic': 'pydantic',
            'pandas': 'pandas',
            'numpy': 'numpy',
            'pyarrow': 'pyarrow',
            'duckdb': 'duckdb',
            
            # NLP and AI
            'nltk': 'nltk',
            'tiktoken': 'tiktoken',
            'openai': 'openai',
            'transformers': 'transformers',
            'torch': 'torch',
            'sentence_transformers': 'sentence-transformers',
            
            # PDF processing
            'fitz': 'PyMuPDF',
            'pdfplumber': 'pdfplumber',
            
            # Image/Computer Vision
            'cv2': 'opencv-python',
            'PIL': 'Pillow',
            
            # Web scraping
            'newspaper': 'newspaper3k "lxml[html_clean]"',
            'readability': 'readability',
            'requests': 'requests',
            'bs4': 'beautifulsoup4',
            
            # Utilities
            'cachetools': 'cachetools',
            'python_magic': 'python-magic',
            'watchdog': 'watchdog',
            'psutil': 'psutil',
            'aiofiles': 'aiofiles',
            'aiohttp': 'aiohttp',
            
            # IPFS and blockchain
            'ipfshttpclient': 'ipfshttpclient',
            'multiformats': 'multiformats',
            'base58': 'base58',
            
            # Vector stores and ML
            'faiss': 'faiss-cpu',
            'sklearn': 'scikit-learn',
            'spacy': 'spacy',
            
            # Vector databases
            'qdrant_client': 'qdrant-client',
            'chromadb': 'chromadb',
            'elasticsearch': 'elasticsearch',
            
            # Knowledge graph and semantics
            'networkx': 'networkx',
            'rdflib': 'rdflib',
            
            # Configuration and serialization
            'yaml': 'PyYAML',
            'toml': 'toml',
            
            # Additional visualization
            'dash_cytoscape': 'dash-cytoscape',
            'dash_bootstrap_components': 'dash-bootstrap-components',
            
            # Additional ML and data science
            'statsmodels': 'statsmodels',
            'seaborn': 'seaborn',
            'scipy': 'scipy',
            'joblib': 'joblib',
            
            # Testing (optional)
            'pytest': 'pytest',
            'pytest_cov': 'pytest-cov',
        }
        
        self.optional_packages = {
            'jupyter': 'jupyter',
            'notebook': 'notebook',
            'ipykernel': 'ipykernel',
            'ipywidgets': 'ipywidgets',
            'jupyterlab': 'jupyterlab',
            
            # Advanced ML (optional)
            'xgboost': 'xgboost',
            'lightgbm': 'lightgbm',
            'catboost': 'catboost',
            
            # GPU support (optional)
            'cupy': 'cupy',
            'faiss_gpu': 'faiss-gpu',
        }
        
    def check_package(self, package_name: str) -> bool:
        """Check if a package is installed."""
        try:
            # Handle special import cases
            if package_name == 'cv2':
                importlib.import_module('cv2')
            elif package_name == 'fitz':
                importlib.import_module('fitz')
            elif package_name == 'PIL':
                importlib.import_module('PIL')
            elif package_name == 'bs4':
                importlib.import_module('bs4')
            elif package_name == 'python_magic':
                importlib.import_module('magic')
            elif package_name == 'newspaper':
                # newspaper3k package imports as 'newspaper'
                importlib.import_module('newspaper')
            elif package_name == 'faiss':
                # FAISS can be faiss-cpu or faiss-gpu
                importlib.import_module('faiss')
            elif package_name == 'sklearn':
                # scikit-learn imports as sklearn
                importlib.import_module('sklearn')
            elif package_name == 'yaml':
                # PyYAML imports as yaml
                importlib.import_module('yaml')
            elif package_name == 'qdrant_client':
                # qdrant-client imports as qdrant_client
                importlib.import_module('qdrant_client')
            else:
                importlib.import_module(package_name)
            return True
        except ImportError:
            return False
    
    def check_system_dependencies(self) -> List[str]:
        """Check for system-level dependencies."""
        missing_system = []
        
        # Check for common system dependencies
        system_deps = {
            'git': 'git --version',
            'curl': 'curl --version',
            'ffmpeg': 'ffmpeg -version',
        }
        
        for dep, check_cmd in system_deps.items():
            try:
                result = subprocess.run(check_cmd.split(), 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    missing_system.append(dep)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                missing_system.append(dep)
        
        return missing_system
    
    def check_all_dependencies(self) -> Tuple[List[str], List[str], List[str]]:
        """Check all dependencies and return missing core, optional, and system deps."""
        missing_core = []
        missing_optional = []
        
        print("Checking core dependencies...")
        for module_name, package_name in self.dependency_map.items():
            if not self.check_package(module_name):
                missing_core.append(package_name)
                print(f"  ❌ Missing: {module_name} ({package_name})")
            else:
                print(f"  ✅ Found: {module_name}")
        
        print("\nChecking optional dependencies...")
        for module_name, package_name in self.optional_packages.items():
            if not self.check_package(module_name):
                missing_optional.append(package_name)
                print(f"  ⚠️  Optional missing: {module_name} ({package_name})")
            else:
                print(f"  ✅ Found: {module_name}")
        
        print("\nChecking system dependencies...")
        missing_system = self.check_system_dependencies()
        for dep in missing_system:
            print(f"  ❌ System missing: {dep}")
        
        return missing_core, missing_optional, missing_system
    
    def install_packages(self, packages: List[str], optional: bool = False) -> bool:
        """Install missing packages."""
        if not packages:
            return True
            
        package_type = "optional" if optional else "core"
        print(f"\nInstalling {package_type} packages: {', '.join(packages)}")
        
        try:
            cmd = [sys.executable, '-m', 'pip', 'install', '--upgrade'] + packages
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print(f"✅ Successfully installed {package_type} packages")
                
                # Verify installation by re-checking packages
                print(f"Verifying {package_type} package installation...")
                verification_failed = []
                for package in packages:
                    # Map pip package name back to import name
                    import_name = self._get_import_name_from_pip_name(package)
                    if import_name and not self.check_package(import_name):
                        verification_failed.append(package)
                
                if verification_failed:
                    print(f"⚠️  Installation verification failed for: {', '.join(verification_failed)}")
                    return False
                else:
                    print(f"✅ All {package_type} packages verified successfully")
                    return True
            else:
                print(f"❌ Failed to install {package_type} packages:")
                print(result.stderr)
                return False
        except subprocess.TimeoutExpired:
            print(f"❌ Timeout installing {package_type} packages")
            return False
        except Exception as e:
            print(f"❌ Error installing {package_type} packages: {e}")
            return False

    def _get_import_name_from_pip_name(self, pip_name: str) -> str:
        """Map pip package names to import names."""
        # Handle special cases and pip package name transformations
        mapping = {
            'fastapi[all]': 'fastapi',
            'uvicorn[standard]': 'uvicorn', 
            'PyMuPDF': 'fitz',
            'opencv-python': 'cv2',
            'newspaper3k "lxml[html_clean]"': 'newspaper',
            'beautifulsoup4': 'bs4',
            'python-magic': 'python_magic',
            'sentence-transformers': 'sentence_transformers',
            'pytest-cov': 'pytest_cov',
            'faiss-cpu': 'faiss',
            'faiss-gpu': 'faiss_gpu',
            'scikit-learn': 'sklearn',
            'PyYAML': 'yaml',
            'qdrant-client': 'qdrant_client',
            'dash-cytoscape': 'dash_cytoscape',
            'dash-bootstrap-components': 'dash_bootstrap_components',
        }
        
        # Remove version specifiers and extras
        clean_name = pip_name.split('[')[0].split('==')[0].split('>=')[0].split('<=')[0]
        
        return mapping.get(pip_name, mapping.get(clean_name, clean_name))
    
    def setup_nltk_data(self):
        """Download required NLTK data."""
        if self.check_package('nltk'):
            print("\nSetting up NLTK data...")
            try:
                import nltk
                datasets = ['punkt', 'averaged_perceptron_tagger', 'maxent_ne_chunker', 
                           'words', 'stopwords', 'vader_lexicon']
                
                for dataset in datasets:
                    try:
                        nltk.download(dataset, quiet=True)
                        print(f"  ✅ Downloaded: {dataset}")
                    except Exception as e:
                        print(f"  ⚠️  Failed to download {dataset}: {e}")
                        
            except Exception as e:
                print(f"❌ NLTK setup failed: {e}")
    
    def run_comprehensive_check(self, install_missing: bool = True, install_optional: bool = False):
        """Run comprehensive dependency check and optionally install missing packages."""
        print("🔍 IPFS Datasets Python - Dependency Check")
        print("=" * 50)
        
        missing_core, missing_optional, missing_system = self.check_all_dependencies()
        
        # Report summary
        print("\n📊 SUMMARY")
        print("-" * 20)
        print(f"Core packages missing: {len(missing_core)}")
        print(f"Optional packages missing: {len(missing_optional)}")
        print(f"System dependencies missing: {len(missing_system)}")
        
        if missing_system:
            print("\n⚠️  System Dependencies Missing:")
            print("Please install these manually:")
            for dep in missing_system:
                if dep == 'ffmpeg':
                    print(f"  - {dep}: sudo apt install ffmpeg  # Ubuntu/Debian")
                elif dep == 'git':
                    print(f"  - {dep}: sudo apt install git")
                elif dep == 'curl':
                    print(f"  - {dep}: sudo apt install curl")
                else:
                    print(f"  - {dep}")
        
        success = True
        
        # Install missing packages
        if install_missing and missing_core:
            success &= self.install_packages(missing_core, optional=False)
            
            # Re-check core dependencies after installation
            if success:
                print("\nRe-checking core dependencies after installation...")
                still_missing_core = []
                for module_name, package_name in self.dependency_map.items():
                    if not self.check_package(module_name):
                        still_missing_core.append(module_name)
                missing_core = still_missing_core  # Update the list
        
        if install_optional and missing_optional:
            success &= self.install_packages(missing_optional, optional=True)
        
        # Setup additional data
        self.setup_nltk_data()
        
        print("\n🎉 Dependency check complete!")
        if success and not missing_core:
            print("✅ All core dependencies are satisfied")
            return True
        elif missing_core:
            print("❌ Some core dependencies are still missing")
            return False
        
        return True
        
        return True

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='IPFS Datasets Python Dependency Checker')
    parser.add_argument('--check-only', action='store_true', help='Only check, do not install')
    parser.add_argument('--install-optional', action='store_true', help='Install optional packages')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    checker = DependencyChecker()
    
    install_missing = not args.check_only
    success = checker.run_comprehensive_check(
        install_missing=install_missing,
        install_optional=args.install_optional
    )
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()