#!/bin/bash

# Load bash profile or zshrc
source ~/.bashrc 2>/dev/null || source ~/.bash_profile 2>/dev/null || source ~/.zshrc 2>/dev/null

# Change to the directory where the script is located.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Check if we have a virtual environment in the current directory.
# If we don't, run the install script.
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    bash "install_server.sh"
fi

# Import .env variables
set -a 
source .env 
set +a

# Activate the virtual environment, then rn the Python script
if [ -d "venv" ]; then
    source venv/bin/activate && python server.py
elif [ -d ".venv" ]; then
    source .venv/bin/activate && uv run server.py
else
    exit 1
fi

# Deactivate the virtual environment
deactivate

exit 0