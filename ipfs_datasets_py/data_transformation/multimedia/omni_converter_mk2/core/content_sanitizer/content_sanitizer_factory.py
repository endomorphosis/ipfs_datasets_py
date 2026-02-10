from configs import configs
from logger import logger
from ._content_sanitizer import ContentSanitizer
from ._sanitized_content import SanitizedContent
from ._constants import Constants

def make_content_sanitizer() -> ContentSanitizer:
    """
    Factory function to create a ContentSanitizer instance.

    Returns:
        An instance of ContentSanitizer configured with proper dependencies.
    """
    resources = {
        'sanitized_content': SanitizedContent,
        'pii_detection_regex': Constants.ContentSanitizer.PII_DETECTION_REGEX,
        'remove_active_content_regex': Constants.ContentSanitizer.REMOVE_ACTIVE_CONTENT_REGEX,
        'remove_scripts_regex': Constants.ContentSanitizer.REMOVE_SCRIPTS_REGEX,
        'sensitive_keys': Constants.ContentSanitizer.SENSITIVE_KEYS,
        'security_rules': Constants.ContentSanitizer.SECURITY_RULES,
        'logger': logger
    }
    return ContentSanitizer(configs=configs, resources=resources)
