"""Official Arkansas Code inventory from the state-designated Lexis portal.

The Arkansas General Assembly's ``Arkansas Law`` page refers the public to a
free Lexis container provided by the Bureau of Legislative Research.  This
adapter inventories that container without accepting terms, solving a CAPTCHA,
or fetching a robot-gated document body.  The inventory supplies authoritative
title/section locators and a closed-frontier receipt; statute bodies recovered
from mirrors or web archives remain separately attributed recovery material.

Enacted section text is public law.  Copyright banners are therefore neither an
admission nor a rejection signal here.  Publisher annotations and access-control
state are kept out of normalized statute bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .base_scraper import current_state_law_run_environment_value

ENABLE_ENV = "ARKANSAS_LEXIS_PUBLIC_ACCESS_ENABLE"
OFFICIAL_REFERRER = "https://www.arkleg.state.ar.us/ArkansasLaw/"
PUBLIC_ENTRY_URL = "https://www.lexisnexis.com/hottopics/arcode/"
ADVANCE_ORIGIN = "https://advance.lexis.com"
PUBLIC_CONTAINER_CONFIG = (
    "00JAA3ZTU0NTIzYy0zZDEyLTRhYmQtYmRmMS1iMWIxNDgxYWMxZTQK"
    "AFBvZENhdGFsb2cubRW4ifTiwi5vLw6cI1uX"
)
PUBLIC_CONTAINER_URL = f"{ADVANCE_ORIGIN}/container?config={PUBLIC_CONTAINER_CONFIG}"

# Exact official trigger evidence for the one Arkansas contingency that can be
# closed without a notice, certification, or source-body inference.  GPO's
# BILLSTATUS bulk-data object was independently observed on 2026-08-25.  The
# object was last updated after the 116th Congress ended and reports H.R. 5330's
# terminal action as placement on the Union Calendar, with no enacted-law node.
# Act 1032 of 2021 allowed the alternate Arkansas text only if H.R. 5330 became
# law by 2026-01-01, so the exact ``until`` locator remains current.
HR5330_BILLSTATUS_URL = (
    "https://www.govinfo.gov/bulkdata/BILLSTATUS/116/hr/"
    "BILLSTATUS-116hr5330.xml"
)
HR5330_BILLSTATUS_SHA256 = (
    "ff17b359294dd8923472fa3a6fea1f5640776e4b715b6bfc075dce3b2779d122"
)
HR5330_BILLSTATUS_BYTE_SIZE = 12_630
HR5330_LATEST_ACTION_DATE = "2020-12-15"
HR5330_LATEST_ACTION_TEXT = (
    "Placed on the Union Calendar, Calendar No. 537."
)
HR5330_STATUS_UPDATE = "2023-01-11T13:44:05Z"
HR5330_CONGRESS_END_DATE = date(2021, 1, 3)
HR5330_TRIGGER_DEADLINE = date(2026, 1, 1)
ACT1032_URL = (
    "https://www.arkleg.state.ar.us/Acts/FTPDocument?"
    "path=%2FACTS%2F2021R%2FPublic%2F&file=1032.pdf&"
    "ddBienniumSession=2021%2F2021R"
)
ACT1032_SHA256 = (
    "59534f794b626bf9d162fec606eb343c9c5f922a3340a34efd1d2ddfbbfae019"
)
ACT1032_BYTE_SIZE = 308_537

# Act 283 of 2021 makes the state-withholding amendments contingent on a
# multi-agency implementation event.  The Arkansas Code Revision Commission's
# exact official contingency exhibit records DWS's statement that the event
# had not occurred.  The exact official DWS form, observed after the fixed TOC
# inventory, still permits federal withholding only.  These three PDF bodies
# are pinned together: an act alone cannot establish trigger status, and an
# operational form alone cannot identify the governing statutory condition.
ACT283_URL = (
    "https://www.arkleg.state.ar.us/Acts/FTPDocument?"
    "path=%2FACTS%2F2021R%2FPublic%2F&file=283.pdf&"
    "ddBienniumSession=2021%2F2021R"
)
ACT283_SHA256 = (
    "3df754fb7c243c620289f2f05a0381a11f2e787a94b6e1998746ee870320b5a0"
)
ACT283_BYTE_SIZE = 245_707
ACT283_CRC_NONOCCURRENCE_URL = (
    "https://webftp.blr.arkansas.gov/Home/FTPDocument?"
    "path=Assembly%2FMeeting+Attachments%2F630%2F26263%2FExhibit+E1.pdf"
)
ACT283_CRC_NONOCCURRENCE_SHA256 = (
    "09fb6ff50d24402023c3446823629d6830864997fb87bc30ae3348ecb31473b1"
)
ACT283_CRC_NONOCCURRENCE_BYTE_SIZE = 150_593
ACT283_CRC_NONOCCURRENCE_STATEMENT = (
    "According to the Division of Workforce Services, this contingency has "
    "not been met."
)
ACT283_DWS_CURRENT_FORM_URL = (
    "https://dws.arkansas.gov/wp-content/uploads/"
    "DWS-ARK-501_6_Notice_to_UI_Withholding_LPS_4.pdf"
)
ACT283_DWS_CURRENT_FORM_SHA256 = (
    "00eca78717a0ce162e2d2d778348c2a25fc2f19c6e5da7c84e769ae349d5a40a"
)
ACT283_DWS_CURRENT_FORM_BYTE_SIZE = 141_982
ACT283_DWS_CURRENT_FORM_STATEMENT = (
    "The Arkansas Division of Workforce Services can make a deduction for "
    "federal income tax only."
)
ACT283_CURRENT_EVIDENCE_NOT_BEFORE = datetime.fromisoformat(
    "2026-08-25T04:32:58.722528+00:00"
)
ACT283_EXCLUSION_DISPOSITION = "future_contingent_not_yet_effective"
ACT283_DECISION_REASON = (
    "official_crc_nonoccurrence_and_current_dws_operation_prove_act283_"
    "contingency_not_met"
)
ACT283_VARIANT_CONTRACT = (
    (
        "11-10-803",
        "AALAAKAAJAAE",
        (
            "/shared/document/statutes-legislation/"
            "urn:contentItem:4WVD-J370-R03N-P1NN-00008-00"
        ),
        (
            "11-10-803. Withdrawals. [Effective until contingency in Acts "
            "2021, No. 283, §  3 is met.]"
        ),
        "AALAAKAAJAAF",
        (
            "/shared/document/statutes-legislation/"
            "urn:contentItem:62N9-CKR0-R03N-V4W1-00008-00"
        ),
        (
            "11-10-803. Withdrawals. [Effective if contingency in Acts 2021, "
            "No. 283, §  3 is met.]"
        ),
    ),
    (
        "26-51-905",
        "ABAAAFAACAAKAAG",
        (
            "/shared/document/statutes-legislation/"
            "urn:contentItem:4WVP-0VS0-R03J-S4T1-00008-00"
        ),
        (
            "26-51-905. Withholding of tax. [Effective until contingency in "
            "Acts 2021, No. 283, § 3 is met.]"
        ),
        "ABAAAFAACAAKAAH",
        (
            "/shared/document/statutes-legislation/"
            "urn:contentItem:62N9-G2T0-R03N-J4W2-00008-00"
        ),
        (
            "26-51-905. Withholding of tax. [Effective if  contingency in "
            "Acts 2021, No. 283, § 3 is met.]"
        ),
    ),
)
HR5330_VARIANT_SECTION = "16-56-106"
HR5330_UNTIL_NODE_ID = "AAQAAFAADAACAAH"
HR5330_UNTIL_LINK_HREF = (
    "/shared/document/statutes-legislation/"
    "urn:contentItem:681V-8950-R03K-G0T5-00008-00"
)
HR5330_UNTIL_TITLE = (
    "16-56-106. Recovery of charges for medical services. "
    "[Effective until contingency in Acts 2021, No. 1032, § 2, is met.]"
)
HR5330_IF_NODE_ID = "AAQAAFAADAACAAI"
HR5330_IF_LINK_HREF = (
    "/shared/document/statutes-legislation/"
    "urn:contentItem:4WVF-H910-R03K-54KW-00008-00"
)
HR5330_IF_TITLE = (
    "16-56-106. Recovery of charges for medical services. "
    "[Effective if contingency in Acts 2021, No. 1032, § 2, is met.]"
)
CURRENT_VARIANT_RESOLVER_PARSER_NAME = "ArkansasCurrentVariantResolution"
ARKANSAS_DELEGATED_INVENTORY_SHA256 = (
    "af92fd2d12405dfe5246ab50563dc9031180b82c8d0fa0e5336e9580f2085475"
)
ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256 = (
    "d2fc5ad212cb87810121667c439cd56ba6d51d8db1e986af4f9b8b897d4c4b55"
)


def _arkansas_2025_change_table_url(title_number: int) -> str:
    return (
        "https://www.arkleg.state.ar.us/Acts/CodeSection?"
        f"section={title_number}&ddBienniumSession=2025%2F2025R"
    )


def _arkansas_2025_act_url(act_number: int) -> str:
    return (
        "https://www.arkleg.state.ar.us/Acts/FTPDocument?"
        "path=%2FACTS%2F2025R%2FPublic%2F&"
        f"file={act_number}.pdf&ddBienniumSession=2025%2F2025R"
    )


_ARKANSAS_ENACTMENT_TOC_CHANGE_TABLE_SHA256 = {
    4: "3734e6e17491c739440a4ef240268cc2e95e2786008a69616efdc67214364362",
    6: "876dd4925c3be77dede5045f069ecbba3aaf24ed1c563dbb02603410ec7b3ae6",
    7: "4a9e204a69f3727f9a90131d3054e2397611234af0e35d64500191da0e44bc7d",
    8: "7235110d3e78a97d0fc1f890f625d401c3e755488aadf5e01149102a624a5492",
    10: "9d62bb92ef67ecfae4c32cff748b7392524c7744973d2777bfb7b1d15ac3cd34",
    14: "a5bbf1c2ea62508426340b257f236c70934db03c9a357062dcf40e2c3f766b0c",
    15: "7bf3d7c7e62b873d1d83e9ada4e85c36aa0e5056394f3113393dff6da64301be",
    16: "f763d3c8c433b512385e3452bdd34314ce6cd9ddb28451bf6c2debea457afeef",
    17: "817773045b55e7e52c4e7ebeffb8f33cbc9f2933ad366bda077ef2e886d5d878",
    19: "a8f44cf1457651b77afd8e343b7d08628b72259c7c6f581f08047fd112df0851",
    21: "2f563a00ae36ff5fc99a517bbe8d73a0d9537e1871a7a8f500f9e9f51cfd6fac",
    23: "5178070bc931f9766f31c96ec9c54b48445e1ebb114a7cc5c85d9d0d4f9b0ec4",
    24: "deeb88176796d0d861faed984af5960ae5a8b9fdadbecbaed7a2e65582b3b636",
    25: "3b77bbaf3e8ad5109d99abde24e3bf522c4c16b0f1cbb7d88a54c2f6cf0028b6",
    26: "c1b6f4c055e466c8972ab035656c0c1a9de13a0cc8967e9b3c2f6bc3eb30539e",
}
_ARKANSAS_ENACTMENT_TOC_ACT_SHA256 = {
    2: "cf952d55b9bf8e42ecb8847d90712e67ff4f28ab6611b6622983c66865d74b64",
    10: "a096adb1a7afebc78a1967e9acffb2e09ea9871b265c27993bd4575c6399d9b4",
    24: "c9ced0141731b9fd9687bbee9096dd6bd43f19f7b1b7396b0d97e2b8178af561",
    25: "932037076cdef651430de1c143768dc84b844a271e0e5281aeb8a0cceb6af46b",
    26: "55dc3931693d4c31b95839f9ab9d461a0d708fa14457ed46b2c3ac6efb5839bd",
    112: "3a52db5e564750b823245f64c210f2dde63ffc72fc32fb5c7e4713fca7dffae9",
    123: "426534a83c1856ebd499712673dd02e156461dd489923238da9402ea7f9e499d",
    153: "d27d4d824d9708e4b9371dde1dfd469a1beed588a4f5e29c625e3f73755ce88d",
    154: "e2e0663e40d9451732e27c294a645a27d994130226e791526e5ac991382a53ba",
    205: "1500bfedf9a5bf840a287d5c55472f0f02eb3ca5b4c234c7175b974e8e18844d",
    218: "367265f73721d2fb7eaaa6c7a6e5a1103400f17d40b8901f9eb7156fadb82f9a",
    234: "46b0ba130ec09ae034c1aa9c916838398b0df909019b7dbfd271b5d059ce7937",
    240: "ce39519f8aa03694e5ab91a20d8822f8e1e4f0826d2e554c5ebc203eaebbf466",
    272: "a6852cc03cc97eb535b978b2f9f01853e14072493d9842b5b0320a89b63a8c39",
    273: "30804a307943aec85e2a426176eb8c1bb26d0d1f8031b1e1cdbc7a736f81ac41",
    274: "385e15e7659e0f036007d606667228698887e143feb1e40d3648043892d40f52",
    292: "187144f083af9f3443eb88351a0243f4288cd999c1162e912c24b99c2b38b44b",
    314: "7c292116b8ccae5540ef24aa299c392def293f2fc8611da77a887b7d4081c8e7",
    340: "2c4e66bb6d7313d1c499268b747a443e5b998c18929f916c2f8864af883f02bc",
    341: "772a439513416b6376340ba971b7bfa02fea966c2546ae3310be40a0fe7a7211",
    373: "fa0ad2a4dd3cef14da56065a2cd128caa29cacb4db3eb7544b4a67eecf4341c4",
    380: "350b5f828c71626101f6af2e2da0176eca4d986b6204347f74328bb11db1c32d",
    407: "a5361fc616adac1c32f88a449c0b8a6df27ed6124deedad62367c57f406d1569",
    419: "5507bef690ecffd984e16d83478224912d3e03103cd6a52c3c9fed7c35b149dd",
    453: "48bbe38662a26db3bd58feb76c75f957e80dcf1a372447bdcb25c5374ae8c510",
    602: "94ae5498873c964a5c1316f53108cdbe11ab299600cda2b1dbbacc25dda44ba7",
    616: "2acabbe4ec7431296c9b9d7bbed4c8febfea234d4d93f687235634e7fdc03244",
    701: "d2e294dbdcd7df5ce1bffb782f81f395d4f08692a885e5de3028a7883914d8e3",
    705: "bef9c4cd2df82e99f7a0f9b0aa4af5cf05ec0ae7916c57c1c2d2fea0b303683a",
    709: "9366f85bcaafc789ca1157005407c95097d6ab277d34bef7654a59df9ff590df",
    719: "eb2300aff5629bd57ca0beee2544344b47154e9555944b5c165a404547e79e6f",
    768: "69854ad9f678f824a7307ef7272d2388c7a9f9c3c86c6b03f5d36852217ddb33",
    815: "fde8b8fa796751d92c7e5544225c14eee4b2e1cc8ba0a69e92625222fad6c55b",
    876: "05f0a17aebe0a0f20b268e7e1ac81019b241f08bd0a8fe7ea1c651f00b0c7f4e",
    880: "ddbb49666ec85a5550421ac0b10f06dc374c961aeca183aac69b7edd0344170c",
    997: "cfc81fbc42576c7c30941f2c4727bd19247f8910b71afb44af80cbc963362915",
    1003: "4e99e09e1f25e616ac873248facb417d875b45bf31c9b41faa5a7526b602ac45",
}
ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT = {
    **{
        f"T{title}": (_arkansas_2025_change_table_url(title), digest)
        for title, digest in _ARKANSAS_ENACTMENT_TOC_CHANGE_TABLE_SHA256.items()
    },
    **{
        f"A{act}": (_arkansas_2025_act_url(act), digest)
        for act, digest in _ARKANSAS_ENACTMENT_TOC_ACT_SHA256.items()
    },
}
ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT = (
    (
        "10-2-133",
        "AAKAADAABABJ",
        "official_change_table_and_act_prove_repealed_locator",
        ("T10", "A2"),
    ),
    (
        "14-40-208",
        "AAOAADAAFAADAAK",
        "official_change_table_and_act_prove_repealed_locator",
        ("T14", "A314"),
    ),
    (
        "14-58-202",
        "AAOAADAAZAADAAD",
        "official_act_and_exact_toc_canonical_branch_prove_current_locator",
        ("T14", "A24"),
    ),
    (
        "15-43-205",
        "AAPAAEAAEAADAAF",
        "official_change_table_and_act_prove_repealed_locator",
        ("T15", "A26"),
    ),
    (
        "16-90-123",
        "AAQAAGAAMAACAAZ",
        "official_change_table_and_act_prove_substantive_locator",
        ("T16", "A1003"),
    ),
    (
        "17-37-202",
        "AARAACABCAADAAD",
        "official_change_table_and_act_prove_repealed_locator",
        ("T17", "A292"),
    ),
    (
        "19-43-222",
        "AATAAEAAEAACAAY",
        "official_act_and_exact_toc_canonical_position_prove_current_locator",
        ("T19", "A419"),
    ),
    (
        "21-5-1101",
        "AAVAAFAAOAAC",
        "official_act_and_exact_toc_canonical_branch_prove_current_locator",
        ("T21", "A205"),
    ),
    (
        "21-5-406",
        "AAVAAFAAFAAI",
        "official_acts_and_exact_toc_ordinal_alignment_prove_current_locator",
        ("T21", "A205", "A234"),
    ),
    (
        "21-5-421",
        "AAVAAFAAFAAY",
        "official_change_table_and_act_prove_repealed_locator",
        ("T21", "A2"),
    ),
    (
        "23-3-201",
        "AAXAABAAEAADAAC",
        "official_acts_and_exact_heading_prove_current_locator",
        ("T23", "A373", "A705"),
    ),
    (
        "24-6-202",
        "AAYAAGAADAAE",
        "official_act_and_exact_toc_canonical_position_prove_current_locator",
        ("T24", "A112"),
    ),
    (
        "25-43-505",
        "AAZABSAAIAAG",
        "official_act_and_exact_toc_canonical_branch_prove_current_locator",
        ("T25", "A10"),
    ),
    (
        "26-3-306",
        "ABAAABAADAADAAJ",
        "official_acts_effective_date_matches_exact_source_label",
        ("T26", "A407", "A876", "A880"),
    ),
    (
        "26-5-101",
        "ABAAABAAFAAE",
        "official_act_effective_date_matches_exact_source_label",
        ("T26", "A719"),
    ),
    (
        "26-51-2702",
        "ABAAAFAACABCAAE",
        "official_acts_repair_boundary_and_match_exact_source_locator",
        ("T26", "A701", "A709"),
    ),
    (
        "26-51-908",
        "ABAAAFAACAAKAAL",
        "official_act_effective_date_matches_exact_source_label",
        ("T26", "A616"),
    ),
    (
        "26-57-1507",
        "ABAAAFAAIAASAAI",
        "official_change_table_and_act_prove_repealed_locator",
        ("T26", "A380"),
    ),
    (
        "4-2A-101",
        "AAEAABAAEAACAAC",
        "official_act_effective_date_and_exact_parent_alignment_prove_current_locator",
        ("T4", "A997"),
    ),
    (
        "6-15-2102",
        "AAGAACAAGAAWAAE",
        "official_change_table_and_acts_prove_substantive_locator",
        ("T6", "A340", "A341"),
    ),
    (
        "6-18-722",
        "AAGAACAAJAAKAAX",
        "official_act_and_exact_toc_canonical_branch_prove_current_locator",
        ("T6", "A123"),
    ),
    (
        "6-51-1101",
        "AAGAAEAACAAMAAE",
        "official_acts_prove_repealed_locator",
        ("T6", "A25", "A419"),
    ),
    (
        "6-51-1102",
        "AAGAAEAACAAMAAG",
        "official_acts_prove_repealed_locator",
        ("T6", "A25", "A419"),
    ),
    (
        "6-51-1103",
        "AAGAAEAACAAMAAI",
        "official_acts_prove_repealed_locator",
        ("T6", "A25", "A419"),
    ),
    (
        "6-51-1104",
        "AAGAAEAACAAMAAJ",
        "official_acts_prove_repealed_locator",
        ("T6", "A25", "A419"),
    ),
    (
        "7-9-103",
        "AAHAAJAACAAF",
        "official_acts_and_exact_toc_canonical_position_prove_current_locator",
        ("T7", "A153", "A218", "A273", "A274", "A453", "A768"),
    ),
    (
        "7-9-107",
        "AAHAAJAACAAK",
        "official_acts_and_exact_toc_canonical_position_prove_current_locator",
        ("T7", "A153", "A154", "A272", "A602", "A768"),
    ),
    (
        "7-9-109",
        "AAHAAJAACAAN",
        "official_acts_and_exact_toc_canonical_position_prove_current_locator",
        ("T7", "A240", "A274"),
    ),
    (
        "8-6-609",
        "AAIAAHAAGAAL",
        "official_change_table_and_act_prove_substantive_locator",
        ("T8", "A815"),
    ),
)
_DELEGATED_DOCUMENT_ROOT = "/shared/document/statutes-legislation/"

# The eight originally open citation pairs in the fixed v6 delegated inventory.
# Keeping this as a locator contract (rather than a second acquisition engine)
# lets Arkansas pass all sixteen stable ``/documentpage/`` URLs to the shared
# multi-fetch/Common-Crawl/WARC batch seam in one aligned frontier.
UNRESOLVED_VARIANT_DOCUMENT_CONTRACT = (
    (
        "11-10-803",
        "AALAAKAAJAAE",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:4WVD-J370-R03N-P1NN-00008-00",
    ),
    (
        "11-10-803",
        "AALAAKAAJAAF",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:62N9-CKR0-R03N-V4W1-00008-00",
    ),
    (HR5330_VARIANT_SECTION, HR5330_UNTIL_NODE_ID, HR5330_UNTIL_LINK_HREF),
    (HR5330_VARIANT_SECTION, HR5330_IF_NODE_ID, HR5330_IF_LINK_HREF),
    (
        "19-42-201",
        "AATAAEAADAACAAC",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:6J02-Y1M0-R03N-11YK-00008-00",
    ),
    (
        "19-42-201",
        "AATAAEAADAACAAD",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:6JJX-0JB0-R03P-11YC-00008-00",
    ),
    (
        "23-4-909",
        "AAXAABAAFAAJAAK",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:4WVJ-BCY0-R03N-60BF-00008-00",
    ),
    (
        "23-4-909",
        "AAXAABAAFAAJAAL",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:6FHK-F8H0-R03M-P2W8-00008-00",
    ),
    (
        "26-51-905",
        "ABAAAFAACAAKAAG",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:4WVP-0VS0-R03J-S4T1-00008-00",
    ),
    (
        "26-51-905",
        "ABAAAFAACAAKAAH",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:62N9-G2T0-R03N-J4W2-00008-00",
    ),
    (
        "27-14-802",
        "ABBAACAACAAJAAD",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:4WVS-4PV0-R03K-72V1-00008-00",
    ),
    (
        "27-14-802",
        "ABBAACAACAAJAAE",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:6G0S-8470-R03N-60JG-00008-00",
    ),
    (
        "27-14-803",
        "ABBAACAACAAJAAF",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:4WVS-4PV0-R03K-72V2-00008-00",
    ),
    (
        "27-14-803",
        "ABBAACAACAAJAAG",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:6G0S-8FX0-R03N-60JH-00008-00",
    ),
    (
        "5-64-308",
        "AAFAAHAAFAAEAAG",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:4WPT-00W0-R03K-10WH-00008-00",
    ),
    (
        "5-64-308",
        "AAFAAHAAFAAEAAH",
        f"{_DELEGATED_DOCUMENT_ROOT}urn:contentItem:5VST-6VD0-R03M-70WR-00008-00",
    ),
)

# The remaining two locator-identity conflicts require four exact bodies.  A
# restart submits this whole same-domain set to one plural archive-aware wave;
# it must not regress to one Common Crawl inventory or WARC request per URN.
UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT = tuple(
    item
    for item in UNRESOLVED_VARIANT_DOCUMENT_CONTRACT
    if item[0] in {"19-42-201", "23-4-909"}
)

# Values exposed by the live Arkansas public-access container on 2026-08-24.
TOC_POD_ID = "6gf5kkk"
TOC_ENDPOINT_PATH = f"/r/tocprovider/{TOC_POD_ID}/toc/{TOC_POD_ID}"
TOC_ROOT_ID = TOC_POD_ID
TOC_URN_PATH = "/shared/tableofcontents/urn:contentItem:50XD-80G1-DY3X-63F1-00008-00"
TOC_SEARCH_CONFIG = (
    "0152JABjOGZiNDRkOC02Y2ZhLTQzY2YtOGNjZS1kYzg2NWI5N2NhMzAK"
    "AFBvZENhdGFsb2dwxrZ4aTVuE2yxDxc8rbYC"
)
TOC_DOCUMENT_CONFIG = (
    "00JAA2ZjZiM2VhNS0wNTVlLTQ3NzUtYjQzYy0yYWZmODJiODRmMDYK"
    "AFBvZENhdGFsb2fXiYCnsel0plIgqpYkw9PK"
)
TOC_SEARCH_MFID = "1000516"
TOC_SEARCH_FILTER = "MTA5MTE5Ng"

EXPECTED_TITLE_NUMBERS = tuple(str(value) for value in range(1, 29))
DEFAULT_MAX_EXPANSIONS = 20_000
DEFAULT_RETRIES = 3
MAX_EXHAUSTIVE_TOC_LEVEL = 12

_NODE_ID_RE = re.compile(r"^[A-Z0-9]{2,128}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TITLE_RE = re.compile(r"^TITLE\s+(?P<number>\d{1,2})\b", re.IGNORECASE)
_SECTION_NUMBER_PATTERN = (
    r"\d{1,2}-\d+[A-Za-z]?(?:\.\d+)*-\d+[A-Za-z]?(?:\.\d+)*"
)
_SECTION_RE = re.compile(
    rf"^(?P<number>{_SECTION_NUMBER_PATTERN})"
    # One retained official label (17-82-707) omits the normal citation period.
    # Accept that source syntax only when ordinary heading text follows.  Range,
    # list, and terminal-disposition labels begin with punctuation and remain
    # non-section documents.
    r"(?:\.(?:\s|$)|\s+(?=[A-Za-z0-9\"'“‘(]))",
    re.IGNORECASE,
)
_DOCUMENT_PATH_RE = re.compile(
    r"^/shared/document/statutes-legislation/urn:contentItem:"
    r"[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}-[A-Z0-9]{5}-[A-Z0-9]{2}$",
    re.IGNORECASE,
)
_DELEGATION_RE = re.compile(
    r"Provided\s+by\s+the\s+Bureau\s+of\s+Legislative\s+Research.*?"
    r"maintained\s+by\s+LexisNexis",
    re.IGNORECASE | re.DOTALL,
)
_BLOCKED_RE = re.compile(
    r"robot\s*validation|captcha|confirm\s+you\s+are\s+human|sign\s+in\s+to\s+continue",
    re.IGNORECASE,
)
_UNLABELED_PROBATE_FORMS_PARENT = (
    "title 28 — appendix administrative order number 12 — official probate forms"
)
_CHILD_SUPPORT_GUIDELINES_PARENT = (
    "title 9, subtitle 2 — appendix administrative order number 10 — "
    "child support guidelines"
)
_SUNSET_LAWS_PARENT = "appendix — title 10 sunset laws."
_BOND_ISSUES_PARENT = "appendix — title 19 bond issues"
_NONOPERATIVE_COLLECTION_RE = re.compile(
    rf"^(?P<first>{_SECTION_NUMBER_PATTERN})\s*"
    rf"(?:(?:—|–)\s*(?P<last>{_SECTION_NUMBER_PATTERN})|"
    rf",\s*(?P<second>{_SECTION_NUMBER_PATTERN}))\.?\s+"
    r"\[(?P<status>Repealed|Reserved|Transferred|Superseded|Expired)\.?\]\.?$",
    re.IGNORECASE,
)
_EDITORIAL_NOTE_RE = re.compile(
    r"^Tit\.\s*(?P<title>\d{1,2})(?:,\s*.+)?(?:\s+—)?\s+Note$",
    re.IGNORECASE,
)
_STRUCTURAL_RESERVED_RE = re.compile(
    r"^(?P<kind>Chapter|Chapters|Subchapter|Subchapters)\b.+"
    r"\[Reserved\.?\]\.?$",
    re.IGNORECASE,
)
_BRACKET_LABEL_RE = re.compile(r"\[([^][]+)\]\.?\s*$")
_DATE_TEXT_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}"
)
_DATE_TEXT_RE = re.compile(_DATE_TEXT_PATTERN, re.IGNORECASE)

# Raw mappings and DOM rows are intentionally unverified value objects.  Only
# this module's exact-container browser path can bind live response evidence to
# a node.  This prevents fixtures or caller-built dataclasses from serializing
# themselves as official source evidence merely by setting public booleans.
_LIVE_EVIDENCE_CAPABILITY = object()
_SOURCE_BOUND_VARIANT_CAPABILITY = object()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _as_optional_bool(value: object) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _as_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enabled() -> bool:
    """Return whether live Arkansas Lexis inventory was explicitly enabled."""

    return current_state_law_run_environment_value(ENABLE_ENV).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def container_url_matches(value: str) -> bool:
    """Require the exact public container while allowing ephemeral request IDs."""

    try:
        parsed = urlparse(str(value or ""))
        invalid_source = bool(
            parsed.scheme != "https"
            or parsed.netloc.lower() != "advance.lexis.com"
            or parsed.path != "/container"
            or parsed.params
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.port is not None
        )
    except ValueError:
        return False
    if invalid_source:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("config") != [PUBLIC_CONTAINER_CONFIG]:
        return False
    if not set(query).issubset({"config", "crid", "prid"}):
        return False
    return all(
        len(query[key]) == 1 and bool(_REQUEST_ID_RE.fullmatch(query[key][0]))
        for key in ("crid", "prid")
        if key in query
    )


def is_document_path(value: object) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    if parsed.params or parsed.query or parsed.fragment:
        return False
    if parsed.scheme or parsed.netloc:
        return bool(
            parsed.scheme == "https"
            and parsed.netloc.lower() == "advance.lexis.com"
            and _DOCUMENT_PATH_RE.fullmatch(parsed.path or "")
        )
    return bool(_DOCUMENT_PATH_RE.fullmatch(parsed.path or ""))


def document_page_url(node: ArkansasLexisNode) -> str:
    """Return the stable public-access locator for a verified statute node.

    Ephemeral ``crid``/``prid`` values are intentionally excluded.  The
    delegated container configuration and exact Lexis content-item path are
    sufficient to bind an archival lookup or a fresh browser navigation to
    the statute locator discovered in the verified TOC.
    """

    if not node.evidence_verified or not node.is_statute_locator:
        raise ValueError("Arkansas Lexis document locator is not verified")
    query = urlencode(
        (
            ("pdmfid", TOC_SEARCH_MFID),
            ("config", TOC_DOCUMENT_CONFIG),
            ("pddocfullpath", node.link_href),
        )
    )
    return f"{ADVANCE_ORIGIN}/documentpage/?{query}"


def toc_expand_request(node_id: object) -> tuple[str, dict[str, Any]]:
    """Build one exact same-origin PATCH request for a validated TOC node."""

    normalized = str(node_id or "").strip()
    if not _NODE_ID_RE.fullmatch(normalized):
        raise ValueError(f"invalid Arkansas Lexis TOC node id: {normalized!r}")
    return (
        f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}",
        {
            "id": TOC_ROOT_ID,
            "props": {
                "action": "expand",
                "items": [{"fieldName": "nodeId", "value": normalized}],
            },
        },
    )


def toc_open_to_request(
    node_id: object,
    *,
    target_level: object,
) -> tuple[str, dict[str, Any]]:
    """Build one source-native request for a complete title subtree.

    The rendered public TOC advertises the deepest supported ``open-to`` level
    for each title.  Using that exact level avoids issuing one PATCH per
    subtitle, chapter, subchapter, and section while retaining the complete
    source hierarchy in a single response.
    """

    normalized = str(node_id or "").strip()
    if not _NODE_ID_RE.fullmatch(normalized):
        raise ValueError(f"invalid Arkansas Lexis TOC node id: {normalized!r}")
    if isinstance(target_level, bool):
        # Keep all malformed source-advertised levels on the existing
        # fail-closed ValueError API, including bool (an int subclass).
        raise ValueError("target_level must be an integer")  # noqa: TRY004
    try:
        level = int(target_level)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_level must be an integer") from exc
    if level < 2 or level > MAX_EXHAUSTIVE_TOC_LEVEL:
        raise ValueError(
            "target_level must be between 2 and "
            f"{MAX_EXHAUSTIVE_TOC_LEVEL}"
        )
    return (
        f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}",
        {
            "id": TOC_ROOT_ID,
            "props": {
                "action": "open-to",
                "items": [
                    {"fieldName": "nodeId", "value": normalized},
                    {"fieldName": "targetLevel", "value": level},
                ],
            },
        },
    )


def _observed_at_valid(value: object) -> bool:
    try:
        observed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return False
    return observed.tzinfo is not None and observed.utcoffset() is not None


def _node_shape_valid(node: ArkansasLexisNode) -> bool:
    return bool(
        _NODE_ID_RE.fullmatch(node.node_id)
        and (
            node.title.strip()
            or node.document_disposition
            == "nonstatutory_unlabeled_probate_form"
        )
        and node.level >= 1
        and node.node_path.startswith("/ROOT/")
        and (
            node.node_path == f"/ROOT/{node.node_id}"
            or node.node_path.endswith(f"/{node.node_id}")
        )
        and (not node.link_href or is_document_path(node.link_href))
    )


@dataclass(frozen=True)
class ArkansasLexisNode:
    """Normalized TOC node returned by the official delegated portal."""

    node_id: str
    title: str
    level: int
    node_path: str
    can_expand: bool
    can_open: bool
    has_children: bool
    link_href: str = ""
    subscribed: bool | None = None
    purchase_required: bool | None = None
    list_price: float | None = None
    net_price: float | None = None
    pricing_present: bool = False
    currency_code: str = ""
    usage_type_code: str = ""
    document_status: str = ""
    document_disposition: str = ""
    expansion_closed: bool = False
    evidence_source_url: str = ""
    evidence_observed_at: str = ""
    evidence_sha256: str = ""
    _evidence_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def title_number(self) -> str | None:
        match = _TITLE_RE.match(self.title.strip())
        return str(int(match.group("number"))) if match else None

    @property
    def section_number(self) -> str | None:
        match = _SECTION_RE.match(self.title.strip())
        if not match:
            return None
        number = match.group("number")
        if number.split("-", 1)[0] not in EXPECTED_TITLE_NUMBERS:
            return None
        return number

    @property
    def public_document_available(self) -> bool:
        return bool(
            is_document_path(self.link_href)
            and self.subscribed is True
            and self.pricing_present
            and self.purchase_required is False
            and self.list_price == 0
            and self.net_price == 0
            and self.currency_code.upper() == "USD"
            and self.usage_type_code.lower() == "subscription"
            and self.document_status.lower() == "available"
        )

    @property
    def is_statute_locator(self) -> bool:
        return bool(self.section_number and self.public_document_available)

    @property
    def evidence_verified(self) -> bool:
        return bool(
            self._evidence_capability is _LIVE_EVIDENCE_CAPABILITY
            and container_url_matches(self.evidence_source_url)
            and _observed_at_valid(self.evidence_observed_at)
            and _SHA256_RE.fullmatch(self.evidence_sha256)
            and _node_shape_valid(self)
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        value.update(
            {
                "title_number": self.title_number,
                "section_number": self.section_number,
                "public_document_available": self.public_document_available,
                "is_statute_locator": self.is_statute_locator,
                "evidence_verified": self.evidence_verified,
                "source_authority_class": (
                    "official" if self.evidence_verified else "unverified"
                ),
                "full_corpus_admissible": False,
                "source_label_missing": not bool(self.title.strip()),
            }
        )
        return value


@dataclass(frozen=True)
class ArkansasLexisVariantDecision:
    """Deterministic current-as-of decision for one repeated citation."""

    section_number: str
    disposition: str
    reason: str
    candidate_node_ids: tuple[str, ...]
    selected_node_id: str = ""
    selected_link_href: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArkansasLexisSourceBoundVariantResolution:
    """One immutable current-locator choice backed by retained official bytes."""

    section_number: str
    candidate_node_ids: tuple[str, ...]
    selected_node_id: str
    selected_link_href: str
    source_url: str
    source_sha256: str
    source_byte_size: int
    source_transport: str
    source_transport_receipt_sha256: str
    parser_input_receipt_sha256: str
    trigger_act_source_url: str
    trigger_act_sha256: str
    trigger_act_byte_size: int
    trigger_act_transport: str
    trigger_act_transport_receipt_sha256: str
    trigger_act_parser_input_receipt_sha256: str
    latest_action_date: str
    latest_action_text: str
    congress_end_date: str
    trigger_deadline: str
    _evidence_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def evidence_verified(self) -> bool:
        return bool(
            self._evidence_capability is _SOURCE_BOUND_VARIANT_CAPABILITY
            and self.section_number == HR5330_VARIANT_SECTION
            and self.candidate_node_ids
            == tuple(sorted((HR5330_UNTIL_NODE_ID, HR5330_IF_NODE_ID)))
            and self.selected_node_id == HR5330_UNTIL_NODE_ID
            and self.selected_link_href == HR5330_UNTIL_LINK_HREF
            and self.source_url == HR5330_BILLSTATUS_URL
            and self.source_sha256 == HR5330_BILLSTATUS_SHA256
            and self.source_byte_size == HR5330_BILLSTATUS_BYTE_SIZE
            and bool(self.source_transport)
            and bool(_SHA256_RE.fullmatch(self.source_transport_receipt_sha256))
            and bool(_SHA256_RE.fullmatch(self.parser_input_receipt_sha256))
            and self.trigger_act_source_url == ACT1032_URL
            and self.trigger_act_sha256 == ACT1032_SHA256
            and self.trigger_act_byte_size == ACT1032_BYTE_SIZE
            and bool(self.trigger_act_transport)
            and bool(
                _SHA256_RE.fullmatch(self.trigger_act_transport_receipt_sha256)
            )
            and bool(
                _SHA256_RE.fullmatch(
                    self.trigger_act_parser_input_receipt_sha256
                )
            )
            and self.latest_action_date == HR5330_LATEST_ACTION_DATE
            and self.latest_action_text == HR5330_LATEST_ACTION_TEXT
            and self.congress_end_date == HR5330_CONGRESS_END_DATE.isoformat()
            and self.trigger_deadline == HR5330_TRIGGER_DEADLINE.isoformat()
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        value["evidence_verified"] = self.evidence_verified
        value["reason"] = self.decision_reason
        return value

    @property
    def decision_reason(self) -> str:
        return (
            "official_govinfo_billstatus_proves_hr5330_not_enacted_before_"
            "trigger_deadline"
        )


@dataclass(frozen=True)
class ArkansasLexisRetainedOfficialInputIdentity:
    """Content and acquisition identity for one exact retained official PDF."""

    source_url: str
    source_sha256: str
    source_byte_size: int
    source_transport: str
    source_transport_receipt_sha256: str
    parser_input_receipt_sha256: str
    retrieved_at: str


@dataclass(frozen=True)
class ArkansasLexisEnactmentTocVariantResolution:
    """A fixed-inventory locator choice backed by exact retained enactments."""

    section_number: str
    candidate_node_ids: tuple[str, ...]
    selected_node_id: str
    selected_link_href: str
    inventory_sha256: str
    selection_plan_sha256: str
    proof_keys: tuple[str, ...]
    proof_inputs: tuple[ArkansasLexisRetainedOfficialInputIdentity, ...]
    reason: str
    _evidence_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def decision_reason(self) -> str:
        return self.reason

    @property
    def evidence_verified(self) -> bool:
        contract = next(
            (
                item
                for item in ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT
                if item[0] == self.section_number
            ),
            None,
        )
        if contract is None:
            return False
        section_number, selected_node_id, reason, proof_keys = contract
        if len(self.proof_inputs) != len(proof_keys):
            return False
        exact_inputs = []
        for key, identity in zip(proof_keys, self.proof_inputs, strict=True):
            expected = ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT.get(key)
            if expected is None:
                return False
            exact_inputs.append((identity, *expected))
        return bool(
            self._evidence_capability is _SOURCE_BOUND_VARIANT_CAPABILITY
            and self.section_number == section_number
            and len(self.candidate_node_ids) >= 2
            and len(set(self.candidate_node_ids)) == len(self.candidate_node_ids)
            and self.selected_node_id == selected_node_id
            and self.selected_node_id in self.candidate_node_ids
            and bool(self.selected_link_href)
            and self.inventory_sha256 == ARKANSAS_DELEGATED_INVENTORY_SHA256
            and self.selection_plan_sha256
            == ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256
            and self.proof_keys == proof_keys
            and self.reason == reason
            and all(
                identity.source_url == expected_url
                and identity.source_sha256 == expected_sha256
                and identity.source_byte_size > 0
                and bool(identity.source_transport)
                and bool(
                    _SHA256_RE.fullmatch(
                        identity.source_transport_receipt_sha256
                    )
                )
                and bool(
                    _SHA256_RE.fullmatch(identity.parser_input_receipt_sha256)
                )
                and _observed_at_valid(identity.retrieved_at)
                for identity, expected_url, expected_sha256 in exact_inputs
            )
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        value["evidence_verified"] = self.evidence_verified
        return value


@dataclass(frozen=True)
class ArkansasLexisAct283VariantResolution:
    """One Act 283 choice plus its preserved future-contingent alternate."""

    section_number: str
    candidate_node_ids: tuple[str, ...]
    selected_node_id: str
    selected_link_href: str
    excluded_node_id: str
    excluded_link_href: str
    excluded_disposition: str
    trigger_act: ArkansasLexisRetainedOfficialInputIdentity
    crc_nonoccurrence: ArkansasLexisRetainedOfficialInputIdentity
    current_dws_form: ArkansasLexisRetainedOfficialInputIdentity
    crc_status_statement: str
    current_dws_statement: str
    _evidence_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def decision_reason(self) -> str:
        return ACT283_DECISION_REASON

    @property
    def evidence_verified(self) -> bool:
        contract = next(
            (
                item
                for item in ACT283_VARIANT_CONTRACT
                if item[0] == self.section_number
            ),
            None,
        )
        if contract is None:
            return False
        (
            _section,
            until_node_id,
            until_link_href,
            _until_title,
            if_node_id,
            if_link_href,
            _if_title,
        ) = contract
        try:
            dws_observed_at = datetime.fromisoformat(
                self.current_dws_form.retrieved_at
            )
        except ValueError:
            return False
        exact_inputs = (
            (
                self.trigger_act,
                ACT283_URL,
                ACT283_SHA256,
                ACT283_BYTE_SIZE,
            ),
            (
                self.crc_nonoccurrence,
                ACT283_CRC_NONOCCURRENCE_URL,
                ACT283_CRC_NONOCCURRENCE_SHA256,
                ACT283_CRC_NONOCCURRENCE_BYTE_SIZE,
            ),
            (
                self.current_dws_form,
                ACT283_DWS_CURRENT_FORM_URL,
                ACT283_DWS_CURRENT_FORM_SHA256,
                ACT283_DWS_CURRENT_FORM_BYTE_SIZE,
            ),
        )
        return bool(
            self._evidence_capability is _SOURCE_BOUND_VARIANT_CAPABILITY
            and self.candidate_node_ids
            == tuple(sorted((until_node_id, if_node_id)))
            and self.selected_node_id == until_node_id
            and self.selected_link_href == until_link_href
            and self.excluded_node_id == if_node_id
            and self.excluded_link_href == if_link_href
            and self.excluded_disposition == ACT283_EXCLUSION_DISPOSITION
            and self.crc_status_statement
            == ACT283_CRC_NONOCCURRENCE_STATEMENT
            and self.current_dws_statement
            == ACT283_DWS_CURRENT_FORM_STATEMENT
            and dws_observed_at.tzinfo is not None
            and dws_observed_at >= ACT283_CURRENT_EVIDENCE_NOT_BEFORE
            and self.current_dws_form.source_transport == "direct"
            and all(
                identity.source_url == expected_url
                and identity.source_sha256 == expected_sha256
                and identity.source_byte_size == expected_byte_size
                and bool(identity.source_transport)
                and bool(
                    _SHA256_RE.fullmatch(
                        identity.source_transport_receipt_sha256
                    )
                )
                and bool(
                    _SHA256_RE.fullmatch(identity.parser_input_receipt_sha256)
                )
                and _observed_at_valid(identity.retrieved_at)
                for identity, expected_url, expected_sha256, expected_byte_size
                in exact_inputs
            )
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        value["evidence_verified"] = self.evidence_verified
        value["reason"] = self.decision_reason
        value["preserved_exclusions"] = [
            {
                "node_id": self.excluded_node_id,
                "link_href": self.excluded_link_href,
                "disposition": self.excluded_disposition,
            }
        ]
        return value


ArkansasLexisVerifiedVariantResolution = (
    ArkansasLexisSourceBoundVariantResolution
    | ArkansasLexisEnactmentTocVariantResolution
    | ArkansasLexisAct283VariantResolution
)


def _single_direct_child(parent: ET.Element, tag: str) -> ET.Element:
    children = parent.findall(tag)
    if len(children) != 1:
        raise ValueError(f"GovInfo BILLSTATUS requires exactly one {tag!r} child")
    return children[0]


def validate_hr5330_billstatus_xml(payload: bytes) -> dict[str, Any]:
    """Verify the exact official bytes and no-enactment XML semantics.

    Digest pinning prevents a later GPO update from silently changing the
    contingency outcome.  The XML checks make the legal inference explicit:
    this is H.R. 5330 of the 116th Congress, its latest action is the Union
    Calendar entry, it has no law node, and that Congress ended before Act
    1032's 2026 trigger deadline.
    """

    body = bytes(payload or b"")
    if len(body) != HR5330_BILLSTATUS_BYTE_SIZE:
        raise ValueError("GovInfo BILLSTATUS byte size drifted")
    digest = hashlib.sha256(body).hexdigest()
    if digest != HR5330_BILLSTATUS_SHA256:
        raise ValueError("GovInfo BILLSTATUS SHA-256 drifted")
    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("GovInfo BILLSTATUS contains an unsafe XML declaration")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("GovInfo BILLSTATUS is not well-formed XML") from exc
    if root.tag != "billStatus":
        raise ValueError("GovInfo BILLSTATUS root identity drifted")
    if (_single_direct_child(root, "version").text or "").strip() != "3.0.0":
        raise ValueError("GovInfo BILLSTATUS schema version drifted")
    bill = _single_direct_child(root, "bill")

    exact_fields = {
        "number": "5330",
        "type": "HR",
        "congress": "116",
        "originChamber": "House",
        "introducedDate": "2019-12-05",
        "updateDate": HR5330_STATUS_UPDATE,
    }
    for tag, expected in exact_fields.items():
        child = _single_direct_child(bill, tag)
        if (child.text or "").strip() != expected:
            raise ValueError(f"GovInfo BILLSTATUS {tag} identity drifted")

    latest = _single_direct_child(bill, "latestAction")
    latest_date = (_single_direct_child(latest, "actionDate").text or "").strip()
    latest_text = (_single_direct_child(latest, "text").text or "").strip()
    if latest_date != HR5330_LATEST_ACTION_DATE:
        raise ValueError("GovInfo BILLSTATUS latest-action date drifted")
    if latest_text != HR5330_LATEST_ACTION_TEXT:
        raise ValueError("GovInfo BILLSTATUS latest-action text drifted")

    actions = _single_direct_child(bill, "actions").findall("item")
    if not actions:
        raise ValueError("GovInfo BILLSTATUS action ledger is empty")
    first_action_date = (
        _single_direct_child(actions[0], "actionDate").text or ""
    ).strip()
    first_action_text = (_single_direct_child(actions[0], "text").text or "").strip()
    if (first_action_date, first_action_text) != (latest_date, latest_text):
        raise ValueError("GovInfo BILLSTATUS latest action is not ledger-bound")
    action_dates: list[date] = []
    for action in actions:
        raw_date = (_single_direct_child(action, "actionDate").text or "").strip()
        try:
            action_dates.append(date.fromisoformat(raw_date))
        except ValueError as exc:
            raise ValueError("GovInfo BILLSTATUS action date is invalid") from exc
    if max(action_dates).isoformat() != HR5330_LATEST_ACTION_DATE:
        raise ValueError("GovInfo BILLSTATUS contains a later unreported action")

    # BILLSTATUS emits a direct ``laws`` collection for enacted measures.  Its
    # absence, together with the exact latest action and post-Congress update,
    # is the source-bound negative trigger evidence here.
    if bill.findall("laws") or bill.findall("law"):
        raise ValueError("GovInfo BILLSTATUS unexpectedly records enactment")
    if not (
        date.fromisoformat(latest_date)
        < HR5330_CONGRESS_END_DATE
        < HR5330_TRIGGER_DEADLINE
    ):
        raise ValueError("H.R. 5330 contingency chronology is invalid")
    return {
        "bill_number": "5330",
        "bill_type": "HR",
        "congress": "116",
        "congress_end_date": HR5330_CONGRESS_END_DATE.isoformat(),
        "latest_action_date": latest_date,
        "latest_action_text": latest_text,
        "law_node_count": 0,
        "source_byte_size": len(body),
        "source_sha256": digest,
        "trigger_deadline": HR5330_TRIGGER_DEADLINE.isoformat(),
    }


def _exact_variant_document_nodes(
    nodes: Iterable[ArkansasLexisNode],
    *,
    contract: Sequence[tuple[str, str, str]],
    label: str,
) -> tuple[ArkansasLexisNode, ...]:
    candidates = list(nodes)
    by_node_id: dict[str, ArkansasLexisNode] = {}
    for node in candidates:
        if node.node_id in by_node_id:
            raise ValueError(f"Arkansas {label} frontier repeats a node id")
        by_node_id[node.node_id] = node
    expected_ids = {node_id for _section, node_id, _href in contract}
    selected: list[ArkansasLexisNode] = []
    for section_number, node_id, link_href in contract:
        node = by_node_id.get(node_id)
        if node is None:
            raise ValueError(f"Arkansas {label} locator {node_id} is missing")
        if not (
            node.evidence_verified
            and node.is_statute_locator
            and node.section_number == section_number
            and node.link_href == link_href
        ):
            raise ValueError(f"Arkansas {label} locator {node_id} drifted")
        selected.append(node)
    selected_ids = {node.node_id for node in selected}
    if selected_ids != expected_ids or len(selected) != len(expected_ids):
        raise ValueError(f"Arkansas {label} locator contract is incomplete")
    return tuple(selected)


def exact_unresolved_variant_document_nodes(
    nodes: Iterable[ArkansasLexisNode],
) -> tuple[ArkansasLexisNode, ...]:
    """Return the exact sixteen originally unresolved locators in order."""

    return _exact_variant_document_nodes(
        nodes,
        contract=UNRESOLVED_VARIANT_DOCUMENT_CONTRACT,
        label="unresolved variant",
    )


def exact_unresolved_variant_identity_document_nodes(
    nodes: Iterable[ArkansasLexisNode],
) -> tuple[ArkansasLexisNode, ...]:
    """Return the exact four still-unbound identity locators in one order."""

    return _exact_variant_document_nodes(
        nodes,
        contract=UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT,
        label="unresolved identity variant",
    )


def _verify_retained_official_input(
    retained: Any,
    *,
    label: str,
    official_url: str,
    expected_sha256: str,
) -> ArkansasLexisRetainedOfficialInputIdentity:
    """Reverify one exact retained source body and complete GET identity."""

    envelope = getattr(retained, "envelope", None)
    if getattr(envelope, "parser_name", "") != CURRENT_VARIANT_RESOLVER_PARSER_NAME:
        raise ValueError(f"{label} parser-input ledger identity drifted")
    body = getattr(envelope, "body", None)
    if body is None:
        raise ValueError(f"{label} retained source bytes are missing")
    payload = bytes(body)
    if not payload or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError(f"{label} retained source bytes drifted")
    acquisition = getattr(envelope, "acquisition", None)
    receipt = getattr(acquisition, "receipt", None)
    if receipt is None:
        raise ValueError(f"{label} parser-input receipt is missing")
    if str(getattr(receipt, "endpoint", "") or "") != official_url:
        raise ValueError(f"{label} parser-input endpoint drifted")
    if dict(getattr(receipt, "sanitized_request", {}) or {}) != {
        "method": "GET",
        "url": official_url,
    }:
        raise ValueError(f"{label} parser-input request identity drifted")
    if int(getattr(receipt, "response_status", 0) or 0) != 200:
        raise ValueError(f"{label} parser-input response was not HTTP 200")
    content = getattr(receipt, "content", None)
    if not (
        str(getattr(content, "sha256", "") or "") == expected_sha256
        and int(getattr(content, "byte_size", -1)) == len(payload)
    ):
        raise ValueError(f"{label} parser-input content identity drifted")
    metadata = dict(getattr(receipt, "metadata", {}) or {})
    if str(metadata.get("jurisdiction") or "").upper() != "AR":
        raise ValueError(f"{label} parser-input jurisdiction drifted")
    parser_receipt_sha256 = str(getattr(receipt, "receipt_sha256", "") or "")
    if not _SHA256_RE.fullmatch(parser_receipt_sha256):
        raise ValueError(f"{label} parser-input receipt digest is invalid")
    retrieved_at_value = getattr(receipt, "retrieved_at", None)
    if isinstance(retrieved_at_value, datetime):
        retrieved_at = retrieved_at_value.isoformat()
    else:
        retrieved_at = str(retrieved_at_value or "")
    if not _observed_at_valid(retrieved_at):
        raise ValueError(f"{label} parser-input observation time is invalid")

    from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
        canonicalize_state_law_transport_receipt,
        verify_state_law_transport_receipt,
    )

    canonical_transport = canonicalize_state_law_transport_receipt(
        getattr(retained, "transport_receipt", None),
        official_url=official_url,
        content_sha256=expected_sha256,
    )
    verified_transport = verify_state_law_transport_receipt(
        canonical_transport,
        official_url=official_url,
        content_sha256=expected_sha256,
    )
    transport_bytes = json.dumps(
        canonical_transport,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ArkansasLexisRetainedOfficialInputIdentity(
        source_url=official_url,
        source_sha256=hashlib.sha256(payload).hexdigest(),
        source_byte_size=len(payload),
        source_transport=str(verified_transport.leaf_transport),
        source_transport_receipt_sha256=hashlib.sha256(
            transport_bytes
        ).hexdigest(),
        parser_input_receipt_sha256=parser_receipt_sha256,
        retrieved_at=retrieved_at,
    )


def resolve_enactment_toc_source_bound_variants(
    nodes: Iterable[ArkansasLexisNode],
    *,
    inventory_sha256: str,
    retained_inputs: Mapping[str, Any],
) -> tuple[ArkansasLexisEnactmentTocVariantResolution, ...]:
    """Replay the exact 29-row enactment/TOC overlay atomically."""

    if inventory_sha256 != ARKANSAS_DELEGATED_INVENTORY_SHA256:
        raise ValueError("Arkansas delegated inventory fingerprint drifted")
    node_list = list(nodes)
    if not node_list or any(not node.evidence_verified for node in node_list):
        raise ValueError("Arkansas delegated inventory contains unverified nodes")
    plan_sha256 = enactment_toc_selection_plan_sha256(node_list)
    if plan_sha256 != ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256:
        raise ValueError("Arkansas enactment/TOC selection plan drifted")

    required_proof_keys = {
        key
        for _section, _selected, _reason, proof_keys
        in ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT
        for key in proof_keys
    }
    if required_proof_keys != set(ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT):
        raise ValueError("Arkansas enactment/TOC proof contract is inconsistent")
    if set(retained_inputs) != required_proof_keys:
        raise ValueError("Arkansas enactment/TOC retained proof bundle is incomplete")

    verified_inputs: dict[str, ArkansasLexisRetainedOfficialInputIdentity] = {}
    for key in sorted(required_proof_keys):
        official_url, expected_sha256 = (
            ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT[key]
        )
        verified_inputs[key] = _verify_retained_official_input(
            retained_inputs[key],
            label=f"Arkansas enactment/TOC input {key}",
            official_url=official_url,
            expected_sha256=expected_sha256,
        )

    resolutions: list[ArkansasLexisEnactmentTocVariantResolution] = []
    for section_number, selected_node_id, reason, proof_keys in (
        ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT
    ):
        candidates = sorted(
            (
                node
                for node in node_list
                if node.section_number == section_number
            ),
            key=lambda node: (node.node_id, node.link_href),
        )
        if len(candidates) < 2:
            raise ValueError(
                f"Arkansas {section_number} requires concurrent locator candidates"
            )
        candidate_node_ids = tuple(node.node_id for node in candidates)
        if len(set(candidate_node_ids)) != len(candidate_node_ids):
            raise ValueError(f"Arkansas {section_number} repeats a locator identity")
        selected = next(
            (node for node in candidates if node.node_id == selected_node_id),
            None,
        )
        if selected is None:
            raise ValueError(f"Arkansas {section_number} selected locator drifted")
        resolution = ArkansasLexisEnactmentTocVariantResolution(
            section_number=section_number,
            candidate_node_ids=candidate_node_ids,
            selected_node_id=selected.node_id,
            selected_link_href=selected.link_href,
            inventory_sha256=inventory_sha256,
            selection_plan_sha256=plan_sha256,
            proof_keys=proof_keys,
            proof_inputs=tuple(verified_inputs[key] for key in proof_keys),
            reason=reason,
        )
        object.__setattr__(
            resolution,
            "_evidence_capability",
            _SOURCE_BOUND_VARIANT_CAPABILITY,
        )
        if not resolution.evidence_verified:
            raise ValueError(
                f"Arkansas {section_number} enactment/TOC resolution did not verify"
            )
        resolutions.append(resolution)
    if len(resolutions) != len(ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT):
        raise ValueError("Arkansas enactment/TOC resolution bundle is incomplete")
    return tuple(resolutions)


def _verify_retained_official_pdf_input(
    retained: Any,
    *,
    label: str,
    official_url: str,
    expected_sha256: str,
    expected_byte_size: int,
) -> ArkansasLexisRetainedOfficialInputIdentity:
    """Reverify one exact official PDF and its complete acquisition identity."""

    envelope = getattr(retained, "envelope", None)
    if getattr(envelope, "parser_name", "") != CURRENT_VARIANT_RESOLVER_PARSER_NAME:
        raise ValueError(f"{label} parser-input ledger identity drifted")
    body = getattr(envelope, "body", None)
    if body is None:
        raise ValueError(f"{label} retained PDF bytes are missing")
    pdf = bytes(body)
    if (
        len(pdf) != expected_byte_size
        or hashlib.sha256(pdf).hexdigest() != expected_sha256
        or not pdf.startswith(b"%PDF-")
    ):
        raise ValueError(f"{label} retained PDF bytes drifted")
    acquisition = getattr(envelope, "acquisition", None)
    receipt = getattr(acquisition, "receipt", None)
    if receipt is None:
        raise ValueError(f"{label} parser-input receipt is missing")
    if str(getattr(receipt, "endpoint", "") or "") != official_url:
        raise ValueError(f"{label} parser-input endpoint drifted")
    if dict(getattr(receipt, "sanitized_request", {}) or {}) != {
        "method": "GET",
        "url": official_url,
    }:
        raise ValueError(f"{label} parser-input request identity drifted")
    if int(getattr(receipt, "response_status", 0) or 0) != 200:
        raise ValueError(f"{label} parser-input response was not HTTP 200")
    content = getattr(receipt, "content", None)
    if not (
        str(getattr(content, "sha256", "") or "") == expected_sha256
        and int(getattr(content, "byte_size", -1)) == expected_byte_size
    ):
        raise ValueError(f"{label} parser-input content identity drifted")
    metadata = dict(getattr(receipt, "metadata", {}) or {})
    if str(metadata.get("jurisdiction") or "").upper() != "AR":
        raise ValueError(f"{label} parser-input jurisdiction drifted")
    parser_receipt_sha256 = str(getattr(receipt, "receipt_sha256", "") or "")
    if not _SHA256_RE.fullmatch(parser_receipt_sha256):
        raise ValueError(f"{label} parser-input receipt digest is invalid")
    retrieved_at_value = getattr(receipt, "retrieved_at", None)
    if isinstance(retrieved_at_value, datetime):
        retrieved_at = retrieved_at_value.isoformat()
    else:
        retrieved_at = str(retrieved_at_value or "")
    if not _observed_at_valid(retrieved_at):
        raise ValueError(f"{label} parser-input observation time is invalid")

    from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
        canonicalize_state_law_transport_receipt,
        verify_state_law_transport_receipt,
    )

    canonical_transport = canonicalize_state_law_transport_receipt(
        getattr(retained, "transport_receipt", None),
        official_url=official_url,
        content_sha256=expected_sha256,
    )
    verified_transport = verify_state_law_transport_receipt(
        canonical_transport,
        official_url=official_url,
        content_sha256=expected_sha256,
    )
    transport_bytes = json.dumps(
        canonical_transport,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ArkansasLexisRetainedOfficialInputIdentity(
        source_url=official_url,
        source_sha256=hashlib.sha256(pdf).hexdigest(),
        source_byte_size=len(pdf),
        source_transport=str(verified_transport.leaf_transport),
        source_transport_receipt_sha256=hashlib.sha256(
            transport_bytes
        ).hexdigest(),
        parser_input_receipt_sha256=parser_receipt_sha256,
        retrieved_at=retrieved_at,
    )


def _verify_act1032_retained_input(retained: Any) -> dict[str, Any]:
    """Reverify the exact official Act 1032 PDF and acquisition identity."""

    identity = _verify_retained_official_pdf_input(
        retained,
        label="Arkansas Act 1032",
        official_url=ACT1032_URL,
        expected_sha256=ACT1032_SHA256,
        expected_byte_size=ACT1032_BYTE_SIZE,
    )
    return {
        "byte_size": identity.source_byte_size,
        "parser_input_receipt_sha256": identity.parser_input_receipt_sha256,
        "sha256": identity.source_sha256,
        "source_transport": identity.source_transport,
        "transport_receipt_sha256": (
            identity.source_transport_receipt_sha256
        ),
    }


def resolve_hr5330_source_bound_variant(
    nodes: Iterable[ArkansasLexisNode],
    *,
    billstatus_xml: bytes,
    source_url: str,
    transport_receipt: Mapping[str, Any],
    parser_input_envelope: Any,
    trigger_act_retained_input: Any,
) -> ArkansasLexisSourceBoundVariantResolution:
    """Select the exact ``until`` node from retained official GPO evidence."""

    if str(source_url or "").strip() != HR5330_BILLSTATUS_URL:
        raise ValueError("GovInfo BILLSTATUS official URL drifted")
    semantics = validate_hr5330_billstatus_xml(billstatus_xml)
    act1032 = _verify_act1032_retained_input(trigger_act_retained_input)
    candidates = [
        node for node in nodes if node.section_number == HR5330_VARIANT_SECTION
    ]
    if len(candidates) != 2 or any(not node.evidence_verified for node in candidates):
        raise ValueError("Arkansas 16-56-106 requires two verified locator candidates")
    by_node_id = {node.node_id: node for node in candidates}
    if len(by_node_id) != 2:
        raise ValueError("Arkansas 16-56-106 repeats a locator identity")
    exact_nodes = {
        HR5330_UNTIL_NODE_ID: (HR5330_UNTIL_LINK_HREF, HR5330_UNTIL_TITLE),
        HR5330_IF_NODE_ID: (HR5330_IF_LINK_HREF, HR5330_IF_TITLE),
    }
    if set(by_node_id) != set(exact_nodes):
        raise ValueError("Arkansas 16-56-106 locator node set drifted")
    for node_id, (expected_href, expected_title) in exact_nodes.items():
        node = by_node_id[node_id]
        if node.link_href != expected_href or node.title != expected_title:
            raise ValueError(f"Arkansas 16-56-106 locator {node_id} drifted")

    from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
        canonicalize_state_law_transport_receipt,
        verify_state_law_transport_receipt,
    )

    canonical_transport = canonicalize_state_law_transport_receipt(
        transport_receipt,
        official_url=HR5330_BILLSTATUS_URL,
        content_sha256=HR5330_BILLSTATUS_SHA256,
    )
    verified_transport = verify_state_law_transport_receipt(
        canonical_transport,
        official_url=HR5330_BILLSTATUS_URL,
        content_sha256=HR5330_BILLSTATUS_SHA256,
    )

    envelope = parser_input_envelope
    if getattr(envelope, "parser_name", "") != CURRENT_VARIANT_RESOLVER_PARSER_NAME:
        raise ValueError("GovInfo BILLSTATUS parser-input ledger identity drifted")
    envelope_body = getattr(envelope, "body", None)
    if envelope_body is None or bytes(envelope_body) != bytes(billstatus_xml):
        raise ValueError("GovInfo BILLSTATUS parser-input bytes are not retained")
    acquisition = getattr(envelope, "acquisition", None)
    receipt = getattr(acquisition, "receipt", None)
    if receipt is None:
        raise ValueError("GovInfo BILLSTATUS parser-input receipt is missing")
    if str(getattr(receipt, "endpoint", "") or "") != HR5330_BILLSTATUS_URL:
        raise ValueError("GovInfo BILLSTATUS parser-input endpoint drifted")
    if dict(getattr(receipt, "sanitized_request", {}) or {}) != {
        "method": "GET",
        "url": HR5330_BILLSTATUS_URL,
    }:
        raise ValueError("GovInfo BILLSTATUS parser-input request identity drifted")
    if int(getattr(receipt, "response_status", 0) or 0) != 200:
        raise ValueError("GovInfo BILLSTATUS parser-input response was not HTTP 200")
    content = getattr(receipt, "content", None)
    if str(getattr(content, "sha256", "") or "") != HR5330_BILLSTATUS_SHA256:
        raise ValueError("GovInfo BILLSTATUS parser-input content digest drifted")
    if int(getattr(content, "byte_size", -1)) != HR5330_BILLSTATUS_BYTE_SIZE:
        raise ValueError("GovInfo BILLSTATUS parser-input content size drifted")
    metadata = dict(getattr(receipt, "metadata", {}) or {})
    if str(metadata.get("jurisdiction") or "").upper() != "AR":
        raise ValueError("GovInfo BILLSTATUS parser-input jurisdiction drifted")
    parser_receipt_sha256 = str(getattr(receipt, "receipt_sha256", "") or "")
    if not _SHA256_RE.fullmatch(parser_receipt_sha256):
        raise ValueError("GovInfo BILLSTATUS parser-input receipt digest is invalid")
    canonical_transport_bytes = json.dumps(
        canonical_transport,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resolution = ArkansasLexisSourceBoundVariantResolution(
        section_number=HR5330_VARIANT_SECTION,
        candidate_node_ids=tuple(sorted(exact_nodes)),
        selected_node_id=HR5330_UNTIL_NODE_ID,
        selected_link_href=HR5330_UNTIL_LINK_HREF,
        source_url=HR5330_BILLSTATUS_URL,
        source_sha256=str(semantics["source_sha256"]),
        source_byte_size=int(semantics["source_byte_size"]),
        source_transport=str(verified_transport.leaf_transport),
        source_transport_receipt_sha256=hashlib.sha256(
            canonical_transport_bytes
        ).hexdigest(),
        parser_input_receipt_sha256=parser_receipt_sha256,
        trigger_act_source_url=ACT1032_URL,
        trigger_act_sha256=str(act1032["sha256"]),
        trigger_act_byte_size=int(act1032["byte_size"]),
        trigger_act_transport=str(act1032["source_transport"]),
        trigger_act_transport_receipt_sha256=str(
            act1032["transport_receipt_sha256"]
        ),
        trigger_act_parser_input_receipt_sha256=str(
            act1032["parser_input_receipt_sha256"]
        ),
        latest_action_date=str(semantics["latest_action_date"]),
        latest_action_text=str(semantics["latest_action_text"]),
        congress_end_date=str(semantics["congress_end_date"]),
        trigger_deadline=str(semantics["trigger_deadline"]),
    )
    object.__setattr__(
        resolution,
        "_evidence_capability",
        _SOURCE_BOUND_VARIANT_CAPABILITY,
    )
    if not resolution.evidence_verified:
        raise ValueError("GovInfo BILLSTATUS source-bound resolution did not verify")
    return resolution


def resolve_act283_source_bound_variants(
    nodes: Iterable[ArkansasLexisNode],
    *,
    trigger_act_retained_input: Any,
    crc_nonoccurrence_retained_input: Any,
    current_dws_form_retained_input: Any,
) -> tuple[ArkansasLexisAct283VariantResolution, ...]:
    """Resolve both Act 283 pairs atomically from three exact official PDFs.

    The two ``until`` locators become the current choices only when all four
    locator identities and all three retained official inputs verify.  Each
    alternate remains represented as a future-contingent exclusion; this is
    not a first/last, content-item-age, or destructive deduplication rule.
    """

    trigger_act = _verify_retained_official_pdf_input(
        trigger_act_retained_input,
        label="Arkansas Act 283",
        official_url=ACT283_URL,
        expected_sha256=ACT283_SHA256,
        expected_byte_size=ACT283_BYTE_SIZE,
    )
    crc_nonoccurrence = _verify_retained_official_pdf_input(
        crc_nonoccurrence_retained_input,
        label="Arkansas CRC Act 283 nonoccurrence record",
        official_url=ACT283_CRC_NONOCCURRENCE_URL,
        expected_sha256=ACT283_CRC_NONOCCURRENCE_SHA256,
        expected_byte_size=ACT283_CRC_NONOCCURRENCE_BYTE_SIZE,
    )
    current_dws_form = _verify_retained_official_pdf_input(
        current_dws_form_retained_input,
        label="Arkansas DWS current withholding form",
        official_url=ACT283_DWS_CURRENT_FORM_URL,
        expected_sha256=ACT283_DWS_CURRENT_FORM_SHA256,
        expected_byte_size=ACT283_DWS_CURRENT_FORM_BYTE_SIZE,
    )
    try:
        dws_observed_at = datetime.fromisoformat(current_dws_form.retrieved_at)
    except ValueError as exc:
        raise ValueError(
            "Arkansas DWS current-form observation time is invalid"
        ) from exc
    if (
        dws_observed_at.tzinfo is None
        or dws_observed_at < ACT283_CURRENT_EVIDENCE_NOT_BEFORE
    ):
        raise ValueError(
            "Arkansas DWS current-form observation predates the fixed inventory"
        )
    if current_dws_form.source_transport != "direct":
        raise ValueError(
            "Arkansas DWS current form requires a live direct observation"
        )

    candidates = list(nodes)
    resolutions: list[ArkansasLexisAct283VariantResolution] = []
    for contract in ACT283_VARIANT_CONTRACT:
        (
            section_number,
            until_node_id,
            until_link_href,
            until_title,
            if_node_id,
            if_link_href,
            if_title,
        ) = contract
        section_candidates = [
            node for node in candidates if node.section_number == section_number
        ]
        if len(section_candidates) != 2 or any(
            not node.evidence_verified for node in section_candidates
        ):
            raise ValueError(
                f"Arkansas {section_number} requires two verified locator "
                "candidates"
            )
        by_node_id = {node.node_id: node for node in section_candidates}
        exact_nodes = {
            until_node_id: (until_link_href, until_title),
            if_node_id: (if_link_href, if_title),
        }
        if len(by_node_id) != 2 or set(by_node_id) != set(exact_nodes):
            raise ValueError(f"Arkansas {section_number} locator node set drifted")
        for node_id, (expected_href, expected_title) in exact_nodes.items():
            node = by_node_id[node_id]
            if node.link_href != expected_href or node.title != expected_title:
                raise ValueError(
                    f"Arkansas {section_number} locator {node_id} drifted"
                )
        resolution = ArkansasLexisAct283VariantResolution(
            section_number=section_number,
            candidate_node_ids=tuple(sorted(exact_nodes)),
            selected_node_id=until_node_id,
            selected_link_href=until_link_href,
            excluded_node_id=if_node_id,
            excluded_link_href=if_link_href,
            excluded_disposition=ACT283_EXCLUSION_DISPOSITION,
            trigger_act=trigger_act,
            crc_nonoccurrence=crc_nonoccurrence,
            current_dws_form=current_dws_form,
            crc_status_statement=ACT283_CRC_NONOCCURRENCE_STATEMENT,
            current_dws_statement=ACT283_DWS_CURRENT_FORM_STATEMENT,
        )
        object.__setattr__(
            resolution,
            "_evidence_capability",
            _SOURCE_BOUND_VARIANT_CAPABILITY,
        )
        if not resolution.evidence_verified:
            raise ValueError(
                f"Arkansas {section_number} Act 283 resolution did not verify"
            )
        resolutions.append(resolution)
    if tuple(item.section_number for item in resolutions) != tuple(
        contract[0] for contract in ACT283_VARIANT_CONTRACT
    ):
        raise ValueError("Arkansas Act 283 resolution bundle is incomplete")
    return tuple(resolutions)


@dataclass(frozen=True)
class _TemporalConstraint:
    kind: str
    start: date | None = None
    end: date | None = None


def _normalized_source_title(value: object) -> str:
    return " ".join(str(value or "").split())


def _parse_source_date(value: str) -> date | None:
    try:
        # The source grammar is a calendar date with no time-of-day or zone.
        return datetime.strptime(value.title(), "%B %d, %Y").date()  # noqa: DTZ007
    except ValueError:
        return None


def _heading_temporal_constraint(heading: str) -> _TemporalConstraint:
    """Parse only the explicit temporal grammar present in the source label."""

    normalized = _normalized_source_title(heading)
    match = _BRACKET_LABEL_RE.search(normalized)
    if match is None:
        return _TemporalConstraint("unmarked")
    label = match.group(1).strip().rstrip(".")
    folded = label.casefold()
    if folded == "repealed":
        return _TemporalConstraint("undated_terminal")
    if "contingency" in folded or "contingent effective date" in folded:
        return _TemporalConstraint("contingent")

    raw_dates = _DATE_TEXT_RE.findall(label)
    dates = tuple(_parse_source_date(value) for value in raw_dates)
    if any(value is None for value in dates):
        return _TemporalConstraint("invalid")
    parsed_dates = tuple(value for value in dates if value is not None)

    if folded.startswith("repealed effective"):
        if (
            len(parsed_dates) != 1
            or not re.search(r"\bon (?:or|and) after\b", folded)
            or "before" in folded
            or "until" in folded
        ):
            return _TemporalConstraint("invalid")
        return _TemporalConstraint("dated_terminal", start=parsed_dates[0])

    if folded.startswith("effective until"):
        # "until tax years beginning before" has no coherent boundary: it is
        # retained verbatim but cannot authorize a current-version choice.
        if len(parsed_dates) != 1 or re.search(r"\bbeginning before\b", folded):
            return _TemporalConstraint("invalid")
        return _TemporalConstraint("bounded", end=parsed_dates[0])

    if not folded.startswith("effective"):
        return _TemporalConstraint("invalid")

    before_match = re.search(
        rf"\bbefore\s+(?P<date>{_DATE_TEXT_PATTERN})", label, re.IGNORECASE
    )
    start_match = re.search(
        rf"\bon (?:or|and) after\s+(?P<date>{_DATE_TEXT_PATTERN})",
        label,
        re.IGNORECASE,
    )
    if "before" in folded:
        if before_match is None:
            return _TemporalConstraint("invalid")
        end = _parse_source_date(before_match.group("date"))
        start = (
            _parse_source_date(start_match.group("date"))
            if start_match is not None
            else None
        )
        if end is None or (start is not None and start >= end):
            return _TemporalConstraint("invalid")
        # A startless interval is accepted only for the source's exact
        # "years beginning before DATE" grammar.
        if start is None and not re.search(r"\byears beginning before\b", folded):
            return _TemporalConstraint("invalid")
        return _TemporalConstraint("bounded", start=start, end=end)

    if start_match is not None and len(parsed_dates) == 1:
        return _TemporalConstraint("bounded", start=parsed_dates[0])
    direct_match = re.fullmatch(
        rf"effective\s+(?P<date>{_DATE_TEXT_PATTERN})",
        label,
        re.IGNORECASE,
    )
    if direct_match is not None:
        start = _parse_source_date(direct_match.group("date"))
        return (
            _TemporalConstraint("bounded", start=start)
            if start is not None
            else _TemporalConstraint("invalid")
        )
    return _TemporalConstraint("invalid")


def reconcile_current_statute_variants(
    nodes: Iterable[ArkansasLexisNode],
    *,
    observed_at: str,
    source_bound_resolutions: Iterable[
        ArkansasLexisVerifiedVariantResolution
    ] = (),
) -> tuple[ArkansasLexisVariantDecision, ...]:
    """Resolve repeated citations only when source labels prove one outcome.

    Undated repeal collisions, condition-triggered alternatives, malformed
    labels, and overlapping active intervals remain explicit unresolved
    decisions.  A fully source-bounded set of expired intervals may resolve to
    ``no_current_locator`` without inventing a replacement section.
    """

    if not _observed_at_valid(observed_at):
        raise ValueError("Arkansas variant observation timestamp is invalid")
    observed_date = datetime.fromisoformat(observed_at).date()
    resolutions_by_section: dict[str, ArkansasLexisVerifiedVariantResolution] = {}
    for resolution in source_bound_resolutions:
        if not (
            isinstance(
                resolution,
                (
                    ArkansasLexisSourceBoundVariantResolution,
                    ArkansasLexisEnactmentTocVariantResolution,
                    ArkansasLexisAct283VariantResolution,
                ),
            )
            and resolution.evidence_verified
        ):
            raise ValueError("Arkansas source-bound variant resolution is unverified")
        if resolution.section_number in resolutions_by_section:
            raise ValueError("Arkansas source-bound variant resolution is duplicated")
        resolutions_by_section[resolution.section_number] = resolution
    consumed_resolutions: set[str] = set()
    grouped: dict[str, list[ArkansasLexisNode]] = {}
    for node in nodes:
        if not node.is_statute_locator:
            continue
        if not node.evidence_verified:
            raise ValueError("Arkansas variant locator lacks verified evidence")
        grouped.setdefault(str(node.section_number), []).append(node)

    decisions: list[ArkansasLexisVariantDecision] = []
    for section_number in sorted(grouped):
        candidates = sorted(
            grouped[section_number], key=lambda node: (node.node_id, node.link_href)
        )
        if len(candidates) < 2:
            continue
        node_ids = tuple(node.node_id for node in candidates)
        if (
            len(set(node_ids)) != len(node_ids)
            or len({node.link_href for node in candidates}) != len(candidates)
        ):
            raise ValueError(
                f"Arkansas variant {section_number} repeats an identity"
            )
        constraints = tuple(
            _heading_temporal_constraint(node.title) for node in candidates
        )
        kinds = {constraint.kind for constraint in constraints}
        resolution = resolutions_by_section.get(section_number)
        if resolution is not None:
            if resolution.candidate_node_ids != node_ids:
                raise ValueError(
                    f"Arkansas source-bound variant {section_number} "
                    "candidate set drifted"
                )
            selected = next(
                (
                    node
                    for node in candidates
                    if node.node_id == resolution.selected_node_id
                ),
                None,
            )
            if (
                selected is None
                or selected.link_href != resolution.selected_link_href
            ):
                raise ValueError(
                    f"Arkansas source-bound variant {section_number} "
                    "selected locator drifted"
                )
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="selected_current_locator",
                    reason=resolution.decision_reason,
                    candidate_node_ids=node_ids,
                    selected_node_id=selected.node_id,
                    selected_link_href=selected.link_href,
                )
            )
            consumed_resolutions.add(section_number)
            continue
        if "contingent" in kinds:
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="unresolved",
                    reason="source_contingency_not_date_resolved",
                    candidate_node_ids=node_ids,
                )
            )
            continue
        if "undated_terminal" in kinds:
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="unresolved",
                    reason="undated_terminal_and_alternate_locator",
                    candidate_node_ids=node_ids,
                )
            )
            continue
        if "invalid" in kinds:
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="unresolved",
                    reason="malformed_or_unknown_temporal_label",
                    candidate_node_ids=node_ids,
                )
            )
            continue

        active = [
            node
            for node, constraint in zip(candidates, constraints, strict=True)
            if (constraint.start is None or constraint.start <= observed_date)
            and (constraint.end is None or observed_date < constraint.end)
        ]
        if len(active) == 1:
            selected = active[0]
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="selected_current_locator",
                    reason="unique_source_interval_active_on_observed_date",
                    candidate_node_ids=node_ids,
                    selected_node_id=selected.node_id,
                    selected_link_href=selected.link_href,
                )
            )
        elif not active:
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="no_current_locator",
                    reason="all_source_intervals_ended_before_observed_date",
                    candidate_node_ids=node_ids,
                )
            )
        else:
            decisions.append(
                ArkansasLexisVariantDecision(
                    section_number=section_number,
                    disposition="unresolved",
                    reason="overlapping_active_source_intervals",
                    candidate_node_ids=node_ids,
                )
            )
    unused_resolutions = set(resolutions_by_section) - consumed_resolutions
    if unused_resolutions:
        raise ValueError(
            "Arkansas source-bound variant resolution did not match a contingent "
            f"citation: {sorted(unused_resolutions)!r}"
        )
    return tuple(decisions)


def enactment_toc_selection_plan_sha256(
    nodes: Iterable[ArkansasLexisNode],
) -> str:
    """Hash all exact locator facts used by the retained 29-row overlay."""

    node_list = list(nodes)
    rows: list[dict[str, Any]] = []
    for section_number, selected_node_id, reason, proof_keys in sorted(
        ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT
    ):
        candidates = sorted(
            (
                node
                for node in node_list
                if node.section_number == section_number
            ),
            key=lambda node: (node.node_id, node.link_href),
        )
        rows.append(
            {
                "candidates": [
                    {
                        "evidence_sha256": node.evidence_sha256,
                        "link_href": node.link_href,
                        "node_id": node.node_id,
                        "node_path": node.node_path,
                        "title": node.title,
                    }
                    for node in candidates
                ],
                "proof_keys": list(proof_keys),
                "reason": reason,
                "section_number": section_number,
                "selected_node_id": selected_node_id,
            }
        )
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def act283_selection_plan_sha256() -> str:
    """Hash the receipt-independent Act 283 selection/preservation algebra."""

    rows = []
    for (
        section_number,
        until_node_id,
        until_link_href,
        _until_title,
        if_node_id,
        if_link_href,
        _if_title,
    ) in ACT283_VARIANT_CONTRACT:
        rows.append(
            {
                "candidate_node_ids": sorted((until_node_id, if_node_id)),
                "preserved_exclusions": [
                    {
                        "disposition": ACT283_EXCLUSION_DISPOSITION,
                        "link_href": if_link_href,
                        "node_id": if_node_id,
                    }
                ],
                "section_number": section_number,
                "selected_link_href": until_link_href,
                "selected_node_id": until_node_id,
            }
        )
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def variant_decision_sha256(
    decisions: Iterable[ArkansasLexisVariantDecision],
) -> str:
    """Return the byte-reproducible digest of an ordered decision plan."""

    payload = [decision.to_dict() for decision in decisions]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _nonstatutory_document_disposition(
    node: ArkansasLexisNode,
    *,
    title_number: str,
    nodes_by_path: Mapping[str, ArkansasLexisNode],
) -> str:
    """Classify an exact non-section document from its retained TOC context."""

    normalized = _normalized_source_title(node.title)
    folded = normalized.casefold()
    immediate_parent = nodes_by_path.get(node.node_path.rsplit("/", 1)[0])
    parent_title = _normalized_source_title(
        immediate_parent.title if immediate_parent is not None else ""
    ).casefold()

    if node.document_disposition == "nonstatutory_unlabeled_probate_form":
        if (
            title_number == "28"
            and parent_title == _UNLABELED_PROBATE_FORMS_PARENT
            and not normalized
        ):
            return node.document_disposition
        return ""

    note_match = _EDITORIAL_NOTE_RE.fullmatch(normalized)
    if note_match is not None:
        return (
            "nonstatutory_editorial_note"
            if str(int(note_match.group("title"))) == title_number
            else ""
        )

    collection_match = _NONOPERATIVE_COLLECTION_RE.fullmatch(normalized)
    if collection_match is not None:
        citations = tuple(
            value
            for value in (
                collection_match.group("first"),
                collection_match.group("last"),
                collection_match.group("second"),
            )
            if value
        )
        if (
            len(citations) != 2
            or len(set(citations)) != 2
        ):
            return ""
        status = collection_match.group("status").casefold()
        citation_titles = tuple(value.split("-", 1)[0] for value in citations)
        if citation_titles[0] != title_number:
            return ""
        if citation_titles[1] != title_number:
            # Preserve the delegated source's exact cross-title endpoint as a
            # typed anomaly; never silently repair or expand it into sections.
            return (
                f"nonstatutory_citation_collection_{status}_"
                "cross_title_source_label"
            )
        return f"nonstatutory_citation_collection_{status}"

    structural_match = _STRUCTURAL_RESERVED_RE.fullmatch(normalized)
    if structural_match is not None:
        kind = structural_match.group("kind").casefold()
        return (
            "nonstatutory_reserved_subchapter"
            if kind.startswith("subchapter")
            else "nonstatutory_reserved_chapter"
        )

    root_dispositions = {
        _CHILD_SUPPORT_GUIDELINES_PARENT: (
            "9",
            "nonstatutory_child_support_guidelines_appendix_root",
        ),
        _SUNSET_LAWS_PARENT: (
            "10",
            "nonstatutory_sunset_laws_appendix_root",
        ),
        _BOND_ISSUES_PARENT: (
            "19",
            "nonstatutory_bond_issues_appendix_root",
        ),
        _UNLABELED_PROBATE_FORMS_PARENT: (
            "28",
            "nonstatutory_probate_forms_appendix_root",
        ),
    }
    root_disposition = root_dispositions.get(folded)
    if root_disposition is not None:
        expected_title, disposition = root_disposition
        return disposition if title_number == expected_title else ""

    if title_number == "9" and parent_title == _CHILD_SUPPORT_GUIDELINES_PARENT:
        if re.fullmatch(r"Section (?:I|II|III|IV|V|VI)\. .+", normalized) or (
            normalized == "FORMS ADDENDUM"
        ):
            return "nonstatutory_child_support_guidelines_component"
        return ""
    if title_number == "10" and parent_title == _SUNSET_LAWS_PARENT:
        return (
            "nonstatutory_sunset_law_enactment"
            if re.fullmatch(r"[1-9]\d*\. Acts \d{4}.+", normalized)
            else ""
        )
    if title_number == "19" and parent_title == _BOND_ISSUES_PARENT:
        return (
            "nonstatutory_bond_issue_enactment"
            if re.match(r"[1-9]\d*\. ", normalized)
            and re.search(r"(?:Acts \d{4}|Amend\. \d+)", normalized)
            else ""
        )
    if title_number == "28" and parent_title == _UNLABELED_PROBATE_FORMS_PARENT:
        return (
            "nonstatutory_probate_forms_component"
            if normalized in {"Authority.", "Captions and Affidavits.", "Forms."}
            else ""
        )
    return ""


def node_from_mapping(value: Mapping[str, Any]) -> ArkansasLexisNode | None:
    """Normalize one exact Lexis TOC node mapping."""

    props = value.get("props")
    if not isinstance(props, Mapping):
        return None
    top_level_id = str(value.get("id") or "").strip()
    props_id = str(props.get("nodeid") or "").strip()
    if top_level_id and props_id and top_level_id != props_id:
        return None
    node_id = top_level_id or props_id
    title = str(props.get("linktemplatetitle") or props.get("title") or "").strip()
    level = _as_int(props.get("level"))
    node_path = str(props.get("nodepath") or "").strip()
    if (
        not _NODE_ID_RE.fullmatch(node_id)
        or level is None
        or level < 1
        or node_path != f"/ROOT/{node_id}"
        and not node_path.endswith(f"/{node_id}")
        or not any(
            key in props for key in ("canexpand", "canopen", "haschildren", "linkhref")
        )
    ):
        return None
    pricing = props.get("tocpricing")
    pricing_map = pricing if isinstance(pricing, Mapping) else {}
    link_href = str(props.get("linkhref") or "").strip()
    if link_href and not is_document_path(link_href):
        return None
    node = ArkansasLexisNode(
        node_id=node_id,
        title=title,
        level=level,
        node_path=node_path,
        can_expand=_as_bool(props.get("canexpand")),
        can_open=_as_bool(props.get("canopen")),
        has_children=_as_bool(props.get("haschildren")),
        link_href=link_href,
        subscribed=_as_optional_bool(props.get("subscribed")),
        purchase_required=_as_optional_bool(pricing_map.get("purchaserequired")),
        list_price=_as_float(pricing_map.get("listprice")),
        net_price=_as_float(pricing_map.get("netprice")),
        pricing_present=bool(pricing_map),
        currency_code=str(pricing_map.get("currencycode") or ""),
        usage_type_code=str(pricing_map.get("usagetypecode") or ""),
        document_status=str(pricing_map.get("documentstatus") or ""),
    )
    candidate_valid = bool(
        _NODE_ID_RE.fullmatch(node.node_id)
        and node.level >= 1
        and node.node_path.startswith("/ROOT/")
        and (
            node.node_path == f"/ROOT/{node.node_id}"
            or node.node_path.endswith(f"/{node.node_id}")
        )
        and (not node.link_href or is_document_path(node.link_href))
        and (
            node.title.strip()
            or (
                node.can_open
                and not node.can_expand
                and not node.has_children
                and bool(node.link_href)
                and node.public_document_available
            )
        )
    )
    return node if candidate_valid else None


def _bind_live_nodes(
    nodes: Iterable[ArkansasLexisNode],
    *,
    source_url: str,
    observed_at: str,
    receipt_sha256: str,
) -> list[ArkansasLexisNode]:
    """Bind exact live-container response evidence to validated nodes."""

    if not (
        container_url_matches(source_url)
        and _observed_at_valid(observed_at)
        and _SHA256_RE.fullmatch(receipt_sha256)
    ):
        return []
    bound: list[ArkansasLexisNode] = []
    for node in nodes:
        if not _node_shape_valid(node):
            return []
        verified = replace(
            node,
            evidence_source_url=source_url,
            evidence_observed_at=observed_at,
            evidence_sha256=receipt_sha256,
        )
        object.__setattr__(verified, "_evidence_capability", _LIVE_EVIDENCE_CAPABILITY)
        if not verified.evidence_verified:
            return []
        bound.append(verified)
    return bound


def parse_expansion_payload(
    payload: object,
    *,
    parent: ArkansasLexisNode,
) -> tuple[list[ArkansasLexisNode], str]:
    """Validate the complete direct-child collection for one expansion."""

    if not parent.evidence_verified or not (parent.can_expand or parent.has_children):
        return [], "parent is not a verified expandable node"
    if not isinstance(payload, Mapping):
        return [], "payload is not an object"
    props = payload.get("props")
    if isinstance(props, Mapping) and props.get("error"):
        return [], "payload contains an error"
    collections = payload.get("collections")
    container = (
        collections.get("toccontainer") if isinstance(collections, Mapping) else None
    )
    nested = container.get("collections") if isinstance(container, Mapping) else None
    raw_nodes = nested.get("tocnodes") if isinstance(nested, Mapping) else None
    if not isinstance(raw_nodes, Sequence) or isinstance(
        raw_nodes, (str, bytes, bytearray)
    ):
        return [], "payload lacks the exact tocnodes collection"
    if not raw_nodes:
        return [], "expandable parent returned no children"

    children: list[ArkansasLexisNode] = []
    seen: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, Mapping):
            return [], "child is not an object"
        child = node_from_mapping(raw_node)
        if child is None:
            return [], "child is malformed"
        if (
            child.node_id in seen
            or child.level != parent.level + 1
            or child.node_path != f"{parent.node_path}/{child.node_id}"
        ):
            return [], "child is duplicate or outside its parent branch"
        seen.add(child.node_id)
        children.append(child)
    return children, ""


def parse_toc_payload(payload: object) -> list[ArkansasLexisNode]:
    """Recursively normalize every TOC node in a nested source response.

    This convenience parser is intentionally non-authorizing.  Exhaustive
    discovery additionally applies :func:`parse_title_subtree_payload`, which
    rejects malformed node-shaped mappings, duplicates, broken ancestry, and
    title-crossing section citations before live evidence is bound.
    """

    nodes: list[ArkansasLexisNode] = []
    seen: set[str] = set()

    def _walk(value: object) -> None:
        if isinstance(value, Mapping):
            node = node_from_mapping(value)
            if node is not None and node.node_id not in seen:
                seen.add(node.node_id)
                nodes.append(node)
            for child in value.values():
                _walk(child)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for child in value:
                _walk(child)

    _walk(payload)
    return nodes


def parse_title_subtree_payload(
    payload: object,
    *,
    parent: ArkansasLexisNode,
    target_level: int,
) -> tuple[list[ArkansasLexisNode], tuple[str, ...], str]:
    """Validate one deepest-level response as a complete title subtree.

    The returned expansion IDs are exactly the expandable nodes proven closed
    by the response.  No fixture or caller-built parent can authorize this
    path: the title root must already carry live public-container evidence.
    """

    if not (
        parent.evidence_verified
        and parent.level == 1
        and parent.title_number in EXPECTED_TITLE_NUMBERS
        and (parent.can_expand or parent.has_children)
    ):
        return [], (), "parent is not a verified expandable title root"
    if (
        isinstance(target_level, bool)
        or not isinstance(target_level, int)
        or target_level < 2
        or target_level > MAX_EXHAUSTIVE_TOC_LEVEL
    ):
        return [], (), "target level is outside the supported TOC range"
    if not isinstance(payload, Mapping):
        return [], (), "payload is not an object"
    props = payload.get("props")
    if isinstance(props, Mapping) and props.get("error"):
        return [], (), "payload contains an error"

    nodes: list[ArkansasLexisNode] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    malformed = False

    def _walk(value: object) -> None:
        nonlocal malformed
        if isinstance(value, Mapping):
            raw_props = value.get("props")
            node_shaped = bool(
                isinstance(raw_props, Mapping)
                and any(
                    key in raw_props
                    for key in (
                        "nodeid",
                        "nodepath",
                        "level",
                        "linktemplatetitle",
                        "canexpand",
                        "canopen",
                        "haschildren",
                        "linkhref",
                    )
                )
            )
            if node_shaped:
                node = node_from_mapping(value)
                if (
                    node is None
                    or node.node_id in seen_ids
                    or node.node_path in seen_paths
                ):
                    malformed = True
                else:
                    seen_ids.add(node.node_id)
                    seen_paths.add(node.node_path)
                    nodes.append(node)
            for child in value.values():
                _walk(child)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for child in value:
                _walk(child)

    _walk(payload)
    if malformed:
        return [], (), "subtree contains a malformed or duplicate TOC node"
    if not nodes:
        return [], (), "subtree contains no TOC nodes"

    prefix = f"{parent.node_path}/"
    branch_paths = {parent.node_path, *(node.node_path for node in nodes)}
    for node in nodes:
        if (
            not node.node_path.startswith(prefix)
            or node.level <= parent.level
            or node.level > target_level
        ):
            return [], (), "subtree contains a node outside the requested title"
        path_parts = [part for part in node.node_path.split("/") if part]
        if node.level != len(path_parts) - 1:
            return [], (), "subtree node level does not match its path"
        immediate_parent_path = "/" + "/".join(path_parts[:-1])
        if immediate_parent_path not in branch_paths:
            return [], (), "subtree contains a node without its immediate parent"
        if (
            node.is_statute_locator
            and node.section_number
            and node.section_number.split("-", 1)[0] != parent.title_number
        ):
            return [], (), "statute locator crossed the requested title boundary"

    nodes_by_path = {parent.node_path: parent}
    nodes_by_path.update({node.node_path: node for node in nodes})
    classified_nodes: list[ArkansasLexisNode] = []
    for node in nodes:
        if node.title.strip() or not node.public_document_available:
            classified_nodes.append(node)
            continue
        parent_node = nodes_by_path.get(node.node_path.rsplit("/", 1)[0])
        normalized_parent_title = " ".join(
            str(parent_node.title if parent_node else "").split()
        ).casefold()
        if not (
            parent.title_number == "28"
            and parent_node is not None
            and parent_node.level == 2
            and normalized_parent_title == _UNLABELED_PROBATE_FORMS_PARENT
            and node.level == 3
            and node.can_open
            and not node.can_expand
            and not node.has_children
            and node.public_document_available
        ):
            return [], (), "unlabeled document is outside the exact probate-forms tail"
        classified_nodes.append(
            replace(
                node,
                document_disposition="nonstatutory_unlabeled_probate_form",
            )
        )
    nodes = classified_nodes

    nodes_by_path = {parent.node_path: parent}
    nodes_by_path.update({node.node_path: node for node in nodes})
    typed_nodes: list[ArkansasLexisNode] = []
    for node in nodes:
        if not node.public_document_available or node.is_statute_locator:
            typed_nodes.append(node)
            continue
        disposition = _nonstatutory_document_disposition(
            node,
            title_number=str(parent.title_number),
            nodes_by_path=nodes_by_path,
        )
        if not disposition:
            return (
                [],
                (),
                f"nonstatutory document {node.node_id} has an untyped source label",
            )
        typed_nodes.append(replace(node, document_disposition=disposition))
    nodes = typed_nodes

    expandable = [
        node for node in (parent, *nodes) if node.can_expand or node.has_children
    ]
    for node in expandable:
        expected_child_level = node.level + 1
        if not any(
            candidate.node_path.startswith(f"{node.node_path}/")
            and candidate.level == expected_child_level
            and candidate.node_path.count("/") == node.node_path.count("/") + 1
            for candidate in nodes
        ):
            return [], (), f"expandable node {node.node_id} has no direct child"

    sections_by_number: dict[str, list[ArkansasLexisNode]] = {}
    nodes_by_path = {node.node_path: node for node in nodes}

    def _ancestor_title_chain(node: ArkansasLexisNode) -> tuple[str, ...]:
        parts = [part for part in node.node_path.split("/") if part]
        titles: list[str] = []
        # Skip ROOT and the already source-bound title root.  Distinct Lexis
        # node IDs may repeat an otherwise identical official subchapter path.
        for end in range(3, len(parts)):
            ancestor = nodes_by_path.get("/" + "/".join(parts[:end]))
            if ancestor is None:
                return ()
            titles.append(" ".join(ancestor.title.split()).casefold())
        return tuple(titles)

    for node in nodes:
        if node.is_statute_locator:
            sections_by_number.setdefault(str(node.section_number), []).append(node)
    for section_number, variants in sections_by_number.items():
        if len(variants) < 2:
            continue
        ancestor_title_chains = {_ancestor_title_chain(node) for node in variants}
        document_paths = {node.link_href for node in variants}
        if () in ancestor_title_chains or len(ancestor_title_chains) != 1:
            return (
                [],
                (),
                f"section {section_number} repeats across different hierarchies",
            )
        if len(document_paths) != len(variants):
            return (
                [],
                (),
                f"section {section_number} reuses an official document locator",
            )
    return nodes, tuple(node.node_id for node in expandable), ""


def parse_root_dom_rows(rows: Iterable[Mapping[str, Any]]) -> list[ArkansasLexisNode]:
    """Normalize the 28 rendered root title nodes."""

    nodes: list[ArkansasLexisNode] = []
    seen: set[str] = set()
    for row in rows:
        node_id = str(row.get("nodeid") or "").strip()
        title = str(row.get("title") or "").strip()
        level = _as_int(row.get("level"))
        node_path = str(row.get("nodepath") or "").strip()
        if (
            not _NODE_ID_RE.fullmatch(node_id)
            or node_id in seen
            or not title
            or level != 1
            or node_path != f"/ROOT/{node_id}"
        ):
            continue
        seen.add(node_id)
        nodes.append(
            ArkansasLexisNode(
                node_id=node_id,
                title=title,
                level=1,
                node_path=node_path,
                can_expand=_as_bool(row.get("canexpand")),
                can_open=_as_bool(row.get("canopen")),
                has_children=_as_bool(row.get("haschildren")),
            )
        )
    return nodes


@dataclass(frozen=True)
class ArkansasLexisInventory:
    status: str
    final_url: str
    observed_at: str
    delegation_verified: bool
    nodes: tuple[ArkansasLexisNode, ...]
    expanded_node_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]
    root_rendered_sha256: str = ""
    expansion_response_sha256: tuple[tuple[str, str], ...] = ()
    root_rendered_path: str = ""
    expansion_response_paths: tuple[tuple[str, str], ...] = ()

    @property
    def frontier(self) -> dict[str, Any]:
        titles = [node for node in self.nodes if node.level == 1 and node.title_number]
        found = [str(node.title_number) for node in titles]
        expected = set(EXPECTED_TITLE_NUMBERS)
        discovered = set(found)
        counts = {number: found.count(number) for number in discovered}
        declared_expanded = set(self.expanded_node_ids)
        response_hashes = dict(self.expansion_response_sha256)
        response_paths = dict(self.expansion_response_paths)
        closed_expanded = {
            node.node_id
            for node in self.nodes
            if (
                node.expansion_closed
                and node.evidence_verified
                and node.node_id in declared_expanded
                and response_hashes.get(node.node_id) == node.evidence_sha256
            )
        }
        unresolved = sorted(
            node.node_id
            for node in self.nodes
            if (node.can_expand or node.has_children)
            and node.node_id not in closed_expanded
        )
        section_nodes = [node for node in self.nodes if node.is_statute_locator]
        document_nodes = [node for node in self.nodes if node.public_document_available]
        nonstatutory_documents = [
            node for node in document_nodes if not node.is_statute_locator
        ]
        typed_unlabeled_documents = [
            node
            for node in nonstatutory_documents
            if node.document_disposition
            == "nonstatutory_unlabeled_probate_form"
        ]
        disposition_counts: dict[str, int] = {}
        for node in nonstatutory_documents:
            if node.document_disposition:
                disposition_counts[node.document_disposition] = (
                    disposition_counts.get(node.document_disposition, 0) + 1
                )
        untyped_nonstatutory_documents = [
            node for node in nonstatutory_documents if not node.document_disposition
        ]
        section_counts: dict[str, int] = {}
        for node in section_nodes:
            section = str(node.section_number or "")
            section_counts[section] = section_counts.get(section, 0) + 1
        duplicate_sections = sorted(
            section for section, count in section_counts.items() if count > 1
        )
        concurrent_variant_locator_count = sum(
            count for count in section_counts.values() if count > 1
        )
        variant_decisions: tuple[ArkansasLexisVariantDecision, ...] = ()
        variant_reconciliation_valid = False
        if (
            _observed_at_valid(self.observed_at)
            and all(node.evidence_verified for node in section_nodes)
        ):
            try:
                variant_decisions = reconcile_current_statute_variants(
                    section_nodes,
                    observed_at=self.observed_at,
                )
                variant_reconciliation_valid = (
                    len(variant_decisions) == len(duplicate_sections)
                )
            except ValueError:
                variant_decisions = ()
        selected_variant_decisions = [
            decision
            for decision in variant_decisions
            if decision.disposition == "selected_current_locator"
        ]
        no_current_variant_decisions = [
            decision
            for decision in variant_decisions
            if decision.disposition == "no_current_locator"
        ]
        unresolved_variant_decisions = [
            decision
            for decision in variant_decisions
            if decision.disposition == "unresolved"
        ]
        title_closed = bool(
            self.delegation_verified
            and container_url_matches(self.final_url)
            and _observed_at_valid(self.observed_at)
            and _SHA256_RE.fullmatch(self.root_rendered_sha256)
            and discovered == expected
            and all(value == 1 for value in counts.values())
            and len(titles) == len(EXPECTED_TITLE_NUMBERS)
            and all(node.evidence_verified for node in titles)
        )
        expansion_receipts_valid = bool(
            len(declared_expanded) == len(self.expanded_node_ids)
            and len(response_hashes) == len(self.expansion_response_sha256)
            and declared_expanded == set(response_hashes)
            and declared_expanded == closed_expanded
            and all(_SHA256_RE.fullmatch(value) for value in response_hashes.values())
        )
        retained_response_paths_valid = bool(
            not self.expansion_response_paths
            or (
                len(response_paths) == len(self.expansion_response_paths)
                and set(response_paths) == declared_expanded
                and all(
                    value.startswith("title-open-to/")
                    and ".." not in Path(value).parts
                    for value in response_paths.values()
                )
            )
        )
        toc_closed = bool(
            title_closed
            and not unresolved
            and expansion_receipts_valid
            and retained_response_paths_valid
            and self.nodes
            and all(node.evidence_verified for node in self.nodes)
            and not untyped_nonstatutory_documents
            and self.status == "complete"
        )
        return {
            "method": "official_delegated_arkansas_lexis_toc",
            "expected_title_count": len(EXPECTED_TITLE_NUMBERS),
            "discovered_title_count": len(titles),
            "discovered_title_numbers": sorted(discovered, key=int),
            "missing_title_numbers": sorted(expected - discovered, key=int),
            "extra_title_numbers": sorted(discovered - expected, key=int),
            "duplicate_title_numbers": sorted(
                (number for number, count in counts.items() if count > 1), key=int
            ),
            "delegation_verified": self.delegation_verified,
            "verified_node_count": sum(node.evidence_verified for node in self.nodes),
            "title_inventory_closed": title_closed,
            "expanded_node_count": len(closed_expanded),
            "expansion_receipts_valid": expansion_receipts_valid,
            "retained_response_paths_valid": retained_response_paths_valid,
            "retained_expansion_response_count": len(
                set(response_paths.values())
            ),
            "unresolved_expandable_node_ids": unresolved,
            "document_locator_count": len(document_nodes),
            "statute_locator_count": len(section_nodes),
            "duplicate_statute_section_numbers": duplicate_sections,
            "unique_statute_citation_count": len(section_counts),
            "concurrent_variant_citation_count": len(duplicate_sections),
            "concurrent_variant_locator_count": concurrent_variant_locator_count,
            "current_variant_reconciliation_valid": variant_reconciliation_valid,
            "current_variant_reconciliation_observed_date": (
                datetime.fromisoformat(self.observed_at).date().isoformat()
                if _observed_at_valid(self.observed_at)
                else ""
            ),
            "current_variant_selected_citation_count": len(
                selected_variant_decisions
            ),
            "current_variant_no_current_citation_count": len(
                no_current_variant_decisions
            ),
            "current_variant_unresolved_citation_count": len(
                unresolved_variant_decisions
            ),
            "current_variant_unresolved_section_numbers": [
                decision.section_number for decision in unresolved_variant_decisions
            ],
            "current_variant_decision_sha256": (
                variant_decision_sha256(variant_decisions)
                if variant_reconciliation_valid
                else ""
            ),
            "non_statute_document_locator_count": len(nonstatutory_documents),
            "non_statute_document_disposition_counts": dict(
                sorted(disposition_counts.items())
            ),
            "untyped_non_statute_document_locator_count": len(
                untyped_nonstatutory_documents
            ),
            "typed_unlabeled_probate_form_locator_count": len(
                typed_unlabeled_documents
            ),
            "toc_frontier_closed": toc_closed,
            "document_body_count": 0,
            "body_frontier_closed": False,
            "frontier_closed": False,
            "full_corpus_admissible": False,
        }

    def to_dict(self) -> dict[str, Any]:
        authority_verified = bool(
            self.delegation_verified
            and container_url_matches(self.final_url)
            and self.nodes
            and all(node.evidence_verified for node in self.nodes)
        )
        return {
            "schema_version": "arkansas-lexis-inventory-v3",
            "status": self.status,
            "final_url": self.final_url,
            "observed_at": self.observed_at,
            "delegation_verified": self.delegation_verified,
            "nodes": [node.to_dict() for node in self.nodes],
            "expanded_node_ids": list(self.expanded_node_ids),
            "diagnostics": list(self.diagnostics),
            "root_rendered_sha256": self.root_rendered_sha256,
            "root_rendered_path": self.root_rendered_path,
            "expansion_response_sha256": [
                list(item) for item in self.expansion_response_sha256
            ],
            "expansion_response_paths": [
                list(item) for item in self.expansion_response_paths
            ],
            "frontier": self.frontier,
            "official_referrer": OFFICIAL_REFERRER,
            "public_entry_url": PUBLIC_ENTRY_URL,
            "public_container_url": PUBLIC_CONTAINER_URL,
            "source_authority_class": (
                "official" if authority_verified else "unverified"
            ),
        }

    def write(self, output_path: str | Path) -> Path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path


def load_exact_retained_inventory(
    inventory_path: str | Path,
) -> tuple[ArkansasLexisInventory, str]:
    """Load the fixed v6 inventory only after all retained bytes verify."""

    unresolved_path = Path(inventory_path).expanduser()
    if not unresolved_path.is_file() or unresolved_path.is_symlink():
        raise ValueError("Arkansas retained inventory path is not a regular file")
    path = unresolved_path.resolve()
    payload = path.read_bytes()
    inventory_sha256 = hashlib.sha256(payload).hexdigest()
    if inventory_sha256 != ARKANSAS_DELEGATED_INVENTORY_SHA256:
        raise ValueError("Arkansas delegated inventory fingerprint drifted")
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("Arkansas delegated inventory JSON is invalid") from exc
    if not isinstance(value, Mapping):
        raise ValueError("Arkansas delegated inventory root is invalid")

    evidence_root = path.parent / "evidence"
    if not evidence_root.is_dir() or evidence_root.is_symlink():
        raise ValueError("Arkansas retained inventory evidence root is invalid")
    retained_hashes: set[str] = set()

    def _verify_relative_evidence(relative: object, expected: object) -> None:
        relative_value = str(relative or "").strip()
        expected_value = str(expected or "").strip().lower()
        relative_path = Path(relative_value)
        if (
            not relative_value
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or not _SHA256_RE.fullmatch(expected_value)
        ):
            raise ValueError("Arkansas retained inventory evidence identity drifted")
        unresolved_evidence_path = evidence_root
        for part in relative_path.parts:
            unresolved_evidence_path /= part
            if unresolved_evidence_path.is_symlink():
                raise ValueError(
                    "Arkansas retained inventory evidence must not use symlinks"
                )
        evidence_path = unresolved_evidence_path.resolve()
        try:
            evidence_path.relative_to(evidence_root.resolve())
        except ValueError as exc:
            raise ValueError(
                "Arkansas retained inventory evidence escaped its root"
            ) from exc
        if not evidence_path.is_file():
            raise ValueError("Arkansas retained inventory evidence is missing")
        actual = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if actual != expected_value:
            raise ValueError("Arkansas retained inventory evidence bytes drifted")
        retained_hashes.add(actual)

    _verify_relative_evidence(
        value.get("root_rendered_path"),
        value.get("root_rendered_sha256"),
    )
    response_paths = dict(value.get("expansion_response_paths") or ())
    response_hashes = dict(value.get("expansion_response_sha256") or ())
    if set(response_paths) != set(response_hashes):
        raise ValueError("Arkansas retained expansion evidence lost alignment")
    verified_relative_paths: set[str] = set()
    for node_id in sorted(response_paths):
        relative = str(response_paths[node_id] or "")
        expected = str(response_hashes[node_id] or "")
        if relative in verified_relative_paths:
            if expected not in retained_hashes:
                raise ValueError(
                    "Arkansas retained expansion evidence alias drifted"
                )
            continue
        _verify_relative_evidence(relative, expected)
        verified_relative_paths.add(relative)

    serialized_nodes = value.get("nodes")
    if not isinstance(serialized_nodes, list) or not serialized_nodes:
        raise ValueError("Arkansas retained inventory nodes are missing")
    nodes: list[ArkansasLexisNode] = []
    for serialized in serialized_nodes:
        if not isinstance(serialized, Mapping):
            raise ValueError("Arkansas retained inventory node is invalid")
        raw = ArkansasLexisNode(
            node_id=str(serialized.get("node_id") or ""),
            title=str(serialized.get("title") or ""),
            level=int(serialized.get("level") or 0),
            node_path=str(serialized.get("node_path") or ""),
            can_expand=bool(serialized.get("can_expand")),
            can_open=bool(serialized.get("can_open")),
            has_children=bool(serialized.get("has_children")),
            link_href=str(serialized.get("link_href") or ""),
            subscribed=serialized.get("subscribed"),
            purchase_required=serialized.get("purchase_required"),
            list_price=serialized.get("list_price"),
            net_price=serialized.get("net_price"),
            pricing_present=bool(serialized.get("pricing_present")),
            currency_code=str(serialized.get("currency_code") or ""),
            usage_type_code=str(serialized.get("usage_type_code") or ""),
            document_status=str(serialized.get("document_status") or ""),
            document_disposition=str(
                serialized.get("document_disposition") or ""
            ),
            expansion_closed=bool(serialized.get("expansion_closed")),
        )
        evidence_sha256 = str(serialized.get("evidence_sha256") or "")
        if evidence_sha256 not in retained_hashes:
            raise ValueError(
                "Arkansas retained node lacks its exact response bytes"
            )
        bound = _bind_live_nodes(
            (raw,),
            source_url=str(serialized.get("evidence_source_url") or ""),
            observed_at=str(serialized.get("evidence_observed_at") or ""),
            receipt_sha256=evidence_sha256,
        )
        if len(bound) != 1 or not bound[0].evidence_verified:
            raise ValueError("Arkansas retained inventory node did not verify")
        nodes.append(bound[0])

    nodes_by_path = {node.node_path: node for node in nodes}
    typed_nodes: list[ArkansasLexisNode] = []
    for node in nodes:
        if (
            not node.public_document_available
            or node.is_statute_locator
            or node.document_disposition
        ):
            typed_nodes.append(node)
            continue
        path_parts = node.node_path.split("/")
        title_node = nodes_by_path.get(
            f"/ROOT/{path_parts[2]}" if len(path_parts) > 2 else ""
        )
        title_number = str(title_node.title_number if title_node else "")
        disposition = _nonstatutory_document_disposition(
            node,
            title_number=title_number,
            nodes_by_path=nodes_by_path,
        )
        if not disposition:
            raise ValueError(
                "Arkansas retained inventory contains an untyped document"
            )
        classified = replace(node, document_disposition=disposition)
        object.__setattr__(
            classified,
            "_evidence_capability",
            _LIVE_EVIDENCE_CAPABILITY,
        )
        if not classified.evidence_verified:
            raise ValueError(
                "Arkansas retained document classification lost evidence"
            )
        typed_nodes.append(classified)
    nodes = typed_nodes

    inventory = ArkansasLexisInventory(
        status=str(value.get("status") or ""),
        final_url=str(value.get("final_url") or ""),
        observed_at=str(value.get("observed_at") or ""),
        delegation_verified=value.get("delegation_verified") is True,
        nodes=tuple(nodes),
        expanded_node_ids=tuple(value.get("expanded_node_ids") or ()),
        diagnostics=tuple(value.get("diagnostics") or ()),
        root_rendered_sha256=str(value.get("root_rendered_sha256") or ""),
        expansion_response_sha256=tuple(
            (str(item[0]), str(item[1]))
            for item in value.get("expansion_response_sha256") or ()
        ),
        root_rendered_path=str(value.get("root_rendered_path") or ""),
        expansion_response_paths=tuple(
            (str(item[0]), str(item[1]))
            for item in value.get("expansion_response_paths") or ()
        ),
    )
    frontier = inventory.frontier
    if not (
        inventory.status == "complete"
        and frontier.get("toc_frontier_closed") is True
        and int(frontier.get("statute_locator_count") or 0) == 38_317
        and int(frontier.get("unique_statute_citation_count") or 0) == 38_183
        and int(frontier.get("concurrent_variant_citation_count") or 0) == 132
    ):
        raise ValueError("Arkansas retained inventory frontier did not close")
    return inventory, inventory_sha256


def _failed_inventory(status: str, diagnostic: str) -> ArkansasLexisInventory:
    return ArkansasLexisInventory(
        status=status,
        final_url="",
        observed_at=datetime.now(UTC).isoformat(),
        delegation_verified=False,
        nodes=(),
        expanded_node_ids=(),
        diagnostics=(diagnostic,),
    )


def _retain_live_evidence_path(
    evidence_dir: Path | None,
    *,
    relative: str,
    payload: bytes,
) -> str:
    """Retain immutable live response bytes beneath an explicit evidence root."""

    if evidence_dir is None:
        return ""
    target = (evidence_dir / relative).resolve()
    target.relative_to(evidence_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise RuntimeError(f"retained Arkansas evidence collision: {target}")
    else:
        target.write_bytes(payload)
    return target.relative_to(evidence_dir).as_posix()


async def _live_toc_patch(
    page: Any,
    *,
    endpoint: str,
    patch_body: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Submit one same-origin public TOC request without UI interaction."""

    raw_result = await page.evaluate(
        """
        async ({endpoint, patchBody}) => {
          const headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
          };
          const requestId = new URL(location.href).searchParams.get('crid');
          if (requestId) headers['X-LN-CurrentRequestId'] = requestId;
          const response = await fetch(endpoint, {
            method: 'PATCH', credentials: 'same-origin', headers,
            body: JSON.stringify(patchBody)
          });
          return {
            status: response.status,
            contentType: response.headers.get('content-type') || '',
            text: await response.text()
          };
        }
        """,
        {"endpoint": endpoint, "patchBody": dict(patch_body)},
    )
    return raw_result if isinstance(raw_result, Mapping) else None


async def _live_toc_patch_with_retries(
    page: Any,
    *,
    endpoint: str,
    patch_body: Mapping[str, Any],
    retry_count: int,
) -> tuple[Mapping[str, Any] | None, str]:
    """Retry only transport/status failures and return their exact boundary."""

    result: Mapping[str, Any] | None = None
    last_error = ""
    for attempt in range(retry_count):
        result = await _live_toc_patch(
            page,
            endpoint=endpoint,
            patch_body=patch_body,
        )
        if (
            result is not None
            and int(result.get("status") or 0) == 200
            and "json" in str(result.get("contentType") or "").lower()
        ):
            return result, ""
        last_error = f"HTTP {result.get('status') if result else 'missing'}"
        if result is not None and int(result.get("status") or 0) == 200:
            last_error += " with non-JSON content type"
        await asyncio.sleep(min(1.0, 0.15 * (attempt + 1)))
    return result, last_error


async def _discover_exhaustive_title_subtrees(
    *,
    page: Any,
    dom_rows: Sequence[Mapping[str, Any]],
    bound_root_nodes: Sequence[ArkansasLexisNode],
    nodes_by_id: dict[str, ArkansasLexisNode],
    expanded: list[str],
    response_hashes: list[tuple[str, str]],
    response_paths: list[tuple[str, str]],
    retry_count: int,
    delay: float,
    source_url: str,
    observed_at: str,
    evidence_root: Path | None,
) -> str:
    """Populate a closed 28-title frontier or return one exact failure."""

    target_levels_by_id: dict[str, tuple[int, ...]] = {}
    for row in dom_rows:
        if not isinstance(row, Mapping):
            return "rendered title row is not an object"
        node_id = str(row.get("nodeid") or "").strip()
        raw_levels = row.get("targetlevels")
        if not isinstance(raw_levels, Sequence) or isinstance(
            raw_levels, (str, bytes, bytearray)
        ):
            return f"title {node_id or '<missing>'} did not advertise open-to levels"
        levels: list[int] = []
        for raw_level in raw_levels:
            if isinstance(raw_level, bool):
                return f"title {node_id} advertised a non-integer open-to level"
            level = _as_int(raw_level)
            if level is None or not 2 <= level <= MAX_EXHAUSTIVE_TOC_LEVEL:
                return f"title {node_id} advertised an invalid open-to level"
            levels.append(level)
        if not levels or len(levels) != len(set(levels)):
            return f"title {node_id} advertised missing or duplicate open-to levels"
        target_levels_by_id[node_id] = tuple(sorted(levels))

    title_nodes = sorted(
        bound_root_nodes,
        key=lambda node: int(node.title_number or 0),
    )
    if tuple(node.title_number for node in title_nodes) != EXPECTED_TITLE_NUMBERS:
        return "exhaustive discovery requires exact ordered Title 1-28 roots"
    if set(target_levels_by_id) != {node.node_id for node in title_nodes}:
        return "open-to level inventory did not align with the 28 title roots"

    for parent in title_nodes:
        target_level = max(target_levels_by_id[parent.node_id])
        endpoint, patch_body = toc_open_to_request(
            parent.node_id,
            target_level=target_level,
        )
        result, request_error = await _live_toc_patch_with_retries(
            page,
            endpoint=endpoint,
            patch_body=patch_body,
            retry_count=retry_count,
        )
        if request_error:
            return (
                f"title open-to {parent.node_id} level {target_level} "
                f"failed after retries: {request_error}"
            )
        if result is None:
            return f"title open-to {parent.node_id} returned no receipt"

        response_text = str(result.get("text") or "")
        response_bytes = response_text.encode("utf-8")
        response_hash = hashlib.sha256(response_bytes).hexdigest()
        retained_path = _retain_live_evidence_path(
            evidence_root,
            relative=(
                "title-open-to/"
                f"{parent.node_id}-level-{target_level}-{response_hash}.json"
            ),
            payload=response_bytes,
        )
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            return f"title open-to {parent.node_id} returned invalid JSON"
        descendants, closed_ids, parse_error = parse_title_subtree_payload(
            payload,
            parent=parent,
            target_level=target_level,
        )
        if parse_error:
            return f"title open-to {parent.node_id}: {parse_error}"
        bound_descendants = _bind_live_nodes(
            descendants,
            source_url=source_url,
            observed_at=observed_at,
            receipt_sha256=response_hash,
        )
        if len(bound_descendants) != len(descendants):
            return f"title open-to {parent.node_id}: live evidence binding failed"

        branch_by_id = {node.node_id: node for node in bound_descendants}
        branch_by_id[parent.node_id] = parent
        closed_by_id: dict[str, ArkansasLexisNode] = {}
        for node_id in closed_ids:
            node = branch_by_id.get(node_id)
            if node is None:
                return f"title open-to {parent.node_id}: closed node is absent"
            closed = dataclass_replace_closed(
                node,
                evidence_sha256=response_hash,
                evidence_source_url=source_url,
                evidence_observed_at=observed_at,
            )
            if closed is None:
                return f"title open-to {parent.node_id}: closure binding failed"
            closed_by_id[node_id] = closed

        branch_nodes = [
            closed_by_id.get(node.node_id, node) for node in bound_descendants
        ]
        branch_ids = {node.node_id for node in branch_nodes}
        if branch_ids & set(nodes_by_id):
            return f"title open-to {parent.node_id}: node id crossed title branches"
        nodes_by_id[parent.node_id] = closed_by_id[parent.node_id]
        nodes_by_id.update({node.node_id: node for node in branch_nodes})
        for node_id in closed_ids:
            expanded.append(node_id)
            response_hashes.append((node_id, response_hash))
            if retained_path:
                response_paths.append((node_id, retained_path))
        if delay:
            await asyncio.sleep(delay)
    return ""


async def discover_live_inventory(
    *,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    retries: int = DEFAULT_RETRIES,
    request_delay_seconds: float = 0.05,
    timeout_ms: int = 60_000,
    require_enabled: bool = True,
    exhaustive: bool = False,
    evidence_dir: str | Path | None = None,
) -> ArkansasLexisInventory:
    """Traverse the official delegated TOC and return a fail-closed receipt.

    Bounded callers retain the historical lazy breadth-first traversal.
    ``exhaustive=True`` instead uses each title root's rendered deepest
    ``open-to`` level, yielding one complete source-native subtree response per
    title.  No document link, consent control, CAPTCHA, or sign-in control is
    opened.  Exact response bytes are retained when ``evidence_dir`` is set.
    """

    if require_enabled and not enabled():
        return _failed_inventory(
            "disabled", f"set {ENABLE_ENV}=1 to enable live inventory"
        )
    max_count = max(1, min(int(max_expansions), DEFAULT_MAX_EXPANSIONS))
    retry_count = max(1, min(int(retries), 5))
    delay = max(0.0, min(float(request_delay_seconds), 2.0))
    timeout = max(5_000, min(int(timeout_ms), 120_000))
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return _failed_inventory("unavailable", f"playwright unavailable: {exc}")

    observed_at = datetime.now(UTC).isoformat()
    diagnostics: list[str] = []
    nodes_by_id: dict[str, ArkansasLexisNode] = {}
    expanded: list[str] = []
    response_hashes: list[tuple[str, str]] = []
    final_url = ""
    root_hash = ""
    delegation_verified = False
    status = "unavailable"
    root_path = ""
    response_paths: list[tuple[str, str]] = []
    evidence_root = (
        Path(evidence_dir).expanduser().resolve()
        if evidence_dir is not None
        else None
    )
    if evidence_root is not None:
        evidence_root.mkdir(parents=True, exist_ok=True)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                )
                page = await context.new_page()
                await page.goto(
                    PUBLIC_CONTAINER_URL,
                    wait_until="domcontentloaded",
                    timeout=timeout,
                    referer=OFFICIAL_REFERRER,
                )
                await page.wait_for_selector("li.js-node", timeout=min(timeout, 30_000))
                final_url = str(page.url or "")
                body_text = str(await page.locator("body").inner_text() or "")
                html = str(await page.content() or "")
                root_bytes = html.encode("utf-8")
                root_hash = hashlib.sha256(root_bytes).hexdigest()
                root_path = _retain_live_evidence_path(
                    evidence_root,
                    relative=f"root-rendered-{root_hash}.html",
                    payload=root_bytes,
                )
                delegation_verified = bool(
                    container_url_matches(final_url)
                    and _DELEGATION_RE.search(body_text)
                    and not _BLOCKED_RE.search(body_text)
                )
                if not delegation_verified:
                    diagnostics.append(
                        "delegation banner or exact public container was not verified"
                    )
                    status = "invalid_source"
                else:
                    dom_rows = await page.evaluate(
                        """
                        () => Array.from(
                          document.querySelectorAll('li.js-node[data-level="1"]')
                        ).map(el => ({
                          nodeid: el.getAttribute('data-nodeid') || '',
                          nodepath: el.getAttribute('data-nodepath') || '',
                          level: el.getAttribute('data-level') || '',
                          title: el.getAttribute('data-title') || '',
                          canexpand: el.getAttribute('data-canexpand') || '',
                          canopen: el.getAttribute('data-canopen') || '',
                          haschildren: el.getAttribute('data-haschildren') || '',
                          targetlevels: Array.from(
                            el.querySelectorAll(
                              ':scope > .js-node-header [data-command="open-to"]'
                            )
                          ).map(item => item.getAttribute('data-targetlevel') || '')
                        }))
                        """
                    )
                    root_nodes = parse_root_dom_rows(
                        dom_rows
                        if isinstance(dom_rows, Sequence)
                        and not isinstance(dom_rows, (str, bytes, bytearray))
                        else ()
                    )
                    root_title_numbers = [node.title_number for node in root_nodes]
                    valid_root_inventory = bool(
                        isinstance(dom_rows, Sequence)
                        and not isinstance(dom_rows, (str, bytes, bytearray))
                        and len(dom_rows) == len(EXPECTED_TITLE_NUMBERS)
                        and len(root_nodes) == len(dom_rows)
                        and set(root_title_numbers) == set(EXPECTED_TITLE_NUMBERS)
                        and len(set(root_title_numbers)) == len(root_title_numbers)
                    )
                    bound_root_nodes = _bind_live_nodes(
                        root_nodes,
                        source_url=final_url,
                        observed_at=observed_at,
                        receipt_sha256=root_hash,
                    )
                    if not valid_root_inventory or len(bound_root_nodes) != len(
                        root_nodes
                    ):
                        diagnostics.append(
                            "expected one valid rendered root for each Arkansas title "
                            f"1-28; received {len(root_nodes)} valid roots"
                        )
                        status = "partial_toc"
                    else:
                        nodes_by_id.update(
                            {node.node_id: node for node in bound_root_nodes}
                        )
                        queue: deque[ArkansasLexisNode] = deque()
                        if exhaustive:
                            exhaustive_error = (
                                await _discover_exhaustive_title_subtrees(
                                    page=page,
                                    dom_rows=dom_rows,
                                    bound_root_nodes=bound_root_nodes,
                                    nodes_by_id=nodes_by_id,
                                    expanded=expanded,
                                    response_hashes=response_hashes,
                                    response_paths=response_paths,
                                    retry_count=retry_count,
                                    delay=delay,
                                    source_url=final_url,
                                    observed_at=observed_at,
                                    evidence_root=evidence_root,
                                )
                            )
                            if exhaustive_error:
                                diagnostics.append(exhaustive_error)
                                status = "partial_toc"
                            else:
                                status = "complete"
                        else:
                            queue.extend(
                                node
                                for node in bound_root_nodes
                                if node.can_expand or node.has_children
                            )
                        while queue and len(expanded) < max_count:
                            parent = queue.popleft()
                            endpoint, patch_body = toc_expand_request(parent.node_id)
                            result, last_error = await _live_toc_patch_with_retries(
                                page,
                                endpoint=endpoint,
                                patch_body=patch_body,
                                retry_count=retry_count,
                            )
                            if (
                                result is None
                                or int(result.get("status") or 0) != 200
                                or "json"
                                not in str(result.get("contentType") or "").lower()
                            ):
                                diagnostics.append(
                                    f"expansion {parent.node_id} failed after retries: {last_error}"
                                )
                                status = "partial_toc"
                                break
                            response_text = str(result.get("text") or "")
                            response_hash = hashlib.sha256(
                                response_text.encode("utf-8")
                            ).hexdigest()
                            try:
                                payload = json.loads(response_text)
                            except json.JSONDecodeError:
                                diagnostics.append(
                                    f"expansion {parent.node_id} returned invalid JSON"
                                )
                                status = "partial_toc"
                                break
                            children, error = parse_expansion_payload(
                                payload, parent=parent
                            )
                            if error:
                                diagnostics.append(
                                    f"expansion {parent.node_id}: {error}"
                                )
                                status = "partial_toc"
                                break
                            bound_children = _bind_live_nodes(
                                children,
                                source_url=final_url,
                                observed_at=observed_at,
                                receipt_sha256=response_hash,
                            )
                            closed_parent = dataclass_replace_closed(
                                parent,
                                evidence_sha256=response_hash,
                            )
                            if closed_parent is None or len(bound_children) != len(
                                children
                            ):
                                diagnostics.append(
                                    f"expansion {parent.node_id}: live evidence binding failed"
                                )
                                status = "partial_toc"
                                break
                            nodes_by_id[parent.node_id] = closed_parent
                            expanded.append(parent.node_id)
                            response_hashes.append((parent.node_id, response_hash))
                            for child in bound_children:
                                if child.node_id in nodes_by_id:
                                    diagnostics.append(
                                        f"duplicate node id crossed branches: {child.node_id}"
                                    )
                                    status = "partial_toc"
                                    queue.clear()
                                    break
                                nodes_by_id[child.node_id] = child
                                if child.can_expand or child.has_children:
                                    queue.append(child)
                            if delay:
                                await asyncio.sleep(delay)
                        if not exhaustive and queue and len(expanded) >= max_count:
                            diagnostics.append(
                                f"expansion limit {max_count} reached with {len(queue)} queued nodes"
                            )
                            status = "partial_toc"
                        elif not exhaustive and not diagnostics:
                            status = "complete"
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 - browser/network boundary is fail-closed
        diagnostics.append(f"live inventory failed: {type(exc).__name__}: {exc}")
        status = "unavailable"

    ordered = tuple(
        sorted(nodes_by_id.values(), key=lambda node: (node.level, node.node_path))
    )
    return ArkansasLexisInventory(
        status=status,
        final_url=final_url,
        observed_at=observed_at,
        delegation_verified=delegation_verified,
        nodes=ordered,
        expanded_node_ids=tuple(expanded),
        diagnostics=tuple(diagnostics),
        root_rendered_sha256=root_hash,
        expansion_response_sha256=tuple(response_hashes),
        root_rendered_path=root_path,
        expansion_response_paths=tuple(response_paths),
    )


def dataclass_replace_closed(
    node: ArkansasLexisNode,
    *,
    evidence_sha256: str,
    evidence_source_url: str | None = None,
    evidence_observed_at: str | None = None,
) -> ArkansasLexisNode | None:
    """Return an immutable node carrying its exact successful response hash."""

    if not (
        node.evidence_verified
        and (node.can_expand or node.has_children)
        and _SHA256_RE.fullmatch(evidence_sha256)
    ):
        return None
    closed = replace(
        node,
        expansion_closed=True,
        evidence_sha256=evidence_sha256,
        evidence_source_url=(
            evidence_source_url
            if evidence_source_url is not None
            else node.evidence_source_url
        ),
        evidence_observed_at=(
            evidence_observed_at
            if evidence_observed_at is not None
            else node.evidence_observed_at
        ),
    )
    object.__setattr__(closed, "_evidence_capability", _LIVE_EVIDENCE_CAPABILITY)
    return closed if closed.evidence_verified else None


__all__ = [
    "ACT283_BYTE_SIZE",
    "ACT283_CRC_NONOCCURRENCE_BYTE_SIZE",
    "ACT283_CRC_NONOCCURRENCE_SHA256",
    "ACT283_CRC_NONOCCURRENCE_URL",
    "ACT283_DWS_CURRENT_FORM_BYTE_SIZE",
    "ACT283_DWS_CURRENT_FORM_SHA256",
    "ACT283_DWS_CURRENT_FORM_URL",
    "ACT283_EXCLUSION_DISPOSITION",
    "ACT283_SHA256",
    "ACT283_URL",
    "ACT283_VARIANT_CONTRACT",
    "ACT1032_BYTE_SIZE",
    "ACT1032_SHA256",
    "ACT1032_URL",
    "ADVANCE_ORIGIN",
    "ARKANSAS_DELEGATED_INVENTORY_SHA256",
    "ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256",
    "ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT",
    "ARKANSAS_ENACTMENT_TOC_VARIANT_CONTRACT",
    "CURRENT_VARIANT_RESOLVER_PARSER_NAME",
    "ENABLE_ENV",
    "EXPECTED_TITLE_NUMBERS",
    "HR5330_BILLSTATUS_BYTE_SIZE",
    "HR5330_BILLSTATUS_SHA256",
    "HR5330_BILLSTATUS_URL",
    "HR5330_IF_LINK_HREF",
    "HR5330_IF_NODE_ID",
    "HR5330_UNTIL_LINK_HREF",
    "HR5330_UNTIL_NODE_ID",
    "HR5330_VARIANT_SECTION",
    "MAX_EXHAUSTIVE_TOC_LEVEL",
    "OFFICIAL_REFERRER",
    "PUBLIC_CONTAINER_URL",
    "PUBLIC_ENTRY_URL",
    "TOC_ENDPOINT_PATH",
    "TOC_POD_ID",
    "UNRESOLVED_VARIANT_DOCUMENT_CONTRACT",
    "UNRESOLVED_VARIANT_IDENTITY_DOCUMENT_CONTRACT",
    "ArkansasLexisAct283VariantResolution",
    "ArkansasLexisEnactmentTocVariantResolution",
    "ArkansasLexisInventory",
    "ArkansasLexisNode",
    "ArkansasLexisRetainedOfficialInputIdentity",
    "ArkansasLexisSourceBoundVariantResolution",
    "ArkansasLexisVariantDecision",
    "act283_selection_plan_sha256",
    "container_url_matches",
    "dataclass_replace_closed",
    "discover_live_inventory",
    "document_page_url",
    "enabled",
    "enactment_toc_selection_plan_sha256",
    "exact_unresolved_variant_document_nodes",
    "exact_unresolved_variant_identity_document_nodes",
    "is_document_path",
    "load_exact_retained_inventory",
    "node_from_mapping",
    "parse_expansion_payload",
    "parse_root_dom_rows",
    "parse_title_subtree_payload",
    "parse_toc_payload",
    "reconcile_current_statute_variants",
    "resolve_act283_source_bound_variants",
    "resolve_enactment_toc_source_bound_variants",
    "resolve_hr5330_source_bound_variant",
    "toc_expand_request",
    "toc_open_to_request",
    "validate_hr5330_billstatus_xml",
    "variant_decision_sha256",
]
