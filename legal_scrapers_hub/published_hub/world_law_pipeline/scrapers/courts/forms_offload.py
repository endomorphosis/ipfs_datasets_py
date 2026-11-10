#!/usr/bin/env python3
"""forms_offload.py - offload world-courts form files to the HF dataset endomorphosis/world_court_forms
and throttle the form downloaders so local staging stays small.

Layout
  local   : /workspace/world_courts/forms/<cc>[/<ST>]/<sha256>.<ext>      (written by us_forms.py, intl/gb_forms.py, ...)
  rows    : /workspace/world_courts/data/*/*_forms*.jsonl                  (pdf_path, pdf_sha256; this tool adds hf_tar / hf_member)
  hub     : pdfs/<cc>/batch-NNNN.tar   (plain tar, member = path relative to forms/<cc>/, e.g. "AK/<sha>.pdf")
            index/forms_index.parquet  (sha256, cc, member, pdf_path, bytes, batch, tar_sha256, ...)
  state   : /workspace/world_courts/forms_offload/state.json  (journal; every step is recorded before the next one)

Per batch pipeline (idempotent + resumable; a crash at any point is picked up by the next run):
  plan/build tar -> self-check members -> upload -> verify on Hub (LFS sha256+size == local tar, or --verify download)
  -> publish index parquet -> add hf_tar to jsonl rows -> delete local files (only if unchanged since packing) -> done
Nothing is deleted before its batch is verified on the Hub. Files seen again after being offloaded (same pdf_path, byte-identical)
are deleted without re-uploading.

Throttle: staging cap (default 3 GB over all forms/ dirs) and min free disk (default 10 GB fleet floor). When over, form downloader
processes (python scripts named *forms*.py living under /workspace/world_courts, except this one) get SIGSTOP and a flag file
forms_offload/PAUSED is written; after an offload frees space they get SIGCONT. Only processes this tool stopped are resumed.

Usage
  forms_offload.py offload [--flush-all] [--target-mb 800] [--min-mb 500] [--verify lfs|download] [--dry-run]
  forms_offload.py throttle            # pause/resume check only
  forms_offload.py cycle               # offload (forced when over cap / low disk) + throttle
  forms_offload.py supervise [--interval 600] [--check-interval 60]   # loop forever (run under nohup setsid)
  forms_offload.py status
Env: HF_TOKEN. Never touches /workspace/ipfs_datasets_py or /workspace/municipal_law.
"""
import os, sys, json, re, time, glob, hashlib, tarfile, signal, fcntl, argparse, shutil, tempfile, datetime, traceback

ROOT = "/workspace/world_courts"
FORMS = ROOT + "/forms"
DATA = ROOT + "/data"
WD = ROOT + "/forms_offload"
STATE = WD + "/state.json"
LOCK = WD + "/offload.lock"
FLAG = WD + "/PAUSED"
TMP = WD + "/tmp"
BACKUPS = WD + "/backups"
REPO = "endomorphosis/world_court_forms"
PIPE_REPO = "endomorphosis/world_law_pipeline"
CAP_BYTES = 3 * 10**9
MIN_FREE_BYTES = 10 * 10**9  # 10 GB fleet floor per Benjamin 2026-11-02
RESUME_CAP_FRAC = 0.9
RESUME_FREE_MARGIN = 2 * 10**9
MIN_AGE_S = 120            # skip files modified in the last 2 min (possibly mid-write)
TARGET_BYTES = 800 * 10**6
MIN_BATCH_BYTES = 500 * 10**6
MAX_BATCH_BYTES = 1000 * 10**6
DL_NAME_RE = re.compile(r"^(?!forms_offload)\w*forms\w*\.py$")


def log(*a):
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------- state
def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"version": 1, "batches": {}, "paused": {}, "stats": {"bytes_deleted": 0, "files_deleted": 0}}


def save_state(st):
    os.makedirs(WD, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=WD, prefix=".state.")
    with os.fdopen(fd, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, STATE)


def sha256_file(p, bs=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(bs)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- disk
def staging_files():
    """all regular files under forms/ -> [(abs, rel_to_ROOT, cc, member, size, mtime_ns)]"""
    out = []
    for cc in sorted(os.listdir(FORMS)) if os.path.isdir(FORMS) else []:
        base = os.path.join(FORMS, cc)
        if not os.path.isdir(base):
            continue
        for d, _, fs in os.walk(base):
            for x in fs:
                p = os.path.join(d, x)
                try:
                    s = os.lstat(p)
                except OSError:
                    continue
                if not os.path.isfile(p) or os.path.islink(p) or x.startswith("."):
                    continue
                out.append((p, os.path.relpath(p, ROOT), cc, os.path.relpath(p, base), s.st_size, s.st_mtime_ns))
    return out


def staging_bytes():
    return sum(f[4] for f in staging_files())


def free_bytes():
    return shutil.disk_usage("/workspace").free


# ---------------------------------------------------------------- hub
def api():
    from huggingface_hub import HfApi
    return HfApi(token=os.environ["HF_TOKEN"])


def retry(fn, *a, tries=5, **k):
    for i in range(tries):
        try:
            return fn(*a, **k)
        except Exception as e:
            if i == tries - 1:
                raise
            w = 10 * (i + 1)
            log("retry", fn.__name__, type(e).__name__, str(e)[:150], "in", w, "s")
            time.sleep(w)


README = """---
license: other
license_name: mixed-government-court-forms
pretty_name: World Court Forms (PDF/DOCX/RTF archive)
tags:
- legal
- court-forms
- law
- pdf
configs:
- config_name: index
  data_files: index/*.parquet
---

# World Court Forms

Archive of blank court / tribunal forms collected for [`endomorphosis/world_courts`](https://huggingface.co/datasets/endomorphosis/world_courts)
(US state judiciaries, Canada, Australia, England & Wales, ...). The structured rows (title, form number, court, source URL,
per-row license and robots policy) live in `world_courts` under `data/forms/<cc>.parquet`; this dataset only stores the
**original files**, packed into plain (uncompressed) tar batches of roughly 0.5-1 GB so the repo stays small in file count.

## Layout

```
pdfs/<cc>/batch-NNNN.tar      # cc = us, gb, ca, au, ...; members are "<ST>/<sha256>.<ext>" (us) or "<sha256>.<ext>"
index/forms_index.parquet     # one row per stored file
```

`index/forms_index.parquet` columns: `sha256` (content hash = file name), `cc`, `member` (path inside the tar),
`pdf_path` (path used in the `world_courts` rows, `forms/<cc>/...`), `bytes`, `ext`, `batch` (repo path of the tar),
`tar_sha256`, `tar_bytes`, `verified_at`.
Join a `world_courts` forms row to its file with `pdf_path` (or `pdf_sha256`); rows also carry `hf_tar` / `hf_member` once offloaded.

## Fetch one file

```python
import tarfile, pandas as pd
from huggingface_hub import hf_hub_download
idx = pd.read_parquet(hf_hub_download("endomorphosis/world_court_forms", "index/forms_index.parquet", repo_type="dataset"))
r = idx[idx.sha256 == "<sha256>"].iloc[0]
tar = hf_hub_download("endomorphosis/world_court_forms", r.batch, repo_type="dataset")
data = tarfile.open(tar).extractfile(r.member).read()
```

## Licensing / provenance

Forms are published by courts and governments. Terms differ by source (e.g. US court forms are generally public
documents, UK forms are OGL / Crown copyright, Canadian federal forms carry a non-commercial government licence).
The authoritative per-form `license`, `source_url` and `site_policy` are in the `world_courts` rows - check them before reuse.

Producer code: `scrapers/courts/forms_offload.py` in [`endomorphosis/world_law_pipeline`](https://huggingface.co/endomorphosis/world_law_pipeline).
"""


def ensure_repo(a):
    a.create_repo(REPO, repo_type="dataset", exist_ok=True, private=False)
    try:
        from huggingface_hub import hf_hub_download
        hf_hub_download(REPO, "README.md", repo_type="dataset", token=os.environ["HF_TOKEN"], force_download=True)
    except Exception:
        retry(a.upload_file, path_or_fileobj=README.encode(), path_in_repo="README.md", repo_id=REPO, repo_type="dataset",
              commit_message="Add dataset card")
        log("created README")


def remote_batch_numbers(a, cc):
    try:
        items = a.list_repo_tree(REPO, path_in_repo=f"pdfs/{cc}", repo_type="dataset")
        nums = [int(m.group(1)) for it in items for m in [re.search(r"batch-(\d+)\.tar$", it.path)] if m]
        return nums
    except Exception:
        return []


def hub_info(a, path):
    infos = retry(a.get_paths_info, REPO, [path], repo_type="dataset", expand=True)
    if not infos:
        return None
    i = infos[0]
    return {"size": i.size, "lfs_sha256": (i.lfs.sha256 if getattr(i, "lfs", None) else None)}


def verify_batch(a, b, mode, tarpath):
    """True only if the Hub copy provably equals the local tar."""
    i = hub_info(a, b["repo_path"])
    if not i:
        return False
    ok = (i["size"] == b["tar_bytes"] and i["lfs_sha256"] == b["tar_sha256"])
    if not ok and i["lfs_sha256"] is None:
        mode = "download"          # not an LFS pointer -> must compare bytes
    if mode == "download":
        from huggingface_hub import hf_hub_download
        p = retry(hf_hub_download, REPO, b["repo_path"], repo_type="dataset", token=os.environ["HF_TOKEN"],
                  cache_dir=TMP + "/hfdl", force_download=True)
        try:
            ok = os.path.getsize(p) == b["tar_bytes"] and sha256_file(p) == b["tar_sha256"]
        finally:
            shutil.rmtree(TMP + "/hfdl", ignore_errors=True)
    return ok


# ---------------------------------------------------------------- processes
def _stat_start(pid):
    try:
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]
    except Exception:
        return None


def _state_char(pid):
    try:
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
    except Exception:
        return None


def find_downloaders():
    res = []
    me = os.getpid()
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == me:
            continue
        pid = int(d)
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            argv = [x.decode("utf-8", "replace") for x in argv if x]
            if not argv or "python" not in os.path.basename(argv[0]):
                continue
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except Exception:
            continue
        script = next((x for x in argv[1:] if x.endswith(".py")), None)
        if not script or not DL_NAME_RE.match(os.path.basename(script)):
            continue
        sp = os.path.realpath(script if os.path.isabs(script) else os.path.join(cwd, script))
        if not sp.startswith(ROOT + "/"):
            continue
        res.append((pid, _stat_start(pid), " ".join(argv)[:120]))
    return res


def pause_downloaders(st, why):
    """SIGSTOP every downloader not already stopped by us. State is persisted BEFORE signalling."""
    newly = []
    for pid, start, cmd in find_downloaders():
        if str(pid) in st["paused"] or _state_char(pid) == "T":
            continue
        st["paused"][str(pid)] = {"start": start, "cmd": cmd, "why": why, "at": now_iso()}
        newly.append(pid)
    if newly:
        save_state(st)
        for pid in newly:
            try:
                os.kill(pid, signal.SIGSTOP)
            except ProcessLookupError:
                st["paused"].pop(str(pid), None)
        save_state(st)
        log("SIGSTOP", newly, why)
    # make sure anything we recorded is actually stopped (e.g. a downloader relaunched with same pid is excluded by start time)
    for pid, v in list(st["paused"].items()):
        if _stat_start(int(pid)) != v["start"]:
            st["paused"].pop(pid)
    return newly


def resume_downloaders(st, only=None):
    done = []
    for pid, v in list(st["paused"].items()):
        if only is not None and int(pid) not in only:
            continue
        if _stat_start(int(pid)) == v["start"]:
            try:
                os.kill(int(pid), signal.SIGCONT)
                done.append(int(pid))
            except ProcessLookupError:
                pass
        st["paused"].pop(pid, None)
    save_state(st)
    if done:
        log("SIGCONT", done)
    return done


def set_flag(on, text=""):
    if on:
        open(FLAG, "w").write(text + "\n")
    elif os.path.exists(FLAG):
        os.remove(FLAG)


def throttle(st, cap=CAP_BYTES, min_free=MIN_FREE_BYTES):
    sb, fb = staging_bytes(), free_bytes()
    over = sb >= cap or fb < min_free
    paused_now = bool(st["paused"]) or os.path.exists(FLAG)
    if over:
        why = f"staging={sb/1e9:.2f}GB cap={cap/1e9:.1f}GB free={fb/1e9:.1f}GB min_free={min_free/1e9:.0f}GB"
        set_flag(True, why)
        pause_downloaders(st, why)
        action = "paused"
    elif paused_now and sb <= cap * RESUME_CAP_FRAC and fb >= min_free + RESUME_FREE_MARGIN:
        resume_downloaders(st)
        set_flag(False)
        action = "resumed"
    else:
        # keep any downloader that (re)appeared while a pause is active stopped
        if os.path.exists(FLAG) and (sb >= cap * RESUME_CAP_FRAC or fb < min_free + RESUME_FREE_MARGIN):
            pause_downloaders(st, "pause flag still set")
        action = "paused(hysteresis)" if os.path.exists(FLAG) else "running"
    log(f"throttle: staging={sb/1e9:.2f}GB free={fb/1e9:.1f}GB -> {action}")
    return action, sb, fb


# ---------------------------------------------------------------- jsonl rows
def row_files():
    return sorted(glob.glob(DATA + "/*/*forms*.jsonl"))


def verified_map(st):
    """pdf_path -> (batch dict, member dict) for every batch whose Hub copy is verified"""
    m = {}
    for b in st["batches"].values():
        if b["status"] in ("verified", "done"):
            for mem in b["members"]:
                m[mem["pdf_path"]] = (b, mem)
    return m


def rows_need_update(vm):
    for f in row_files():
        with open(f, "rb") as fh:
            for line in fh:
                if b'"pdf_path"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                pp = r.get("pdf_path")
                if pp and pp in vm and r.get("hf_tar") != vm[pp][0]["repo_path"]:
                    return True
    return False


def update_rows(st, vm):
    """add hf_tar/hf_member to rows whose file is in a verified batch. Downloaders are SIGSTOPped while jsonl files are
    rewritten IN PLACE (same inode: appenders hold O_APPEND fds) with a backup first. Unparseable lines are kept verbatim."""
    if not rows_need_update(vm):
        return 0
    already = bool(st["paused"])
    newly = [] if already else pause_downloaders(st, "rewriting jsonl rows")
    changed = 0
    try:
        time.sleep(0.5)
        os.makedirs(BACKUPS, exist_ok=True)
        for f in row_files():
            raw = open(f, "rb").read()
            lines = raw.split(b"\n")
            out, n = [], 0
            for line in lines:
                if line.strip() and b'"pdf_path"' in line:
                    try:
                        r = json.loads(line)
                    except Exception:
                        r = None
                    if r is not None:
                        pp = r.get("pdf_path")
                        if pp and pp in vm and r.get("hf_tar") != vm[pp][0]["repo_path"]:
                            r["hf_tar"] = vm[pp][0]["repo_path"]
                            r["hf_member"] = vm[pp][1]["member"]
                            line = json.dumps(r, ensure_ascii=False).encode()
                            n += 1
                out.append(line)
            if n:
                bk = f"{BACKUPS}/{os.path.basename(f)}.{int(time.time())}"
                shutil.copy2(f, bk)
                for old in sorted(glob.glob(f"{BACKUPS}/{os.path.basename(f)}.*"))[:-3]:
                    os.remove(old)
                new = b"\n".join(out)
                with open(f, "r+b") as fh:           # in place: keep inode for running appenders
                    fh.write(new); fh.truncate(); fh.flush(); os.fsync(fh.fileno())
                changed += n
                log(f"rows: {os.path.relpath(f, ROOT)} +hf_tar on {n} rows")
    finally:
        if newly:
            resume_downloaders(st, only=set(newly))
    return changed


# ---------------------------------------------------------------- index parquet
def build_index(st):
    import pandas as pd
    rows = []
    for b in st["batches"].values():
        if b["status"] in ("verified", "done"):
            for m in b["members"]:
                rows.append(dict(sha256=m["sha256"], cc=b["cc"], member=m["member"], pdf_path=m["pdf_path"], bytes=m["bytes"],
                                 ext=os.path.splitext(m["member"])[1].lstrip("."), batch=b["repo_path"],
                                 tar_sha256=b["tar_sha256"], tar_bytes=b["tar_bytes"], verified_at=b.get("verified_at")))
    df = pd.DataFrame(rows).sort_values(["cc", "batch", "member"]).reset_index(drop=True)
    p = WD + "/forms_index.parquet"
    df.to_parquet(p, index=False)
    return p, len(df)


def publish_index(a, st):
    p, n = build_index(st)
    retry(a.upload_file, path_or_fileobj=p, path_in_repo="index/forms_index.parquet", repo_id=REPO, repo_type="dataset",
          commit_message=f"index: {n} files")
    log(f"index published ({n} files)")


# ---------------------------------------------------------------- batches
def plan_batches(st, files, force, target, min_b):
    """-> list of (cc, [file tuples]) to build. Files already in a non-done batch are excluded."""
    inflight = {m["pdf_path"] for b in st["batches"].values() if b["status"] != "done" for m in b["members"]}
    vm = verified_map(st)
    now = time.time()
    by_cc = {}
    for f in files:
        p, rel, cc, mem, size, mt = f
        if rel in inflight or rel in vm:
            continue
        if now - mt / 1e9 < MIN_AGE_S or size == 0:
            continue
        by_cc.setdefault(cc, []).append(f)
    plans = []
    for cc in sorted(by_cc, key=lambda c: -sum(f[4] for f in by_cc[c])):
        fl = sorted(by_cc[cc], key=lambda f: f[1])
        cur, cur_b = [], 0
        for f in fl:
            if cur and cur_b + f[4] > MAX_BATCH_BYTES:
                plans.append((cc, cur)); cur, cur_b = [], 0
            cur.append(f); cur_b += f[4]
            if cur_b >= target:
                plans.append((cc, cur)); cur, cur_b = [], 0
        if cur and (force or cur_b >= min_b):
            plans.append((cc, cur))
    return plans


def next_batch_no(st, a, cc):
    nums = [b["n"] for b in st["batches"].values() if b["cc"] == cc]
    nums += remote_batch_numbers(a, cc)
    return (max(nums) + 1) if nums else 1


def build_tar(st, a, cc, flist):
    n = next_batch_no(st, a, cc)
    key = f"{cc}/{n:04d}"
    name = f"batch-{n:04d}.tar"
    os.makedirs(TMP, exist_ok=True)
    tarp = f"{TMP}/{cc}-{name}"
    members = []
    with tarfile.open(tarp + ".partial", "w", format=tarfile.GNU_FORMAT) as tf:
        for p, rel, _cc, mem, size, mt in flist:
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                data = fh.read()
            if len(data) != size:                       # changed while reading: skip
                continue
            h.update(data)
            ti = tarfile.TarInfo(mem)
            ti.size = len(data); ti.mtime = int(mt // 10**9); ti.mode = 0o644; ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
            import io
            tf.addfile(ti, io.BytesIO(data))
            members.append(dict(pdf_path=rel, member=mem, bytes=size, mtime_ns=mt, sha256=h.hexdigest()))
    if not members:
        os.remove(tarp + ".partial")
        return None
    os.replace(tarp + ".partial", tarp)
    # self-check: re-read the finished tar and compare every member hash
    want = {m["member"]: m["sha256"] for m in members}
    with tarfile.open(tarp) as tf:
        got = {}
        for ti in tf:
            got[ti.name] = hashlib.sha256(tf.extractfile(ti).read()).hexdigest()
    if got != want:
        os.remove(tarp)
        raise RuntimeError(f"tar self-check failed for {key}")
    b = dict(cc=cc, n=n, key=key, repo_path=f"pdfs/{cc}/{name}", tar_local=tarp, tar_bytes=os.path.getsize(tarp),
             tar_sha256=sha256_file(tarp), members=members, status="built", built_at=now_iso())
    st["batches"][key] = b
    save_state(st)
    log(f"built {key}: {len(members)} files, {b['tar_bytes']/1e6:.0f} MB, sha {b['tar_sha256'][:12]}")
    return b


def delete_local(st, b):
    freed = cnt = skipped = 0
    for m in b["members"]:
        p = os.path.join(ROOT, m["pdf_path"])
        try:
            s = os.lstat(p)
        except FileNotFoundError:
            continue
        if s.st_size == m["bytes"] and s.st_mtime_ns == m["mtime_ns"]:
            same = True                     # unchanged since it was packed + verified
        elif s.st_size == m["bytes"] and sha256_file(p) == m["sha256"]:
            same = True                     # re-written with identical bytes
        else:
            same = False
        if not same:
            skipped += 1
            log("keep (changed since packing):", m["pdf_path"])
            continue
        os.remove(p)
        freed += s.st_size; cnt += 1
    st["stats"]["bytes_deleted"] += freed
    st["stats"]["files_deleted"] += cnt
    b["deleted_bytes"] = b.get("deleted_bytes", 0) + freed
    b["deleted_files"] = b.get("deleted_files", 0) + cnt
    return freed, cnt, skipped


def drop_dupes(st):
    """local files that are byte-identical to an already-verified member (re-downloaded) -> delete without re-upload"""
    vm = verified_map(st)
    freed = cnt = 0
    for p, rel, cc, mem, size, mt in staging_files():
        if rel in vm and time.time() - mt / 1e9 > MIN_AGE_S:
            b, m = vm[rel]
            if size == m["bytes"] and sha256_file(p) == m["sha256"]:
                os.remove(p); freed += size; cnt += 1
    if cnt:
        st["stats"]["bytes_deleted"] += freed; st["stats"]["files_deleted"] += cnt
        log(f"dedupe: removed {cnt} already-offloaded files ({freed/1e6:.0f} MB)")
        save_state(st)
    return freed, cnt


def advance(a, st, b, verify_mode, dry):
    key = b["key"]
    if b["status"] == "built":
        tp = b["tar_local"]
        if not (os.path.exists(tp) and os.path.getsize(tp) == b["tar_bytes"] and sha256_file(tp) == b["tar_sha256"]):
            raise RuntimeError(f"{key}: local tar missing/corrupt; remove its entry from state.json to rebuild (local files untouched)")
        if dry:
            log("dry-run: would upload", b["repo_path"]); return False
        t0 = time.time()
        retry(a.upload_file, path_or_fileobj=tp, path_in_repo=b["repo_path"], repo_id=REPO, repo_type="dataset",
              commit_message=f"{b['repo_path']}: {len(b['members'])} files")
        b["status"] = "uploaded"; b["uploaded_at"] = now_iso(); save_state(st)
        log(f"uploaded {key} {b['tar_bytes']/1e6:.0f} MB in {time.time()-t0:.0f}s")
    if b["status"] == "uploaded":
        if not verify_batch(a, b, verify_mode, b["tar_local"]):
            raise RuntimeError(f"{key}: Hub verification FAILED - nothing deleted")
        b["status"] = "verified"; b["verified_at"] = now_iso(); b["verify_mode"] = verify_mode; save_state(st)
        log(f"verified {key} on Hub ({verify_mode})")
    if b["status"] == "verified":
        publish_index(a, st)
        update_rows(st, verified_map(st))
        freed, cnt, sk = delete_local(st, b)
        b["status"] = "done"; b["done_at"] = now_iso()
        save_state(st)
        if os.path.exists(b["tar_local"]):
            os.remove(b["tar_local"])
        log(f"done {key}: deleted {cnt} local files, {freed/1e6:.0f} MB freed, {sk} kept")
    return True


def offload(force=False, target=TARGET_BYTES, min_b=MIN_BATCH_BYTES, verify_mode="lfs", dry=False, max_batches=None):
    st = load_state()
    a = api()
    ensure_repo(a)
    fb0, sb0 = free_bytes(), staging_bytes()
    log(f"offload start: staging={sb0/1e9:.2f}GB free={fb0/1e9:.1f}GB force={force}")
    n_done = 0
    # 1) resume anything in flight
    for key in sorted(st["batches"]):
        b = st["batches"][key]
        if b["status"] != "done":
            log("resuming", key, b["status"])
            if advance(a, st, b, verify_mode, dry):
                n_done += 1
    # 2) already-offloaded files that reappeared; rows for verified batches that lack hf_tar
    if not dry:
        drop_dupes(st)
        update_rows(st, verified_map(st))
    # 3) new batches
    while max_batches is None or n_done < max_batches:
        plans = plan_batches(st, staging_files(), force, target, min_b)
        if not plans:
            break
        cc, fl = plans[0]
        if dry:
            log(f"dry-run: would build {cc} batch of {len(fl)} files {sum(f[4] for f in fl)/1e6:.0f} MB"); break
        b = build_tar(st, a, cc, fl)
        if b is None:
            continue
        advance(a, st, b, verify_mode, dry)
        n_done += 1
    log(f"offload end: batches={n_done} staging={staging_bytes()/1e9:.2f}GB free={free_bytes()/1e9:.1f}GB "
        f"total_deleted={st['stats']['bytes_deleted']/1e6:.0f}MB")
    return n_done


def cycle(args):
    st = load_state()
    sb, fb = staging_bytes(), free_bytes()
    force = args.flush_all or sb >= CAP_BYTES or fb < MIN_FREE_BYTES
    try:
        offload(force=force, target=args.target_mb * 10**6, min_b=args.min_mb * 10**6, verify_mode=args.verify)
    except Exception:
        log("offload error:\n" + traceback.format_exc())
    st = load_state()
    throttle(st)


def status():
    st = load_state()
    sb, fb = staging_bytes(), free_bytes()
    by = {}
    for b in st["batches"].values():
        by.setdefault(b["status"], []).append(b["key"])
    print(json.dumps(dict(staging_gb=round(sb / 1e9, 3), free_gb=round(fb / 1e9, 2), paused=st["paused"], flag=os.path.exists(FLAG),
                          batches={k: len(v) for k, v in by.items()}, stats=st["stats"],
                          downloaders=[(p, c) for p, _, c in find_downloaders()]), indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["offload", "throttle", "cycle", "supervise", "status"])
    ap.add_argument("--flush-all", action="store_true")
    ap.add_argument("--target-mb", type=int, default=TARGET_BYTES // 10**6)
    ap.add_argument("--min-mb", type=int, default=MIN_BATCH_BYTES // 10**6)
    ap.add_argument("--verify", choices=["lfs", "download"], default="lfs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-batches", type=int)
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--check-interval", type=int, default=60)
    args = ap.parse_args()
    os.makedirs(WD, exist_ok=True)
    if args.cmd == "status":
        return status()
    if args.cmd == "supervise":
        sl = open(WD + "/supervisor.lock", "w")
        try:
            fcntl.flock(sl, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("supervisor already running"); return
        log(f"supervisor pid={os.getpid()} interval={args.interval}s check={args.check_interval}s "
            f"cap={CAP_BYTES/1e9}GB min_free={MIN_FREE_BYTES/1e9}GB")
        last_cycle = 0
        while True:
            lk = open(LOCK, "w")
            try:
                fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if time.time() - last_cycle >= args.interval:
                    cycle(args); last_cycle = time.time()
                else:
                    throttle(load_state())          # light pause-only check between offload cycles
            except OSError:
                log("manual offload running; skipping this tick")
            except Exception:
                log("supervisor error:\n" + traceback.format_exc())
            finally:
                lk.close()
            time.sleep(args.check_interval)
    lk = open(LOCK, "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another offload/cycle is already running"); return
    if args.cmd == "offload":
        offload(args.flush_all, args.target_mb * 10**6, args.min_mb * 10**6, args.verify, args.dry_run, args.max_batches)
        if not args.dry_run:
            throttle(load_state())
    elif args.cmd == "throttle":
        throttle(load_state())
    elif args.cmd == "cycle":
        cycle(args)


if __name__ == "__main__":
    main()
