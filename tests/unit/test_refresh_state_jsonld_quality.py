from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "ops" / "legal_data" / "refresh_state_jsonld_quality.py"
    spec = importlib.util.spec_from_file_location("refresh_state_jsonld_quality", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_keyboard_interrupt_emits_json(monkeypatch, capsys) -> None:
    module = _load_module()

    monkeypatch.setattr(
        "sys.argv",
        [
            "refresh_state_jsonld_quality.py",
            "--state",
            "HI",
            "--target-lines",
            "40",
            "--min-full-text-chars",
            "160",
        ],
    )

    def _raise_interrupt(coro):
        coro.close()
        raise KeyboardInterrupt()

    monkeypatch.setattr(module.asyncio, "run", _raise_interrupt)

    rc = module.main()
    assert rc == 130

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == "HI"
    assert payload["status"] == "error"
    assert payload["error_type"] == "KeyboardInterrupt"


def test_main_exception_emits_json(monkeypatch, capsys) -> None:
    module = _load_module()

    monkeypatch.setattr(
        "sys.argv",
        [
            "refresh_state_jsonld_quality.py",
            "--state",
            "UT",
            "--target-lines",
            "55",
            "--min-full-text-chars",
            "200",
        ],
    )

    def _raise_error(coro):
        coro.close()
        raise RuntimeError("boom")

    monkeypatch.setattr(module.asyncio, "run", _raise_error)

    rc = module.main()
    assert rc == 1

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == "UT"
    assert payload["status"] == "error"
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "boom"


def test_main_success_path_returns_zero(monkeypatch, capsys) -> None:
    module = _load_module()

    monkeypatch.setattr(
        "sys.argv",
        [
            "refresh_state_jsonld_quality.py",
            "--state",
            "IN",
            "--target-lines",
            "40",
            "--min-full-text-chars",
            "160",
        ],
    )

    def _success(coro):
        coro.close()
        return {"state": "IN", "selected": "after"}

    monkeypatch.setattr(module.asyncio, "run", _success)

    rc = module.main()
    assert rc == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == "IN"
    assert payload["selected"] == "after"
