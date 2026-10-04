#!/bin/bash

# Load bash profile or zshrc
source ~/.bashrc 2>/dev/null || source ~/.bash_profile 2>/dev/null || source ~/.zshrc 2>/dev/null

# Change to the directory where the script is located.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Import .env variables
set -a 
source .env 
set +a

# Activate the virtual environment, then rn the Python script
if [ -d ".venv" ]; then
    source .venv/bin/activate && python _run_tests.py
else
    exit 1
fi

# Deactivate the virtual environment
deactivate

exit 0