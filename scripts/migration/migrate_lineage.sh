#!/bin/bash
#
# Quick migration script for knowledge_graphs lineage imports
#
# This script uses sed to update import statements from the legacy
# cross_document_lineage modules to the new lineage package.
#
# Usage:
#     ./migrate_lineage.sh [options] <path>
#
# Options:
#     --dry-run     Show what would be changed without modifying files
#     --no-backup   Don't create .backup files (default: create backups)
#     --help        Show this help message
#
# Examples:
#     # Preview changes
#     ./migrate_lineage.sh --dry-run myfile.py
#     
#     # Migrate with backups
#     ./migrate_lineage.sh src/
#     
#     # Migrate without backups
#     ./migrate_lineage.sh --no-backup myfile.py
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DRY_RUN=false
CREATE_BACKUP=true
VERBOSE=false

# Usage message
usage() {
    cat << EOF
Usage: $0 [options] <path>

Quick migration script for knowledge_graphs lineage imports.

Options:
    --dry-run       Show what would be changed without modifying files
    --no-backup     Don't create .backup files
    --verbose       Show detailed information
    --help          Show this help message

Examples:
    # Preview changes
    $0 --dry-run myfile.py
    
    # Migrate directory with backups
    $0 src/
    
    # Migrate without backups
    $0 --no-backup myfile.py

EOF
}

# Parse arguments
PATH_TO_MIGRATE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-backup)
            CREATE_BACKUP=false
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            if [[ -z "$PATH_TO_MIGRATE" ]]; then
                PATH_TO_MIGRATE="$1"
            else
                echo -e "${RED}Error: Unexpected argument: $1${NC}"
                usage
                exit 1
            fi
            shift
            ;;
    esac
done

# Check if path provided
if [[ -z "$PATH_TO_MIGRATE" ]]; then
    echo -e "${RED}Error: No path provided${NC}"
    usage
    exit 1
fi

# Check if path exists
if [[ ! -e "$PATH_TO_MIGRATE" ]]; then
    echo -e "${RED}Error: Path not found: $PATH_TO_MIGRATE${NC}"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Lineage Import Migration Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if $DRY_RUN; then
    echo -e "${YELLOW}DRY RUN MODE - No files will be modified${NC}"
    echo ""
fi

# Find Python files
echo "Scanning for Python files..."
if [[ -f "$PATH_TO_MIGRATE" ]]; then
    if [[ "$PATH_TO_MIGRATE" == *.py ]]; then
        FILES=("$PATH_TO_MIGRATE")
    else
        echo -e "${RED}Error: File is not a Python file: $PATH_TO_MIGRATE${NC}"
        exit 1
    fi
else
    mapfile -t FILES < <(find "$PATH_TO_MIGRATE" -name "*.py" \
        ! -path "*/.*" \
        ! -path "*/__pycache__/*" \
        ! -path "*/node_modules/*" \
        ! -path "*/.venv/*" \
        ! -path "*/venv/*")
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo -e "${YELLOW}No Python files found${NC}"
    exit 0
fi

echo "Found ${#FILES[@]} Python file(s)"
echo ""

# Migration patterns
declare -a PATTERNS=(
    # Pattern 1: from ...cross_document_lineage import
    's/from \(.*\)cross_document_lineage import/from \1lineage import/g'
    # Pattern 2: from ...cross_document_lineage_enhanced import
    's/from \(.*\)cross_document_lineage_enhanced import/from \1lineage import/g'
    # Pattern 3: import ...cross_document_lineage (as module)
    's/import \(.*\)cross_document_lineage\b/import \1lineage/g'
    # Pattern 4: import ...cross_document_lineage_enhanced (as module)
    's/import \(.*\)cross_document_lineage_enhanced\b/import \1lineage/g'
)

# Statistics
FILES_MODIFIED=0
LINES_CHANGED=0

# Process each file
for file in "${FILES[@]}"; do
    # Check if file contains old imports
    if ! grep -qE '(cross_document_lineage|cross_document_lineage_enhanced)' "$file" 2>/dev/null; then
        if $VERBOSE; then
            echo "  Skipping (no old imports): $file"
        fi
        continue
    fi
    
    if $DRY_RUN; then
        echo -e "${YELLOW}Would modify: $file${NC}"
        
        # Show what would change
        temp_file=$(mktemp)
        cp "$file" "$temp_file"
        for pattern in "${PATTERNS[@]}"; do
            sed -i.tmp "$pattern" "$temp_file" 2>/dev/null || true
        done
        
        # Show diff
        if ! diff -u "$file" "$temp_file" | head -50; then
            LINES_CHANGED=$((LINES_CHANGED + $(diff -u "$file" "$temp_file" | grep -c '^[\+\-][^+\-]' || echo 0) / 2))
        fi
        
        rm -f "$temp_file" "$temp_file.tmp"
        FILES_MODIFIED=$((FILES_MODIFIED + 1))
        echo ""
    else
        # Create backup if requested
        if $CREATE_BACKUP; then
            cp "$file" "${file}.backup"
            if $VERBOSE; then
                echo "  Created backup: ${file}.backup"
            fi
        fi
        
        # Count lines before
        lines_before=$(wc -l < "$file")
        
        # Apply all patterns
        for pattern in "${PATTERNS[@]}"; do
            sed -i.tmp "$pattern" "$file" 2>/dev/null || true
            rm -f "${file}.tmp"
        done
        
        # Count changes (simple check)
        if grep -qE '(cross_document_lineage|cross_document_lineage_enhanced)' "$file" 2>/dev/null; then
            if $VERBOSE; then
                echo -e "${YELLOW}  Warning: Old imports still found in: $file${NC}"
            fi
        else
            echo -e "${GREEN}✓ Modified: $file${NC}"
            FILES_MODIFIED=$((FILES_MODIFIED + 1))
            # Rough estimate of lines changed
            LINES_CHANGED=$((LINES_CHANGED + 1))
        fi
    fi
done

# Print summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Migration Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Files scanned:   ${#FILES[@]}"
if $DRY_RUN; then
    echo "Files to modify: $FILES_MODIFIED"
    echo "Lines to change: $LINES_CHANGED (estimated)"
else
    echo "Files modified:  $FILES_MODIFIED"
    echo "Changes made:    $LINES_CHANGED (estimated)"
    
    if $CREATE_BACKUP && [[ $FILES_MODIFIED -gt 0 ]]; then
        echo ""
        echo -e "${GREEN}Backup files created (*.backup)${NC}"
        echo "To rollback, run:"
        echo "  for f in $PATH_TO_MIGRATE/**/*.py.backup; do mv \"\$f\" \"\${f%.backup}\"; done"
    fi
fi
echo -e "${BLUE}========================================${NC}"
echo ""

if $DRY_RUN; then
    echo -e "${YELLOW}DRY RUN COMPLETE - Run without --dry-run to apply changes${NC}"
else
    echo -e "${GREEN}MIGRATION COMPLETE${NC}"
fi

exit 0
