#!/usr/bin/env python3
"""
Semi-Automated Dependency Management System
Comprehensive tool suite for managing dependencies and preventing dependency-related errors.
"""

import os
import sys
import json
import subprocess
import importlib
import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Union
from dataclasses import dataclass, asdict
import argparse
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class DependencyStatus:
    """Status of a dependency"""
    name: str
    installed: bool
    version: Optional[str] = None
    import_error: Optional[str] = None
    install_method: Optional[str] = None
    required_by: List[str] = None
    
    def __post_init__(self):
        if self.required_by is None:
            self.required_by = []

@dataclass
class InstallationProfile:
    """Installation profile for different use cases"""
    name: str
    description: str
    dependencies: List[str]
    system_deps: List[str] = None
    optional: bool = False
    
    def __post_init__(self):
        if self.system_deps is None:
            self.system_deps = []

class DependencyDetector:
    """Scans codebase and detects all dependencies"""
    
    def __init__(self, root_path: str = None):
        self.root_path = Path(root_path) if root_path else Path.cwd()
        self.python_files = []
        self.found_imports = set()
        self.found_from_imports = set()
        
    def scan_codebase(self) -> Dict[str, Set[str]]:
        """Scan all Python files and extract imports"""
        logger.info(f"Scanning codebase at {self.root_path}")
        
        # Find all Python files
        for pattern in ['**/*.py']:
            for file_path in self.root_path.glob(pattern):
                if self._should_include_file(file_path):
                    self.python_files.append(file_path)
        
        logger.info(f"Found {len(self.python_files)} Python files to scan")
        
        imports_by_file = {}
        
        for file_path in self.python_files:
            try:
                imports = self._extract_imports_from_file(file_path)
                if imports:
                    imports_by_file[str(file_path.relative_to(self.root_path))] = imports
                    self.found_imports.update(imports)
            except Exception as e:
                logger.warning(f"Error scanning {file_path}: {e}")
                
        return imports_by_file
    
    def _should_include_file(self, file_path: Path) -> bool:
        """Check if file should be included in scan"""
        exclude_dirs = {
            '__pycache__', '.git', '.pytest_cache', 'node_modules',
            'venv', 'env', '.venv', '.env', 'build', 'dist'
        }
        
        # Check if any parent directory is in exclude list
        for parent in file_path.parents:
            if parent.name in exclude_dirs:
                return False
                
        return True
    
    def _extract_imports_from_file(self, file_path: Path) -> Set[str]:
        """Extract all imports from a Python file"""
        imports = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
                        
            # Also look for string-based imports (for dynamic imports)
            self._find_string_imports(content, imports)
            
        except Exception as e:
            logger.debug(f"Could not parse {file_path}: {e}")
            
        return imports
    
    def _find_string_imports(self, content: str, imports: Set[str]):
        """Find imports in string form (importlib.import_module, etc.)"""
        patterns = [
            r'importlib\.import_module\([\'"]([^.\'"]+)',
            r'__import__\([\'"]([^.\'"]+)',
            r'from\s+[\'"]([^.\'"]+)[\'"]',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                imports.add(match)

class DependencyValidator:
    """Validates if dependencies are properly installed and working"""
    
    def __init__(self):
        self.status_cache = {}
        
    def check_dependency(self, name: str, test_import: str = None) -> DependencyStatus:
        """Check if a single dependency is available"""
        if name in self.status_cache:
            return self.status_cache[name]
            
        import_name = test_import or name
        status = DependencyStatus(name=name, installed=False)
        
        try:
            module = importlib.import_module(import_name)
            status.installed = True
            
            # Try to get version
            version = getattr(module, '__version__', None)
            if version:
                status.version = version
            else:
                # Try alternative version attributes
                for attr in ['version', 'VERSION', '_version']:
                    version = getattr(module, attr, None)
                    if version:
                        status.version = str(version)
                        break
                        
        except ImportError as e:
            status.import_error = str(e)
            
        self.status_cache[name] = status
        return status
    
    def check_multiple_dependencies(self, dependencies: List[str]) -> Dict[str, DependencyStatus]:
        """Check multiple dependencies"""
        results = {}
        for dep in dependencies:
            results[dep] = self.check_dependency(dep)
        return results
    
    def check_system_command(self, command: str) -> bool:
        """Check if a system command is available"""
        try:
            result = subprocess.run([command, '--version'], 
                                  capture_output=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

class InstallationManager:
    """Manages installation of dependencies based on profiles"""
    
    def __init__(self):
        self.profiles = self._create_installation_profiles()
        self.installer = self._get_auto_installer()
        
    def _get_auto_installer(self):
        """Get the auto installer from the existing module"""
        try:
            from ipfs_datasets_py.auto_installer import get_installer
            return get_installer()
        except ImportError:
            logger.warning("Auto installer not available")
            return None
    
    def _create_installation_profiles(self) -> Dict[str, InstallationProfile]:
        """Create predefined installation profiles"""
        profiles = {
            'minimal': InstallationProfile(
                name='minimal',
                description='Basic functionality only',
                dependencies=[
                    'requests', 'pyyaml', 'tqdm', 'psutil', 'jsonschema'
                ]
            ),
            'cli': InstallationProfile(
                name='cli',
                description='CLI tools functionality',
                dependencies=[
                    'requests', 'pyyaml', 'tqdm', 'psutil', 'jsonschema',
                    'pandas', 'numpy', 'pyarrow'
                ]
            ),
            'pdf': InstallationProfile(
                name='pdf',
                description='PDF processing capabilities',
                dependencies=[
                    'requests', 'pyyaml', 'tqdm', 'psutil',
                    'pymupdf', 'pdfplumber', 'pytesseract', 'pillow',
                    'opencv-python', 'networkx'
                ],
                system_deps=['tesseract', 'poppler']
            ),
            'ml': InstallationProfile(
                name='ml',
                description='Machine learning and AI features',
                dependencies=[
                    'numpy', 'pandas', 'torch', 'transformers', 
                    'sentence-transformers', 'datasets', 'scipy',
                    'scikit-learn', 'nltk', 'tiktoken'
                ]
            ),
            'vectors': InstallationProfile(
                name='vectors',
                description='Vector storage and search',
                dependencies=[
                    'numpy', 'faiss-cpu', 'qdrant-client',
                    'elasticsearch', 'sentence-transformers'
                ]
            ),
            'web': InstallationProfile(
                name='web',
                description='Web scraping and archiving',
                dependencies=[
                    'requests', 'beautifulsoup4', 'selenium',
                    'newspaper3k', 'readability-lxml',
                    'cdx-toolkit', 'wayback', 'internetarchive',
                    'autoscraper', 'warcio', 'aiohttp'
                ]
            ),
            'media': InstallationProfile(
                name='media',
                description='Media processing (audio/video)',
                dependencies=[
                    'ffmpeg-python', 'moviepy', 'pillow',
                    'opencv-python', 'yt-dlp'
                ],
                system_deps=['ffmpeg']
            ),
            'api': InstallationProfile(
                name='api',
                description='FastAPI web services',
                dependencies=[
                    'fastapi', 'uvicorn', 'pydantic', 'python-multipart',
                    'PyJWT', 'passlib'
                ]
            ),
            'dev': InstallationProfile(
                name='dev',
                description='Development and testing',
                dependencies=[
                    'pytest', 'pytest-cov', 'pytest-asyncio',
                    'coverage', 'mypy', 'flake8', 'black'
                ]
            ),
            'full': InstallationProfile(
                name='full',
                description='All functionality (everything)',
                dependencies=[],  # Will be populated by combining all profiles
                optional=True
            )
        }
        
        # Create full profile by combining all others
        all_deps = set()
        all_system_deps = set()
        for name, profile in profiles.items():
            if name != 'full':
                all_deps.update(profile.dependencies)
                all_system_deps.update(profile.system_deps)
        
        profiles['full'].dependencies = list(all_deps)
        profiles['full'].system_deps = list(all_system_deps)
        
        return profiles
    
    def install_profile(self, profile_name: str, dry_run: bool = False) -> Dict[str, bool]:
        """Install all dependencies for a profile"""
        if profile_name not in self.profiles:
            raise ValueError(f"Unknown profile: {profile_name}")
            
        profile = self.profiles[profile_name]
        logger.info(f"Installing profile '{profile_name}': {profile.description}")
        
        if dry_run:
            logger.info("DRY RUN - would install:")
            for dep in profile.dependencies:
                logger.info(f"  - {dep}")
            if profile.system_deps:
                logger.info("System dependencies:")
                for dep in profile.system_deps:
                    logger.info(f"  - {dep}")
            return {}
        
        results = {}
        
        if not self.installer:
            logger.error("Auto installer not available")
            return results
        
        # Install system dependencies first
        for sys_dep in profile.system_deps:
            try:
                success = self.installer.install_system_dependency(sys_dep)
                results[f"system:{sys_dep}"] = success
            except Exception as e:
                logger.error(f"Failed to install system dependency {sys_dep}: {e}")
                results[f"system:{sys_dep}"] = False
        
        # Install Python dependencies
        for dep in profile.dependencies:
            try:
                success = self.installer.install_python_dependency(dep)
                results[dep] = success
            except Exception as e:
                logger.error(f"Failed to install {dep}: {e}")
                results[dep] = False
                
        return results

class DependencyManager:
    """Main dependency management interface"""
    
    def __init__(self, root_path: str = None):
        self.detector = DependencyDetector(root_path)
        self.validator = DependencyValidator()
        self.installer = InstallationManager()
        
    def analyze_dependencies(self) -> Dict:
        """Comprehensive dependency analysis"""
        logger.info("Starting comprehensive dependency analysis...")
        
        # Detect dependencies in codebase
        imports_by_file = self.detector.scan_codebase()
        all_imports = self.detector.found_imports
        
        # Check status of all detected dependencies
        dependency_status = self.validator.check_multiple_dependencies(list(all_imports))
        
        # Categorize dependencies
        installed = {name: status for name, status in dependency_status.items() if status.installed}
        missing = {name: status for name, status in dependency_status.items() if not status.installed}
        
        # Generate recommendations
        recommendations = self._generate_recommendations(missing)
        
        return {
            'summary': {
                'total_dependencies': len(all_imports),
                'installed': len(installed),
                'missing': len(missing),
                'files_scanned': len(imports_by_file)
            },
            'dependencies': {
                'installed': installed,
                'missing': missing
            },
            'imports_by_file': imports_by_file,
            'recommendations': recommendations
        }
    
    def _generate_recommendations(self, missing_deps: Dict[str, DependencyStatus]) -> Dict:
        """Generate installation recommendations"""
        recommendations = {
            'profiles': [],
            'manual_installs': []
        }
        
        missing_names = set(missing_deps.keys())
        
        # Check which profiles would satisfy the most missing dependencies
        for profile_name, profile in self.installer.profiles.items():
            profile_deps = set(profile.dependencies)
            satisfied = missing_names.intersection(profile_deps)
            
            if satisfied:
                recommendations['profiles'].append({
                    'name': profile_name,
                    'description': profile.description,
                    'satisfies': list(satisfied),
                    'coverage': len(satisfied) / len(missing_names) if missing_names else 0
                })
        
        # Sort profiles by coverage
        recommendations['profiles'].sort(key=lambda x: x['coverage'], reverse=True)
        
        # Find dependencies not covered by any profile
        all_profile_deps = set()
        for profile in self.installer.profiles.values():
            all_profile_deps.update(profile.dependencies)
            
        uncovered = missing_names - all_profile_deps
        if uncovered:
            recommendations['manual_installs'] = list(uncovered)
            
        return recommendations
    
    def interactive_setup(self):
        """Interactive setup wizard"""
        print("\n🔧 IPFS Datasets Dependency Setup Wizard")
        print("=" * 50)
        
        # Check current status
        analysis = self.analyze_dependencies()
        missing_count = analysis['summary']['missing']
        
        if missing_count == 0:
            print("✅ All dependencies are already installed!")
            return
            
        print(f"Found {missing_count} missing dependencies.")
        print("\nAvailable installation profiles:")
        
        # Show profiles
        for i, (name, profile) in enumerate(self.installer.profiles.items(), 1):
            print(f"{i:2d}. {name:12s} - {profile.description}")
            
        print(f"{len(self.installer.profiles)+1:2d}. custom      - Manual dependency selection")
        print(f"{len(self.installer.profiles)+2:2d}. analyze     - Show detailed analysis only")
        
        while True:
            try:
                choice = input(f"\nSelect option (1-{len(self.installer.profiles)+2}): ").strip()
                
                if choice == str(len(self.installer.profiles)+2):
                    # Show analysis
                    self._print_detailed_analysis(analysis)
                    return
                elif choice == str(len(self.installer.profiles)+1):
                    # Custom installation
                    self._custom_installation(analysis)
                    return
                else:
                    # Profile installation
                    profile_idx = int(choice) - 1
                    profile_names = list(self.installer.profiles.keys())
                    if 0 <= profile_idx < len(profile_names):
                        profile_name = profile_names[profile_idx]
                        self._install_profile_interactive(profile_name)
                        return
                    else:
                        print("Invalid selection, please try again.")
                        
            except (ValueError, KeyboardInterrupt):
                print("\nExiting setup.")
                return
    
    def _print_detailed_analysis(self, analysis: Dict):
        """Print detailed dependency analysis"""
        print("\n📊 Detailed Dependency Analysis")
        print("=" * 40)
        
        summary = analysis['summary']
        print(f"Total dependencies found: {summary['total_dependencies']}")
        print(f"✅ Installed: {summary['installed']}")
        print(f"❌ Missing: {summary['missing']}")
        print(f"Files scanned: {summary['files_scanned']}")
        
        if analysis['dependencies']['missing']:
            print(f"\n❌ Missing Dependencies ({len(analysis['dependencies']['missing'])}):")
            for name, status in analysis['dependencies']['missing'].items():
                print(f"  - {name:20s} ({status.import_error or 'Not found'})")
        
        if analysis['recommendations']['profiles']:
            print(f"\n💡 Recommended Installation Profiles:")
            for rec in analysis['recommendations']['profiles'][:3]:  # Top 3
                coverage_pct = rec['coverage'] * 100
                print(f"  {rec['name']:12s} - {coverage_pct:5.1f}% coverage - {rec['description']}")
                
    def _install_profile_interactive(self, profile_name: str):
        """Install a profile with user confirmation"""
        profile = self.installer.profiles[profile_name]
        
        print(f"\n📦 Installing profile: {profile_name}")
        print(f"Description: {profile.description}")
        print(f"Dependencies ({len(profile.dependencies)}):")
        for dep in profile.dependencies[:10]:  # Show first 10
            print(f"  - {dep}")
        if len(profile.dependencies) > 10:
            print(f"  ... and {len(profile.dependencies) - 10} more")
            
        if profile.system_deps:
            print(f"System dependencies ({len(profile.system_deps)}):")
            for dep in profile.system_deps:
                print(f"  - {dep}")
        
        confirm = input(f"\nProceed with installation? [y/N]: ").strip().lower()
        if confirm in ['y', 'yes']:
            print("Installing...")
            results = self.installer.install_profile(profile_name)
            
            success_count = sum(1 for success in results.values() if success)
            total_count = len(results)
            
            print(f"\n✅ Installation complete: {success_count}/{total_count} successful")
            
            if success_count < total_count:
                print("❌ Failed installations:")
                for name, success in results.items():
                    if not success:
                        print(f"  - {name}")
        else:
            print("Installation cancelled.")
    
    def _custom_installation(self, analysis: Dict):
        """Custom dependency installation"""
        missing_deps = list(analysis['dependencies']['missing'].keys())
        
        print(f"\n🎯 Custom Installation")
        print(f"Missing dependencies:")
        for i, dep in enumerate(missing_deps, 1):
            print(f"{i:2d}. {dep}")
            
        print("\nEnter numbers to install (e.g., 1,3,5 or 'all'):")
        selection = input("> ").strip()
        
        if selection.lower() == 'all':
            to_install = missing_deps
        else:
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                to_install = [missing_deps[i] for i in indices if 0 <= i < len(missing_deps)]
            except (ValueError, IndexError):
                print("Invalid selection.")
                return
        
        if to_install:
            print(f"Installing {len(to_install)} dependencies...")
            if self.installer.installer:
                results = {}
                for dep in to_install:
                    success = self.installer.installer.install_python_dependency(dep)
                    results[dep] = success
                    
                success_count = sum(1 for success in results.values() if success)
                print(f"✅ Installation complete: {success_count}/{len(to_install)} successful")
            else:
                print("❌ Auto installer not available")

def create_dependency_report(output_file: str = None) -> Dict:
    """Create a comprehensive dependency report"""
    manager = DependencyManager()
    analysis = manager.analyze_dependencies()
    
    # Add system info
    analysis['system_info'] = {
        'python_version': sys.version,
        'platform': sys.platform,
        'executable': sys.executable
    }
    
    # Save to file if requested
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        logger.info(f"Report saved to {output_file}")
    
    return analysis

def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description='IPFS Datasets Dependency Manager')
    parser.add_argument('command', choices=['analyze', 'install', 'setup', 'validate', 'report'],
                       help='Command to execute')
    parser.add_argument('--profile', help='Installation profile name')
    parser.add_argument('--output', help='Output file for reports')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be installed')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--root-path', help='Root path to scan (default: current directory)')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    manager = DependencyManager(args.root_path)
    
    if args.command == 'analyze':
        analysis = manager.analyze_dependencies()
        manager._print_detailed_analysis(analysis)
        
    elif args.command == 'install':
        if not args.profile:
            print("Error: --profile required for install command")
            print("Available profiles:")
            for name, profile in manager.installer.profiles.items():
                print(f"  {name:12s} - {profile.description}")
            return 1
            
        results = manager.installer.install_profile(args.profile, args.dry_run)
        if not args.dry_run:
            success_count = sum(1 for success in results.values() if success)
            print(f"Installation complete: {success_count}/{len(results)} successful")
            
    elif args.command == 'setup':
        manager.interactive_setup()
        
    elif args.command == 'validate':
        analysis = manager.analyze_dependencies()
        missing_count = analysis['summary']['missing']
        if missing_count == 0:
            print("✅ All dependencies validated successfully")
            return 0
        else:
            print(f"❌ {missing_count} dependencies missing")
            return 1
            
    elif args.command == 'report':
        output_file = args.output or 'dependency_report.json'
        create_dependency_report(output_file)
        print(f"Report saved to {output_file}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())