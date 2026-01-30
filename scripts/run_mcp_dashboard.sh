#!/usr/bin/env bash
set -euo pipefail

# Defaults
HOST=${MCP_DASHBOARD_HOST:-127.0.0.1}
PORT=${MCP_DASHBOARD_PORT:-8899}
LOG=${LOG:-mcp_dashboard.out}
BLOCKING=${MCP_DASHBOARD_BLOCKING:-0}

# Change to project directory
cd "$(dirname "$0")/.." || exit 1

# Function to check if a Python package is installed
check_package() {
    python -c "import $1" 2>/dev/null
}

# Function to install packages safely
install_packages() {
    local packages=("$@")
    echo "Installing packages: ${packages[*]}"
    pip install --upgrade --no-cache-dir "${packages[@]}"
}

# Function to check and install missing dependencies
check_and_install_dependencies() {
    local missing_packages=()
    
    # Core web framework dependencies
    if ! check_package flask; then missing_packages+=("flask"); fi
    if ! check_package dash; then missing_packages+=("dash"); fi
    if ! check_package dash_bootstrap_components; then missing_packages+=("dash-bootstrap-components"); fi
    if ! check_package plotly; then missing_packages+=("plotly"); fi
    
    # Core functionality dependencies
    if ! check_package fastapi; then missing_packages+=("fastapi[all]"); fi
    if ! check_package pydantic; then missing_packages+=("pydantic"); fi
    if ! check_package tiktoken; then missing_packages+=("tiktoken"); fi
    if ! check_package nltk; then missing_packages+=("nltk"); fi
    if ! check_package cv2; then missing_packages+=("opencv-python"); fi
    if ! check_package cachetools; then missing_packages+=("cachetools"); fi
    
    # PDF processing dependencies
    if ! check_package fitz; then missing_packages+=("PyMuPDF"); fi
    if ! check_package pdfplumber; then missing_packages+=("pdfplumber"); fi
    
    # Web scraping dependencies  
    if ! check_package newspaper; then missing_packages+=("newspaper3k"); fi
    if ! check_package readability; then missing_packages+=("readability"); fi
    
    # AI/ML dependencies
    if ! check_package openai; then missing_packages+=("openai"); fi
    if ! check_package torch; then missing_packages+=("torch"); fi
    
    # Install missing packages in batches
    if [ ${#missing_packages[@]} -gt 0 ]; then
        echo "Missing dependencies detected: ${missing_packages[*]}"
        install_packages "${missing_packages[@]}"
    else
        echo "All core dependencies are present"
    fi
}

# Function to download NLTK data
setup_nltk_data() {
    if check_package nltk; then
        echo "Setting up NLTK data..."
        python -c "
import nltk
import os
try:
    nltk.download('punkt', quiet=True)
    nltk.download('averaged_perceptron_tagger', quiet=True) 
    nltk.download('maxent_ne_chunker', quiet=True)
    nltk.download('words', quiet=True)
    nltk.download('stopwords', quiet=True)
    print('NLTK data setup complete')
except Exception as e:
    print(f'NLTK data setup failed: {e}')
" 2>/dev/null || echo "NLTK data setup skipped"
    fi
}

# Activate venv if present, otherwise create it
if [ -d ".venv" ]; then
  echo "Activating existing virtual environment..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Creating virtual environment..."
  python3 -m venv .venv
  source .venv/bin/activate
  
  echo "Installing core project..."
  pip install --upgrade pip
  pip install -e . 2>/dev/null || pip install -r requirements.txt
fi

# Pre-launch dependency check and installation
echo "Running comprehensive dependency check..."
python scripts/utilities/dependency_checker.py --install-optional

# Additional quick check for critical packages
check_and_install_dependencies

# Setup additional data files
setup_nltk_data

# Export environment variables
export MCP_DASHBOARD_HOST="${HOST}"
export MCP_DASHBOARD_PORT="${PORT}"
export MCP_DASHBOARD_BLOCKING="${BLOCKING}"

echo "Pre-launch checks complete. Starting MCP Dashboard on ${HOST}:${PORT}..."
python -m ipfs_datasets_py.mcp_dashboard
