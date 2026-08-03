"""
Compact synthetic office-action text generators for PATLAW-032.

Produces minimal office-action / notice surfaces that exercise:
  - non-final rejections with claim ranges, form paragraphs, citations
  - final rejections and response instructions
  - rescinded / reissued lifecycle
  - malformed / empty / ambiguous claim-range surfaces
  - notices and uncompiled examiner language

Canaries are synthetic markers — not real confidential filings.
Prefer generators over bulk golden dumps.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

NON_FINAL_CANARY = "SYNTHETIC-OA-NONFINAL-112A-CLAIM1"
FINAL_CANARY = "SYNTHETIC-OA-FINAL-103-CLAIMS1-3"
RESCIND_CANARY = "SYNTHETIC-OA-RESCINDED-2026-02-01"
REISSUE_CANARY = "SYNTHETIC-OA-REISSUE-2026-03-01"
MALFORMED_CANARY = "SYNTHETIC-OA-MALFORMED-GARBLED"
AMBIGUOUS_CANARY = "SYNTHETIC-OA-AMBIGUOUS-CLAIMS"
NOTICE_CANARY = "SYNTHETIC-NOTICE-MISSING-PARTS"


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def build_non_final_office_action_text() -> str:
    """Non-final office action with 112(a) rejection, form paragraph, fees, response period."""
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/123,456
Mailing Date: 2026-08-01
Office Action Summary

This is a non-final office action.

Detailed Action

Claim Rejections - 35 U.S.C. § 112(a)

Claim 1 is rejected under 35 U.S.C. 112(a) as failing to comply with the written description requirement.
The specification does not reasonably convey possession of the full scope of claim 1.
See form paragraph 7.30.01. {NON_FINAL_CANARY}

Claim Objections

Claims 2-3 are objected to as being dependent upon a rejected base claim, but would be allowable if rewritten in independent form.

Claim Informalities

Claim 4 contains the following informality: inconsistent antecedent basis for "the module".

Notice of References Cited

U.S. Patent 9,999,999 to Smith.
US 2020/0123456 A1 to Jones.
Non-Patent Literature: Synthetic Examiner Note 2024.

Fee Information

A fee code 1201 may be required for extension of time under 37 C.F.R. 1.136(a).
See also Form PTO/SB/22.

Response Period

A shortened statutory period for reply is set to expire in 3 months from the mailing date of this communication.
Applicant is required to traverse the rejection or amend the claims.
In the alternative, applicant may cancel claim 1 without prejudice.
Unless a complete response is filed, the application may become abandoned.

Conclusion

The examiner notes that further search may be required after amendment.
It is noted that allowable subject matter appears in dependent claim 5.
"""


def build_final_office_action_text() -> str:
    """Final rejection under 103 with multi-claim range and prior art."""
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 15/987,654
Mailing Date: 03/15/2026
Office Action Summary

This action is made final.

Claim Rejections - 35 U.S.C. § 103

Claims 1-3 and 5 are rejected under 35 U.S.C. 103 as being unpatentable over U.S. Patent 8,888,888 in view of US 2019/0111111 A1.
It would have been obvious to one of ordinary skill to combine the teachings. {FINAL_CANARY}
See MPEP § 2141 and form paragraph 7.15.

Response to Arguments

Applicant's arguments filed 2026-01-10 have been fully considered but they are not persuasive.

Period for Reply

A shortened statutory period for reply is set to expire in 3 months.
Applicant must respond to this final office action.
"""


def build_rescinded_action_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/555,000
Mailing Date: 2026-02-01
Office Action Summary

This is a non-final office action. {RESCIND_CANARY}

Claim Rejections - 35 U.S.C. § 103

Claim 1 is rejected under 35 U.S.C. 103 as being unpatentable over U.S. Patent 7,777,777.

Response Period

A shortened statutory period for reply is set to expire in 3 months.
"""


def build_reissued_action_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/555,000
Mailing Date: 2026-03-01
Office Action Summary

This reissued office action supersedes the office action mailed 2026-02-01.
The previous office action is hereby withdrawn. {REISSUE_CANARY}

Claim Rejections - 35 U.S.C. § 103

Claim 1 is rejected under 35 U.S.C. 103 as being unpatentable over U.S. Patent 7,777,777 in view of US 2018/0000001 A1.

Response Period

A shortened statutory period for reply is set to expire in 3 months from the mailing date of this reissued office action.
"""


def build_rescinded_reissued_pair() -> dict[str, Any]:
    """Lifecycle pair: rescinded original + active reissue (compact recipe payload)."""
    original = build_rescinded_action_text()
    reissue = build_reissued_action_text()
    return {
        "actions": [
            {
                "action_id": "oa:original-2026-02-01",
                "status": "rescinded",
                "mailing_date": "2026-02-01",
                "text": original,
                "content_sha256": sha256_hex(original),
            },
            {
                "action_id": "oa:reissue-2026-03-01",
                "status": "active",
                "mailing_date": "2026-03-01",
                "supersedes": "oa:original-2026-02-01",
                "text": reissue,
                "content_sha256": sha256_hex(reissue),
            },
        ]
    }


def build_malformed_office_action_text() -> str:
    """Garbled / incomplete action that should surface as malformed or review."""
    return f"""??? {MALFORMED_CANARY}
cl@imz r3jected under ???
@@@@ form paragraph ??
no mailing date here
"""


def build_empty_office_action_text() -> str:
    return ""


def build_ambiguous_claim_range_text() -> str:
    """Claim ranges that must retain ambiguity (open-ended / approximate)."""
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Office Action Summary

This is a non-final office action. {AMBIGUOUS_CANARY}

Claim Rejections - 35 U.S.C. § 102

Claims about 1-5 are rejected under 35 U.S.C. 102 as being anticipated by U.S. Patent 6,666,666.
Claims all are rejected under 35 U.S.C. 103.
Claims 1-3 and 8 are rejected under 35 U.S.C. 112(b) as being indefinite.

Period for Reply

A shortened statutory period for reply is set to expire in 3 months.
"""


def build_notice_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Notice of Non-Compliant Amendment

Application No.: 16/111,222
Mailing Date: 2026-07-01

{NOTICE_CANARY}
The amendment filed 2026-06-15 is non-compliant under 37 C.F.R. 1.121.
Applicant is required to submit a compliant claim listing.
Fee code 1202 may apply.
"""


def fixture_manifest(output_dir: str | Path) -> dict[str, Any]:
    """Write compact text fixtures and return a manifest (no bulk golden dumps)."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    mapping = {
        "non_final_oa.txt": build_non_final_office_action_text(),
        "final_oa.txt": build_final_office_action_text(),
        "rescinded_oa.txt": build_rescinded_action_text(),
        "reissued_oa.txt": build_reissued_action_text(),
        "malformed_oa.txt": build_malformed_office_action_text(),
        "ambiguous_claims_oa.txt": build_ambiguous_claim_range_text(),
        "notice.txt": build_notice_text(),
    }
    for name, body in mapping.items():
        path = root / name
        path.write_text(body, encoding="utf-8")
        files[name] = sha256_hex(body)
    pair = build_rescinded_reissued_pair()
    pair_path = root / "rescinded_reissued_pair.json"
    pair_path.write_text(
        json.dumps(pair, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files[pair_path.name] = sha256_hex(pair_path.read_bytes())
    manifest = {
        "schema_version": "uspto.office-action-fixture-manifest.v1",
        "files": files,
        "notes": "Synthetic PATLAW-032 generators; not real USPTO filings.",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
