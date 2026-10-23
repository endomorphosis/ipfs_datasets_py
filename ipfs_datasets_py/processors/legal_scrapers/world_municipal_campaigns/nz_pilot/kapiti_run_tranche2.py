"""Tranche-2 Kāpiti runner: sets the tranche date, then nz_kapiti.main()."""
import nz_tranche1 as T

T.TODAY = "2026-10-14"

import nz_kapiti  # noqa: E402

if __name__ == "__main__":
    nz_kapiti.main()
