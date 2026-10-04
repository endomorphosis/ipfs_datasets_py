#!/bin/bash

# Start distributed GitHub cache daemon
# This service enables P2P cache sharing between GitHub Actions runners
# to reduce API rate limit usage

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Starting Distributed GitHub Cache${NC}"
echo "======================================"
echo ""

# Load environment if exists
if [ -f "$PROJECT_ROOT/.env.cache" ]; then
    echo "Loading configuration from .env.cache"
    source "$PROJECT_ROOT/.env.cache"
else
    echo -e "${YELLOW}⚠️  No .env.cache found, using defaults${NC}"
    echo "   Create one from: cp .env.cache.example .env.cache"
fi

# Set defaults
CACHE_LISTEN_PORT=${CACHE_LISTEN_PORT:-9000}
CACHE_DIR=${CACHE_DIR:-~/.github-cache}
CACHE_DIR="${CACHE_DIR/#\~/$HOME}"

# Check dependencies
echo ""
echo "📦 Checking dependencies..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python 3${NC}"

# Check pylibp2p
if python3 -c "import libp2p" 2>/dev/null; then
    echo -e "${GREEN}✅ pylibp2p${NC}"
    P2P_AVAILABLE=true
else
    echo -e "${YELLOW}⚠️  pylibp2p not available (P2P features disabled)${NC}"
    echo "   Install: pip install libp2p"
    P2P_AVAILABLE=false
fi

# Check multiformats
if python3 -c "from multiformats import CID" 2>/dev/null; then
    echo -e "${GREEN}✅ multiformats${NC}"
else
    echo -e "${YELLOW}⚠️  multiformats not available (using SHA256 fallback)${NC}"
    echo "   Install: pip install py-multiformats-cid"
fi

# Create cache directory
mkdir -p "$CACHE_DIR"
echo ""
echo "📁 Cache directory: $CACHE_DIR"

# Discover other runners on localhost
echo ""
echo "🔍 Discovering other GitHub Actions runners..."
RUNNER_PORTS=""

# Check for running github-autoscaler instances
if pgrep -f "github_autoscaler" > /dev/null; then
    echo -e "${GREEN}✅ Found github-autoscaler running${NC}"
fi

# Look for other cache instances
PEER_COUNT=0
BOOTSTRAP_PEERS=""

if [ -n "$CACHE_BOOTSTRAP_PEERS" ]; then
    BOOTSTRAP_PEERS="$CACHE_BOOTSTRAP_PEERS"
    PEER_COUNT=$(echo "$BOOTSTRAP_PEERS" | tr ',' '\n' | wc -l)
    echo "   Configured bootstrap peers: $PEER_COUNT"
fi

# Start the cache daemon
echo ""
echo "🌐 Starting cache daemon..."
echo "   Listen port: $CACHE_LISTEN_PORT"
echo "   Bootstrap peers: $PEER_COUNT"
echo "   P2P enabled: $P2P_AVAILABLE"
echo ""

# Run the Python daemon
cd "$PROJECT_ROOT"

python3 << EOF
import asyncio
import sys
import os
import signal

# Add project to path
sys.path.insert(0, "$PROJECT_ROOT")

from ipfs_accelerate_py.distributed_cache import initialize_cache
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('cache_daemon')

cache = None

async def main():
    global cache
    
    # Parse bootstrap peers
    bootstrap_peers = []
    peers_str = "$BOOTSTRAP_PEERS"
    if peers_str:
        bootstrap_peers = [p.strip() for p in peers_str.split(',') if p.strip()]
    
    # Initialize cache
    logger.info("Initializing distributed cache...")
    cache = await initialize_cache(
        listen_port=$CACHE_LISTEN_PORT,
        bootstrap_peers=bootstrap_peers
    )
    
    logger.info("✅ Cache daemon started successfully")
    logger.info(f"   Peer ID: {cache.peer_id}")
    logger.info(f"   Cache dir: $CACHE_DIR")
    logger.info(f"   Connected peers: {len(cache.connected_peers)}")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(10)
            
            # Periodic cleanup
            cache.clear_stale()
            
            # Log stats every minute
            stats = cache.get_stats()
            logger.info(f"Stats: {stats['local_hits']} hits, {stats['misses']} misses, "
                       f"{stats['api_calls_saved']} API calls saved, "
                       f"{len(cache.connected_peers)} peers")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await cache.stop()

def signal_handler(sig, frame):
    logger.info("Received signal, shutting down...")
    if cache:
        asyncio.create_task(cache.stop())
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Run
asyncio.run(main())
EOF

echo ""
echo -e "${GREEN}✅ Cache daemon stopped${NC}"
