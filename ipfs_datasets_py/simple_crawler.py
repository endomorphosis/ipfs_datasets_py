#!/usr/bin/env python3
"""
Simple Web Crawler for WARC Creation

Creates basic WARC files by fetching web pages and their resources.
This is a simplified implementation for demonstration purposes.
"""

import os
import requests
import gzip
import mimetypes
from datetime import datetime
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Set, Any
from bs4 import BeautifulSoup


class SimpleWebCrawler:
    """
    Simple web crawler that creates WARC-like files for GraphRAG processing.
    
    This is a simplified implementation that fetches web content and stores it
    in a format that can be processed by the ContentDiscoveryEngine.
    """
    
    def __init__(self, max_pages: int = 10, max_depth: int = 2):
        """
        Initialize the web crawler
        
        Args:
            max_pages: Maximum number of pages to crawl
            max_depth: Maximum depth to crawl from starting URL
        """
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.visited_urls: Set[str] = set()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'GraphRAG-WebCrawler/1.0 (Educational Purpose)'
        })
        
    def crawl_website(self, start_url: str, output_path: str = None) -> str:
        """
        Crawl a website and create a WARC-like file
        
        Args:
            start_url: Starting URL to crawl
            output_path: Output path for the WARC file
            
        Returns:
            Path to the created WARC file
        """
        if output_path is None:
            domain = urlparse(start_url).netloc
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"warc_{domain}_{timestamp}.warc"
        
        print(f"Starting crawl of {start_url}")
        print(f"Output file: {output_path}")
        
        # Collect pages to crawl
        pages_to_crawl = [(start_url, 0)]  # (url, depth)
        crawled_pages = []
        
        while pages_to_crawl and len(crawled_pages) < self.max_pages:
            current_url, depth = pages_to_crawl.pop(0)
            
            if current_url in self.visited_urls or depth > self.max_depth:
                continue
                
            try:
                print(f"Crawling: {current_url} (depth {depth})")
                response = self.session.get(current_url, timeout=10)
                response.raise_for_status()
                
                # Store the response
                self.visited_urls.add(current_url)
                crawled_pages.append({
                    'url': current_url,
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'content': response.content,
                    'text': response.text,
                    'timestamp': datetime.now().isoformat(),
                    'depth': depth
                })
                
                # Extract links for further crawling (if not at max depth)
                if depth < self.max_depth and 'text/html' in response.headers.get('Content-Type', ''):
                    soup = BeautifulSoup(response.text, 'html.parser')
                    for link in soup.find_all('a', href=True):
                        next_url = urljoin(current_url, link['href'])
                        next_parsed = urlparse(next_url)
                        current_parsed = urlparse(current_url)
                        
                        # Only crawl same domain
                        if (next_parsed.netloc == current_parsed.netloc and 
                            next_url not in self.visited_urls and
                            next_parsed.scheme in ['http', 'https']):
                            pages_to_crawl.append((next_url, depth + 1))
                
            except Exception as e:
                print(f"Error crawling {current_url}: {e}")
                continue
        
        # Create WARC-like file
        self._create_warc_file(crawled_pages, output_path)
        
        print(f"Crawl completed: {len(crawled_pages)} pages saved to {output_path}")
        return os.path.abspath(output_path)
        
    def _create_warc_file(self, pages: List[Dict[str, Any]], output_path: str):
        """Create a simplified WARC file from crawled pages"""
        
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write WARC file header
            f.write("WARC/1.0\r\n")
            f.write(f"WARC-Type: warcinfo\r\n")
            f.write(f"WARC-Date: {datetime.now().isoformat()}Z\r\n")
            f.write(f"WARC-Filename: {os.path.basename(output_path)}\r\n")
            f.write(f"Content-Length: 0\r\n")
            f.write("\r\n")
            
            # Write each page as a WARC record
            for page in pages:
                content_bytes = page['content']
                content_length = len(content_bytes)
                
                # WARC record header
                f.write("WARC/1.0\r\n")
                f.write("WARC-Type: response\r\n")
                f.write(f"WARC-Target-URI: {page['url']}\r\n")
                f.write(f"WARC-Date: {page['timestamp']}Z\r\n")
                f.write(f"Content-Type: application/http; msgtype=response\r\n")
                f.write(f"Content-Length: {content_length + len(page['text'])}\r\n")
                f.write("\r\n")
                
                # HTTP response header
                f.write(f"HTTP/1.1 {page['status_code']} OK\r\n")
                for header_name, header_value in page['headers'].items():
                    f.write(f"{header_name}: {header_value}\r\n")
                f.write("\r\n")
                
                # Content (for HTML, write text; for binary, write placeholder)
                content_type = page['headers'].get('Content-Type', '')
                if 'text/html' in content_type:
                    f.write(page['text'])
                else:
                    f.write(f"[Binary content of {content_length} bytes]")
                
                f.write("\r\n\r\n")
                
    def extract_media_links(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract media links from crawled HTML pages"""
        media_links = []
        
        for page in pages:
            if 'text/html' not in page['headers'].get('Content-Type', ''):
                continue
                
            try:
                soup = BeautifulSoup(page['text'], 'html.parser')
                base_url = page['url']
                
                # Images
                for img in soup.find_all('img', src=True):
                    img_url = urljoin(base_url, img['src'])
                    media_links.append({
                        'url': img_url,
                        'type': 'image',
                        'source_page': base_url,
                        'alt_text': img.get('alt', ''),
                        'title': img.get('title', '')
                    })
                
                # Videos  
                for video in soup.find_all('video', src=True):
                    video_url = urljoin(base_url, video['src'])
                    media_links.append({
                        'url': video_url,
                        'type': 'video', 
                        'source_page': base_url,
                        'poster': video.get('poster', ''),
                        'controls': video.get('controls') is not None
                    })
                
                # Audio
                for audio in soup.find_all('audio', src=True):
                    audio_url = urljoin(base_url, audio['src'])
                    media_links.append({
                        'url': audio_url,
                        'type': 'audio',
                        'source_page': base_url,
                        'controls': audio.get('controls') is not None
                    })
                
                # PDFs and documents
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if any(ext in href.lower() for ext in ['.pdf', '.doc', '.docx', '.ppt', '.pptx']):
                        doc_url = urljoin(base_url, href)
                        media_links.append({
                            'url': doc_url,
                            'type': 'document',
                            'source_page': base_url,
                            'link_text': link.get_text(strip=True),
                            'title': link.get('title', '')
                        })
                        
            except Exception as e:
                print(f"Error extracting media from {page['url']}: {e}")
                continue
                
        return media_links


def main():
    """Example usage of SimpleWebCrawler"""
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python simple_crawler.py <URL>")
        print("Example: python simple_crawler.py https://example.com")
        return
    
    url = sys.argv[1]
    crawler = SimpleWebCrawler(max_pages=5, max_depth=2)
    
    try:
        warc_file = crawler.crawl_website(url)
        print(f"\nCrawl completed successfully!")
        print(f"WARC file created: {warc_file}")
        
        # Show basic stats
        with open(warc_file, 'r', encoding='utf-8') as f:
            content = f.read()
            num_records = content.count('WARC-Type: response')
            print(f"Number of pages crawled: {num_records}")
            print(f"File size: {len(content)} characters")
            
    except Exception as e:
        print(f"Crawl failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())