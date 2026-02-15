#!/bin/bash

# FFmpeg Installation Script
set -e

echo "Installing FFmpeg..."

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "Error: This script should not be run as root"
    exit 1
fi

# Detect OS and install FFmpeg
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        echo "Updating package list..."
        sudo apt-get update
        echo "Installing FFmpeg..."
        sudo apt-get install -y ffmpeg
    elif command -v yum &> /dev/null; then
        # RHEL/CentOS/Fedora (older)
        sudo yum install -y epel-release
        sudo yum install -y ffmpeg ffmpeg-devel
    elif command -v dnf &> /dev/null; then
        # Fedora (newer)
        sudo dnf install -y ffmpeg ffmpeg-devel
    elif command -v pacman &> /dev/null; then
        # Arch Linux
        sudo pacman -S --noconfirm ffmpeg
    else
        echo "Unsupported Linux distribution"
        exit 1
    fi
else
    echo "This script is designed for Linux systems only"
    exit 1
fi

# Verify installation
if command -v ffmpeg &> /dev/null; then
    echo "FFmpeg installed successfully!"
    ffmpeg -version | head -1
else
    echo "FFmpeg installation failed!"
    exit 1
fi