#!/usr/bin/env python3
"""Build offline runtime v2, with bounded RECORD-verified native dependencies.

No downloads, pip execution, broad host-library mounts, task transitions, or
model calls. Existing images/caches remain intact. Local RECORD hashes attest
installed bytes, not upstream authenticity. ELF loading occurs only inside the
network-disabled, read-only image probe, never in the operator interpreter.
"""
from __future__ import annotations

import argparse
import base64
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile

from packaging.utils import canonicalize_name

from prepare_autoformal_offline_runtime import canonical, digest, local_closure, PURELIB
from run_autoformal_supervisor import pin_accelerate

MAX_FILE = 64 * 1024**2
MAX_BUNDLE = 512 * 1024**2
PROFILE = "autoformal-runtime-v2"
# CLI wrappers are outside site-packages and unused by the Python validator.
# A missing/unknown outside-prefix member is never normalized into a copy path.
EXCLUDED_MEMBERS = {
    "charset-normalizer": {"../../../bin/normalizer"},
    "httpx": {"../../../bin/httpx"},
    "idna": {"../../../bin/idna"},
    "numpy": {"../../../bin/f2py"},
    "spacy": {"../../../bin/spacy"},
    "tqdm": {"../../../bin/tqdm"},
    "typer": {"../../../bin/typer"},
    "weasel": {"../../../bin/weasel"},
    # Never introduce startup execution into the image. setuptools can be
    # imported explicitly; its optional distutils startup shim is not shipped.
    "setuptools": {"distutils-precedence.pth"},
}


def safe_member(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (not value or value == "." or path.is_absolute() or ".." in path.parts
            or str(path) != value or "\\" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("unsafe native runtime member")
    if path.suffix in {".pth", ".dll", ".dylib"} or path.name in {"sitecustomize.py", "usercustomize.py"}:
        raise ValueError("native runtime forbids startup hooks and foreign binaries")
    return path


def elf_identity(raw: bytes, path: str, *, machine: str) -> dict | None:
    """Inspect only ELF headers; never use host ldd or load copied objects."""
    shared_name = re.search(r"\.so(?:\.[0-9.]+)?$", path) is not None
    if not raw.startswith(b"\x7fELF"):
        if shared_name:
            raise ValueError("shared library lacks ELF header")
        return None
    machines = {"aarch64": 183, "x86_64": 62}
    python_abi = re.search(r"\.cpython-(\d+)-", path)
    if python_abi and python_abi.group(1) != "312":
        raise ValueError("native library targets another Python ABI")
    if (len(raw) < 64 or not shared_name or machine not in machines
            or raw[4:7] != bytes([2, 1, 1])):
        raise ValueError("native runtime requires recognized little-endian ELF64 libraries")
    kind, architecture, version = struct.unpack_from("<HHI", raw, 16)
    if kind != 3 or architecture != machines[machine] or version != 1:
        raise ValueError("native runtime ELF architecture or object type differs")
    return {"class": 64, "byte_order": "little", "machine": machine, "type": "shared"}


def verified_file(dist, member, *, machine: str):
    relative = safe_member(str(member))
    root = Path(dist.locate_file("")).absolute()
    path = Path(dist.locate_file(member)).absolute()
    if root.resolve(strict=True) != root or path.resolve(strict=True) != path or not path.is_relative_to(root):
        raise ValueError("native runtime file is not canonical and contained")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise ValueError("native runtime file exceeds bounds")
        raw = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (len(raw) > MAX_FILE or any(getattr(before, k) != getattr(after, k) for k in fields)
            or any(getattr(after, k) != getattr(path.stat(), k) for k in fields)):
        raise ValueError("native runtime file changed during read")
    if member.hash is None:
        if relative.name != "RECORD" or not relative.parent.name.endswith(".dist-info"):
            raise ValueError("native runtime has an unhashed non-RECORD file")
        verification = "record_self_hash_generated_locally"
    else:
        expected = base64.urlsafe_b64encode(bytes.fromhex(digest(raw))).decode().rstrip("=")
        if member.hash.mode != "sha256" or member.hash.value != expected or member.size != len(raw):
            raise ValueError("native runtime RECORD hash or size mismatch: " + str(relative))
        verification = "installed_RECORD_sha256"
    return str(relative), raw, verification, elf_identity(raw, str(relative), machine=machine)


def collect_bundle(distributions, *, base_packages: dict, machine: str, base_paths=()):
    files, excluded, payload, reused, packages, total = [], [], {}, {}, {}, 0
    existing_paths = set(base_paths)
    for name, dist in sorted(distributions.items()):
        packages[name] = dist.version
        if name in base_packages:
            if base_packages[name] != dist.version:
                raise ValueError("native runtime would change an existing distribution: " + name)
            reused[name] = dist.version
            continue
        if not dist.files or len(dist.files) > 12000:
            raise ValueError("native runtime lacks a bounded RECORD inventory: " + name)
        for member in dist.files:
            value = str(member)
            if value in EXCLUDED_MEMBERS.get(name, ()):
                excluded.append({"distribution": name, "path": value,
                                 "reason": "reviewed_nonruntime_entry_not_copied_or_executed"})
                continue
            relative = safe_member(value)
            if "__pycache__" in relative.parts or relative.suffix == ".pyc":
                continue
            path, raw, verification, elf = verified_file(dist, member, machine=machine)
            if path in payload or path in existing_paths:
                raise ValueError("native runtime distributions overlap")
            total += len(raw)
            if total > MAX_BUNDLE or len(files) >= 32000:
                raise ValueError("native runtime bundle exceeds bounds")
            payload[path] = raw
            files.append({"path": path, "sha256": digest(raw), "bytes": len(raw),
                          "distribution": name, "verification": verification, "elf": elf})
    return {"schema": "autoformal.offline-runtime-bundle/v2", "packages": packages,
            "base_packages_reused": reused, "files": files, "excluded": excluded,
            "bytes": total, "pycache_copied": False,
            "trust": "copied bytes checked against local RECORD; base bytes pinned by image ID; not upstream signatures"}, payload


def require_abi(host: dict, image: dict) -> None:
    keys = ("python", "soabi", "machine", "libc", "byteorder", "pointer_bits")
    if (any(host.get(k) != image.get(k) for k in keys) or host["python"] != [3, 12]
            or host["machine"] not in {"aarch64", "x86_64"} or host["libc"][0] != "glibc"
            or image.get("purelib") != PURELIB):
        raise ValueError("host and image native Python ABI differ")


def cached_distribution(path: Path, *, name: str):
    """Admit reviewed wheel-cache distributions, not host-site overrides."""
    versions = {"markupsafe": "3.0.2", "mdurl": "0.1.2"}
    if name not in versions:
        raise ValueError("unreviewed cached distribution")
    if path.absolute() != path.resolve(strict=True) or not path.name.endswith('.dist-info'):
        raise ValueError("cached distribution metadata path must be canonical")
    dist = metadata.Distribution.at(path)
    if canonicalize_name(dist.metadata['Name']) != name or dist.version != versions[name]:
        raise ValueError("cached distribution must match reviewed name/version: " + name)
    return dist


ABI_PROBE = '''import sys,sysconfig,platform,struct,json,pathlib,importlib.metadata as m
root = pathlib.Path(sysconfig.get_path("purelib"))
print(json.dumps({"python":list(sys.version_info[:2]),"soabi":sysconfig.get_config_var("SOABI"),
"machine":platform.machine(),"libc":list(platform.libc_ver()),"byteorder":sys.byteorder,
"pointer_bits":struct.calcsize("P")*8,"purelib":sysconfig.get_path("purelib"),
"packages":{d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions()},
"paths":[str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]}))
'''

VERIFY_IMAGE = r'''
import ctypes, hashlib, importlib.metadata as m, json, os, pathlib
from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name
root = pathlib.Path('/opt/pcpc-runtime/lib/python3.12/site-packages')
raw_manifest = pathlib.Path('/opt/autoformal-runtime-v2/manifest.json').read_bytes()
manifest = json.loads(raw_manifest)
environment = dict(default_environment(), extra='')
for name, version in manifest['packages'].items():
    assert m.version(name) == version, name
    for value in m.requires(name) or []:
        req = Requirement(value)
        if req.marker and not req.marker.evaluate(environment): continue
        assert not req.url and not req.extras, value
        assert canonicalize_name(req.name) in manifest['packages'], value
        assert m.version(req.name) in req.specifier, value
for item in manifest['files']:
    path = root / item['path']
    assert path.is_file() and not path.is_symlink(), item['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
for item in manifest['excluded']:
    if '..' not in pathlib.PurePosixPath(item['path']).parts:
        assert not (root / item['path']).exists(), item['path']
import numpy as np
import spacy
from thinc.api import NumpyOps
assert np.dot(np.array([1, 2]), np.array([3, 4])) == 11
assert NumpyOps().alloc2f(2, 3).shape == (2, 3)
nlp = spacy.blank('en')
nlp.add_pipe('sentencizer')
doc = nlp('The agency shall retain records. It may publish them.')
assert len(list(doc.sents)) == 2 and any(t.text == 'shall' for t in doc)
native = [item for item in manifest['files'] if item['elf']]
handles = [ctypes.CDLL(str(root / item['path']), mode=os.RTLD_NOW | os.RTLD_LOCAL) for item in native]
print(json.dumps({'manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(),
    'files_verified': len(manifest['files']), 'native_libraries_loaded': len(handles),
    'packages': manifest['packages'], 'dependency_closure_passed': True,
    'numpy_smoke': True, 'spacy_smoke': True, 'language_model': 'spacy.blank(en)',
    'model_downloads': False}))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--base-isolation-config", type=Path, required=True)
    parser.add_argument("--markupsafe-distribution", type=Path,
                        help="Canonical cached MarkupSafe 3.0.2 dist-info; all shipped files require RECORD verification.")
    parser.add_argument("--mdurl-distribution", type=Path,
                        help="Canonical cached mdurl 0.1.2 dist-info; all shipped files require RECORD verification.")
    args = parser.parse_args(argv)
    pin_accelerate(args.accelerate_root)
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import implementation_daemon as native
    from ipfs_datasets_py.logic.autoformal.feedback_cycle import check_storage, exclusive_loop
    from ipfs_datasets_py.logic.autoformal.validator_profile import RUNTIME_REQUIREMENTS_V2
    runtime = args.runtime_root.resolve(strict=True)
    with exclusive_loop(runtime):
        check_storage(runtime, 50_000_000_000, reserve=4 * MAX_BUNDLE + 256 * 1024**2)
        directory = Path(tempfile.mkdtemp(prefix="offline-validator-runtime-v2-", dir=runtime))
        report = {"schema": "autoformal.offline-runtime-build/v2", "passed": False,
                  "provider_calls": 0, "tasks_claimed": 0, "published": False,
                  "downloads": False, "old_images_modified": False, "caches_removed": False,
                  "directory": str(directory), "live_repair_qualified": False}
        try:
            config = native.validate_external_provider_isolation_config(json.loads(args.base_isolation_config.read_text()))
            docker = [config.runtime_executable, "--host=" + config.runtime_endpoint]
            def capture(*command):
                return subprocess.check_output([*docker, *command], text=True, timeout=90)
            if "name=rootless" not in json.loads(capture("info", "--format", "{{json .SecurityOptions}}")):
                raise ValueError("native runtime requires rootless Docker")
            def probe(image, program):
                return json.loads(capture("run", "--pull=never", "--rm", "--network=none", "--read-only",
                    "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--pids-limit=128",
                    "--memory=2147483648", "--memory-swap=2147483648", "--cpus=2",
                    "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=67108864", "--env=OPENBLAS_NUM_THREADS=1",
                    "--env=OMP_NUM_THREADS=1", "--entrypoint=/opt/pcpc-runtime/bin/python", image, "-I", "-B", "-c", program))
            baseline = probe(config.image_id, ABI_PROBE)
            host = {"python": list(sys.version_info[:2]), "soabi": sysconfig.get_config_var("SOABI"),
                    "machine": platform.machine(), "libc": list(platform.libc_ver()),
                    "byteorder": sys.byteorder, "pointer_bits": struct.calcsize("P") * 8}
            require_abi(host, baseline)
            report["abi"] = host
            overrides = {}
            report['cached_distributions'] = {}
            for name, path in [('markupsafe', args.markupsafe_distribution), ('mdurl', args.mdurl_distribution)]:
                if path is not None:
                    overrides[name] = cached_distribution(path, name=name)
                    report['cached_distributions'][name] = str(path)
            def distribution(name):
                return overrides[name] if name in overrides else metadata.distribution(name)
            distributions = local_closure(RUNTIME_REQUIREMENTS_V2, max_distributions=96, distribution=distribution)
            manifest, payload = collect_bundle(distributions,
                base_packages={canonicalize_name(n): v for n, v in baseline["packages"].items()},
                machine=host["machine"], base_paths=baseline["paths"])
            manifest.update(base_image=config.image_id, abi=host, requirements=list(RUNTIME_REQUIREMENTS_V2))
            report.update(base_image=config.image_id, packages=manifest["packages"],
                file_count=len(payload), bundle_bytes=manifest["bytes"], manifest_sha256=digest(canonical(manifest)))
            report["base_image_bytes"] = int(capture("image", "inspect", "--format", "{{.Size}}", config.image_id))
            context = directory / "context"
            context.mkdir()
            for relative, raw in payload.items():
                path = context / "packages" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(raw)
                path.chmod(0o644)
            (context / "manifest.json").write_bytes(canonical(manifest))
            dockerfile = (f"FROM {config.image_id}\n"
                f'LABEL org.ipfs-accelerate.pcpc-runtime="{PROFILE}"\n'
                f'LABEL org.ipfs-accelerate.autoformal.bundle-sha256="{report["manifest_sha256"]}"\n'
                f"COPY packages/ {PURELIB}/\n"
                "COPY manifest.json /opt/autoformal-runtime-v2/manifest.json\n")
            (context / "Dockerfile").write_text(dockerfile)
            report["dockerfile_sha256"] = digest(dockerfile.encode())
            image_file = directory / "image-id.txt"
            with (directory / "build.log").open("xb") as stream:
                built = subprocess.run([*docker, "build", "--network=none", "--pull=false", "--rm=false",
                    "--iidfile", str(image_file), str(context)], stdout=stream, stderr=subprocess.STDOUT,
                    env={"HOME": "/nonexistent", "PATH": "/usr/bin:/bin", "DOCKER_BUILDKIT": "0"},
                    timeout=180, check=False)
            report["build_returncode"] = built.returncode
            if built.returncode:
                raise ValueError("native runtime build failed; artifacts retained")
            image = image_file.read_text().strip()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or image == config.image_id:
                raise ValueError("native runtime must have a new immutable image ID")
            report["image_id"] = image
            report["incremental_image_bytes"] = int(capture("image", "inspect", "--format", "{{.Size}}", image)) - report["base_image_bytes"]
            report["verification"] = probe(image, VERIFY_IMAGE)
            if (report["verification"]["manifest_sha256"] != report["manifest_sha256"]
                    or report["verification"]["packages"] != manifest["packages"]):
                raise ValueError("native runtime image differs from verified bundle")
            new_config = config.to_dict()
            new_config.update(image_id=image, image_label=PROFILE)
            native.validate_external_provider_isolation_config(new_config)
            path = directory / "isolation-config.json"
            path.write_bytes(canonical(new_config))
            report.update(isolation_config=str(path), isolation_config_sha256=digest(canonical(new_config)), passed=True)
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        report["retained_runtime_bytes"] = check_storage(runtime, 50_000_000_000,
            reserve=max(0, report.get("incremental_image_bytes", 0)))
        path = directory / "receipt.json"
        with path.open("x") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print(json.dumps({"receipt": str(path), "passed": report["passed"],
                          "image_id": report.get("image_id"), "provider_calls": 0}))
        return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
