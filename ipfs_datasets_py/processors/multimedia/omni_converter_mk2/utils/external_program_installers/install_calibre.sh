#!/bin/bash
# From: https://calibre-ebook.com/download_linux
# libxcb-cursor-dev from https://stackoverflow.com/questions/77725761/from-6-5-0-xcb-cursor0-or-libxcb-cursor0-is-needed-to-load-the-qt-xcb-platform

set -e

echo "Installing calibre..."

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "Error: This script should not be run as root"
    exit 1
fi

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install required library
echo "Installing libxcb-cursor-dev..."
sudo apt-get install -y libxcb-cursor-dev

# Install calibre
echo "Downloading and installing calibre..."
wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin

echo "Calibre installation completed successfully!"