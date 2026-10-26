"""Parse the ABS ASGS Ed.3 LGA 2025 shapefile .dbf (no geopandas needed)
into a council registry JSONL: code, name, state."""
import json, struct, sys, collections

DBF = sys.argv[1]
OUT = sys.argv[2]

with open(DBF, "rb") as f:
    data = f.read()
nrec = struct.unpack("<I", data[4:8])[0]
hdr_len = struct.unpack("<H", data[8:10])[0]
rec_len = struct.unpack("<H", data[10:12])[0]
fields = []
off = 32
while data[off] != 0x0D:
    name = data[off:off+11].split(b"\x00")[0].decode()
    ftype = chr(data[off+11])
    flen = data[off+16]
    fields.append((name, ftype, flen))
    off += 32
print("fields:", fields, "nrec:", nrec)

rows = []
for i in range(nrec):
    base = hdr_len + i * rec_len + 1
    rec = {}
    pos = base
    for name, ftype, flen in fields:
        raw = data[pos:pos+flen]
        rec[name] = raw.decode("utf-8", "replace").strip()
        pos += flen
    rows.append(rec)

for r in rows[:5]:
    print(r)
codes = [r.get("LGA_CODE25") or r.get("LGA_CODE_2025") or r.get("LGA_CODE") for r in rows]
print("total rows:", len(rows))
print("code sample:", codes[:5])
states = collections.Counter()
out = []
seen = set()
for r in rows:
    code = r.get("LGA_CODE25") or r.get("LGA_CODE_2025") or r.get("LGA_CODE")
    name = r.get("LGA_NAME25") or r.get("LGA_NAME_2025") or r.get("LGA_NAME")
    ste = r.get("STE_NAME21") or r.get("STE_NAME") or ""
    if not code or code in seen:
        continue
    seen.add(code)
    states[ste] += 1
    if code == "ZZZZZ" or code.endswith("9499") or code.endswith("9799"):
        kind = "pseudo"  # No usual address / Migratory-Offshore-Shipping / Outside Australia
    elif name.startswith("Unincorporated") or name.startswith("Unincorp."):
        kind = "unincorporated"
    else:
        kind = "lga"
    out.append({"code": code, "name": name, "state_name21": ste, "kind": kind,
                "area_sqkm": r.get("AREASQKM") or r.get("AREA_SQKM") or ""})
print("unique codes:", len(out))
print("by state field:", dict(states))
with open(OUT, "w") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
