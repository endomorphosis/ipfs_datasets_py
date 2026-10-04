#!/bin/bash
# Fast pytest execution script with optimization features
# Usage: ./pytest-fast.sh [pytest options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Fast Pytest Execution ===${NC}"
echo ""

# Get current git commit hash for cache invalidation
CURRENT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "no-git")
CACHE_FILE=".pytest_cache/last_commit"

# Check if we should invalidate cache
if [ -f "$CACHE_FILE" ]; then
    LAST_COMMIT=$(cat "$CACHE_FILE")
    if [ "$LAST_COMMIT" != "$CURRENT_COMMIT" ]; then
        echo -e "${YELLOW}Commit changed: $LAST_COMMIT -> $CURRENT_COMMIT${NC}"
        echo -e "${YELLOW}Clearing pytest cache...${NC}"
        pytest --cache-clear > /dev/null 2>&1 || true
        echo "$CURRENT_COMMIT" > "$CACHE_FILE"
    else
        echo -e "${GREEN}Cache valid for commit: $CURRENT_COMMIT${NC}"
    fi
else
    mkdir -p .pytest_cache
    echo "$CURRENT_COMMIT" > "$CACHE_FILE"
    echo -e "${YELLOW}Initializing cache for commit: $CURRENT_COMMIT${NC}"
fi

echo ""
echo -e "${GREEN}Optimization features enabled:${NC}"
echo "  ✓ Test randomization (pytest-randomly)"
echo "  ✓ Failed-first execution (--ff)"
echo "  ✓ Parallel execution (pytest-xdist)"
echo "  ✓ Commit-hash based caching"
echo ""

# Determine number of CPUs for parallel execution
if command -v nproc &> /dev/null; then
    NCPUS=$(nproc)
elif command -v sysctl &> /dev/null; then
    NCPUS=$(sysctl -n hw.ncpu)
else
    NCPUS=4
fi

# Use 75% of CPUs for parallel execution
WORKERS=$((NCPUS * 3 / 4))
if [ $WORKERS -lt 2 ]; then
    WORKERS=2
fi

echo -e "${GREEN}Running with $WORKERS parallel workers${NC}"
echo ""

# Default pytest options for fast execution
DEFAULT_OPTS=(
    "-n" "$WORKERS"           # Parallel execution
    "--ff"                    # Failed first
    "--tb=short"              # Short traceback
    "--disable-warnings"      # Reduce noise
    "-v"                      # Verbose
)

# Run pytest with optimizations
if [ $# -eq 0 ]; then
    # No arguments, use defaults
    pytest "${DEFAULT_OPTS[@]}"
else
    # Pass through arguments
    pytest "${DEFAULT_OPTS[@]}" "$@"
fi

EXIT_CODE=$?

# Save commit hash on successful run
if [ $EXIT_CODE -eq 0 ]; then
    echo "$CURRENT_COMMIT" > "$CACHE_FILE"
fi

exit $EXIT_CODE
