"""Public web_archiving shim for Google search engine."""

from ..processors.web_archiving.google_search_engine import (
	batch_search_google,
	search_google,
	search_google_images,
)

__all__ = [
	"search_google",
	"search_google_images",
	"batch_search_google",
]
