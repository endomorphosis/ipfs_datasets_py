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
from pathlib import Path

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