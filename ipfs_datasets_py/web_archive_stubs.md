# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/web_archive.py'

Files last updated: 1748635923.4713795

Stub file last updated: 2025-07-07 02:11:02

## WebArchive

```python
class WebArchive:
    """
    Web archive functionality for storing and retrieving web content.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WebArchiveProcessor

```python
class WebArchiveProcessor:
    """
    Processor for web archive operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage_path: Optional[str] = None):
    """
    Initialize web archive with optional storage path.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchive

## __init__

```python
def __init__(self):
    """
    Initialize web archive processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## archive_url

```python
def archive_url(self, url: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Archive a URL with optional metadata.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchive

## archive_web_content

```python
def archive_web_content(url: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Archive web content from a URL.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_warc

```python
def create_warc(self, urls: List[str], output_path: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Create a WARC file from a list of URLs.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## create_web_archive

```python
def create_web_archive(storage_path: Optional[str] = None) -> WebArchive:
    """
    Create a new web archive instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_dataset_from_cdxj

```python
def extract_dataset_from_cdxj(self, cdxj_path: str, output_format: str = "json") -> Dict[str, Any]:
    """
    Extract dataset from CDXJ file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## extract_links_from_warc

```python
def extract_links_from_warc(self, warc_path: str) -> List[Dict[str, Any]]:
    """
    Extract links from a WARC file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## extract_metadata_from_warc

```python
def extract_metadata_from_warc(self, warc_path: str) -> Dict[str, Any]:
    """
    Extract metadata from a WARC file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## extract_text_from_html

```python
def extract_text_from_html(self, html_content: str) -> Dict[str, Any]:
    """
    Extract text content from HTML.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## extract_text_from_warc

```python
def extract_text_from_warc(self, warc_path: str) -> List[Dict[str, Any]]:
    """
    Extract text content from a WARC file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## index_warc

```python
def index_warc(self, warc_path: str, output_path: Optional[str] = None, encryption_key: Optional[str] = None) -> str:
    """
    Create an index for a WARC file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## list_archives

```python
def list_archives(self) -> List[Dict[str, Any]]:
    """
    List all archived items.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchive

## process_html_content

```python
def process_html_content(self, html: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Process HTML content and extract useful information.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## process_urls

```python
def process_urls(self, urls: List[str]) -> Dict[str, Any]:
    """
    Process multiple URLs for archiving.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor

## retrieve_archive

```python
def retrieve_archive(self, archive_id: str) -> Dict[str, Any]:
    """
    Retrieve archived content by ID.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchive

## retrieve_web_content

```python
def retrieve_web_content(archive_id: str) -> Dict[str, Any]:
    """
    Retrieve archived web content.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## search_archives

```python
def search_archives(self, query: str) -> List[Dict[str, Any]]:
    """
    Search archived content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WebArchiveProcessor
