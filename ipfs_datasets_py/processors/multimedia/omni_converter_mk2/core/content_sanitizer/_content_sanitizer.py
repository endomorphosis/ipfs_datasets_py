from __future__ import annotations
import re

from types_ import Any, Configs, Content, SanitizedContent, Pattern, Logger


from logger import logger as debug_logger

class ContentSanitizer: # TODO Add more tests for the regex used by this class. There's a LOT of different patterns and rules that need to be tested.
    """
    A class to sanitize content by removing unwanted characters and patterns.
    """

    def __init__(self, 
                 configs: Configs = None, 
                 resources: dict[str, Any] = None
                ):
        """Initialize the content sanitizer with injected dependencies."""
        self.configs = configs
        self.resources = resources

        self._sanitized_content:           SanitizedContent          = self.resources['sanitized_content']
        self._pii_detection:               list[tuple[Pattern, str]] = self.resources['pii_detection_regex']
        self._remove_active_content_regex: list[Pattern]             = self.resources['remove_active_content_regex']
        self._remove_scripts_regex:        list[Pattern]             = self.resources['remove_scripts_regex']
        self._sensitive_keys:              list[str]                 = self.resources['sensitive_keys']
        self._sanitization_rules:          dict[str, bool]           = self.resources['security_rules']
        self._logger:                      Logger                    = self.resources['logger']

    def sanitize(self, content: 'Content') -> SanitizedContent:
        """Sanitize content for security.

        Args:
            content: The content to sanitize.

        Returns:
            Sanitized content.
        """
        if not self._sanitization_rules["sanitize_content"]:
            debug_logger.debug("Content sanitization is disabled, returning content as-is.")
            # Return content as-is if sanitization is disabled
            return self._sanitized_content(
                content=content,
                sanitization_applied=["none"],
                removed_content={}
            )

        text = content.text
        metadata = content.metadata.copy() if content.metadata else {}
        sections = content.sections.copy() if content.sections else []
        applied_sanitizers = []
        removed_content = {}

        # Apply sanitization rules
        text_rules = { 
            "remove_scripts": ("scripts", self._remove_scripts),
            "remove_active_content": ("active_content", self._remove_active_content),
            "remove_personal_data": ("personal_data", self._remove_personal_data),
        }

        for rule, tup in text_rules.items():
            key, func = tup
            if self._sanitization_rules[rule]:
                text, count = func(text)
                if count > 0:
                    applied_sanitizers.append(rule)
                    removed_content[key] = count

        # Remove personal data from metadata
        if self._sanitization_rules["remove_metadata"]:
            metadata, removed_keys = self._sanitize_metadata(metadata)
            if removed_keys:
                applied_sanitizers.append("remove_metadata")
                removed_content["metadata_keys"] = removed_keys

        # Apply the sanitized content back to the content object
        content.metadata = metadata
        content.sections = sections
        content.text = text

        return self._sanitized_content(
            content=content,
            sanitization_applied=applied_sanitizers,
            removed_content=removed_content
        )

    def _remove_scripts(self, text: str) -> tuple[str, int]:
        """
        Remove script content from text.
        
        Args:
            text: The text to sanitize.
            
        Returns:
            Tuple of (sanitized text, count of items removed).
        """
        # Remove the following: script tags, javascript: URLs, VBScript, eval() and similar
        count = 0
        new_text = text
        for regex in self._remove_scripts_regex:
            flags = re.IGNORECASE | re.DOTALL
            new_text, removal_count = re.subn(regex, "", new_text, flags=flags)
            count += removal_count
        return new_text, count

    def _remove_active_content(self, text: str) -> tuple[str, int]:
        """
        Remove active content from text.
        
        Args:
            text: The text to sanitize.
            
        Returns:
            Tuple of (sanitized text, count of items removed).
        """
        # Remove active content like iframes, objects, embeds, applets, forms
        count = 0
        new_text = text
        for regex in self._remove_active_content_regex:
            flags = re.IGNORECASE | re.DOTALL
            new_text, removal_count = re.subn(regex, "", new_text, flags=flags)
            count += removal_count
        return new_text, count

    def _remove_personal_data(self, text: str) -> tuple[str, int]:
        """
        Remove personal data from text.
        
        Args:
            text: The text to sanitize.
            
        Returns:
            Tuple of (sanitized text, count of items removed).
        """
        count = 0
        new_text = text
        # Very basic PII detection and removal (not comprehensive) TODO see core/content_sanitizer/_constants.py for more patterns.
        for pattern, replacement in self._pii_detection:
            new_text, replacements = re.subn(pattern, replacement, new_text)
            count += replacements
        return new_text, count

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Sanitize metadata.
        
        Args:
            metadata: The metadata to sanitize.
            
        Returns:
            Tuple of (sanitized metadata, list of removed keys).
        """
        if not metadata:
            return metadata, []

        removed_keys = []
        sanitized_metadata = {}

        for key, value in metadata.items():
            # Check if key contains sensitive information
            should_remove = False
            for sensitive in self._sensitive_keys:
                if sensitive.lower() in key.lower():
                    removed_keys.append(key)
                    should_remove = True
                    break

            if not should_remove:
                sanitized_metadata[key] = value
        return sanitized_metadata, removed_keys

    def set_sanitization_rules(self, rules: dict[str, Any]) -> None:
        """Set the dictionary of security rules."""
        for key, value in rules.items():
            if key in self._sanitization_rules:
                self._sanitization_rules[key] = value
            else:
                self._logger.warning(f"Unknown security rule: {key}")
        
        self._logger.info("Sanitization rules updated", {"rules": self._sanitization_rules})
