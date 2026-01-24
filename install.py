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

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

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

def ensure_known_good_ipfs_kit_py() -> None:
    """Ensure ipfs_kit_py is installed from the known_good branch on Windows."""
    if not IS_WINDOWS:
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
        print(f"⚠️ Git not available; skipping known_good ipfs_kit_py install: {e}")
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
        print(f"⚠️ Failed to install known_good ipfs_kit_py: {e}")

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
        result = subprocess.run([sys.executable, 'quick_setup.py'], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Quick setup failed: {e}")
        return 1

def interactive_setup():
    """Run interactive dependency manager setup"""
    print("\n🎛️ Running Interactive Setup...")
    
    try:
        result = subprocess.run([sys.executable, 'dependency_manager.py', 'setup'], 
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
                sys.executable, 'dependency_manager.py', 'install', 
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
        result = subprocess.run([sys.executable, 'dependency_health_checker.py', 'check'], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return 1

def full_analysis():
    """Run comprehensive dependency analysis"""
    print("\n📊 Running Full Analysis...")
    
    try:
        result = subprocess.run([sys.executable, 'dependency_manager.py', 'analyze'], 
                              check=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        return 1

def test_installation():
    """Test CLI functionality after installation"""
    print("\n🧪 Testing CLI Functionality...")
    
    try:
        result = subprocess.run([sys.executable, 'comprehensive_cli_test.py'], 
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
    critical_deps = ['numpy', 'pandas', 'requests', 'pyyaml', 'tqdm']
    
    for dep in critical_deps:
        try:
            __import__(dep)
            print(f"✅ {dep:12s} - Available")
        except ImportError:
            print(f"❌ {dep:12s} - Missing")
    
    print("\nFor detailed status, run: python dependency_health_checker.py check")

def main():
    """Main CLI interface"""
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
    
    args = parser.parse_args()

    if IS_WINDOWS:
        ensure_known_good_ipfs_kit_py()
    
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
                sys.executable, 'dependency_manager.py', 'install',
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