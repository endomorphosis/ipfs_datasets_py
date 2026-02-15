import copy
from dataclasses import dataclass, field


from types_ import Any, Content


@dataclass(frozen=True)
class NormalizedContent:
    """
    Normalized content from a file.
    
    This class represents normalized content with normalization metadata.
    
    Attributes:
        text (str): The normalized text content object.
        normalized_by (list[str]): list of normalizers applied to the content.
    """
    content: Content
    normalized_by: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """String representation of the normalized content."""
        return f"NormalizedContent(content={self.content.to_dict()}, normalized_by={self.normalized_by})"

    def __repr__(self) -> str:
        """String representation of the normalized content.
        
        Returns:
            A string representation of the normalized content.
        """
        # Dump the content to a dictionary and format it as a string
        return f"NormalizedContent(content={self.content.to_dict()}, normalized_by={self.normalized_by})"

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary.
        
        Returns:
            A dictionary representation of the normalized content.
        """
        content_dict = self.content.to_dict()
        content_dict.update({
            'normalized_by': self.normalized_by
        })
        return copy.deepcopy(content_dict)
