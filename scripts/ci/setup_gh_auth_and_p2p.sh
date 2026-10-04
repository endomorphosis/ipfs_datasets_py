#!/bin/bash
# GitHub API Authentication and P2P Cache Setup
# This script ensures GitHub CLI authentication and initializes P2P caching
# to dramatically reduce API calls across self-hosted runners.
#
# Usage: source scripts/ci/setup_gh_auth_and_p2p.sh
# Environment variables required:
#   - GH_TOKEN or GITHUB_TOKEN: GitHub authentication token
#   - GITHUB_REPOSITORY: Repository name (owner/repo)

set -euo pipefail

echo "::group::🔐 GitHub CLI Authentication"

# Ensure GH_TOKEN is set
if [ -z "${GH_TOKEN:-}" ] && [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "::error::❌ No GitHub token found. Set GH_TOKEN or GITHUB_TOKEN."
    exit 1
fi

# Use GH_TOKEN or fall back to GITHUB_TOKEN
export GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$GH_TOKEN}"

# Install GitHub CLI if not present
if ! command -v gh >/dev/null 2>&1; then
    echo "::notice::Installing GitHub CLI..."
    type -p curl >/dev/null || (sudo apt update && sudo apt install curl -y)
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
        sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
    sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
        sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update > /dev/null 2>&1
    sudo apt install gh -y
fi

echo "✓ GitHub CLI version: $(gh --version | head -1)"

# Authenticate gh CLI
echo "$GH_TOKEN" | gh auth login --with-token 2>&1 > /dev/null

# Verify authentication
if gh auth status 2>&1; then
    echo "::notice::✅ GitHub CLI authenticated successfully"
else
    echo "::error::❌ GitHub CLI authentication failed"
    exit 1
fi

# Check API rate limit
RATE_LIMIT=$(gh api rate_limit --jq '.resources.core.remaining' 2>/dev/null || echo "0")
RATE_LIMIT_TOTAL=$(gh api rate_limit --jq '.resources.core.limit' 2>/dev/null || echo "5000")
RATE_LIMIT_RESET=$(gh api rate_limit --jq '.resources.core.reset' 2>/dev/null || echo "0")

echo "::notice::📊 GitHub API Rate Limit: $RATE_LIMIT / $RATE_LIMIT_TOTAL remaining"

if [ "$RATE_LIMIT" -lt 100 ]; then
    RESET_TIME=$(date -d "@$RATE_LIMIT_RESET" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "unknown")
    echo "::warning::⚠️ Low API rate limit ($RATE_LIMIT remaining). Resets at: $RESET_TIME"
    echo "::notice::P2P cache will help reduce API calls significantly!"
fi

echo "::endgroup::"

# Initialize P2P Cache if enabled
if [ "${ENABLE_P2P_CACHE:-true}" = "true" ]; then
    echo "::group::📡 P2P Cache Initialization"
    
    # Set environment variables for P2P cache
    export ENABLE_P2P_CACHE=true
    export GITHUB_CACHE_SIZE="${GITHUB_CACHE_SIZE:-5000}"
    export P2P_LISTEN_PORT="${P2P_LISTEN_PORT:-9000}"
    export ENABLE_PEER_DISCOVERY="${ENABLE_PEER_DISCOVERY:-true}"
    export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
    
    # Create cache directory
    CACHE_DIR="${HOME}/.cache/github-api-p2p"
    mkdir -p "$CACHE_DIR"
    export P2P_CACHE_DIR="$CACHE_DIR"
    
    echo "::notice::✅ P2P cache directory: $CACHE_DIR"
    echo "::notice::📡 Peer discovery enabled for ${GITHUB_REPOSITORY}"
    
    # Test P2P cache functionality (if Python script exists)
    if [ -f "scripts/ci/init_p2p_cache.py" ]; then
        if python3 scripts/ci/init_p2p_cache.py; then
            echo "::notice::✅ P2P cache initialized successfully"
        else
            echo "::warning::⚠️ P2P cache initialization had issues, continuing with standard cache"
        fi
    else
        echo "::notice::P2P cache enabled (initialization script not found, will use defaults)"
    fi
    
    echo "::endgroup::"
else
    echo "::notice::P2P cache disabled (set ENABLE_P2P_CACHE=true to enable)"
fi

# Export configuration summary
cat > /tmp/gh-cache-config.env << EOF
# GitHub API and P2P Cache Configuration
GH_TOKEN_SET=true
GITHUB_TOKEN_SET=true
API_RATE_LIMIT=$RATE_LIMIT
API_RATE_LIMIT_TOTAL=$RATE_LIMIT_TOTAL
ENABLE_P2P_CACHE=${ENABLE_P2P_CACHE:-true}
P2P_CACHE_DIR=${P2P_CACHE_DIR:-}
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-}
EOF

echo "::notice::✅ GitHub authentication and cache setup complete"
echo "::notice::Configuration saved to /tmp/gh-cache-config.env"
