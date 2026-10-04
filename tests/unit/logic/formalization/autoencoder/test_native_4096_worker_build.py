"""Model-free build/provenance tests; compilation belongs to reserved preflight."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


P = Path(__file__).resolve().parents[5]
spec = importlib.util.spec_from_file_location("native_worker_build_test_owner", P / "scripts/ops/autoencoder/build_leanstral4096_worker.py")
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)


def sha(value):
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def installation(tmp_path, monkeypatch):
    package = tmp_path / "package"
    native = tmp_path / "native"
    source = package / owner.SOURCE
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }\n")
    headers = {name: ("header:" + name).encode() for name in owner.HEADER_SHA256}
    headers["ggml/include/extra.h"] = b"extra public header"
    for name, value in headers.items():
        path = native / "source/llama.cpp" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    libraries = native / "build/bin"
    libraries.mkdir(parents=True)
    library_values = {name: ("library:" + name).encode() for name in owner.LIBRARY_SHA256}
    for name, value in library_values.items():
        (libraries / name).write_bytes(value)
    for name, target in owner.LINK_NAMES.items():
        (libraries / ("lib" + name + ".so")).symlink_to(target)
    monkeypatch.setattr(owner, "HEADER_SHA256", {name: sha(headers[name]) for name in owner.HEADER_SHA256})
    monkeypatch.setattr(owner, "LIBRARY_SHA256", {name: sha(value) for name, value in library_values.items()})

    def git_show(command, **kwargs):
        assert command[:2] == ["git", "show"]
        assert command[2].startswith(owner.REVISION + ":")
        assert kwargs["cwd"] == native / "source/llama.cpp"
        assert kwargs["timeout"] == 15
        return headers[command[2].split(":", 1)[1]]

    monkeypatch.setattr(owner.subprocess, "check_output", git_show)
    return package, native


def test_inventory_binds_source_public_headers_and_cpu_libraries(installation):
    package, native = installation
    result = owner.source_inventory(package, native)
    assert str(package / owner.SOURCE) in result["inputs"]
    assert str(native / "source/llama.cpp/ggml/include/extra.h") in result["inputs"]
    assert len(result["inputs"]) == 11
    assert all("cuda" not in name for name in result["inputs"])


@pytest.mark.parametrize("kind", ["header", "library", "public_header", "alias", "source_symlink"])
def test_inventory_fails_closed_on_changed_or_redirected_inputs(installation, kind):
    package, native = installation
    if kind == "header":
        (native / "source/llama.cpp/include/llama.h").write_bytes(b"drift")
    elif kind == "library":
        (native / "build/bin/libllama.so.0.0.1").write_bytes(b"drift")
    elif kind == "public_header":
        (native / "source/llama.cpp/ggml/include/extra.h").write_bytes(b"drift")
    elif kind == "alias":
        path = native / "build/bin/libllama.so"
        path.unlink()
        path.symlink_to("libggml.so.0.17.0")
    else:
        source = package / owner.SOURCE
        other = source.with_suffix(".copy")
        source.rename(other)
        source.symlink_to(other)
    with pytest.raises(ValueError):
        owner.source_inventory(package, native)


def test_compile_command_pins_source_and_has_no_cuda_backend(installation, tmp_path):
    inventory = owner.source_inventory(*installation)
    command = owner.compile_command(inventory, tmp_path / "out", Path("/usr/bin/g++"))
    assert command[0] == "/usr/bin/g++"
    assert '-DOWNER_SOURCE_SHA256="' + sha(inventory["source"].read_bytes()) + '"' in command
    assert all("cuda" not in argument.lower() for argument in command)
    assert "-lcrypto" in command and "-lggml-cpu" in command
    assert "-lllama" in command and "-llama" not in command
    assert not any(argument.startswith("-march") for argument in command)


def test_dependency_paths_handle_continuations_spaces_and_relative_paths(tmp_path):
    path = tmp_path / "worker.d"
    path.write_text("worker: relative.h \\\n folder\\ with\\ spaces/header.h /usr/include/stdio.h relative.h\n")
    assert owner.dependency_paths(path) == sorted([
        str(tmp_path / "relative.h"), str(tmp_path / "folder with spaces/header.h"), "/usr/include/stdio.h"])


def test_invalid_dependency_file_is_rejected(tmp_path):
    path = tmp_path / "worker.d"
    path.write_text("not a dependency file")
    with pytest.raises(ValueError, match="lacks target"):
        owner.dependency_paths(path)


def fake_compiler(monkeypatch, output, *, action=None, status=0):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["cwd"] == output
        assert kwargs["stdin"] == owner.subprocess.DEVNULL
        assert set(kwargs["env"]) == {"PATH", "LANG", "LC_ALL", "TMPDIR"}
        assert kwargs["timeout"] == 120
        kwargs["stdout"].write(b"fake compiler receipt; no native execution\n")
        (output / "leanstral4096-worker").write_bytes(b"synthetic executable, never executed")
        (output / "worker.d").write_text("worker: leanstral4096_worker.cpp\n")
        if action:
            action()
        return SimpleNamespace(returncode=status)

    monkeypatch.setattr(owner.subprocess, "run", run)
    return calls


def test_build_only_sanitizes_environment_and_authenticates_artifacts(installation, tmp_path, monkeypatch):
    output = tmp_path / "owned-output"
    monkeypatch.setenv("LD_PRELOAD", "/not/loaded.so")
    monkeypatch.setenv("CXX", "/not/invoked")
    calls = fake_compiler(monkeypatch, output)
    result = owner.build_worker(output, *installation)
    assert len(calls) == 1
    assert result == json.loads((output / "build-manifest.json").read_text())
    assert result["worker_source_sha256"] == sha((installation[0] / owner.SOURCE).read_bytes())
    assert result["compiler_dependencies"] == {str(output / "leanstral4096_worker.cpp"): owner.metadata(output / "leanstral4096_worker.cpp")}
    assert Path(result["executable"]["path"]).stat().st_mode & 0o777 == 0o700
    for key in ("worker_executed", "model_opened", "model_weights_loaded", "encoder_executed", "downloads_performed", "shared_native_source_or_service_modified", "qualified", "admitted"):
        assert result[key] is False


def test_build_rejects_changed_inputs_without_success_manifest(installation, tmp_path, monkeypatch):
    output = tmp_path / "owned-output"
    source = installation[0] / owner.SOURCE
    fake_compiler(monkeypatch, output, action=lambda: source.write_text("changed during compilation"))
    with pytest.raises(ValueError, match="changed during compilation"):
        owner.build_worker(output, *installation)
    assert (output / "build.log").exists()
    assert not (output / "build-manifest.json").exists()


def test_compiler_failure_retains_log_and_does_not_make_success_manifest(installation, tmp_path, monkeypatch):
    output = tmp_path / "owned-output"
    fake_compiler(monkeypatch, output, status=1)
    with pytest.raises(ValueError, match="compilation failed"):
        owner.build_worker(output, *installation)
    assert (output / "build.log").read_bytes()
    assert not (output / "build-manifest.json").exists()


@pytest.mark.parametrize("existing", ["directory", "file", "broken_symlink"])
def test_build_never_overwrites_output(installation, tmp_path, monkeypatch, existing):
    output = tmp_path / "owned-output"
    if existing == "directory":
        output.mkdir()
    elif existing == "file":
        output.write_text("retained")
    else:
        output.symlink_to(tmp_path / "absent")
    monkeypatch.setattr(owner, "source_inventory", lambda *_: pytest.fail("must reject before inventory"))
    with pytest.raises(ValueError, match="fresh owned"):
        owner.build_worker(output, *installation)


def test_missing_compiler_does_not_create_output(installation, tmp_path, monkeypatch):
    output = tmp_path / "owned-output"
    monkeypatch.setattr(owner.shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="compiler required"):
        owner.build_worker(output, *installation)
    assert not output.exists()
