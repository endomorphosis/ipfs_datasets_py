#!/usr/bin/env python3
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
    
    print(f"\n📊 Installed {success_count}/{len(packages)} packages successfully")
    return success_count >= len(packages) * 0.8

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python install_deps.py <profile>")
        print("Profiles: minimal, cli, pdf, ml, web")
        sys.exit(1)
    
    profile = sys.argv[1]
    success = install_profile(profile)
    sys.exit(0 if success else 1)
