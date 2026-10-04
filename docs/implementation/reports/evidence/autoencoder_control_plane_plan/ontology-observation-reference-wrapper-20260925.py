def _capture_ontology(samples: Sequence[Any]) -> list[dict[str, Any]]:
    """Frame-logic triples already on each sample. Capture never admits a fragment."""

    try:
        from ipfs_datasets_py.logic.autoformal.ontology_capture import capture_samples
    except (ImportError, OSError):
        return []
    try:
        return capture_samples(samples)
    except (TypeError, ValueError):
        return []
