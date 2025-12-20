#!/usr/bin/env python3
"""
WARC Import/Export for Common Crawl Integration

This module provides functionality to:
1. Import content from Common Crawl WARC files
2. Export scraped content to WARC format
3. Search Common Crawl indexes for URLs
4. Download and parse WARC records
5. Integrate with content-addressed scraping system

WARC (Web ARChive) is the standard format used by Common Crawl and Internet Archive.
"""

import logging
import gzip
import json
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)

# Try to import warcio (standard WARC library)
try:
    from warcio.archiveiterator import ArchiveIterator
    from warcio.warcwriter import WARCWriter
    from warcio.statusandheaders import StatusAndHeaders
    HAVE_WARCIO = True
except ImportError:
    HAVE_WARCIO = False
    logger.warning("warcio not available - install with: pip install warcio")

# Import for HTTP requests
try:
    import aiohttp
    HAVE_AIOHTTP = True
except ImportError:
    HAVE_AIOHTTP = False
    logger.warning("aiohttp not available")


class CommonCrawlWARCImporter:
    """
    Import content from Common Crawl WARC files.
    
    Common Crawl provides web archive data in WARC format.
    Each crawl creates thousands of WARC files stored on S3.
    """
    
    def __init__(self, content_addressed_scraper=None):
        """
        Initialize Common Crawl WARC importer.
        
        Args:
            content_addressed_scraper: Optional ContentAddressedScraper for CID tracking
        """
        self.content_scraper = content_addressed_scraper
        self.base_url = "https://data.commoncrawl.org/"
        
        logger.info("CommonCrawlWARCImporter initialized")
    
    async def search_common_crawl_index(
        self,
        url_pattern: str,
        index_id: str = "CC-MAIN-2025-47",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search Common Crawl CDX index for URL pattern.
        
        Args:
            url_pattern: URL pattern to search (e.g., "library.municode.com/*")
            index_id: Common Crawl index ID (e.g., "CC-MAIN-2025-47")
            limit: Maximum number of results
            
        Returns:
            List of CDX records with WARC file locations
        """
        if not HAVE_AIOHTTP:
            logger.error("aiohttp required for Common Crawl search")
            return []
        
        index_url = f"https://index.commoncrawl.org/{index_id}-index"
        params = {
            "url": url_pattern,
            "output": "json",
            "limit": limit
        }
        
        logger.info(f"Searching Common Crawl index: {index_id} for {url_pattern}")
        
        results = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(index_url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        # CDX API returns newline-delimited JSON
                        text = await response.text()
                        for line in text.strip().split('\n'):
                            if line:
                                try:
                                    record = json.loads(line)
                                    results.append(record)
                                except json.JSONDecodeError:
                                    continue
                        
                        logger.info(f"Found {len(results)} records in Common Crawl index")
                    else:
                        logger.error(f"Common Crawl index search failed: HTTP {response.status}")
        
        except Exception as e:
            logger.error(f"Error searching Common Crawl index: {e}")
        
        return results
    
    async def fetch_warc_record(
        self,
        warc_filename: str,
        offset: int,
        length: int
    ) -> Optional[bytes]:
        """
        Fetch a specific WARC record from Common Crawl.
        
        Args:
            warc_filename: WARC file path (from CDX record)
            offset: Byte offset in the file
            length: Number of bytes to read
            
        Returns:
            Raw WARC record bytes or None if failed
        """
        if not HAVE_AIOHTTP:
            logger.error("aiohttp required for WARC fetching")
            return None
        
        # Build full URL
        warc_url = f"{self.base_url}{warc_filename}"
        
        # Request specific byte range
        headers = {
            "Range": f"bytes={offset}-{offset + length - 1}"
        }
        
        logger.debug(f"Fetching WARC record: {warc_filename} at offset {offset}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(warc_url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status in [200, 206]:  # 206 = Partial Content
                        data = await response.read()
                        logger.debug(f"Fetched {len(data)} bytes from WARC")
                        return data
                    else:
                        logger.error(f"WARC fetch failed: HTTP {response.status}")
                        return None
        
        except Exception as e:
            logger.error(f"Error fetching WARC record: {e}")
            return None
    
    async def parse_warc_record(self, warc_data: bytes) -> Optional[Dict[str, Any]]:
        """
        Parse a WARC record to extract HTTP response.
        
        Args:
            warc_data: Raw WARC record bytes (possibly gzipped)
            
        Returns:
            Dict with parsed content and metadata
        """
        if not HAVE_WARCIO:
            logger.error("warcio required for WARC parsing")
            return None
        
        try:
            # Decompress if gzipped
            try:
                warc_data = gzip.decompress(warc_data)
            except:
                pass  # Not gzipped
            
            # Parse WARC record
            from io import BytesIO
            stream = BytesIO(warc_data)
            
            for record in ArchiveIterator(stream):
                if record.rec_type == 'response':
                    # Extract HTTP response
                    content = record.content_stream().read()
                    
                    return {
                        "url": record.rec_headers.get_header('WARC-Target-URI'),
                        "timestamp": record.rec_headers.get_header('WARC-Date'),
                        "content_type": record.http_headers.get_header('Content-Type') if record.http_headers else None,
                        "content": content,
                        "content_length": len(content),
                        "warc_record_id": record.rec_headers.get_header('WARC-Record-ID'),
                        "status_code": record.http_headers.get_statuscode() if record.http_headers else None
                    }
        
        except Exception as e:
            logger.error(f"Error parsing WARC record: {e}")
            return None
    
    async def import_from_common_crawl(
        self,
        url_pattern: str,
        index_id: str = "CC-MAIN-2025-47",
        max_records: int = 10,
        store_with_cid: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Import content from Common Crawl for a URL pattern.
        
        This is the main method to get historical content from Common Crawl.
        
        Args:
            url_pattern: URL pattern to search
            index_id: Common Crawl index to search
            max_records: Maximum records to import
            store_with_cid: Store with content addressing
            
        Returns:
            List of imported records with content and CIDs
        """
        logger.info(f"Importing from Common Crawl: {url_pattern}")
        
        # 1. Search index
        cdx_records = await self.search_common_crawl_index(
            url_pattern=url_pattern,
            index_id=index_id,
            limit=max_records
        )
        
        if not cdx_records:
            logger.warning("No records found in Common Crawl index")
            return []
        
        # 2. Fetch and parse WARC records
        imported_records = []
        
        for cdx_record in cdx_records[:max_records]:
            try:
                # Get WARC location
                warc_filename = cdx_record.get('filename')
                offset = int(cdx_record.get('offset', 0))
                length = int(cdx_record.get('length', 0))
                
                # Fetch WARC record
                warc_data = await self.fetch_warc_record(warc_filename, offset, length)
                
                if not warc_data:
                    continue
                
                # Parse WARC record
                parsed = await self.parse_warc_record(warc_data)
                
                if not parsed:
                    continue
                
                # Add CDX metadata
                parsed['cdx_record'] = cdx_record
                parsed['common_crawl_index'] = index_id
                
                # Compute CID if requested
                if store_with_cid and self.content_scraper:
                    content_cid = self.content_scraper.compute_content_cid(parsed['content'])
                    parsed['content_cid'] = content_cid
                    
                    # Store in content-addressed database
                    metadata = {
                        "source": "common_crawl",
                        "index": index_id,
                        "url": parsed['url'],
                        "timestamp": parsed['timestamp']
                    }
                    
                    # Check if already have this content
                    exists = self.content_scraper.check_content_exists(content_cid)
                    if exists['exists']:
                        logger.info(f"Content already exists with CID {content_cid}")
                        parsed['already_existed'] = True
                    else:
                        logger.info(f"New content from Common Crawl: {content_cid}")
                        parsed['already_existed'] = False
                
                imported_records.append(parsed)
                logger.info(f"Imported: {parsed['url']} ({len(parsed['content'])} bytes)")
            
            except Exception as e:
                logger.error(f"Error importing record: {e}")
                continue
        
        logger.info(f"Imported {len(imported_records)} records from Common Crawl")
        return imported_records


class WARCExporter:
    """
    Export scraped content to WARC format.
    
    Allows saving scraped content in standard WARC format for:
    - Archiving
    - Sharing with Internet Archive
    - Backup and preservation
    - Compatibility with archive tools
    """
    
    def __init__(self, output_dir: str = "./warc_exports"):
        """
        Initialize WARC exporter.
        
        Args:
            output_dir: Directory to store WARC files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"WARCExporter initialized: {self.output_dir}")
    
    def export_to_warc(
        self,
        records: List[Dict[str, Any]],
        output_filename: Optional[str] = None,
        compress: bool = True
    ) -> str:
        """
        Export records to WARC file.
        
        Args:
            records: List of records to export (each with url, content, timestamp)
            output_filename: Custom filename (generated if not provided)
            compress: Gzip compress the WARC file
            
        Returns:
            Path to created WARC file
        """
        if not HAVE_WARCIO:
            logger.error("warcio required for WARC export")
            raise ImportError("warcio not available - install with: pip install warcio")
        
        # Generate filename if not provided
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_filename = f"scraped-{timestamp}.warc"
            if compress:
                output_filename += ".gz"
        
        output_path = self.output_dir / output_filename
        
        logger.info(f"Exporting {len(records)} records to WARC: {output_path}")
        
        # Open file for writing
        mode = 'wb' if compress else 'w'
        fh = gzip.open(output_path, mode) if compress else open(output_path, mode)
        
        try:
            writer = WARCWriter(fh, gzip=compress)
            
            for record in records:
                url = record.get('url', 'unknown://unknown')
                content = record.get('content', b'')
                timestamp = record.get('timestamp', datetime.now().isoformat())
                content_type = record.get('content_type', 'application/octet-stream')
                
                # Convert content to bytes if string
                if isinstance(content, str):
                    content = content.encode('utf-8')
                
                # Create HTTP headers
                http_headers = StatusAndHeaders(
                    '200 OK',
                    [('Content-Type', content_type),
                     ('Content-Length', str(len(content)))],
                    protocol='HTTP/1.1'
                )
                
                # Write WARC response record
                from io import BytesIO
                writer.write_record(
                    writer.create_warc_record(
                        uri=url,
                        record_type='response',
                        payload=BytesIO(content),
                        warc_headers_dict={
                            'WARC-Date': timestamp,
                            'Content-Type': 'application/http; msgtype=response'
                        },
                        http_headers=http_headers
                    )
                )
                
                logger.debug(f"Wrote record: {url} ({len(content)} bytes)")
        
        finally:
            fh.close()
        
        logger.info(f"WARC export complete: {output_path}")
        return str(output_path)


# Convenience functions

async def import_municode_from_common_crawl(
    jurisdiction_pattern: str = "library.municode.com/*",
    max_records: int = 10
) -> List[Dict[str, Any]]:
    """
    Convenience function to import Municode content from Common Crawl.
    
    Args:
        jurisdiction_pattern: URL pattern to search
        max_records: Maximum records to import
        
    Returns:
        List of imported records
    """
    from content_addressed_scraper import get_content_addressed_scraper
    
    scraper = get_content_addressed_scraper()
    importer = CommonCrawlWARCImporter(scraper)
    
    return await importer.import_from_common_crawl(
        url_pattern=jurisdiction_pattern,
        max_records=max_records
    )


def export_scraped_to_warc(
    records: List[Dict[str, Any]],
    output_filename: Optional[str] = None
) -> str:
    """
    Convenience function to export scraped records to WARC.
    
    Args:
        records: List of scraped records
        output_filename: Optional custom filename
        
    Returns:
        Path to created WARC file
    """
    exporter = WARCExporter()
    return exporter.export_to_warc(records, output_filename)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    async def example():
        print("=" * 70)
        print("WARC Import/Export Example")
        print("=" * 70)
        
        # 1. Search Common Crawl index
        print("\n1. Searching Common Crawl index...")
        importer = CommonCrawlWARCImporter()
        cdx_records = await importer.search_common_crawl_index(
            url_pattern="library.municode.com/ak/*",
            index_id="CC-MAIN-2025-47",
            limit=5
        )
        print(f"   Found {len(cdx_records)} records")
        
        if cdx_records:
            print(f"   First record: {cdx_records[0]['url']}")
            print(f"   WARC file: {cdx_records[0]['filename']}")
        
        # 2. Import from Common Crawl
        print("\n2. Importing content from Common Crawl...")
        imported = await importer.import_from_common_crawl(
            url_pattern="library.municode.com/ak/anchorage/*",
            max_records=2,
            store_with_cid=False
        )
        print(f"   Imported {len(imported)} records")
        
        # 3. Export to WARC
        if imported:
            print("\n3. Exporting to WARC format...")
            exporter = WARCExporter()
            warc_path = exporter.export_to_warc(imported)
            print(f"   Exported to: {warc_path}")
        
        print("\n✅ WARC integration example complete!")
    
    asyncio.run(example())
