"""Read an isolated staged index against a finite expected map; mutate no Git.

Call only after root has staged its reviewed contribution. Ordinary blobs are
checked by bytes/SHA256; gitlinks require an explicit immutable commit identity.
No worktree discovery, fetching, staging, checkout, commit or merge occurs here.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

F = Path(__file__).resolve().parent
REPOS = {str(F / "datasets"), str(F / "workspace")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(repo, *arguments):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *arguments],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def main():
    require(len(sys.argv) == 5, "isolated repo, expected-map path, expected-map SHA and new receipt filename required")
    repo, expected_path = Path(sys.argv[1]), Path(sys.argv[2])
    require(str(repo) in REPOS and repo.resolve() == repo, "only the two isolated contribution repos may be observed")
    require(expected_path.parent == F and expected_path.resolve() == expected_path and expected_path.is_file()
            and not expected_path.is_symlink(), "ordinary owned finite expected map required")
    raw = expected_path.read_bytes()
    require(len(raw) <= 2_000_000, "finite expected-map byte bound exceeded")
    require(hashlib.sha256(raw).hexdigest() == sys.argv[3], "exact expected map SHA differs")

    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate expected-map JSON key")
            result[key] = value
        return result

    def unsupported_number(value):
        raise ValueError("noninteger/nonfinite expected-map metadata refused")

    expected = json.loads(raw, object_pairs_hook=unique, parse_float=unsupported_number, parse_constant=unsupported_number)
    require(type(expected) is dict and 0 < len(expected) <= 1000, "bounded finite expected staged-path map required")
    changed = git(repo, "diff", "--cached", "--name-only", "-z", "HEAD").decode().split("\0")[:-1]
    require(set(changed) == set(expected) and len(changed) == len(expected), "staged changed-path inventory differs")
    raw_index = git(repo, "ls-files", "--stage", "-z")
    staged = {}
    for entry in raw_index.decode().split("\0")[:-1]:
        metadata, path = entry.split("\t", 1)
        mode, identity, stage = metadata.split(" ")
        if path in expected:
            require(stage == "0" and path not in staged, "unmerged/duplicated contribution stage")
            staged[path] = dict(mode=mode, object_id=identity)
    require(set(staged) == set(expected), "closed staged objects missing")
    for path, value in expected.items():
        require(not Path(path).is_absolute() and ".." not in Path(path).parts, "ordinary repository-relative path required")
        record = staged[path]
        require(record["mode"] == value["mode"], "staged mode differs")
        if record["mode"] == "160000":
            require(set(value) == {"mode", "object_id"} and record["object_id"] == value["object_id"], "exact gitlink differs")
        else:
            require(record["mode"] in {"100644", "100755"} and set(value) == {"mode", "bytes", "sha256"},
                    "ordinary closed staged blob descriptor required")
            require(type(value["bytes"]) is int and value["bytes"] >= 0, "exact integer staged blob bytes required")
            blob = git(repo, "cat-file", "blob", record["object_id"])
            require(len(blob) == value["bytes"] and hashlib.sha256(blob).hexdigest() == value["sha256"], "staged blob bytes differ")
            record.update(bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())
    output = F / sys.argv[4]
    require(output.parent == F and output.resolve() == output and not output.exists(), "new owned observation filename required")
    result = dict(schema="temporal-binding-closed-stage-observation/v1", passed=True, findings=[], repo=str(repo),
                  HEAD=git(repo, "rev-parse", "HEAD").decode().strip(),
                  expected_map=dict(path=str(expected_path), bytes=len(raw), sha256=sys.argv[3]),
                  staged_paths=len(staged), objects=staged, git_mutations=False)
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps(dict(status="observed_only_no_git_mutation", paths=len(staged))))


if __name__ == "__main__":
    main()
