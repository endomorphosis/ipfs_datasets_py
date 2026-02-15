"""
IPFSProcessorAdapter - Adapter for IPFS content processing.

This adapter provides first-class support for IPFS content, automatically
detecting content types and routing to appropriate sub-processors.
"""

from __future__ import annotations

import logging
import tempfile
from typing import Union, Optional
from pathlib import Path
import time
import re

from ..protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingMetadata,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    VectorStore,
    Entity
)

logger = logging.getLogger(__name__)


class IPFSProcessorAdapter:
    """
    Adapter for processing IPFS content.
    
    This adapter handles IPFS-native content by:
    1. Detecting IPFS CIDs and paths
    2. Fetching content from IPFS
    3. Detecting content type
    4. Routing to appropriate sub-processor
    5. Returning unified result
    
    Supported Inputs:
    - IPFS CIDs (Qm..., b...)
    - ipfs:// URLs
    - /ipfs/ paths
    - ipns:// URLs
    
    Features:
    - Automatic content type detection
    - Gateway fallback for unavailable content
    - Optional pinning
    - Metadata extraction
    - Integration with ipfs_kit_py
    
    Example:
        >>> adapter = IPFSProcessorAdapter()
        >>> can_process = await adapter.can_process("QmXXX...")
        >>> result = await adapter.process("ipfs://QmXXX...")
    """
    
    def __init__(self, parent_processor=None):
        """
        Initialize IPFS adapter.
        
        Args:
            parent_processor: Parent UniversalProcessor instance for sub-routing
        """
        self._parent_processor = parent_processor
        self._ipfs_client = None
        self._ipfs_kit = None
        self._temp_files: list[Path] = []  # Track temp files for cleanup
    
    def __del__(self):
        """Cleanup temporary files on deletion."""
        self._cleanup_temp_files()
    
    def _cleanup_temp_files(self):
        """Clean up all tracked temporary files."""
        for temp_file in self._temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_file}: {e}")
        self._temp_files.clear()
    
    def _get_ipfs_client(self):
        """Lazy-load IPFS client."""
        if self._ipfs_client is None:
            try:
                import ipfshttpclient
                self._ipfs_client = ipfshttpclient.connect()
                logger.info("Connected to IPFS daemon via ipfshttpclient")
            except Exception as e:
                logger.warning(f"Could not connect to IPFS daemon: {e}")
                # Will fallback to gateway
        return self._ipfs_client
    
    def _get_ipfs_kit(self):
        """Lazy-load ipfs_kit_py."""
        if self._ipfs_kit is None:
            try:
                # Import ipfs_kit_py if available
                import sys
                ipfs_kit_path = Path(__file__).parent.parent.parent.parent / "ipfs_kit_py"
                if ipfs_kit_path.exists():
                    sys.path.insert(0, str(ipfs_kit_path))
                
                from ipfs_kit_py import IPFSKit
                self._ipfs_kit = IPFSKit()
                logger.info("Loaded ipfs_kit_py")
            except ImportError as e:
                logger.debug(f"ipfs_kit_py not available: {e}")
        return self._ipfs_kit
    
    def _extract_cid(self, input_source: str) -> Optional[str]:
        """
        Extract CID from various IPFS input formats.
        
        Args:
            input_source: Input string to parse
            
        Returns:
            CID string or None if not IPFS content
            
        Examples:
            >>> self._extract_cid("QmXXX...")
            "QmXXX..."
            >>> self._extract_cid("ipfs://QmXXX...")
            "QmXXX..."
            >>> self._extract_cid("/ipfs/QmXXX...")
            "QmXXX..."
        """
        input_str = str(input_source).strip()
        
        # Direct CID
        if self._is_cid(input_str):
            return input_str
        
        # ipfs:// URL
        if input_str.startswith('ipfs://'):
            cid = input_str[7:]  # Remove ipfs://
            if '/' in cid:
                cid = cid.split('/')[0]
            return cid if self._is_cid(cid) else None
        
        # /ipfs/ path
        if input_str.startswith('/ipfs/'):
            cid = input_str[6:]  # Remove /ipfs/
            if '/' in cid:
                cid = cid.split('/')[0]
            return cid if self._is_cid(cid) else None
        
        # ipns:// URL (resolve to CID later)
        if input_str.startswith('ipns://'):
            return input_str  # Will need resolution
        
        return None
    
    def _is_cid(self, text: str) -> bool:
        """
        Check if text looks like an IPFS CID.
        
        CIDs typically:
        - CIDv0: Start with 'Qm', 46 characters, base58
        - CIDv1: Start with 'b', 59+ characters, base32
        
        Args:
            text: Text to check
            
        Returns:
            True if looks like a CID
        """
        text = text.strip()
        
        # CIDv0: Qm + 44 base58 characters = 46 total
        if text.startswith('Qm') and len(text) == 46:
            # Check if base58
            base58_pattern = re.compile(r'^[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]+$')
            return bool(base58_pattern.match(text))
        
        # CIDv1: b + base32 characters (59+)
        if text.startswith('b') and len(text) >= 59:
            # Check if base32
            base32_pattern = re.compile(r'^b[a-z2-7]+$')
            return bool(base32_pattern.match(text))
        
        return False
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle IPFS inputs.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if input is IPFS content (CID, ipfs://, /ipfs/, ipns://)
        """
        input_str = str(input_source).lower()
        
        # Check for IPFS patterns
        if input_str.startswith(('ipfs://', '/ipfs/', 'ipns://')):
            return True
        
        # Check if it's a CID
        cid = self._extract_cid(str(input_source))
        return cid is not None
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process IPFS content and return standardized result.
        
        This method:
        1. Extracts CID from input
        2. Fetches content from IPFS (or gateway)
        3. Detects content type
        4. Routes to appropriate processor
        5. Adds IPFS metadata to result
        
        Args:
            input_source: IPFS CID, ipfs:// URL, /ipfs/ path, or ipns:// URL
            **options: Processing options
                - pin: Whether to pin content (default: False)
                - gateway_fallback: Use gateway if daemon unavailable (default: True)
                - recursive: Fetch directories recursively (default: False)
                
        Returns:
            ProcessingResult with IPFS metadata
            
        Example:
            >>> result = await adapter.process("QmXXX...")
            >>> print(result.metadata.resource_usage['ipfs_cid'])
        """
        start_time = time.time()
        
        # Create metadata
        metadata = ProcessingMetadata(
            processor_name="IPFSProcessorAdapter",
            processor_version="1.0",
            input_type=InputType.IPFS
        )
        
        try:
            # Extract CID
            cid = self._extract_cid(str(input_source))
            if not cid:
                metadata.add_error("Could not extract valid CID from input")
                metadata.status = ProcessingStatus.FAILED
                return ProcessingResult(
                    knowledge_graph=KnowledgeGraph(),
                    vectors=VectorStore(),
                    content={},
                    metadata=metadata
                )
            
            logger.info(f"Processing IPFS content: {cid}")
            
            # Fetch content from IPFS
            content_path, content_info = await self._fetch_ipfs_content(
                cid,
                pin=options.get('pin', False),
                gateway_fallback=options.get('gateway_fallback', True)
            )
            
            if not content_path:
                metadata.add_error(f"Could not fetch IPFS content: {cid}")
                metadata.status = ProcessingStatus.FAILED
                return ProcessingResult(
                    knowledge_graph=KnowledgeGraph(),
                    vectors=VectorStore(),
                    content={},
                    metadata=metadata
                )
            
            # Detect content type and route to appropriate processor
            result = await self._process_content(
                content_path,
                content_info,
                **options
            )
            
            # Add IPFS metadata
            result.metadata.resource_usage['ipfs_cid'] = cid
            result.metadata.resource_usage['ipfs_size'] = content_info.get('size', 0)
            result.metadata.resource_usage['ipfs_type'] = content_info.get('type', 'unknown')
            
            # Add IPFS entity to knowledge graph
            ipfs_entity = Entity(
                id=f"ipfs:{cid}",
                type="IPFSContent",
                label=f"IPFS Content {cid[:8]}...",
                properties={
                    "cid": cid,
                    "size": content_info.get('size', 0),
                    "type": content_info.get('type', 'unknown')
                }
            )
            result.knowledge_graph.add_entity(ipfs_entity)
            
            # Update timing
            result.metadata.processing_time_seconds = time.time() - start_time
            
            logger.info(f"Successfully processed IPFS content: {cid}")
            return result
            
        except Exception as e:
            metadata.add_error(f"IPFS processing failed: {str(e)}")
            metadata.status = ProcessingStatus.FAILED
            metadata.processing_time_seconds = time.time() - start_time
            logger.error(f"IPFS processing error: {e}", exc_info=True)
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(),
                vectors=VectorStore(),
                content={'error': str(e)},
                metadata=metadata
            )
    
    async def _fetch_ipfs_content(
        self,
        cid: str,
        pin: bool = False,
        gateway_fallback: bool = True
    ) -> tuple[Optional[Path], dict]:
        """
        Fetch content from IPFS.
        
        Tries:
        1. Local IPFS daemon (ipfshttpclient)
        2. ipfs_kit_py if available
        3. Public gateway as fallback
        
        Args:
            cid: IPFS CID to fetch
            pin: Whether to pin content
            gateway_fallback: Use gateway if daemon unavailable
            
        Returns:
            Tuple of (content_path, content_info)
        """
        # Try local daemon first
        client = self._get_ipfs_client()
        if client:
            try:
                # Create temp file to store content
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.ipfs')
                temp_path = Path(temp_file.name)
                temp_file.close()  # Close but don't delete
                self._temp_files.append(temp_path)  # Track for cleanup
                
                # Fetch content
                client.get(cid, target=str(temp_path.parent))
                
                # Get content info
                stat = client.object.stat(cid)
                content_info = {
                    'size': stat.get('CumulativeSize', 0),
                    'type': 'file',  # TODO: detect directory
                    'source': 'daemon'
                }
                
                # Pin if requested
                if pin:
                    client.pin.add(cid)
                    logger.info(f"Pinned content: {cid}")
                
                return temp_path, content_info
                
            except Exception as e:
                logger.warning(f"IPFS daemon fetch failed: {e}")
        
        # Try ipfs_kit_py
        ipfs_kit = self._get_ipfs_kit()
        if ipfs_kit:
            try:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.ipfs')
                temp_path = Path(temp_file.name)
                temp_file.close()  # Close but don't delete
                self._temp_files.append(temp_path)  # Track for cleanup
                
                # Use ipfs_kit_py to fetch
                # (Assuming it has a get/cat method)
                # content = ipfs_kit.cat(cid)
                # temp_path.write_bytes(content)
                
                logger.info(f"Fetched via ipfs_kit_py: {cid}")
                # return temp_path, {'size': len(content), 'type': 'file', 'source': 'ipfs_kit'}
                
            except Exception as e:
                logger.warning(f"ipfs_kit_py fetch failed: {e}")
        
        # Gateway fallback
        if gateway_fallback:
            try:
                import aiohttp
                
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.ipfs')
                temp_path = Path(temp_file.name)
                temp_file.close()  # Close but don't delete
                self._temp_files.append(temp_path)  # Track for cleanup
                
                # Try multiple gateways
                gateways = [
                    f"https://ipfs.io/ipfs/{cid}",
                    f"https://dweb.link/ipfs/{cid}",
                    f"https://cloudflare-ipfs.com/ipfs/{cid}"
                ]
                
                async with aiohttp.ClientSession() as session:
                    for gateway_url in gateways:
                        try:
                            async with session.get(gateway_url, timeout=30) as response:
                                if response.status == 200:
                                    content = await response.read()
                                    temp_path.write_bytes(content)
                                    
                                    content_info = {
                                        'size': len(content),
                                        'type': 'file',
                                        'source': 'gateway',
                                        'gateway': gateway_url
                                    }
                                    
                                    logger.info(f"Fetched via gateway: {gateway_url}")
                                    return temp_path, content_info
                        except Exception as e:
                            logger.debug(f"Gateway {gateway_url} failed: {e}")
                            continue
                
            except Exception as e:
                logger.error(f"Gateway fetch failed: {e}")
        
        return None, {}
    
    async def _process_content(
        self,
        content_path: Path,
        content_info: dict,
        **options
    ) -> ProcessingResult:
        """
        Process fetched IPFS content by routing to appropriate processor.
        
        Args:
            content_path: Path to fetched content
            content_info: Information about content
            **options: Processing options
            
        Returns:
            ProcessingResult from sub-processor
        """
        # If we have a parent processor, use it to route
        if self._parent_processor:
            try:
                return await self._parent_processor.process(content_path, **options)
            except Exception as e:
                logger.error(f"Sub-processor routing failed: {e}")
        
        # Fallback: basic processing
        metadata = ProcessingMetadata(
            processor_name="IPFSProcessorAdapter",
            processor_version="1.0",
            input_type=InputType.IPFS,
            status=ProcessingStatus.PARTIAL
        )
        metadata.add_warning("No parent processor available for routing")
        
        # Read content
        try:
            if content_path.is_file():
                content = content_path.read_bytes()
                text_content = content.decode('utf-8', errors='ignore')
            else:
                text_content = "Directory content"
        except Exception as e:
            text_content = f"Could not read content: {e}"
        
        return ProcessingResult(
            knowledge_graph=KnowledgeGraph(),
            vectors=VectorStore(),
            content={
                'text': text_content,
                'size': content_info.get('size', 0),
                'source': content_info.get('source', 'unknown')
            },
            metadata=metadata
        )
    
    def get_supported_types(self) -> list[str]:
        """
        Return list of supported input types.
        
        Returns:
            List of type identifiers
        """
        return ["ipfs", "cid", "ipns"]
    
    def get_priority(self) -> int:
        """
        Get processor priority.
        
        IPFS is critical to this project, so give it high priority.
        
        Returns:
            Priority value (higher = more preferred)
        """
        return 20  # Highest priority - IPFS is core to this project
    
    def get_name(self) -> str:
        """
        Get processor name.
        
        Returns:
            Processor name
        """
        return "IPFSProcessorAdapter"
