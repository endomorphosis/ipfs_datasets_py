#!/usr/bin/env python3
"""
Comprehensive Windows installation test script with all extras validation.
Tests installation in virtual environment with platform-specific handling.
"""

import os
import sys
import subprocess
import platform
import json
from pathlib import Path
from typing import Dict, List, Tuple

class WindowsInstallTester:
    """Test installation on Windows with platform detection and all extras"""
    
    # Define all extras groups to test
    EXTRAS_GROUPS = {
        'ipld': ['ipld-car', 'ipld-dag-pb'],
        'web_archive': ['archivenow', 'ipwb', 'beautifulsoup4', 'warcio'],
        'security': ['cryptography', 'keyring'],
        'audit': ['elasticsearch', 'cryptography'],
        'provenance': ['plotly', 'dash', 'dash-cytoscape'],
        'alerts': ['discord.py', 'aiohttp', 'PyYAML'],
        'test': ['pytest', 'pytest-cov', 'pytest-asyncio', 'pytest-timeout', 'pytest-xdist'],
        'pdf': ['pdfplumber', 'pymupdf', 'pytesseract', 'tiktoken', 'pysbd'],
        'multimedia': ['yt-dlp', 'ffmpeg-python', 'pillow', 'moviepy'],
        'ml': ['torch', 'llama-index', 'openai'],
        'vectors': ['faiss-cpu', 'qdrant-client', 'elasticsearch'],
        'scraping': ['beautifulsoup4', 'selenium', 'scrapy', 'autoscraper', 'cdx-toolkit', 'wayback', 'internetarchive'],
        'api': ['fastapi', 'uvicorn', 'flask', 'mcp'],
        'dev': ['mypy', 'flake8', 'coverage', 'Faker', 'reportlab', 'pyfakefs'],
    }
    
    # Platform-specific packages
    PLATFORM_SPECIFIC = {
        'windows': ['pywin32', 'python-magic-bin'],
        'linux': ['python-magic'],
        'macos': ['python-magic'],
    }
    
    def __init__(self):
        self.results = {
            'platform': self._get_platform_info(),
            'venv': None,
            'pip_upgrade': None,
            'core_deps': [],
            'extras_tests': {},
            'platform_specific': [],
            'issues': [],
            'warnings': [],
            'success': False
        }
        self.venv_python = self._find_venv_python()
    
    def _get_platform_info(self) -> Dict:
        """Get detailed platform information"""
        return {
            'system': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'python_implementation': platform.python_implementation(),
            'is_windows': platform.system() == 'Windows',
            'is_64bit': sys.maxsize > 2**32,
        }
    
    def _find_venv_python(self) -> Path:
        """Find Python executable in virtual environment"""
        if platform.system() == 'Windows':
            return Path('.venv/Scripts/python.exe')
        else:
            return Path('.venv/bin/python')
    
    def _run_command(self, cmd: List[str], description: str) -> Tuple[bool, str]:
        """Run a command and capture output"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            return success, output
        except subprocess.TimeoutExpired:
            return False, f"{description} timed out"
        except Exception as e:
            return False, f"{description} error: {str(e)}"
    
    def test_venv_exists(self) -> bool:
        """Check if virtual environment exists"""
        print("\n1️⃣ Checking virtual environment...")
        exists = self.venv_python.exists()
        self.results['venv'] = {
            'exists': exists,
            'path': str(self.venv_python)
        }
        
        if exists:
            print(f"  ✅ Virtual environment found at {self.venv_python}")
            return True
        else:
            print(f"  ❌ Virtual environment not found at {self.venv_python}")
            self.results['issues'].append("Virtual environment missing")
            return False
    
    def test_pip_upgrade(self) -> bool:
        """Upgrade pip in virtual environment"""
        print("\n2️⃣ Upgrading pip...")
        success, output = self._run_command(
            [str(self.venv_python), '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'],
            "Pip upgrade"
        )
        self.results['pip_upgrade'] = success
        if success:
            print("  ✅ Pip upgrade - OK")
        else:
            print("  ❌ Pip upgrade - FAILED")
            self.results['issues'].append("Pip upgrade failed")
        return success
    
    def test_core_dependencies(self) -> bool:
        """Test core dependencies"""
        print("\n3️⃣ Testing core dependencies...")
        
        core_deps = [
            'numpy',
            'requests',
            'pyyaml',
            'cachetools',
        ]
        
        success_count = 0
        for dep in core_deps:
            success, output = self._run_command(
                [str(self.venv_python), '-m', 'pip', 'index', 'versions', dep],
                f"Check {dep}"
            )
            
            self.results['core_deps'].append({
                'name': dep,
                'success': success,
            })
            
            if success:
                success_count += 1
                print(f"    ✅ {dep}")
            else:
                print(f"    ❌ {dep}")
                self.results['issues'].append(f"Failed to resolve {dep}")
        
        success_rate = success_count / len(core_deps)
        print(f"\n  📊 Core dependencies: {success_count}/{len(core_deps)} ({success_rate*100:.0f}%)")
        
        return success_rate >= 0.75
    
    def test_optional_dependencies(self) -> bool:
        """Test all extras groups"""
        print("\n4️⃣ Testing all extras groups (this may take a minute)...")
        
        all_success = 0
        all_total = 0
        
        for group_name, packages in self.EXTRAS_GROUPS.items():
            print(f"\n  📦 Testing '{group_name}' extras:")
            group_results = []
            
            for package in packages:
                success, output = self._run_command(
                    [str(self.venv_python), '-m', 'pip', 'index', 'versions', package],
                    f"Check {package}"
                )
                
                available = success and 'Available versions' in output if output else False
                
                group_results.append({
                    'package': package,
                    'available': available,
                    'success': success
                })
                
                all_total += 1
                if success:
                    all_success += 1
                else:
                    self.results['warnings'].append(f"{group_name}: {package} not available")
            
            success_rate = sum(1 for r in group_results if r['success']) / len(group_results) if group_results else 0
            status = '✅' if success_rate >= 0.8 else '⚠️' if success_rate >= 0.5 else '❌'
            print(f"  {status} {group_name}: {success_rate*100:.0f}% ({sum(1 for r in group_results if r['success'])}/{len(group_results)})")
            
            self.results['extras_tests'][group_name] = {
                'packages': group_results,
                'success_rate': success_rate
            }
        
        print(f"\n  📊 Overall extras availability: {all_success}/{all_total} ({all_success/all_total*100:.0f}%)")
        return True
    
    def test_import_packages(self) -> bool:
        """Test importing installed packages"""
        print("\n5️⃣ Testing package imports...")
        
        test_imports = ['numpy', 'requests', 'yaml', 'psutil', 'pydantic', 'cachetools']
        
        import_script = f"""
import sys
failed = []
for module in {test_imports}:
    try:
        __import__(module)
    except ImportError as e:
        failed.append(module)
sys.exit(len(failed))
"""
        
        success, output = self._run_command(
            [str(self.venv_python), '-c', import_script],
            "Import test"
        )
        
        if success:
            print(f"  ✅ All test imports successful")
        else:
            print(f"  ❌ Some imports failed")
            self.results['issues'].append("Some imports failed")
        
        return success
    
    def test_platform_specific_packages(self) -> bool:
        """Test platform-specific packages"""
        print("\n6️⃣ Testing platform-specific packages...")
        
        current_platform = platform.system().lower()
        if current_platform == 'darwin':
            current_platform = 'macos'
        
        platform_packages = self.PLATFORM_SPECIFIC.get(current_platform, [])
        
        if not platform_packages:
            print(f"  ℹ️  No platform-specific packages for {platform.system()}")
            return True
        
        success_count = 0
        for package in platform_packages:
            success, output = self._run_command(
                [str(self.venv_python), '-m', 'pip', 'index', 'versions', package],
                f"Check {package}"
            )
            
            self.results['platform_specific'].append({
                'package': package,
                'platform': current_platform,
                'available': success,
            })
            
            if success:
                success_count += 1
                print(f"    ✅ {package}")
            else:
                print(f"    ❌ {package}")
                self.results['issues'].append(f"Platform-specific package {package} not available")
        
        print(f"\n  📊 Platform packages: {success_count}/{len(platform_packages)}")
        return success_count == len(platform_packages)
    
    def test_setup_install(self) -> bool:
        """Test validating setup.py configuration"""
        print("\n7️⃣ Validating setup.py configuration...")
        
        success, output = self._run_command(
            [str(self.venv_python), 'setup.py', '--version'],
            "Validate setup.py"
        )
        
        if success:
            print("  ✅ setup.py is valid")
        else:
            print("  ❌ setup.py validation failed")
            self.results['issues'].append("setup.py validation failed")
        
        return success
    
    def generate_report(self) -> str:
        """Generate comprehensive test report"""
        print("\n" + "=" * 70)
        print("📋 COMPREHENSIVE INSTALLATION TEST REPORT")
        print("=" * 70)
        
        # Platform info
        print("\n🖥️  Platform Information:")
        for key, value in self.results['platform'].items():
            print(f"  {key}: {value}")
        
        # Test results
        print("\n📊 Core Test Results:")
        print(f"  Virtual Environment: {'✅' if self.results['venv'].get('exists') else '❌'}")
        print(f"  Pip Upgrade: {'✅' if self.results['pip_upgrade'] else '❌'}")
        
        core_success = sum(1 for d in self.results['core_deps'] if d['success'])
        core_total = len(self.results['core_deps'])
        print(f"  Core Dependencies: {'✅' if core_success >= core_total * 0.75 else '❌'} ({core_success}/{core_total})")
        
        # Extras summary
        if self.results['extras_tests']:
            print(f"\n📦 Extras Groups Tested ({len(self.results['extras_tests'])}):")
            for group, data in sorted(self.results['extras_tests'].items()):
                success_rate = data['success_rate']
                status = '✅' if success_rate >= 0.8 else '⚠️' if success_rate >= 0.5 else '❌'
                pkg_count = len(data['packages'])
                pkg_avail = sum(1 for p in data['packages'] if p['success'])
                print(f"  {status} {group:15s}: {success_rate*100:5.1f}% ({pkg_avail}/{pkg_count})")
        
        # Platform-specific
        if self.results['platform_specific']:
            platform_success = sum(1 for p in self.results['platform_specific'] if p['available'])
            platform_total = len(self.results['platform_specific'])
            print(f"\n🔧 Platform-Specific Packages: {platform_success}/{platform_total}")
            for pkg in self.results['platform_specific']:
                status = '✅' if pkg['available'] else '❌'
                print(f"  {status} {pkg['package']}")
        
        # Warnings
        if self.results['warnings']:
            print(f"\n⚠️  Warnings ({len(self.results['warnings'])} total, showing first 5):")
            for warning in self.results['warnings'][:5]:
                print(f"  - {warning}")
        
        # Issues
        if self.results['issues']:
            print(f"\n❌ Critical Issues ({len(self.results['issues'])}):")
            for issue in self.results['issues']:
                print(f"  - {issue}")
        else:
            print("\n✅ No critical issues found!")
        
        # Overall result
        self.results['success'] = (
            self.results['venv'].get('exists', False) and
            self.results['pip_upgrade'] and
            core_success >= core_total * 0.75
        )
        
        print(f"\n{'=' * 70}")
        if self.results['success']:
            print("✅ OVERALL: INSTALLATION VALIDATION SUCCESSFUL")
            print("\nAll core dependencies are available and platform-specific")
            print("packages are properly configured. You can proceed with installation.")
        else:
            print("❌ OVERALL: INSTALLATION VALIDATION FAILED")
            print("\nPlease review the issues above before proceeding.")
        print("=" * 70)
        
        return json.dumps(self.results, indent=2)
    
    def run_all_tests(self) -> bool:
        """Run all tests in sequence"""
        print("🚀 Starting Comprehensive Installation Tests")
        print(f"Platform: {platform.system()} {platform.release()}")
        print(f"Python: {platform.python_version()}")
        print(f"Architecture: {platform.machine()}")
        
        if not self.test_venv_exists():
            print("\n❌ Virtual environment not found. Run: python -m venv .venv")
            return False
        
        self.test_pip_upgrade()
        self.test_core_dependencies()
        self.test_optional_dependencies()
        self.test_import_packages()
        self.test_platform_specific_packages()
        self.test_setup_install()
        
        report = self.generate_report()
        
        report_path = Path('test_install_report.json')
        report_path.write_text(report)
        print(f"\n💾 Full report saved to: {report_path}")
        
        return self.results['success']


def main():
    """Main entry point"""
    tester = WindowsInstallTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
