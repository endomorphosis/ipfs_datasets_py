#!/bin/bash
# Rate-limited wrapper for GitHub CLI (gh) commands
#
# This script wraps gh CLI commands with intelligent rate limiting to prevent
# hitting GitHub API rate limits when running multiple workflows.
#
# Usage:
#   ./gh_rate_limited.sh pr list --limit 10
#   ./gh_rate_limited.sh issue view 123
#   ./gh_rate_limited.sh api /user
#
# Features:
# - Adds configurable delays between calls
# - Tracks recent API calls to prevent bursts
# - Caches certain read-only operations
# - Provides backoff on rate limit errors

set -e

# Configuration
RATE_LIMIT_DELAY="${GH_RATE_LIMIT_DELAY:-2}"  # Seconds between calls
CACHE_DIR="${GH_CACHE_DIR:-${HOME}/.gh_cache}"
CACHE_TTL="${GH_CACHE_TTL:-300}"  # Cache TTL in seconds (5 minutes)
ENABLE_CACHE="${GH_ENABLE_CACHE:-true}"
DEBUG="${GH_DEBUG:-false}"

# Rate limiting state file
RATE_LIMIT_FILE="/tmp/gh_rate_limit_state"

# Ensure cache directory exists
if [ "$ENABLE_CACHE" = "true" ]; then
    mkdir -p "$CACHE_DIR"
fi

# Function to log debug messages
debug_log() {
    if [ "$DEBUG" = "true" ]; then
        echo "[DEBUG] $*" >&2
    fi
}

# Function to check if command is cacheable
is_cacheable() {
    local cmd="$1"
    
    # Only cache read-only operations
    case "$cmd" in
        pr\ view|pr\ list|issue\ view|issue\ list|api\ /*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Function to generate cache key
get_cache_key() {
    echo "$@" | md5sum | cut -d' ' -f1
}

# Function to check cache
check_cache() {
    local cache_key="$1"
    local cache_file="$CACHE_DIR/$cache_key"
    
    if [ ! -f "$cache_file" ]; then
        debug_log "Cache miss for key: $cache_key"
        return 1
    fi
    
    # Check if cache is expired
    local cache_age=$(($(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || stat -f %m "$cache_file" 2>/dev/null || echo 0)))
    
    if [ "$cache_age" -gt "$CACHE_TTL" ]; then
        debug_log "Cache expired for key: $cache_key (age: ${cache_age}s)"
        rm -f "$cache_file"
        return 1
    fi
    
    debug_log "Cache hit for key: $cache_key (age: ${cache_age}s)"
    cat "$cache_file"
    return 0
}

# Function to save to cache
save_cache() {
    local cache_key="$1"
    local cache_file="$CACHE_DIR/$cache_key"
    
    # Read from stdin and save
    cat > "$cache_file"
    
    # Also output to stdout for immediate use
    cat "$cache_file"
    
    debug_log "Saved to cache: $cache_key"
}

# Function to apply rate limiting
apply_rate_limit() {
    # Create rate limit file if it doesn't exist
    touch "$RATE_LIMIT_FILE"
    
    # Get last call time
    if [ -f "$RATE_LIMIT_FILE" ]; then
        LAST_CALL=$(cat "$RATE_LIMIT_FILE" 2>/dev/null || echo 0)
    else
        LAST_CALL=0
    fi
    
    CURRENT_TIME=$(date +%s)
    TIME_SINCE_LAST=$((CURRENT_TIME - LAST_CALL))
    
    # If last call was recent, wait
    if [ "$TIME_SINCE_LAST" -lt "$RATE_LIMIT_DELAY" ]; then
        SLEEP_TIME=$((RATE_LIMIT_DELAY - TIME_SINCE_LAST))
        debug_log "Rate limiting: sleeping ${SLEEP_TIME}s (last call ${TIME_SINCE_LAST}s ago)"
        sleep "$SLEEP_TIME"
    fi
    
    # Update last call time
    echo "$CURRENT_TIME" > "$RATE_LIMIT_FILE"
}

# Function to execute gh command with retry on rate limit
execute_gh_command() {
    local max_retries=3
    local retry_delay=5
    local attempt=1
    
    while [ $attempt -le $max_retries ]; do
        debug_log "Executing: gh $* (attempt $attempt/$max_retries)"
        
        # Execute command and capture both stdout and stderr
        if output=$(gh "$@" 2>&1); then
            echo "$output"
            return 0
        else
            # Check if it's a rate limit error
            if echo "$output" | grep -qi "rate limit\|API rate limit"; then
                if [ $attempt -lt $max_retries ]; then
                    echo "⚠️  Rate limit detected, waiting ${retry_delay}s before retry (attempt $attempt/$max_retries)..." >&2
                    sleep $retry_delay
                    retry_delay=$((retry_delay * 2))  # Exponential backoff
                    attempt=$((attempt + 1))
                    continue
                else
                    echo "❌ Rate limit error after $max_retries attempts" >&2
                    echo "$output" >&2
                    return 1
                fi
            else
                # Not a rate limit error, return the error
                echo "$output" >&2
                return 1
            fi
        fi
    done
    
    return 1
}

# Main execution
main() {
    if [ $# -eq 0 ]; then
        echo "Usage: $0 <gh-command> [args...]" >&2
        echo "Example: $0 pr list --limit 10" >&2
        exit 1
    fi
    
    local command_string="$*"
    
    # Check if command is cacheable
    if [ "$ENABLE_CACHE" = "true" ] && is_cacheable "$command_string"; then
        local cache_key=$(get_cache_key "$command_string")
        
        # Try to get from cache
        if check_cache "$cache_key"; then
            debug_log "Returned cached result"
            exit 0
        fi
        
        # Not in cache, need to execute
        apply_rate_limit
        
        # Execute and cache result
        if result=$(execute_gh_command "$@"); then
            echo "$result" | save_cache "$cache_key"
            exit 0
        else
            exit 1
        fi
    else
        # Not cacheable, just execute with rate limiting
        apply_rate_limit
        execute_gh_command "$@"
        exit $?
    fi
}

# Run main function
main "$@"
