from dataclasses import dataclass, field
from types_ import Any, Content


@dataclass
class SanitizedContent:
    """Sanitized content from a file.
    
    This class extends the base Content class with sanitization information.
    
    Attributes:
        sanitization_applied (list[str]): list of sanitization techniques applied.
        removed_content (dict[str, Any]): Information about content that was removed.
    """
    content: Content
    sanitization_applied: list[str] = field(default_factory=list)
    removed_content: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary.

        Returns:
            A dictionary representation of the sanitized content.
        """
        result = self.content.to_dict()
        result["sanitization_applied"] = self.sanitization_applied
        result["removed_content"] = self.removed_content
        return result
