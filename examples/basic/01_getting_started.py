"""
Getting Started with IPFS Datasets Python

This example demonstrates the basic setup and verification of the ipfs_datasets_py
package. It's designed to help you confirm that the package is properly installed
and to introduce the core concepts.

Requirements:
    - ipfs_datasets_py package installed
    - No external services required for basic checks

Usage:
    python examples/01_getting_started.py
"""

import sys
from pathlib import Path


def check_installation():
    """Verify the package is properly installed."""
    print("\n" + "="*70)
    print("CHECKING INSTALLATION")
    print("="*70)
    
    try:
        import ipfs_datasets_py
        print(f"✅ ipfs_datasets_py version: {ipfs_datasets_py.__version__}")
        return True
    except ImportError as e:
        print(f"❌ Failed to import ipfs_datasets_py: {e}")
        return False


def check_core_modules():
    """Check availability of core modules."""
    print("\n" + "="*70)
    print("CHECKING CORE MODULES")
    print("="*70)
    
    modules = {
        "Processors": "ipfs_datasets_py.processors",
        "Embeddings": "ipfs_datasets_py.ml.embeddings",
        "Vector Stores": "ipfs_datasets_py.vector_stores",
        "Knowledge Graphs": "ipfs_datasets_py.knowledge_graphs",
        "File Converter": "ipfs_datasets_py.processors.file_converter",
        "Logic Module": "ipfs_datasets_py.logic",
    }
    
    results = {}
    for name, module_path in modules.items():
        try:
            __import__(module_path)
            print(f"✅ {name:20s} - Available")
            results[name] = True
        except ImportError as e:
            print(f"⚠️  {name:20s} - Not available: {e}")
            results[name] = False
    
    return results


def check_optional_dependencies():
    """Check optional dependencies for advanced features."""
    print("\n" + "="*70)
    print("CHECKING OPTIONAL DEPENDENCIES")
    print("="*70)
    
    dependencies = {
        "Transformers (for embeddings)": "transformers",
        "FAISS (for vector search)": "faiss",
        "Torch (for ML models)": "torch",
        "Qdrant Client": "qdrant_client",
        "DuckDB (for analytics)": "duckdb",
        "FFmpeg-python (for multimedia)": "ffmpeg",
        "yt-dlp (for video download)": "yt_dlp",
        "Pandas": "pandas",
        "NumPy": "numpy",
    }
    
    results = {}
    for name, module in dependencies.items():
        try:
            __import__(module)
            print(f"✅ {name:35s} - Available")
            results[name] = True
        except ImportError:
            print(f"⚠️  {name:35s} - Not installed (optional)")
            results[name] = False
    
    return results


def demo_basic_imports():
    """Demonstrate basic imports and usage."""
    print("\n" + "="*70)
    print("BASIC IMPORT DEMONSTRATION")
    print("="*70)
    
    try:
        # Import core routers
        from ipfs_datasets_py.router_deps import RouterDeps, get_default_router_deps
        print("✅ Successfully imported RouterDeps")
        
        # Import file detector
        try:
            from ipfs_datasets_py.file_detector import FileTypeDetector
            print("✅ Successfully imported FileTypeDetector")
        except ImportError:
            print("⚠️  FileTypeDetector not available (optional)")
        
        # Import processors
        try:
            from ipfs_datasets_py.processors.unified_processor import UnifiedProcessor
            print("✅ Successfully imported UnifiedProcessor")
        except ImportError as e:
            print(f"⚠️  UnifiedProcessor import error: {e}")
        
        # Import file converter
        try:
            from ipfs_datasets_py.processors.file_converter import FileConverter
            print("✅ Successfully imported FileConverter")
        except ImportError as e:
            print(f"⚠️  FileConverter import error: {e}")
            
        return True
        
    except Exception as e:
        print(f"❌ Error during basic imports: {e}")
        return False


def show_installation_tips():
    """Show tips for installing optional dependencies."""
    print("\n" + "="*70)
    print("INSTALLATION TIPS")
    print("="*70)
    
    print("\nTo install optional dependencies, use:")
    print("  pip install ipfs_datasets_py[all]        # Install everything")
    print("  pip install ipfs_datasets_py[ml]         # ML/embeddings features")
    print("  pip install ipfs_datasets_py[test]       # Testing dependencies")
    print("  pip install ipfs_datasets_py[legal]      # Legal dataset tools")
    print("  pip install ipfs_datasets_py[security]   # Security features")
    
    print("\nOr use the install script:")
    print("  python install.py --quick                # Core dependencies")
    print("  python install.py --profile ml           # ML profile")
    print("  python dependency_health_checker.py check # Verify installation")


def main():
    """Run all verification checks."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - GETTING STARTED")
    print("="*70)
    
    # Run checks
    installed = check_installation()
    if not installed:
        print("\n❌ Package not properly installed. Please install it first:")
        print("   pip install -e .")
        return
    
    core_modules = check_core_modules()
    optional_deps = check_optional_dependencies()
    basic_imports = demo_basic_imports()
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    core_available = sum(1 for v in core_modules.values() if v)
    optional_available = sum(1 for v in optional_deps.values() if v)
    
    print(f"\n✅ Core modules available: {core_available}/{len(core_modules)}")
    print(f"⚠️  Optional dependencies: {optional_available}/{len(optional_deps)}")
    
    if core_available == len(core_modules):
        print("\n🎉 All core modules are available! You're ready to go.")
    else:
        print("\n⚠️  Some core modules are missing. Please check your installation.")
    
    if optional_available < len(optional_deps):
        print("\n💡 Install optional dependencies for additional features.")
        show_installation_tips()
    
    # Next steps
    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    print("\n1. Try the embeddings example:")
    print("   python examples/02_embeddings_basic.py")
    print("\n2. Try file conversion:")
    print("   python examples/04_file_conversion.py")
    print("\n3. Explore the README:")
    print("   cat examples/README.md")


if __name__ == "__main__":
    main()
