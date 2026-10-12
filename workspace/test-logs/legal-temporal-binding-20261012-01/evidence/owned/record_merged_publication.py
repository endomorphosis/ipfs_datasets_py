"""Observe actual GitHub merges against a closed, previously staged object map.

This reads Git and GitHub metadata. It does not fetch, stage, commit, push or
merge, and it writes only a new owned publication receipt.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

F = Path(__file__).resolve().parent
REPOS = {
    "source": (F / "datasets", "endomorphosis/ipfs_datasets_py"),
    "root": (F / "workspace", "endomorphosis/lift_coding"),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def run(argv):
    return subprocess.check_output(argv)


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def main():
    require(len(sys.argv) == 6, "kind, PR number, closed object map, its SHA and new receipt name required")
    kind, number, map_name, map_sha, output_name = sys.argv[1:]
    require(kind in REPOS and number.isdecimal(), "known repository and PR required")
    root, repo = REPOS[kind]

    def git(*args):
        return run(["git", "--no-optional-locks", "-C", str(root), *args])

    map_path, output = F / map_name, F / output_name
    require(map_path.parent == F and map_path.resolve() == map_path and map_path.is_file(), "owned closed map required")
    require(output.parent == F and output.resolve() == output and not output.exists(), "new owned receipt required")
    map_raw = map_path.read_bytes()
    require(len(map_raw) <= 2_000_000 and hashlib.sha256(map_raw).hexdigest() == map_sha, "bounded independently reviewed map pin required")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate object-map key")
            value[key] = item
        return value

    def invalid_number(value):
        raise ValueError("noninteger/nonfinite object-map metadata refused")

    objects = json.loads(map_raw, object_pairs_hook=unique, parse_float=invalid_number, parse_constant=invalid_number)
    require(type(objects) is dict and 0 < len(objects) <= 1000, "bounded closed map required")
    for path, value in objects.items():
        require(type(path) is str and not Path(path).is_absolute() and ".." not in Path(path).parts, "ordinary relative path required")
        require(type(value) is dict and value.get("mode") in {"100644", "100755", "160000"}, "closed object descriptor required")
        fields = {"mode", "object_id"} if value["mode"] == "160000" else {"mode", "object_id", "bytes", "sha256"}
        require(set(value) == fields and type(value["object_id"]) is str and len(value["object_id"]) == 40, "exact object fields required")
        if value["mode"] != "160000":
            require(type(value["bytes"]) is int and value["bytes"] >= 0 and type(value["sha256"]) is str and len(value["sha256"]) == 64, "exact blob metadata required")
    api = json.loads(run(["gh", "pr", "view", number, "--repo", repo, "--json",
                         "url,state,headRefOid,mergeCommit,mergedAt"]))
    require(api["state"] == "MERGED" and api["mergedAt"], "actual merged PR required")
    own = git("rev-parse", "HEAD").decode().strip()
    require(api["headRefOid"] == own, "actual PR head differs from owned checkout")
    merge = api["mergeCommit"]["oid"]
    parents = git("rev-list", "--parents", "-n", "1", merge).decode().split()
    require(len(parents) == 3 and parents[2] == own, "ordinary exact-head merge required")
    parent = parents[1]

    def tree(commit):
        entries = {}
        for row in git("ls-tree", "-rz", commit).decode().split("\0")[:-1]:
            meta, path = row.split("\t", 1)
            mode, object_kind, identity = meta.split()
            entries[path] = dict(mode=mode, object_kind=object_kind, object_id=identity)
        return entries

    before, after = tree(parent), tree(merge)
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    require(changed == set(objects), "actual first-parent changes differ from closed contribution")
    for path, expected in objects.items():
        actual = after[path]
        require(actual["mode"] == expected["mode"] and actual["object_id"] == expected["object_id"], "merged object differs")
        if actual["mode"] != "160000":
            raw = git("cat-file", "blob", actual["object_id"])
            require(len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"], "merged content differs")
    before_links = {p: d["object_id"] for p, d in before.items() if d["mode"] == "160000"}
    after_links = {p: d["object_id"] for p, d in after.items() if d["mode"] == "160000"}
    if kind == "root":
        require(len(before_links) == len(after_links) == 9, "all nine root gitlinks required")
        require({p: o for p, o in before_links.items() if p != "external/ipfs_datasets"} ==
                {p: o for p, o in after_links.items() if p != "external/ipfs_datasets"}, "parallel gitlink changed")
    value = dict(schema="temporal-binding-actual-merged-publication/v1", passed=True, findings=[],
                 repository=repo, pull_request=api, contribution_head=own, actual_merge=merge,
                 actual_first_parent=parent, closed_objects=pin(map_path), paths=len(objects),
                 first_parent_changes_exactly_owned=True, nonowned_first_parent_objects_preserved=True,
                 before_gitlinks=before_links, after_gitlinks=after_links,
                 scope="Actual Git objects and metadata; no CI, runtime, legal or continuous custody qualification")
    with output.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps(dict(passed=True, merge=merge, parent=parent, paths=len(objects))))


if __name__ == "__main__":
    main()
