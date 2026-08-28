"""Target projections for UI/UX IR (web, mobile, glasses)."""

from .glasses import project_to_glasses
from .mobile import project_to_mobile
from .semantic_items import SemanticItem, document_to_semantic_items
from .solver import project_ui_document
from .web import project_to_web

__all__ = [
    "SemanticItem",
    "document_to_semantic_items",
    "project_to_glasses",
    "project_to_mobile",
    "project_to_web",
    "project_ui_document",
]
