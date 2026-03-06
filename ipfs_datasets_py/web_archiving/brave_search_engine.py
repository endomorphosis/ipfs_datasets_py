"""Public web_archiving shim for Brave search engine."""

from ..processors.web_archiving.brave_search_engine import (
	BraveSearchAPI,
	HAVE_BRAVE_CLIENT,
	batch_search_brave,
	clear_brave_cache,
	get_brave_cache_stats,
	search_brave,
	search_brave_images,
	search_brave_news,
)

__all__ = [
	"BraveSearchAPI",
	"HAVE_BRAVE_CLIENT",
	"search_brave",
	"search_brave_news",
	"search_brave_images",
	"batch_search_brave",
	"get_brave_cache_stats",
	"clear_brave_cache",
]
