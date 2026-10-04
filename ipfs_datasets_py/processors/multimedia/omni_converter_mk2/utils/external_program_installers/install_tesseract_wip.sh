#!/bin/bash

# Tesseract OCR Installation Script
set -e

echo "Installing Tesseract OCR..."

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "Error: This script should not be run as root"
    exit 1
fi

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        sudo apt-get update
        sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
    elif command -v yum &> /dev/null; then
        # RHEL/CentOS/Fedora
        sudo yum install -y tesseract tesseract-langpack-eng
    elif command -v dnf &> /dev/null; then
        # Fedora (newer)
        sudo dnf install -y tesseract tesseract-langpack-eng
    elif command -v pacman &> /dev/null; then
        # Arch Linux
        sudo pacman -S --noconfirm tesseract tesseract-data-eng
    else
        echo "Unsupported Linux distribution"
        exit 1
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    if command -v brew &> /dev/null; then
        brew install tesseract
    else
        echo "Homebrew not found. Please install Homebrew first."
        exit 1
    fi
else
    echo "Unsupported operating system"
    exit 1
fi

# Verify installation
if command -v tesseract &> /dev/null; then
    echo "Tesseract installed successfully!"
    tesseract --version
else
    echo "Tesseract installation failed!"
    exit 1
fi