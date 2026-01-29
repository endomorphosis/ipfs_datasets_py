"""Compatibility shim for Jsonnet utilities.

Historically, this project exposed Jsonnet helpers as `ipfs_datasets_py.jsonnet_utils`.
The implementation lives in `ipfs_datasets_py.utils.jsonnet_utils`.

This wrapper exists so tests can monkeypatch module-level flags like
`HAVE_JSONNET` and `_jsonnet` on *this* module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ipfs_datasets_py.utils import jsonnet_utils as _impl

# Re-export dependency flags so tests can monkeypatch them here.
HAVE_JSONNET = getattr(_impl, "HAVE_JSONNET", False)
HAVE_ARROW = getattr(_impl, "HAVE_ARROW", False)
_jsonnet = getattr(_impl, "_jsonnet", None)


class JsonnetConverter(_impl.JsonnetConverter):
	"""Proxy converter that respects monkeypatching on this shim module."""

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		# Keep the underlying implementation module in sync with shim globals.
		_impl.HAVE_JSONNET = HAVE_JSONNET
		_impl._jsonnet = _jsonnet
		super().__init__(*args, **kwargs)


def jsonnet_to_json(
	jsonnet_str: str,
	ext_vars: Optional[Dict[str, str]] = None,
	tla_vars: Optional[Dict[str, str]] = None,
) -> str:
	"""Evaluate Jsonnet string to JSON."""

	return JsonnetConverter().jsonnet_to_json(jsonnet_str, ext_vars=ext_vars, tla_vars=tla_vars)


def jsonnet_to_jsonl(
	jsonnet_str: str,
	output_path: str,
	ext_vars: Optional[Dict[str, str]] = None,
	tla_vars: Optional[Dict[str, str]] = None,
) -> str:
	"""Convert Jsonnet array to JSONL file."""

	return JsonnetConverter().jsonnet_to_jsonl(
		jsonnet_str,
		output_path,
		ext_vars=ext_vars,
		tla_vars=tla_vars,
	)


def jsonl_to_jsonnet(
	jsonl_path: str,
	output_path: Optional[str] = None,
	pretty: bool = True,
) -> str:
	"""Convert JSONL file to Jsonnet (string or file)."""

	return JsonnetConverter().jsonl_to_jsonnet(
		jsonl_path,
		output_path=output_path,
		pretty=pretty,
	)


__all__ = [
	"HAVE_JSONNET",
	"HAVE_ARROW",
	"_jsonnet",
	"JsonnetConverter",
	"jsonnet_to_json",
	"jsonnet_to_jsonl",
	"jsonl_to_jsonnet",
]
