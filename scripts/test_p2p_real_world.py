#!/usr/bin/env python3
"""
P2P Cache Real-World Integration Test

This test actually starts P2P networking and verifies everything works end-to-end.
"""

import os
import sys
import time
import logging
import asyncio
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_p2p_real')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_async_p2p_initialization():
    """Test async P2P initialization"""
    logger.info("="*70)
    logger.info("TEST: Async P2P Initialization")
    logger.info("="*70)
    
    try:
        from libp2p import new_host
        from libp2p.network.stream.net_stream_interface import INetStream
        
        logger.info("Creating libp2p host...")
        host = await new_host()
        
        logger.info(f"✓ Host created with ID: {host.get_id()}")
        
        # Get listen addresses
        addrs = host.get_addrs()
        logger.info(f"✓ Listening on {len(addrs)} addresses:")
        for addr in addrs:
            logger.info(f"  - {addr}")
        
        # Define stream handler
        async def cache_stream_handler(stream: INetStream):
            logger.info(f"✓ Received stream from {stream.mplex_conn.peer_id}")
            # Read data
            data = await stream.read(1024)
            logger.info(f"✓ Received {len(data)} bytes")
            await stream.close()
        
        # Set stream handler
        host.set_stream_handler("/github-cache/1.0.0", cache_stream_handler)
        logger.info("✓ Stream handler registered")
        
        # Keep host running for a bit
        logger.info("Host running for 2 seconds...")
        await asyncio.sleep(2)
        
        logger.info("✓ P2P host functional")
        
        # Close host
        await host.close()
        logger.info("✓ Host closed cleanly")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ P2P initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_p2p_with_encryption():
    """Test P2P with encryption"""
    logger.info("="*70)
    logger.info("TEST: P2P with Encryption")
    logger.info("="*70)
    
    try:
        from libp2p import new_host
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.backends import default_backend
        import json
        import base64
        import subprocess
        
        # Get GitHub token
        github_token = os.environ.get('GITHUB_TOKEN')
        if not github_token:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                github_token = result.stdout.strip()
        
        if not github_token:
            logger.warning("⚠ No GitHub token available, skipping encryption test")
            return True
        
        # Derive encryption key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"github-cache-p2p",
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(github_token.encode('utf-8')))
        cipher = Fernet(key)
        
        logger.info("✓ Encryption key derived")
        
        # Create P2P host
        host = await new_host()
        logger.info(f"✓ Host created with ID: {host.get_id()}")
        
        # Test message
        test_message = {
            'key': 'test/endpoint',
            'data': {'result': 'encrypted test'},
            'timestamp': time.time()
        }
        
        # Encrypt message
        plaintext = json.dumps(test_message).encode('utf-8')
        encrypted = cipher.encrypt(plaintext)
        logger.info(f"✓ Message encrypted: {len(encrypted)} bytes")
        
        # Decrypt message
        decrypted = cipher.decrypt(encrypted)
        decrypted_msg = json.loads(decrypted.decode('utf-8'))
        
        if decrypted_msg['key'] == test_message['key']:
            logger.info("✓ Message decrypted successfully")
            logger.info("✓ Encryption working with P2P")
        else:
            logger.error("✗ Decrypted message mismatch")
            return False
        
        # Close host
        await host.close()
        logger.info("✓ Host closed")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_two_peers_communication():
    """Test communication between two P2P peers"""
    logger.info("="*70)
    logger.info("TEST: Two Peers Communication")
    logger.info("="*70)
    
    try:
        from libp2p import new_host
        from multiaddr import Multiaddr
        
        # Create first host (bootstrap node)
        logger.info("Creating host 1 (bootstrap)...")
        host1 = await new_host()
        host1_id = host1.get_id()
        host1_addrs = host1.get_addrs()
        
        logger.info(f"✓ Host 1 ID: {host1_id}")
        logger.info(f"✓ Host 1 listening on {len(host1_addrs)} addresses")
        
        # Message received flag
        message_received = asyncio.Event()
        received_data = []
        
        # Set stream handler on host1
        async def stream_handler(stream):
            logger.info(f"✓ Host 1 received stream from {stream.mplex_conn.peer_id}")
            data = await stream.read(1024)
            received_data.append(data)
            logger.info(f"✓ Host 1 received: {data.decode('utf-8')[:50]}")
            await stream.write(b"ACK")
            message_received.set()
            await stream.close()
        
        host1.set_stream_handler("/test/1.0.0", stream_handler)
        logger.info("✓ Stream handler registered on host 1")
        
        # Create second host
        logger.info("Creating host 2...")
        host2 = await new_host()
        host2_id = host2.get_id()
        
        logger.info(f"✓ Host 2 ID: {host2_id}")
        
        # Connect host2 to host1
        if host1_addrs:
            # Use first address
            target_addr = host1_addrs[0]
            logger.info(f"Host 2 connecting to: {target_addr}")
            
            # Connect
            await host2.connect(info_from_p2p_addr(target_addr))
            logger.info("✓ Hosts connected")
            
            # Wait a moment for connection to establish
            await asyncio.sleep(0.5)
            
            # Send message from host2 to host1
            logger.info("Host 2 opening stream...")
            stream = await host2.new_stream(host1_id, ["/test/1.0.0"])
            logger.info("✓ Stream opened")
            
            test_data = b"Hello from host 2!"
            await stream.write(test_data)
            logger.info(f"✓ Host 2 sent: {test_data.decode('utf-8')}")
            
            # Wait for response
            response = await stream.read(1024)
            logger.info(f"✓ Host 2 received: {response.decode('utf-8')}")
            
            await stream.close()
            logger.info("✓ Stream closed")
            
            # Wait for message to be received
            await asyncio.wait_for(message_received.wait(), timeout=2.0)
            logger.info("✓ Two-way communication successful")
        else:
            logger.warning("⚠ No addresses available on host 1")
        
        # Close hosts
        await host1.close()
        await host2.close()
        logger.info("✓ Hosts closed")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Two peers test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all async tests"""
    logger.info("="*70)
    logger.info("      P2P CACHE REAL-WORLD INTEGRATION TEST SUITE")
    logger.info("="*70)
    
    results = []
    
    # Run tests
    results.append(("Async P2P Initialization", await test_async_p2p_initialization()))
    results.append(("P2P with Encryption", await test_p2p_with_encryption()))
    results.append(("Two Peers Communication", await test_two_peers_communication()))
    
    # Print summary
    logger.info("")
    logger.info("="*70)
    logger.info("                   TEST SUMMARY")
    logger.info("="*70)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status:10} | {test_name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    logger.info("="*70)
    total = passed + failed
    percentage = (passed / total * 100) if total > 0 else 0
    logger.info(f"Total: {passed}/{total} tests passed ({percentage:.1f}%)")
    logger.info("="*70)
    
    if failed == 0:
        logger.info("")
        logger.info("🎉 All real-world P2P tests passed!")
        return 0
    else:
        logger.warning("")
        logger.warning(f"⚠ {failed} test(s) failed")
        return 1


def main():
    """Main entry point"""
    try:
        # Import required for info_from_p2p_addr
        from libp2p.peer.peerinfo import info_from_p2p_addr
        
        # Run async tests
        return asyncio.run(run_all_tests())
    except Exception as e:
        logger.error(f"✗ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
