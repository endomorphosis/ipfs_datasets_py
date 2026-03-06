"""Public web_archiving shim for the AutoScraper engine."""

from ..processors.web_archiving.autoscraper_engine import (
	batch_scrape_with_autoscraper,
	create_autoscraper_model,
	list_autoscraper_models,
	optimize_autoscraper_model,
	scrape_with_autoscraper,
)

__all__ = [
	"create_autoscraper_model",
	"scrape_with_autoscraper",
	"optimize_autoscraper_model",
	"batch_scrape_with_autoscraper",
	"list_autoscraper_models",
]
