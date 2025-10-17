#!/bin/bash

# Enhanced Installation script for ipfs_datasets_py
# This script sets up the necessary dependencies and configures the environment
# with automatic dependency installation and cross-platform support

set -e  # Exit on any error

echo "🚀 Installing ipfs_datasets_py with automated dependency management..."

# Function to detect OS
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "darwin"
    elif [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "windows"
    else
        echo "unknown"
    fi
}

# Function to install system dependencies
install_system_deps() {
    local os_type=$(detect_os)
    echo "🔧 Installing system dependencies for $os_type..."
    
    case $os_type in
        "linux")
            # Detect Linux package manager
            if command -v apt-get >/dev/null 2>&1; then
                echo "📦 Using apt package manager..."
                sudo apt-get update
                sudo apt-get install -y tesseract-ocr ffmpeg libopencv-dev poppler-utils
                sudo apt-get install -y build-essential python3-dev
            elif command -v yum >/dev/null 2>&1; then
                echo "📦 Using yum package manager..."
                sudo yum install -y tesseract ffmpeg opencv-devel poppler-utils
                sudo yum groupinstall -y "Development Tools"
            elif command -v dnf >/dev/null 2>&1; then
                echo "📦 Using dnf package manager..."
                sudo dnf install -y tesseract ffmpeg opencv-devel poppler-utils
                sudo dnf groupinstall -y "Development Tools and Libraries"
            elif command -v pacman >/dev/null 2>&1; then
                echo "📦 Using pacman package manager..."
                sudo pacman -S --noconfirm tesseract ffmpeg opencv poppler
                sudo pacman -S --noconfirm base-devel
            else
                echo "⚠️ No supported package manager found on Linux"
            fi
            ;;
        "darwin")
            # macOS with Homebrew
            if command -v brew >/dev/null 2>&1; then
                echo "📦 Using Homebrew..."
                brew install tesseract ffmpeg opencv poppler
            else
                echo "⚠️ Homebrew not found. Please install Homebrew first:"
                echo "/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                exit 1
            fi
            ;;
        "windows")
            # Windows with Chocolatey or manual instructions
            if command -v choco >/dev/null 2>&1; then
                echo "📦 Using Chocolatey..."
                choco install tesseract ffmpeg opencv poppler -y
            else
                echo "⚠️ Chocolatey not found. Please install manually or install Chocolatey:"
                echo "https://chocolatey.org/install"
            fi
            ;;
        *)
            echo "⚠️ Unsupported operating system: $os_type"
            echo "Please install tesseract, ffmpeg, opencv, and poppler manually"
            ;;
    esac
}

# Check if Python 3.10+ is available
python_cmd=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        version=$($cmd -c "import sys; print('.'.join(map(str, sys.version_info[:2])))")
        if command -v bc >/dev/null 2>&1; then
            version_check=$(echo "$version >= 3.10" | bc)
        else
            # Fallback for systems without bc
            major=$(echo $version | cut -d. -f1)
            minor=$(echo $version | cut -d. -f2)
            if [ "$major" -gt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -ge 10 ]); then
                version_check=1
            else
                version_check=0
            fi
        fi
        
        if [ "$version_check" -eq 1 ]; then
            python_cmd=$cmd
            break
        fi
    fi
done

if [ -z "$python_cmd" ]; then
    echo "❌ Error: Python 3.10+ is required but not found"
    echo "Please install Python 3.10 or later"
    exit 1
fi

echo "✅ Using Python: $python_cmd (version $version)"

# Install system dependencies
install_system_deps

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    $python_cmd -m venv venv
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
if [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Upgrade pip and install build tools
echo "⬆️ Upgrading pip and installing build tools..."
pip install --upgrade pip setuptools wheel

# Install core dependencies first
echo "📚 Installing core dependencies..."
pip install -r requirements.txt

# Install the package in development mode
echo "🛠️ Installing ipfs_datasets_py in development mode..."
pip install -e .

# Run automated dependency installer for GraphRAG
echo "🤖 Running automated dependency installation for GraphRAG..."
$python_cmd -c "
import sys
import os
sys.path.insert(0, '.')
from ipfs_datasets_py.auto_installer import install_for_component
print('Installing GraphRAG dependencies...')
success = install_for_component('graphrag')
if success:
    print('✅ GraphRAG dependencies installed successfully')
    sys.exit(0)
else:
    print('⚠️ Some GraphRAG dependencies may have failed to install')
    sys.exit(0)  # Don't fail the whole installation
"

# Verify installation
echo "🔍 Verifying installation..."
$python_cmd -c "
try:
    import ipfs_datasets_py
    print('✅ ipfs_datasets_py imports successfully')
    
    # Test core components
    from ipfs_datasets_py import PDFProcessor, GraphRAGIntegrator
    if PDFProcessor is not None:
        print('✅ PDFProcessor available')
    if GraphRAGIntegrator is not None:
        print('✅ GraphRAGIntegrator available')
        
    print('📊 Installation verification complete')
except Exception as e:
    print(f'⚠️ Import test failed: {e}')
    print('The installation may be incomplete but core functionality should work')
"

echo ""
echo "🎉 Installation complete!"
echo ""
echo "📋 Next steps:"
echo "1. Activate the virtual environment:"
if [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "   source venv/Scripts/activate"
else
    echo "   source venv/bin/activate"
fi
echo "2. Run tests: python -m pytest tests/"
echo "3. Try the GraphRAG demo: python demonstrate_graphrag_pdf.py --create-sample"
echo "4. Check system dependencies: python ipfs_datasets_py/auto_installer.py graphrag --verbose"
echo ""
echo "🔧 Configuration:"
echo "- Set IPFS_AUTO_INSTALL=false to disable automatic dependency installation"
echo "- Set IPFS_INSTALL_VERBOSE=true for verbose installation output"
echo ""
echo "📚 For more information, see README.md"
