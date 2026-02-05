import os


def _build_dummy_argument(prompt: str):
    class DummyProp:
        def __init__(self, text: str):
            self.raw_input = False
            self.processed_input = text
            self.prepared_input = ""
            self.prompt = text
            self.instance = None
            self.payload = None
            self.input_handler = None
            self.output_handler = None

    class DummyArgument:
        def __init__(self, text: str):
            self.prop = DummyProp(text)
            self.args = []
            self.kwargs = {}

    return DummyArgument(prompt)


def _run_engine(engine, prompt: str):
    argument = _build_dummy_argument(prompt)
    engine.prepare(argument)
    outputs, metadata = engine.forward(argument)
    assert outputs, "Expected outputs"
    assert isinstance(outputs, list)
    return outputs, metadata


def test_symai_engine_router_smoke():
    try:
        from symai.backend.settings import SYMAI_CONFIG
    except Exception:
        print("SyMAI not available; skipping router smoke test.")
        return

    os.environ["IPFS_DATASETS_PY_SYMAI_ROUTER_DRY_RUN"] = "1"

    # Configure router-backed engines.
    SYMAI_CONFIG["SYMBOLIC_ENGINE"] = "ipfs"
    SYMAI_CONFIG["EMBEDDING_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["SEARCH_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["OCR_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["SPEECH_TO_TEXT_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["TEXT_TO_SPEECH_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["DRAWING_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["VISION_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["CAPTION_ENGINE_MODEL"] = "ipfs:default"
    SYMAI_CONFIG["INDEXING_ENGINE_ENVIRONMENT"] = "ipfs:default"

    from ipfs_datasets_py.utils.symai_ipfs_engine import (
        IPFSSyMAIEngine,
        IPFSSyMAISymbolicEngine,
        register_ipfs_symai_engines,
    )

    register_ipfs_symai_engines()

    engines = [
        IPFSSyMAISymbolicEngine("symbolic", "SYMBOLIC_ENGINE"),
        IPFSSyMAIEngine("embedding", "EMBEDDING_ENGINE_MODEL", mode="embedding"),
        IPFSSyMAIEngine("search", "SEARCH_ENGINE_MODEL"),
        IPFSSyMAIEngine("ocr", "OCR_ENGINE_MODEL"),
        IPFSSyMAIEngine("speech_to_text", "SPEECH_TO_TEXT_ENGINE_MODEL"),
        IPFSSyMAIEngine("text_to_speech", "TEXT_TO_SPEECH_ENGINE_MODEL"),
        IPFSSyMAIEngine("drawing", "DRAWING_ENGINE_MODEL"),
        IPFSSyMAIEngine("vision", "VISION_ENGINE_MODEL"),
        IPFSSyMAIEngine("caption", "CAPTION_ENGINE_MODEL"),
        IPFSSyMAIEngine("indexing", "INDEXING_ENGINE_ENVIRONMENT"),
    ]

    for engine in engines:
        outputs, metadata = _run_engine(engine, "Ping")
        assert metadata.get("backend") == "dry_run"