#!/bin/bash

# FFprobe Installation Script
set -e

echo "Installing FFprobe..."

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "Error: This script should not be run as root"
    exit 1
fi

# Check if this is Ubuntu/Debian
if ! command -v apt-get &> /dev/null; then
    echo "Error: This script is designed for Ubuntu/Debian systems only"
    exit 1
fi

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install FFprobe (part of ffmpeg package)
echo "Installing FFprobe..."
sudo apt-get install -y ffmpeg

# Verify installation
if command -v ffprobe &> /dev/null; then
    echo "FFprobe installed successfully!"
    ffprobe -version | head -1
else
    echo "FFprobe installation failed!"
    exit 1
fi