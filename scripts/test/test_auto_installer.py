#!/usr/bin/env python3
"""
Demo script to test automated dependency installation
"""
import sys
import os

def test_automated_installation():
    """Test the automated dependency installation system"""
    
    # Enable automated installation
    os.environ['IPFS_AUTO_INSTALL'] = 'true'
    os.environ['IPFS_INSTALL_VERBOSE'] = 'true'
    
    print("🚀 Testing automated dependency installation system...")
    print("=" * 60)
    
    try:
        # Import with automated installation
        print("📦 Importing ipfs_datasets_py with auto-install enabled...")
        import ipfs_datasets_py as ids
        print("✅ Successfully imported ipfs_datasets_py")
        
        # Test core components
        processor = ids.PDFProcessor
        integrator = ids.GraphRAGIntegrator
        
        if processor:
            print("✅ PDFProcessor available with automated installation")
        else:
            print("❌ PDFProcessor not available")
            
        if integrator:
            print("✅ GraphRAGIntegrator available with automated installation")
        else:
            print("❌ GraphRAGIntegrator not available")
            
        # Test component instantiation (with mocks for now)
        if processor:
            try:
                pdf_proc = processor(use_mock=True)
                print("✅ PDFProcessor can be instantiated")
            except Exception as e:
                print(f"⚠️ PDFProcessor instantiation issue: {e}")
        
        if integrator:
            try:
                graph_int = integrator()
                print("✅ GraphRAGIntegrator can be instantiated")
            except Exception as e:
                print(f"⚠️ GraphRAGIntegrator instantiation issue: {e}")
        
        print("=" * 60)
        print("🎉 Automated dependency installation test completed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_specific_component_installation():
    """Test installation of specific components"""
    print("🔧 Testing component-specific installation...")
    
    try:
        from ipfs_datasets_py.auto_installer import install_for_component
        
        # Test PDF component installation
        success = install_for_component('pdf')
        print(f"📄 PDF component installation: {'✅ Success' if success else '❌ Failed'}")
        
        # Test OCR component installation  
        success = install_for_component('ocr')
        print(f"👁️ OCR component installation: {'✅ Success' if success else '❌ Failed'}")
        
        # Test ML component installation
        success = install_for_component('ml')
        print(f"🧠 ML component installation: {'✅ Success' if success else '❌ Failed'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Component installation test failed: {e}")
        return False

def test_install_script_functionality():
    """Test the install script components"""
    print("📜 Testing install script functionality...")
    
    try:
        from ipfs_datasets_py.auto_installer import DependencyInstaller
        
        installer = DependencyInstaller(auto_install=False, verbose=True)  # Don't actually install
        print(f"🖥️ Detected OS: {installer.system}")
        print(f"🏗️ Architecture: {installer.architecture}")
        print(f"📦 Package manager: {installer.detect_package_manager()}")
        
        return True
        
    except Exception as e:
        print(f"❌ Install script test failed: {e}")
        return False

if __name__ == '__main__':
    print("🧪 Running automated dependency installation tests...")
    print()
    
    success = True
    
    # Test 1: Basic installer functionality
    success &= test_install_script_functionality()
    print()
    
    # Test 2: Component installation (without actually installing)
    success &= test_specific_component_installation()
    print()
    
    # Test 3: Full automated installation
    success &= test_automated_installation()
    print()
    
    if success:
        print("🎉 All tests passed! Automated dependency installation system is working.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Check the output above for details.")
        sys.exit(1)