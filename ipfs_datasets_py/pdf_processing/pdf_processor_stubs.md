# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 21:47:52

## PDFProcessor

```python
class PDFProcessor:
    """
    Core PDF processing class implementing the complete pipeline.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage: Optional[IPLDStorage] = None, enable_monitoring: bool = False, enable_audit: bool = True):
    """
    Initialize the PDF processor.

Args:
    storage: IPLD storage instance
    enable_monitoring: Enable performance monitoring
    enable_audit: Enable audit logging
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _analyze_cross_document_relationships

```python
async def _analyze_cross_document_relationships(self, graph_nodes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Stage 9: Cross-Document Analysis - Analyze relationships across documents.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _calculate_file_hash

```python
def _calculate_file_hash(self, file_path: Path) -> str:
    """
    Calculate SHA-256 hash of the file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _create_embeddings

```python
async def _create_embeddings(self, optimized_content: Dict[str, Any], entities_and_relations: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 7: Vector Embedding - Create embeddings for content.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _create_ipld_structure

```python
async def _create_ipld_structure(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 3: IPLD Structuring - Create content-addressed data structures.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _decompose_pdf

```python
async def _decompose_pdf(self, pdf_path: Path) -> Dict[str, Any]:
    """
    Stage 2: Decomposition - Extract PDF layers and content.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _extract_entities

```python
async def _extract_entities(self, optimized_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 6: Entity Extraction - Extract entities and relationships.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _extract_native_text

```python
def _extract_native_text(self, text_blocks: List[Dict[str, Any]]) -> str:
    """
    Extract native text from text blocks.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _extract_page_content

```python
async def _extract_page_content(self, page, page_num: int) -> Dict[str, Any]:
    """
    Extract content from a single PDF page.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _get_processing_time

```python
def _get_processing_time(self) -> float:
    """
    Get total processing time.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _get_quality_scores

```python
def _get_quality_scores(self) -> Dict[str, float]:
    """
    Get quality scores for the processing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _integrate_with_graphrag

```python
async def _integrate_with_graphrag(self, ipld_structure: Dict[str, Any], entities_and_relations: Dict[str, Any], embeddings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 8: IPLD GraphRAG Integration - Integrate with GraphRAG system.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _optimize_for_llm

```python
async def _optimize_for_llm(self, decomposed_content: Dict[str, Any], ocr_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 5: LLM Optimization - Optimize content for LLM consumption.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _process_ocr

```python
async def _process_ocr(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 4: OCR Processing - Process images with OCR.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _setup_query_interface

```python
async def _setup_query_interface(self, graph_nodes: Dict[str, Any], cross_doc_relations: List[Dict[str, Any]]):
    """
    Stage 10: Query Interface Setup - Setup query interface for the processed content.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _validate_and_analyze_pdf

```python
async def _validate_and_analyze_pdf(self, pdf_path: Path) -> Dict[str, Any]:
    """
    Stage 1: PDF Input - Validate and analyze PDF file.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## process_pdf

```python
async def process_pdf(self, pdf_path: Union[str, Path], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute the complete PDF processing pipeline.

Args:
    pdf_path: Path to the PDF file
    metadata: Additional metadata for the document
    
Returns:
    Dict containing processing results and metadata
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor
