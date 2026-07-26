import subprocess
import os

def check_dirty(path):
    if not os.path.isdir(path):
        return False
    try:
        out = subprocess.check_output(["git", "-C", path, "status", "--porcelain"], stderr=subprocess.STDOUT).decode()
        return len(out.strip()) > 0
    except:
        return False

def get_worktrees():
    out = subprocess.check_output(["git", "worktree", "list", "--porcelain"]).decode()
    worktrees = []
    current = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[9:]
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("branch "):
            current["branch"] = line[7:]
    if current:
        worktrees.append(current)
    return worktrees

# Initial list
worktrees = get_worktrees()
main_path = worktrees[0]["path"] if worktrees else ""

removed_count = 0
failures = []

for wt in worktrees:
    path = wt["path"]
    if path == main_path:
        continue
    
    # Task: for each DETACHED non-main worktree path, force remove
    # "detached" implies non-main branch.
    if wt.get("detached"):
        try:
            subprocess.check_call(["git", "worktree", "remove", "--force", path])
            removed_count += 1
        except subprocess.CalledProcessError as e:
            failures.append(f"Failed to remove {path}")

# Run prune
subprocess.call(["git", "worktree", "prune"])

# Recount
worktrees_post = get_worktrees()
total = len(worktrees_post)
detached_clean = 0
detached_dirty = 0
named_non_main = 0
stale = 0

for wt in worktrees_post:
    path = wt["path"]
    if not os.path.exists(path):
        stale += 1
        continue
    
    is_detached = wt.get("detached", False)
    branch = wt.get("branch", "")
    
    if is_detached:
        if check_dirty(path):
            detached_dirty += 1
        else:
            detached_clean += 1
    elif branch:
        # refs/heads/branchname
        bname = branch.split('/')[-1]
        if bname != "main":
            named_non_main += 1

print(f"REMOVED_COUNT: {removed_count}")
print(f"FAIL_COUNT: {len(failures)}")
for f in failures[:10]:
    print(f"FAILURE: {f}")
print(f"TOTAL: {total}")
print(f"DETACHED_CLEAN: {detached_clean}")
print(f"DETACHED_DIRTY: {detached_dirty}")
print(f"NAMED_NON_MAIN: {named_non_main}")
print(f"STALE: {stale}")
