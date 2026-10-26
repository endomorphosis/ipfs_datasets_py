import sys
sys.path.insert(0, ".")
import harvest as H, harvest3 as H3

# guard sanity
tests = [
    ("Qanun Kabupaten Aceh Besar Nomor 3 Tahun 2020 Tentang Pajak Daerah", True, False),
    ("QANUN KOTA BANDA ACEH NOMOR 4 TAHUN 2019 TENTANG RETRIBUSI", True, False),
    ("Peraturan Daerah Kabupaten Aceh Besar Nomor 2 Tahun 2020 Tentang X", False, True),
    ("Peraturan Bupati Aceh Besar Nomor 9 Tahun 2020 Tentang X", False, False),
    ("Rancangan Qanun Kabupaten Aceh Besar Tahun 2020", False, False),
    ("Qanun Kabupaten Aceh Besar Nomor 1 Tahun 2021 Tentang Perubahan Peraturan Daerah Nomor 2", True, True),  # heads with Qanun; is_perda_title's loose contains-check also fires, but qanun is always tested first in the Aceh paths
]
for title, want_q, want_p in tests:
    got_q, got_p = H.is_qanun_title(title), H.is_perda_title(title)
    assert (got_q, got_p) == (want_q, want_p), (title, got_q, got_p)
print("guard tests pass")

units = {u["bps"]: u for u in H3.aceh_units()}
print("aceh units:", len(units), "sample host:", units["1116"]["host"])
u = units["1116"]
sess = H.PoliteSession()
base = f'https://{u["host"]}'
cands = H.ENUMERATORS["dih_qanun"](sess, base, u)
q = sum(1 for c in cands.values() if H.is_qanun_title(c["title"]))
p = sum(1 for c in cands.values() if H.is_perda_title(c["title"]))
print(f"1116 enumeration: {len(cands)} candidates = {p} Perda + {q} Qanun")
print("qanun_included bookkeeping:", u.get("dih_qanun_included"),
      "catalog total:", u.get("dih_catalog_total"))
for c in list(cands.values())[:2]:
    print(" sample:", c["tahun"], c["nomor"], c["title"][:80])
