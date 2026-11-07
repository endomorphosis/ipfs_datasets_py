"""States lane (2026-10-31): compact append-only deferred.tsv files in place (newest line per key wins, -1 = cleared).
Safe next to a live writer: takes the queue's sidecar flock (<path>.lock, also used by deferq.DeferQueue since
2026-10-31) and re-reads any bytes appended between the scan and os.replace."""
import fcntl, os, sys


def parse(lines, q):
    for line in lines:
        p = line.rstrip("\n").split("\t")
        if len(p) < 2 or not p[0]:
            continue
        try:
            nb = float(p[1])
        except ValueError:
            continue
        if nb < 0:
            q.pop(p[0], None)
        else:
            q[p[0]] = (nb, int(p[2]) if len(p) > 2 and p[2].isdigit() else 1, p[3] if len(p) > 3 else "")


def compact(path):
    lk = open(path + ".lock", "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    try:
        q = {}
        n = 0
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                n += 1
                parse([line], q)
            off = f.tell()
        tmp = path + ".compact.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for k, (nb, c, r) in sorted(q.items()):
                f.write(f"{k}\t{nb:.0f}\t{c}\t{r}\n")
        if os.path.getsize(path) > off:              # appended meanwhile by an old-code writer: apply the tail
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(off)
                tail = f.readlines()
            parse(tail, q)
            with open(tmp, "w", encoding="utf-8") as f:
                for k, (nb, c, r) in sorted(q.items()):
                    f.write(f"{k}\t{nb:.0f}\t{c}\t{r}\n")
        os.replace(tmp, path)
        return n, len(q)
    finally:
        lk.close()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        b = os.path.getsize(p)
        n, k = compact(p)
        print(f"{p}: {n} lines / {b} B -> {k} keys / {os.path.getsize(p)} B", flush=True)
