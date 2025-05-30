"""
Web Archive Utilities Module

Provides tools for working with web archives, including WARC files and
IPFS-based web archives via IPWB.
"""

import os
import json
import tempfile
import subprocess
from typing import Dict, List, Optional, Tuple, Union, Any, Iterator

# Check for dependencies
try:
    from archivenow import archivenow
    HAVE_ARCHIVENOW = True
except ImportError:
    HAVE_ARCHIVENOW = False

try:
    import ipwb
    from ipwb import indexer, replay, util
    HAVE_IPWB = True
except ImportError:
    HAVE_IPWB = False

try:
    import pyarrow as pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from bs4 import BeautifulSoup
    HAVE_BS4 = True
except ImportError:
    HAVE_BS4 = False


class WebArchiveProcessor:
    """
    Processes web archives, including creating, indexing, and extracting data.

    This class provides methods for:
    - Creating WARC files using ArchiveNow
    - Indexing WARC files to IPFS using IPWB
    - Extracting datasets from CDXJ indexes
    - Extracting text and links from WARC files
    """

    def __init__(self):
        """Initialize a new WebArchiveProcessor."""
        pass

    def create_warc(self, url, output_path=None, options=None):
        """
        Create a WARC file using ArchiveNow.

        Args:
            url (str): URL to archive
            output_path (str, optional): Path for the output WARC file
            options (dict, optional): Options for ArchiveNow, such as:
                - agent: "wget" or "squidwarc"
                - depth: crawl depth (for squidwarc)

        Returns:
            str: Path to the created WARC file

        Raises:
            ImportError: If ArchiveNow is not available
        """
        if not HAVE_ARCHIVENOW:
            raise ImportError("ArchiveNow is required for WARC creation. Install with pip install archivenow")

        # Set default options
        if options is None:
            options = {}

        # Set up WARC options
        warc_options = {}
        if output_path:
            warc_options["warc"] = os.path.splitext(os.path.basename(output_path))[0]

        # Add other options
        for key, value in options.items():
            warc_options[key] = value

        # Create the WARC
        result = archivenow.push(url, "warc", warc_options)

        # If output_path is specified, move the file to that location
        if output_path and result and os.path.exists(result):
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            os.rename(result, output_path)
            return output_path

        return result

    def index_warc(self, warc_path, output_path=None, encryption_key=None):
        """
        Index a WARC file using IPWB.

        Args:
            warc_path (str): Path to the WARC file
            output_path (str, optional): Path for the output CDXJ file
            encryption_key (str, optional): Key for encrypting the archive

        Returns:
            str: Path to the created CDXJ file

        Raises:
            ImportError: If IPWB is not available
            FileNotFoundError: If the WARC file does not exist
        """
        if not HAVE_IPWB:
            raise ImportError("IPWB is required for WARC indexing. Install with pip install ipwb")

        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Set up indexing options
        index_options = {
            "quiet": True
        }

        if encryption_key:
            index_options["encryptionKey"] = encryption_key

        # If no output path is specified, create one based on the WARC path
        if not output_path:
            output_path = os.path.splitext(warc_path)[0] + ".cdxj"

        # Index the WARC
        cdxj_lines = indexer.index_file_at(warc_path, outfile=output_path, **index_options)

        return output_path

    def extract_dataset_from_cdxj(self, cdxj_path, output_format="arrow"):
        """
        Extract a dataset from a CDXJ index.

        Args:
            cdxj_path (str): Path to the CDXJ file
            output_format (str): Output format: "arrow", "huggingface", or "dict"

        Returns:
            Dataset in the specified format

        Raises:
            ImportError: If required dependencies are not available
            FileNotFoundError: If the CDXJ file does not exist
        """
        if not HAVE_IPWB:
            raise ImportError("IPWB is required for CDXJ extraction. Install with pip install ipwb")

        if not os.path.isfile(cdxj_path):
            raise FileNotFoundError(f"CDXJ file not found: {cdxj_path}")

        # Read the CDXJ file
        with open(cdxj_path, 'r') as f:
            cdxj_lines = f.readlines()

        # Extract data from each line
        records = []
        for line in cdxj_lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Parse the CDXJ line
            try:
                uri_k, timestamp, json_str = line.split(' ', 2)
                record = json.loads(json_str)

                # Add the URI and timestamp
                record['uri_k'] = uri_k
                record['timestamp'] = timestamp

                # Convert surt format to regular URI if needed
                if 'uri' not in record and uri_k:
                    from ipwb.util import unsurt
                    record['uri'] = unsurt(uri_k)

                # Get the content if possible
                if 'ipfs' in record:
                    try:
                        content = util.pull_from_ipfs(record['ipfs'])

                        # Extract text if possible
                        if 'mime' in record and record['mime'].startswith('text/html') and HAVE_BS4:
                            soup = BeautifulSoup(content, 'html.parser')
                            record['text'] = soup.get_text(separator=' ', strip=True)
                        else:
                            # Just store the raw content
                            record['content'] = content

                    except Exception as e:
                        print(f"Warning: Could not retrieve content for {record.get('uri', uri_k)}: {e}")

                records.append(record)

            except Exception as e:
                print(f"Warning: Could not parse CDXJ line: {line}: {e}")

        # Convert to the requested output format
        if output_format == "dict":
            return records

        elif output_format == "arrow":
            if not HAVE_ARROW:
                raise ImportError("PyArrow is required for Arrow output. Install with pip install pyarrow")

            # Convert to PyArrow table
            # First, normalize the records to have the same keys
            all_keys = set()
            for record in records:
                all_keys.update(record.keys())

            # Fill in missing keys with None
            for record in records:
                for key in all_keys:
                    if key not in record:
                        record[key] = None

            # Convert to dict of lists
            data = {key: [record.get(key) for record in records] for key in all_keys}

            # Handle binary data in the table
            for key in data:
                if key == 'content' and data[key][0] is not None:
                    # If content is binary, use binary type
                    data[key] = pa.array(data[key], type=pa.binary())

            return pa.Table.from_pydict(data)

        elif output_format == "huggingface":
            try:
                from datasets import Dataset
            except ImportError:
                raise ImportError("HuggingFace datasets is required for HuggingFace output. Install with pip install datasets")

            # Convert to HuggingFace dataset
            if HAVE_ARROW:
                # Use Arrow as intermediate format
                table = self.extract_dataset_from_cdxj(cdxj_path, output_format="arrow")
                return Dataset(pa.table(table))
            else:
                # Use dict as intermediate format
                data = self.extract_dataset_from_cdxj(cdxj_path, output_format="dict")
                return Dataset.from_dict({key: [record.get(key) for record in data] for key in data[0]})

        else:
            raise ValueError(f"Unknown output format: {output_format}")

    def extract_text_from_warc(self, warc_path):
        """
        Extract text content from a WARC file.

        Args:
            warc_path (str): Path to the WARC file

        Returns:
            List[Dict]: List of records with URI and text content

        Raises:
            ImportError: If required dependencies are not available
            FileNotFoundError: If the WARC file does not exist
        """
        if not HAVE_BS4:
            raise ImportError("BeautifulSoup is required for text extraction. Install with pip install beautifulsoup4")

        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Import locally to avoid hard dependency
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            raise ImportError("warcio is required for WARC processing. Install with pip install warcio")

        # Process the WARC file
        records = []
        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                if record.rec_type == 'response' and record.http_headers:
                    # Get the URI
                    uri = record.rec_headers.get_header('WARC-Target-URI')

                    # Get the content type
                    content_type = record.http_headers.get_header('Content-Type')

                    # Process HTML content
                    if content_type and 'text/html' in content_type:
                        content = record.content_stream().read()

                        # Extract text using BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')
                        text = soup.get_text(separator=' ', strip=True)

                        records.append({
                            'uri': uri,
                            'text': text
                        })

        return records

    def extract_links_from_warc(self, warc_path):
        """
        Extract links from a WARC file.

        Args:
            warc_path (str): Path to the WARC file

        Returns:
            List[Dict]: List of records with source and target URIs

        Raises:
            ImportError: If required dependencies are not available
            FileNotFoundError: If the WARC file does not exist
        """
        if not HAVE_BS4:
            raise ImportError("BeautifulSoup is required for link extraction. Install with pip install beautifulsoup4")

        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Import locally to avoid hard dependency
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            raise ImportError("warcio is required for WARC processing. Install with pip install warcio")

        # Process the WARC file
        links = []
        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                if record.rec_type == 'response' and record.http_headers:
                    # Get the URI
                    uri = record.rec_headers.get_header('WARC-Target-URI')

                    # Get the content type
                    content_type = record.http_headers.get_header('Content-Type')

                    # Process HTML content
                    if content_type and 'text/html' in content_type:
                        content = record.content_stream().read()

                        # Extract links using BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')
                        for link in soup.find_all('a', href=True):
                            href = link['href']

                            # Resolve relative URLs
                            if href.startswith('/'):
                                import urllib.parse
                                base_url = urllib.parse.urlparse(uri)
                                href = f"{base_url.scheme}://{base_url.netloc}{href}"

                            links.append({
                                'source': uri,
                                'target': href,
                                'text': link.get_text(strip=True)
                            })

        return links

    def extract_metadata_from_warc(self, warc_path):
        """
        Extract metadata from a WARC file.

        Args:
            warc_path (str): Path to the WARC file

        Returns:
            Dict: Metadata about the WARC file

        Raises:
            FileNotFoundError: If the WARC file does not exist
        """
        if not os.path.isfile(warc_path):
            raise FileNotFoundError(f"WARC file not found: {warc_path}")

        # Import locally to avoid hard dependency
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            raise ImportError("warcio is required for WARC processing. Install with pip install warcio")

        # Process the WARC file
        metadata = {
            'filename': os.path.basename(warc_path),
            'size': os.path.getsize(warc_path),
            'records': 0,
            'content_types': {},
            'domains': {}
        }

        with open(warc_path, 'rb') as f:
            for record in ArchiveIterator(f):
                metadata['records'] += 1

                if record.rec_type == 'response' and record.http_headers:
                    # Get the URI
                    uri = record.rec_headers.get_header('WARC-Target-URI')

                    # Get the content type
                    content_type = record.http_headers.get_header('Content-Type')
                    if content_type:
                        metadata['content_types'][content_type] = metadata['content_types'].get(content_type, 0) + 1

                    # Get the domain
                    if uri:
                        import urllib.parse
                        try:
                            domain = urllib.parse.urlparse(uri).netloc
                            metadata['domains'][domain] = metadata['domains'].get(domain, 0) + 1
                        except:
                            pass

        return metadata


def index_warc(warc_path, output_path=None, encryption_key=None):
    """
    Convenience function to index a WARC file using IPWB.

    Args:
        warc_path (str): Path to the WARC file
        output_path (str, optional): Path for the output CDXJ file
        encryption_key (str, optional): Key for encrypting the archive

    Returns:
        str: Path to the created CDXJ file
    """
    processor = WebArchiveProcessor()
    return processor.index_warc(warc_path, output_path, encryption_key)


def create_warc(url, output_path=None, options=None):
    """
    Convenience function to create a WARC file using ArchiveNow.

    Args:
        url (str): URL to archive
        output_path (str, optional): Path for the output WARC file
        options (dict, optional): Options for ArchiveNow

    Returns:
        str: Path to the created WARC file
    """
    processor = WebArchiveProcessor()
    return processor.create_warc(url, output_path, options)
