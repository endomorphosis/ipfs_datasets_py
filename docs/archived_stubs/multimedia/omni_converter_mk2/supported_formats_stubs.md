# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/supported_formats.py'

Files last updated: 1750800502.219368

Stub file last updated: 2025-07-17 05:36:42

## ALL_ROADMAP_FORMATS

```python
@_classproperty
def ALL_ROADMAP_FORMATS(cls) -> set[str]:
    """
    All formats from ROADMAP.md (implemented + unimplemented)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## APPLICATION_FORMAT_EXTENSIONS

```python
@_classproperty
def APPLICATION_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping application format names to their supported file extensions.

Example:
    >>> {
    "pdf": frozenset(("pdf",)),
    "json": frozenset(("json", "jsonl")),
    "docx": frozenset(("docx",)),
    "xlsx": frozenset(("xlsx", "xlsm", "xlsb", "xltx", "xltm")),
    "zip": frozenset(("zip",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## ARCHIVE_FORMAT_EXTENSIONS

```python
@_classproperty
def ARCHIVE_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
    """
    Set of supported ZIP formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## AUDIO_FORMAT_EXTENSIONS

```python
@_classproperty
def AUDIO_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping audio format names to their supported file extensions.

Example:
    >>> {
    "mp3": frozenset(("mp3", "mpeg")),
    "wav": frozenset(("wav", "x-wav")),
    "ogg": frozenset(("ogg",)),
    "flac": frozenset(("flac",)),
    "aac": frozenset(("aac",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## CALENDAR_FORMAT_EXTENSIONS

```python
@_classproperty
def CALENDAR_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
    """
    Set of supported calendar formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## CSV_FORMAT_EXTENSIONS

```python
@_classproperty
def CSV_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
    """
    Set of supported CSV formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## DOCUMENT_FORMAT_EXTENSIONS

```python
@_classproperty
def DOCUMENT_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping document format names to their supported file extensions.

Example:
    >>> {
        "docx": frozenset(("docx",)),
        "doc": frozenset(("doc",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## EBOOK_FORMAT_EXTENSIONS

```python
@_classproperty
def EBOOK_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping ebook format names to their supported file extensions.

Example:
    >>> {
        "epub": frozenset(("epub",)),
        "mobi": frozenset(("mobi",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## FORMAT_EXTENSIONS

```python
@_classproperty
def FORMAT_EXTENSIONS(cls) -> dict[str, str]:
    """
    Map of file extensions to formats

Example:
    >>> {
        '.html': 'html',
        '.xml': 'xml',
        '.txt': 'plain',
        ...
        }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## FORMAT_REGISTRY

```python
@_classproperty
def FORMAT_REGISTRY(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping format names to sets of supported file extensions.

Example:
    >>> {
        "audio": {"mp3", "wav", "ogg", "flac", "aac"},
        "video": {"mp4", "webm", "avi", "mkv", "mov"},
        "image": {"jpeg", "jpg", "png", "gif", "webp", "svg+xml"},
        "text": {"html", "xml", "plaintext", "calendar", "csv"},
        "application": {"pdf", "json", "docx", "xlsx", "zip"}
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## FORMAT_SIGNATURES

```python
@_classproperty
def FORMAT_SIGNATURES(cls) -> dict[str, set[str]]:
    """
    Map of MIME types to formats

Example:
    {
    'text/html': 'html',
    'application/xhtml+xml': 'html',
    ...
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## HTML_FORMAT_EXTENSIONS

```python
@_classproperty
def HTML_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    Set of supported HTML formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## IMAGE_FORMAT_EXTENSIONS

```python
@_classproperty
def IMAGE_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping image format names to their supported file extensions.

Example:
    >>> {
    "jpeg": frozenset(("jpeg", "jpg")),
    "png": frozenset(("png",)),
    "gif": frozenset(("gif",)),
    "webp": frozenset(("webp",)),
    "svg": frozenset(("svg",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## PLAINTEXT_FORMAT_EXTENSIONS

```python
@_classproperty
def PLAINTEXT_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    Set of supported plaintext formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## RASTER_IMAGE_FORMAT_EXTENSIONS

```python
@_classproperty
def RASTER_IMAGE_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping raster image format names to their supported file extensions.

Example:
    >>> {
    "jpeg": frozenset(("jpeg", "jpg")),
    "png": frozenset(("png",)),
    "gif": frozenset(("gif",)),
    "webp": frozenset(("webp",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SUPPORTED_APPLICATION_FORMATS

```python
@_classproperty
def SUPPORTED_APPLICATION_FORMATS(cls) -> frozenset[str]:
    """
    Set of supported application formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SUPPORTED_AUDIO_FORMATS

```python
@_classproperty
def SUPPORTED_AUDIO_FORMATS(cls) -> frozenset[str]:
    """
    Set of supported audio formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SUPPORTED_FORMATS

```python
@_classproperty
def SUPPORTED_FORMATS(cls) -> set[str]:
    """
    A set of all supported mime-type formats across categories.

Example:
    >>> {
        "mp3", "wav", "ogg", "flac", "aac",
        "mp4", "webm", "avi", "mkv", "mov",
        "jpeg", "jpg", "png", "gif", "webp", "svg+xml",
        "html", "xml", "plain", "calendar", "csv",
        "pdf", "json", "docx", "xlsx", "zip"
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SUPPORTED_IMAGE_FORMATS

```python
@_classproperty
def SUPPORTED_IMAGE_FORMATS(cls) -> frozenset[str]:
    """
    Set of supported image formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SUPPORTED_TEXT_FORMATS

```python
@_classproperty
def SUPPORTED_TEXT_FORMATS(cls) -> frozenset[str]:
    """
    Set of supported text formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SUPPORTED_VIDEO_FORMATS

```python
@_classproperty
def SUPPORTED_VIDEO_FORMATS(cls) -> frozenset[str]:
    """
    Set of supported video formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## SupportedFormats

```python
class SupportedFormats:
    """
    Utility class for managing supported formats and their extensions.

Properties:
    SUPPORTED_AUDIO_FORMATS (frozenset[str]): Set of supported audio format extensions.
    SUPPORTED_APPLICATION_FORMATS (frozenset[str]): Set of supported application format extensions.
    SUPPORTED_VIDEO_FORMATS (frozenset[str]): Set of supported video format extensions.
    SUPPORTED_IMAGE_FORMATS (frozenset[str]): Set of supported image format extensions.
    SUPPORTED_TEXT_FORMATS (frozenset[str]): Set of supported text format extensions.
    SUPPORTED_FORMATS (frozenset[str]): Set of all supported format extensions across categories.
    FORMAT_REGISTRY (dict[str, frozenset[str]]): Mapping of format categories to their supported extensions.
    FORMAT_SIGNATURES (dict[str, str]): Mapping of MIME types to format names.
    FORMAT_EXTENSIONS (dict[str, str]): Mapping of file extensions to format names.
    TEXT_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Text format names to extensions mapping.
    AUDIO_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Audio format names to extensions mapping.
    APPLICATION_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Application format names to extensions mapping.
    IMAGE_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Image format names to extensions mapping.
    VIDEO_FORMAT_EXTENSIONS (dict[str, frozenset[str]]): Video format names to extensions mapping.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TEXT_FORMAT_EXTENSIONS

```python
@_classproperty
def TEXT_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping format names to their supported file extensions.

Example:
    >>> {
        "html": frozenset(("html", "htm", "xhtml", "xml")),
        "xml": frozenset(("xml",)),
        "plain": frozenset(("txt", "text")),
        "calendar": frozenset(("ics", "ical")),
        "csv": frozenset(("csv",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## TRANSCRIPTION_FORMAT_EXTENSIONS

```python
@_classproperty
def TRANSCRIPTION_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
    """
    Set of supported transcription formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_APPLICATION_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_APPLICATION_FORMATS_SET(cls) -> set[str]:
    """
    Returns a set of application formats that are not currently supported by the converter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_AUDIO_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_AUDIO_FORMATS_SET(cls) -> set[str]:
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_BINARY_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_BINARY_FORMATS_SET(cls) -> set[str]:
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_IMAGE_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_IMAGE_FORMATS_SET(cls) -> set[str]:
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_MESSAGE_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_MESSAGE_FORMATS_SET(cls) -> set[str]:
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_TEXT_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_TEXT_FORMATS_SET(cls) -> set[str]:
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## UNIMPLEMENTED_VIDEO_FORMATS_SET

```python
@_classproperty
def UNIMPLEMENTED_VIDEO_FORMATS_SET(cls) -> set[str]:
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## VECTOR_IMAGE_FORMAT_EXTENSIONS

```python
@_classproperty
def VECTOR_IMAGE_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping vector image format names to their supported file extensions.

Example:
    >>> {
    "svg": frozenset(("svg",)),
    "eps": frozenset(("eps",)),
    "ai": frozenset(("ai",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## VIDEO_FORMAT_EXTENSIONS

```python
@_classproperty
def VIDEO_FORMAT_EXTENSIONS(cls) -> dict[str, frozenset[tuple[str]]]:
    """
    A dictionary mapping video format names to their supported file extensions.

Example:
    >>> {
    "mp4": frozenset(("mp4",)),
    "webm": frozenset(("webm",)),
    "avi": frozenset(("avi",)),
    "mkv": frozenset(("mkv",)),
    "mov": frozenset(("mov",))
    }
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## XML_FORMAT_EXTENSIONS

```python
@_classproperty
def XML_FORMAT_EXTENSIONS(cls) -> frozenset[str]:
    """
    Set of supported XML formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## __contains__

```python
@classmethod
def __contains__(cls, key):
    """
    Check if a key is in the supported formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## __contains__

```python
def __contains__(cls, item: str) -> bool:
    """
    Check if a format is supported (e.g. can be processed).

Args:
    item: The name of the supported format.

Returns:
    Boolean: True if the format is supported, else False.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## __get__

```python
def __get__(self, instance, owner):
```
* **Async:** False
* **Method:** True
* **Class:** _classproperty

## __getitem__

```python
@classmethod
def __getitem__(cls, name: str) -> bool:
    """
    Get a supported format by name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

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
* **Class:** SupportedFormats

## _make_frozen_set_from_frozen_set_dict

```python
def _make_frozen_set_from_frozen_set_dict(set_dict: dict[str, frozenset]) -> frozenset[str]:
    """
    Convert a dictionary of sets into a single set containing all unique elements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## get

```python
@classmethod
def get(cls, name: str, default: bool = False) -> bool:
    """
    Get a supported format by name with a default value.

Args:
    name: The name of the supported format.
    default: The default value to return if the supported format is not found.

Returns:
    The supported format if found, otherwise the default value.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## items

```python
@classmethod
def items(cls) -> list[tuple[str, bool]]:
    """
    Get a list of all supported formats as (name, format) tuples.

Returns:
    A list of tuples containing supported format names and their corresponding objects.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats

## keys

```python
@classmethod
def keys(cls) -> list[str]:
    """
    Get a list of all supported format names.

Returns:
    A list of supported format names.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SupportedFormats
