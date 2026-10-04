#!/bin/bash

# Echo to indicate start of the program
echo "STARTING PROTOCOL CHECKS ..."

# Activate the virtual environment
source .venv/bin/activate

# Import .env variables
set -a 
source .env 
set +a

# Echo to indicate the start of the Python script
echo "*** BEGINNING CHECKS ***"

# Run the Python scripts
echo "Checking if all mime-type processors implement the Processor protocol..."
python core/content_extractor/processors/by_mime_type/processor_class_protocol.py
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "ERROR: Mime-Type Protocol check failed with exit code $exit_code"
else
    echo "✓ All mime-type  processors implement the protocol correctly"
fi

echo "Checking if all ability-type processors implement the Processor protocol..."
python core/content_extractor/processors/by_mime_type/processor_class_protocol.py
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "ERROR: Ability-Type Protocol check failed with exit code $exit_code"
else
    echo "✓ All ability-type processors implement the protocol correctly"
fi

echo "Checking if all fallback processors implement the Processor protocol..."
python core/content_extractor/processors/by_mime_type/processor_class_protocol.py
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "ERROR: Fallback Protocol check failed with exit code $exit_code"
else
    echo "✓ All fallback processors implement the protocol correctly"
fi


# Echo to indicate the end of the Python script
echo "*** ENDING PROTOCOL CHECKS ***"

# Deactivate the virtual environment
deactivate

# Echo to indicate program completion
echo "PROTOCOL CHECKS COMPLETE."
