#!/usr/bin/env python3
"""Re-evaluate 'unmatched' legislation items after place-rule changes (successors, canonical places)."""
import json, sys
sys.argv = [sys.argv[0]]
import legislation_uk as L
R = L.Run()
try:
    rows = R.st.c.execute("SELECT key, info FROM items WHERE status='unmatched'").fetchall()
    todo = []
    for key, info in rows:
        title = json.loads(info)["title"]
        r, how = L.place_for(R.P, title)
        if r:
            todo.append((key, title))
    print("re-evaluating", len(todo), "of", len(rows), flush=True)
    for key, title in todo:
        R.st.c.execute("DELETE FROM items WHERE key=?", (key,)); R.st.c.commit()
        R.handle("ukla" if key.startswith("ukla/") else "lsi", {"id": f"{L.BASE}/id/{key}", "title": title, "xml": []})
finally:
    files = R.flush()
    print(json.dumps({"files": [f.rsplit('/', 1)[1] for f in files], **R.n}))
