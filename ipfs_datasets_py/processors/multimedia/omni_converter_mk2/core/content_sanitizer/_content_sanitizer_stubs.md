# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_sanitizer/_content_sanitizer.py'

Files last updated: 1752609374.4353218

Stub file last updated: 2025-07-17 05:40:08

## ContentSanitizer

```python
class ContentSanitizer:
    """
    A class to sanitize content by removing unwanted characters and patterns.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, configs: Configs = None, resources: dict[str, Any] = None):
    """
    Initialize the content sanitizer with injected dependencies.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer

## _remove_active_content

```python
def _remove_active_content(self, text: str) -> tuple[str, int]:
    """
    Remove active content from text.

Args:
    text: The text to sanitize.
    
Returns:
    Tuple of (sanitized text, count of items removed).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer

## _remove_personal_data

```python
def _remove_personal_data(self, text: str) -> tuple[str, int]:
    """
    Remove personal data from text.

Args:
    text: The text to sanitize.
    
Returns:
    Tuple of (sanitized text, count of items removed).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer

## _remove_scripts

```python
def _remove_scripts(self, text: str) -> tuple[str, int]:
    """
    Remove script content from text.

Args:
    text: The text to sanitize.
    
Returns:
    Tuple of (sanitized text, count of items removed).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer

## _sanitize_metadata

```python
def _sanitize_metadata(self, metadata: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Sanitize metadata.

Args:
    metadata: The metadata to sanitize.
    
Returns:
    Tuple of (sanitized metadata, list of removed keys).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer

## sanitize

```python
def sanitize(self, content: "Content") -> SanitizedContent:
    """
    Sanitize content for security.

Args:
    content: The content to sanitize.

Returns:
    Sanitized content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer

## set_sanitization_rules

```python
def set_sanitization_rules(self, rules: dict[str, Any]) -> None:
    """
    Set the dictionary of security rules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentSanitizer
