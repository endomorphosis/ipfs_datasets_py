# IPFS Datasets Auto-Install Configuration
# This enables automatic dependency installation

import os

# Enable auto-installation of dependencies
os.environ.setdefault('IPFS_DATASETS_AUTO_INSTALL', 'true')
os.environ.setdefault('IPFS_INSTALL_VERBOSE', 'false')  # Set to 'true' for verbose output

print("✅ Auto-installation enabled for IPFS Datasets")
