#!/bin/bash
# https://tesseract-ocr.github.io/tessdoc/Installation.html

# Echo a message indicating the start of the installation
echo "Installing optional dependencies..."
echo "WARNING: This script will use sudo to install packages."
echo ""

read -p "Do you want to install Tesseract OCR and its dependencies? (y/n): " install_choice
if [[ "$install_choice" != "y" && "$install_choice" != "Y" ]]; then
    echo "Installation aborted by user."
    exit 0
fi

# Update package lists
echo "Updating package lists..."
sudo apt-get update

# Install Tesseract OCR and language data
echo "Installing Tesseract OCR and English language data..."
sudo apt-get install -y tesseract-ocr
sudo apt-get install -y tesseract-ocr-eng

echo "Installing 7-Zip..."
sudo apt-get install -y p7zip-full

echo "Installing LibreOffice..."
sudo apt-get install -y libreoffice

echo "Installing poppler-utils..." # TODO For pdf???
sudo apt-get install -y poppler-utils



# Optional: Install additional language packs if needed
# Uncomment and modify as necessary
# echo "Installing additional language packs..."
# sudo apt-get install -y tesseract-ocr-fra  # French
# sudo apt-get install -y tesseract-ocr-deu  # German
# sudo apt-get install -y tesseract-ocr-spa  # Spanish

# Verify installation
echo "Verifying Tesseract installation..."
tesseract --version

echo "Tesseract OCR installation complete!"


