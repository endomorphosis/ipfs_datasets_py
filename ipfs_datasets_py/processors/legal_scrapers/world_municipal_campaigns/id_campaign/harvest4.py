"""Indonesia tranche-4 driver — extends harvest3 (all gates unchanged).

Adds, without modifying the tranche-3 machinery:
  - retries: the tranche-3 retry tail WITHOUT the stock phase's dih
    block (the Aceh loop owns those hosts) and without 6405 (native
    yield proven 0; it goes to the OCR lane instead).
  - pk / wp: adapter drives for the tranche-3 fit-proven units plus
    the bounded no-fit lists.
  - ocr:<bps,...>: harvest3 OCR lane with OCR_UNITS extended for the
    tranche-4 scan candidates (6405, 1813, 5371, 3212).
  - ocr3317: Rembang's 3 over-cap PDFs — the 45 MB cap is raised
    in-process for this run only (47,251,456-byte files, ~65 KB over
    the cap; the tranche-4 brief scopes them in explicitly).
  - ocr3212: Indramayu Drive-catalog top-up; produkhukum is dropped
    from RESOLVER_ADAPTERS for this run because the Drive-table
    candidates already carry direct pdf_url + catalog titles and a
    detail resolution against the catalog page would lose them.

State: env ID_T3_STATE exactly as harvest3 (tranche-4 runs always
pass a tranche-4 state file; the Aceh loop's state is never used).
"""
import os
import sys
from pathlib import Path

CAMP = Path(__file__).resolve().parent
sys.path.insert(0, str(CAMP))

import harvest as H  # noqa: E402
import harvest3 as H3  # noqa: E402

SWING_HOST = H3.SWING_HOST
reg_unit = H3.reg_unit

DOKVIEW_TAIL = ["7318", "7410", "7413", "7472", "7503",
                "7603", "7604", "8207", "9171", "9471"]


def retries_units():
    out = []
    for b in ("3604", "6311"):
        if b in SWING_HOST:
            n, h, a = SWING_HOST[b]
            out.append(dict(bps=b, name=n, host=h, adapter=a,
                            family="swing_t1"))
        else:
            out.append(reg_unit(b, "generic_probe", "unreachable_now"))
    out.append(reg_unit("6303", "banjar", "swing_t1"))
    out += [reg_unit(b, "dokumen_view", "dokumen_view")
            for b in DOKVIEW_TAIL]
    return out


def units_drive(specs, label):
    units = [reg_unit(b, a, a) for b, a in specs]
    H3.drive3(units, label)


def ocr_main(bps_arg):
    H3.OCR_UNITS.update({
        "6405": ("dokumen_view", "dokumen_view"),
        "1813": ("dokumen_view", "dokumen_view"),
        "5371": ("dokumen_view", "dokumen_view"),
        "3212": ("produkhukum", "produkhukum"),
        "3317": ("inventarisasi", "swing_t1"),
    })
    sys.argv = ["harvest3.py", f"ocr:{bps_arg}"]
    H3.main()


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "retries"
    if phase == "retries":
        H3.drive3(retries_units(), "retries-t4")
    elif phase == "pk":
        units_drive([("3328", "produkhukum"), ("3402", "produkhukum"),
                     ("7172", "produkhukum"), ("7202", "produkhukum"),
                     ("7212", "produkhukum"), ("7271", "produkhukum")],
                    "produkhukum-t4")
    elif phase == "wp":
        units_drive([("1407", "wordpress"), ("2103", "wordpress"),
                     ("3206", "wordpress"), ("3214", "wordpress"),
                     ("3505", "wordpress"), ("3520", "wordpress"),
                     ("7208", "wordpress")], "wordpress-t4")
    elif phase == "ocr3317":
        H.MAX_PDF_BYTES = 60 * 1024 * 1024  # this run only; see docstring
        ocr_main("3317")
    elif phase == "ocr3212":
        H.RESOLVER_ADAPTERS.discard("produkhukum")
        ocr_main("3212")
    elif phase.startswith("ocr:"):
        ocr_main(phase.split(":", 1)[1])
    else:
        print("unknown phase", phase)


if __name__ == "__main__":
    main()
