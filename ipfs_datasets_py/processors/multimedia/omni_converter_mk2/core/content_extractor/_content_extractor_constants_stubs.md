# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/_content_extractor_constants.py'

Files last updated: 1749505557.2583442

Stub file last updated: 2025-07-17 05:42:08

## ANTHROPIC_AVAILABLE

```python
@_classproperty
def ANTHROPIC_AVAILABLE(cls) -> bool:
    """
    Check if anthropic is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## BS4_AVAILABLE

```python
@_classproperty
def BS4_AVAILABLE(cls) -> bool:
    """
    Check if BeautifulSoup is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## CV2_AVAILABLE

```python
@_classproperty
def CV2_AVAILABLE(cls) -> bool:
    """
    Check if cv2 is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## Constants

```python
class Constants:
    """
    Utility class for managing constants related to format handlers.
This includes 
Constants for format handlers including supported formats and capabilities.

Table of Contents:
- Dependency and External Programs Availability
    Boolean properties to check if external cls._dependencies and programs are available.
- Combination Processors
    Boolean properties to check if a combination of cls._dependencies are available to enable certain processors.
    For example, if openpyxl *or* pandas is available, the xlsx processor can be used.
- Format Handlers Constants
- MIME Type to Format Mapping
- Unimplemented Formats
- All Formats from ROADMAP
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DUCKDB_AVAILABLE

```python
@_classproperty
def DUCKDB_AVAILABLE(cls) -> bool:
    """
    Check if duckdb is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## FFMPEG_AVAILABLE

```python
@_classproperty
def FFMPEG_AVAILABLE(cls) -> bool:
    """
    Check if ffmpeg is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## FFPROBE_AVAILABLE

```python
@_classproperty
def FFPROBE_AVAILABLE(cls) -> bool:
    """
    Check if ffprobe is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## GENERIC_HTML_PROCESSOR_AVAILABLE

```python
@_classproperty
def GENERIC_HTML_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if generic plaintext processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## GENERIC_PLAINTEXT_PROCESSOR_AVAILABLE

```python
@_classproperty
def GENERIC_PLAINTEXT_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if generic plaintext processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## GENERIC_SVG_PROCESSOR_AVAILABLE

```python
@_classproperty
def GENERIC_SVG_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if generic plaintext processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## GENERIC_XML_PROCESSOR_AVAILABLE

```python
@_classproperty
def GENERIC_XML_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if generic plaintext processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## HTML_PROCESSOR_AVAILABLE

```python
@_classproperty
def HTML_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if HTML processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## IMAGE_PROCESSOR_AVAILABLE

```python
@_classproperty
def IMAGE_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if image processing capabilities are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## JINJA2_AVAILABLE

```python
@_classproperty
def JINJA2_AVAILABLE(cls) -> bool:
    """
    Check if jinja2 is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## NLTK_AVAILABLE

```python
@_classproperty
def NLTK_AVAILABLE(cls) -> bool:
    """
    Check if nltk is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## NUMPY_AVAILABLE

```python
@_classproperty
def NUMPY_AVAILABLE(cls) -> bool:
    """
    Check if numpy is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## OCR_PROCESSOR_AVAILABLE

```python
@_classproperty
def OCR_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if OCR capabilities are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## OPENAI_AVAILABLE

```python
@_classproperty
def OPENAI_AVAILABLE(cls) -> bool:
    """
    Check if openai is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## OPENPYXL_AVAILABLE

```python
@_classproperty
def OPENPYXL_AVAILABLE(cls) -> bool:
    """
    Check if openpyxl is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PANDAS_AVAILABLE

```python
@_classproperty
def PANDAS_AVAILABLE(cls) -> bool:
    """
    Check if pandas is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PDF_PROCESSOR_AVAILABLE

```python
@_classproperty
def PDF_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if PDF processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PIL_AVAILABLE

```python
@_classproperty
def PIL_AVAILABLE(cls) -> bool:
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PLAINTEXT_PROCESSOR_AVAILABLE

```python
@_classproperty
def PLAINTEXT_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if plaintext processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PSUTIL_AVAILABLE

```python
@_classproperty
def PSUTIL_AVAILABLE(cls) -> bool:
    """
    Check if psutil is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYDANTIC_AVAILABLE

```python
@_classproperty
def PYDANTIC_AVAILABLE(cls) -> bool:
    """
    Check if pydantic is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYDUB_AVAILABLE

```python
@_classproperty
def PYDUB_AVAILABLE(cls) -> bool:
    """
    Check if pydub is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYMEDIAINFO_AVAILABLE

```python
@_classproperty
def PYMEDIAINFO_AVAILABLE(cls) -> bool:
    """
    Check if pymediainfo is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYPDF2_AVAILABLE

```python
@_classproperty
def PYPDF2_AVAILABLE(cls) -> bool:
    """
    Check if PyPDF2 is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYPDF2_AVAILABLE

```python
@_classproperty
def PYPDF2_AVAILABLE(cls) -> bool:
    """
    Check if PDF processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYTESSERACT_AVAILABLE

```python
@_classproperty
def PYTESSERACT_AVAILABLE(cls) -> bool:
    """
    Check if pytesseract is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYTHON_DOCX_AVAILABLE

```python
@_classproperty
def PYTHON_DOCX_AVAILABLE(cls) -> bool:
    """
    Check if DOCX processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## PYYAML_AVAILABLE

```python
@_classproperty
def PYYAML_AVAILABLE(cls) -> bool:
    """
    Check if yaml is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## REPORTLAB_AVAILABLE

```python
@_classproperty
def REPORTLAB_AVAILABLE(cls) -> bool:
    """
    Check if reportlab is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## ROUGE_AVAILABLE

```python
@_classproperty
def ROUGE_AVAILABLE(cls) -> bool:
    """
    Check if rouge is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## TESSERACT_AVAILABLE

```python
@_classproperty
def TESSERACT_AVAILABLE(cls) -> bool:
    """
    Check if tesseract is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## TIKTOKEN_AVAILABLE

```python
@_classproperty
def TIKTOKEN_AVAILABLE(cls) -> bool:
    """
    Check if tiktoken is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## TORCH_AVAILABLE

```python
@_classproperty
def TORCH_AVAILABLE(cls) -> bool:
    """
    Check if torch is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## TQDM_AVAILABLE

```python
@_classproperty
def TQDM_AVAILABLE(cls) -> bool:
    """
    Check if tqdm is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## TRANSCRIPTION_PROCESSOR_AVAILABLE

```python
@_classproperty
def TRANSCRIPTION_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if transcription capabilities are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## VIDEO_PROCESSOR_AVAILABLE

```python
@_classproperty
def VIDEO_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if video processing capabilities are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## WHISPER_AVAILABLE

```python
@_classproperty
def WHISPER_AVAILABLE(cls) -> bool:
    """
    Check if whisper is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## XLSX_PROCESSOR_AVAILABLE

```python
@_classproperty
def XLSX_PROCESSOR_AVAILABLE(cls) -> bool:
    """
    Check if XLSX processing capabilities are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## __get__

```python
def __get__(self, instance, owner):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## __getitem__

```python
def __getitem__(self, name: str) -> bool:
    """
    Get a external program by name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## __init__

```python
def __init__(self, func):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## _classproperty

```python
class _classproperty:
    """
    Helper decorator to turn class methods into properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_generic_processors

```python
def _get_generic_processors() -> Generator[set[str], None, None]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get

```python
@classmethod
def get(cls, name: str, default: bool = False) -> bool:
    """
    Get a external program by name with a default value.

Args:
    name: The name of the external program.
    default: The default value to return if the external program is not found.

Returns:
    The external program if found, otherwise the default value.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## items

```python
@classmethod
def items(cls) -> list[tuple[str, bool]]:
    """
    Get a list of all dependencies as (name, dependency) tuples.

Returns:
    A list of tuples containing dependency names and their corresponding objects.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants

## keys

```python
@classmethod
def keys(cls) -> list[str]:
    """
    Get a list of all external program names.

Returns:
    A list of external program names.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Constants
