"""Official Louisiana legis.la.gov Law.aspx parser.

Adapted from Vaquill-AI/open-us-law ``la_bulk.parse`` (Apache-2.0).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

_WS = re.compile(r"[\s\xa0]+")
_LABEL_RE = re.compile(r"^(RS|CCRP|CCP|CHC|CE|CC)\s+(.+?)\s*$")
_HEADING_RE = re.compile(r"^(?:§|Art\.)\s*[0-9][0-9A-Za-z.\-]*\.?\s*(?P<title>.*)$")
_DOCID_RE = re.compile(r"Law\.aspx\?d=(\d+)")
_BARE_RS_TITLE_LABEL_RE = re.compile(r"^RS\s+(?P<title>\d+[A-Za-z]?)$")
_TITLE_HEADING_RE = re.compile(
    r"^TITLE\s+(?P<title>\d+[A-Za-z]?)\.?(?:\s+.+)?$",
    re.IGNORECASE,
)
_BLANK_HEADING_RE = re.compile(
    r"^(?:(?:§{1,2}\s*)?[0-9][0-9A-Za-z.\-]*"
    r"(?:\s+to\s+[0-9][0-9A-Za-z.\-]*)?\s+)?(?:\[Blank\]|Blank)\.?$",
    re.IGNORECASE,
)
_RESERVED_HEADING_RE = re.compile(r"^\[Reserved\.?\]\.?$", re.IGNORECASE)
_SEE_CROSS_REFERENCE_HEADING_RE = re.compile(
    r"^\[See R\.S\.\s+[0-9][0-9A-Za-z]*:[0-9][0-9A-Za-z.\-]*"
    r"(?:\s+and\s+[0-9][0-9A-Za-z.\-]*)*,\s+Acts\s+[0-9]{4},\s+"
    r"No\.\s+[0-9]+,\s+§[0-9]+\]\.?$",
    re.IGNORECASE,
)
_BLANK_CIVIL_CODE_CROSS_REFERENCE_HEADING_RE = re.compile(
    r"^\[Blank\s+-\s+See\s+C\.C\.\s+Art\.\s+"
    r"[0-9][0-9A-Za-z.\-]*(?:\([0-9A-Za-z]+\))*\]\.?$",
    re.IGNORECASE,
)
_TERMINATED_BY_ACT_HEADING_RE = re.compile(
    r"^Terminated\s+by\s+Acts\s+[0-9]{4},\s+"
    r"(?:[0-9]+\s*(?:st|nd|rd|th)\s+Ex\.\s+Sess\.,\s+)?"
    r"No\.\s+[0-9]+,\s+(?:§[0-9]+,\s+)?eff\.\s+"
    r"(?:Jan\.|Feb\.|Mar\.|Apr\.|May|June|July|Aug\.|Sept\.|Oct\.|Nov\.|Dec\.)"
    r"\s+[0-9]{1,2},\s+[0-9]{4}\.$",
    re.IGNORECASE,
)
_REDESIGNATED_BY_ACT_HEADING_RE = re.compile(
    r"^Redesignated\s+as\s+R\.S\.\s+"
    r"(?P<to_title>[0-9][0-9A-Za-z]*):"
    r"(?P<to_section>[0-9][0-9A-Za-z.\-]*)\s+"
    r"(?:pursuant\s+to\s+Acts\s+[0-9]{4},\s+No\.\s+[0-9]+"
    r"(?:,\s+§[0-9]+)?|"
    r"by\s+Acts\s+[0-9]{4},\s+No\.\s+[0-9]+,\s+§[0-9]+)\.$",
    re.IGNORECASE,
)
_BLANK_REDESIGNATED_HEADING_RE = re.compile(
    r"^\[Blank\]\s+Acts\s+[0-9]{4},\s+No\.\s+[0-9]+,\s+§[0-9]+,\s+"
    r"redesignated\s+R\.S\.\s+(?P<from_title>[0-9][0-9A-Za-z]*):"
    r"(?P<from_section>[0-9][0-9A-Za-z.\-]*)\s+as\s+R\.S\.\s+"
    r"(?P<to_title>[0-9][0-9A-Za-z]*):"
    r"(?P<to_section>[0-9][0-9A-Za-z.\-]*)\.$",
    re.IGNORECASE,
)

# The official page for R.S. 32:1270.41 publishes a period where every other
# Revised Statutes label uses the title/section colon: ``RS 32.1270.41``.  Its
# document heading, operative paragraph, history, neighboring-page controls,
# print link, and hidden document identity all establish that this is the
# operative R.S. 32:1270.41 page.  Correct only this exact retained response;
# a dotted label is not a generally admissible Revised Statutes label.
#
# * retained Law.aspx SHA-256:
#   6a214b4818727430a920f47092719819377e0d900a05968e1e6c4f285ea8228a
# * retained Law.aspx CID:
#   bafkreidkeffuqgdsoqyksihuocjhdgazg57a3eakawli4htmj4uf5kbcri
# * retained receipt SHA-256:
#   87c2d80e0bc44bb0b803729709cdc2ddf049f8fe42e845ee5d21321132605e3e
# * retained receipt CID:
#   bafkreiehylma4c6ejoylqa3ss4e43qw56be7r7sc5bc64xjbgiiteyc6hy
_EXACT_OPERATIVE_LABEL_CORRECTIONS = {
    "https://legis.la.gov/legis/Law.aspx?d=1238853": {
        "content_sha256": (
            "6a214b4818727430a920f47092719819377e0d900a05968e1e6c4f285ea8228a"
        ),
        "content_cid": (
            "bafkreidkeffuqgdsoqyksihuocjhdgazg57a3eakawli4htmj4uf5kbcri"
        ),
        "receipt_sha256": (
            "87c2d80e0bc44bb0b803729709cdc2ddf049f8fe42e845ee5d21321132605e3e"
        ),
        "receipt_cid": (
            "bafkreiehylma4c6ejoylqa3ss4e43qw56be7r7sc5bc64xjbgiiteyc6hy"
        ),
        "source_label": "RS 32.1270.41",
        "canonical_label": "RS 32:1270.41",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "1238853",
        "form_action": "./Law.aspx?d=1238853",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=1238853",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {"name": "div", "attributes": {"id": "WPMainDoc"}},
        "document_children": [
            {
                "name": "p",
                "attributes": {
                    "style": (
                        "text-align:left; text-indent: -0.5in; margin-left: 0.5in"
                    )
                },
                "text": "§1270.41. Exclusiveness",
            },
            {
                "name": "p",
                "attributes": {"style": "text-align:left"},
                "text": (
                    "This Part provides exclusive remedies, warranties, and "
                    "peremptive periods as between the manufacturer, dealer, and "
                    "consumer, relative to nonconformity defects as defined in "
                    "this Part, and no other provisions of law relative to "
                    "recreational vehicle warranties and redhibitory vices and "
                    "defects shall apply. Nothing herein shall be construed to "
                    "affect or limit any warranty of title."
                ),
            },
            {
                "name": "p",
                "attributes": {"style": "text-align:left"},
                "text": "Acts 2021, No. 220, §1.",
            },
        ],
        "document_blocks": [
            "§1270.41. Exclusiveness",
            (
                "This Part provides exclusive remedies, warranties, and "
                "peremptive periods as between the manufacturer, dealer, and "
                "consumer, relative to nonconformity defects as defined in "
                "this Part, and no other provisions of law relative to "
                "recreational vehicle warranties and redhibitory vices and "
                "defects shall apply. Nothing herein shall be construed to "
                "affect or limit any warranty of title."
            ),
            "Acts 2021, No. 220, §1.",
        ],
        "heading": "Exclusiveness",
    },
    # The official R.S. 40:1002 page uses the same erroneous title/section
    # period.  Unlike the clustered terminals below, its three exact document
    # blocks contain operative text and history, so retain it as a row after
    # correcting only this exact direct response.
    #
    # * retained Law.aspx SHA-256:
    #   0234c200da98088719529d540a191d5f941d08a1093bcf95fb4b119ad340c8fd
    # * retained Law.aspx CID:
    #   bafkreiacgtbabwuybcdrsuu5kqfbshk7sqoqriijhphzl62lcgnngqgi7u
    # * retained receipt SHA-256:
    #   9806163855e178e5db498aa5bc927f6f4cd6ee120ed87fe041e87ddda7b1e58a
    # * retained receipt CID:
    #   bafkreieyayldqvpbpds5wsmkuw6je73pjtlo4eqo3b76aqpipxo2pmpfri
    "https://legis.la.gov/legis/Law.aspx?d=409416": {
        "content_sha256": (
            "0234c200da98088719529d540a191d5f941d08a1093bcf95fb4b119ad340c8fd"
        ),
        "content_cid": (
            "bafkreiacgtbabwuybcdrsuu5kqfbshk7sqoqriijhphzl62lcgnngqgi7u"
        ),
        "receipt_sha256": (
            "9806163855e178e5db498aa5bc927f6f4cd6ee120ed87fe041e87ddda7b1e58a"
        ),
        "receipt_cid": (
            "bafkreieyayldqvpbpds5wsmkuw6je73pjtlo4eqo3b76aqpipxo2pmpfri"
        ),
        "source_label": "RS 40.1002",
        "canonical_label": "RS 40:1002",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "409416",
        "form_action": "./Law.aspx?d=409416",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=409416",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"class": ["A0001"], "align": "justify"},
                "text": "§1002. Purpose",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "justify"},
                "text": (
                    "The purpose of this Part is to authorize the development, "
                    "implementation, operation, and evaluation of an electronic "
                    "system for the monitoring of controlled substances and "
                    "other drugs of concern that are dispensed in the state or "
                    "dispensed to an address within the state. The goal of the "
                    "program is to improve the state's ability to identify and "
                    "inhibit the diversion of controlled substances and drugs "
                    "in an efficient and cost-effective manner and in a manner "
                    "that shall not impede the appropriate utilization of these "
                    "drugs for legitimate medical purposes."
                ),
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "justify"},
                "text": "Acts 2006, No. 676, §1, eff. July 1, 2006.",
            },
        ],
        "document_blocks": [
            "§1002. Purpose",
            (
                "The purpose of this Part is to authorize the development, "
                "implementation, operation, and evaluation of an electronic "
                "system for the monitoring of controlled substances and other "
                "drugs of concern that are dispensed in the state or dispensed "
                "to an address within the state. The goal of the program is to "
                "improve the state's ability to identify and inhibit the "
                "diversion of controlled substances and drugs in an efficient "
                "and cost-effective manner and in a manner that shall not "
                "impede the appropriate utilization of these drugs for "
                "legitimate medical purposes."
            ),
            "Acts 2006, No. 676, §1, eff. July 1, 2006.",
        ],
        "heading": "Purpose",
    },
}
# The official Title 13 TOC retains this locator between R.S. 13:2589 and
# 13:2590 with an empty caption.  Its direct Law.aspx response and independent
# LawPrint.aspx view both publish the exact label with an empty document:
#
# * retained TOC POST SHA-256:
#   1fa0a01b5178fcefe63c8e1c8306d043658ebeca4eed99d74c70b84b0a1b3743
# * retained/live Law.aspx SHA-256:
#   2e9db3dcbb9afe49bfa5679ea4355e4a2a68a4d82437068b25f0455651b0ca50
# * live LawPrint.aspx SHA-256:
#   3bf776be91381cc498ae2aeec3038196f8c24167e04663fc0f2533f3c6bd00b7
#
# Louisiana does not label the locator repealed or relocated, so preserve the
# narrower editorial disposition.  This evidence is deliberately byte- and
# source-bound; it must never become a generic empty-LabelDocument exemption.
_EXACT_EMPTY_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=763423": {
        "content_sha256": (
            "2e9db3dcbb9afe49bfa5679ea4355e4a2a68a4d82437068b25f0455651b0ca50"
        ),
        "label": "RS 13:2589.1",
        "document_id": "763423",
        "form_action": "./Law.aspx?d=763423",
        "print_href": "LawPrint.aspx?d=763423",
    }
}

# The official Title 13 TOC identifies R.S. 13:5556 as ``Blank`` while the
# linked Law.aspx and independent LawPrint.aspx views both publish the same
# malformed terminal marker, ``[Blank)]``.  The general classifier must remain
# strict, so bind this one upstream editorial typo to its exact official bytes
# and page identity instead of accepting mismatched brackets generically:
#
# * retained Title 13 TOC POST SHA-256:
#   1fa0a01b5178fcefe63c8e1c8306d043658ebeca4eed99d74c70b84b0a1b3743
# * retained/live Law.aspx SHA-256:
#   79f07b2ca2ad90affc7e75c7bd3fcf1d1398def1c4ee181861dc00761ec20b6b
# * live LawPrint.aspx SHA-256:
#   381be8fe69452bb3cbe5de412e010f22ccf7eff7fd72c409c8b2bfad7c25c995
_EXACT_MALFORMED_BLANK_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=781433": {
        "content_sha256": (
            "79f07b2ca2ad90affc7e75c7bd3fcf1d1398def1c4ee181861dc00761ec20b6b"
        ),
        "label": "RS 13:5556",
        "document_id": "781433",
        "form_action": "./Law.aspx?d=781433",
        "print_href": "LawPrint.aspx?d=781433",
        "document_text": "§5556. [Blank)]",
        "heading": "[Blank)]",
        "disposition": "blank_editorial_typo",
    }
}

# The official R.S. 33:130.431 page is an editorial range locator, not an
# operative section.  Its document says that R.S. 33:130.431 through
# 33:130.436 are blank and points to the controlling R.S. 33:9083 provision.
# The trailing cross-reference deliberately falls outside the generic
# ``Blank`` grammar.  Bind this disposition to the exact retained response,
# official page controls, and direct-child document structure:
#
# * retained Law.aspx SHA-256:
#   cc9e76f9cbe66aacbb702b7e5d6650bde9a83873efa6d692c34919396e680f87
# * retained Law.aspx CID:
#   bafkreigmtz3pts7gnkwlw4blpzowmuf55gudq47pu3ljfq2jde4w42apq4
# * retained receipt SHA-256:
#   2532482b3a53555115411151d20bc565800d0e3de1e356e480742c224ed85054
# * retained receipt CID:
#   bafkreibfgjecwostkvirkqirkhjaxrlfqagq4ppb4nlojadufqre5wcqkq
_EXACT_BLANK_RANGE_CROSS_REFERENCE_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=88919": {
        "content_sha256": (
            "cc9e76f9cbe66aacbb702b7e5d6650bde9a83873efa6d692c34919396e680f87"
        ),
        "label": "RS 33:130.431",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "88919",
        "form_action": "./Law.aspx?d=88919",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=88919",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"align": "center", "class": ["A0001"]},
                "text": "SUBPART B-19. FOURTEENTH AND SIXTEENTH WARDS",
            },
            {
                "name": "p",
                "attributes": {"align": "center", "class": ["A0001"]},
                "text": "NEIGHBORHOOD DEVELOPMENT DISTRICT",
            },
            {
                "name": "p",
                "attributes": {"align": "justify", "class": ["A0002"]},
                "text": "§130.431. §§130.431-130.436 Blank. See R.S. 33:9083.",
            },
        ],
        "document_blocks": [
            "SUBPART B-19. FOURTEENTH AND SIXTEENTH WARDS",
            "NEIGHBORHOOD DEVELOPMENT DISTRICT",
            "§130.431. §§130.431-130.436 Blank. See R.S. 33:9083.",
        ],
        "document_text": (
            "SUBPART B-19. FOURTEENTH AND SIXTEENTH WARDS "
            "NEIGHBORHOOD DEVELOPMENT DISTRICT "
            "§130.431. §§130.431-130.436 Blank. See R.S. 33:9083."
        ),
        "heading": "§§130.431-130.436 Blank. See R.S. 33:9083.",
        "disposition": "blank_range_cross_reference",
    },
    # The retained Title 33 page is likewise an editorial terminal: it marks
    # the entire former municipal-officers pension range blank and points to
    # the controlling Title 11 range.  Bind the bracketed/``See, now`` form to
    # its exact direct-200 bytes and ASP.NET DOM instead of widening the
    # generic blank grammar.
    #
    # * retained Law.aspx SHA-256:
    #   1a33bc4caa6fdc6b3ccd57696a5271e8a56715356c4f1ae782444022e9ae6008
    # * retained Law.aspx CID:
    #   bafkreia2go6ezktp3rvtztkxnfvfe4piuvtrknlmj4nopaseiarotltaba
    # * retained receipt SHA-256:
    #   74086f02fb85121ee6d243967822aae8cc42d911ccdc4ab8f4b3b4be38746648
    # * retained receipt CID:
    #   bafkreidubbxqf64fciponusdsz4cfkxizrbnseom3rflr5ftws7dq5dgja
    "https://legis.la.gov/legis/Law.aspx?d=89411": {
        "content_sha256": (
            "1a33bc4caa6fdc6b3ccd57696a5271e8a56715356c4f1ae782444022e9ae6008"
        ),
        "content_cid": (
            "bafkreia2go6ezktp3rvtztkxnfvfe4piuvtrknlmj4nopaseiarotltaba"
        ),
        "receipt_sha256": (
            "74086f02fb85121ee6d243967822aae8cc42d911ccdc4ab8f4b3b4be38746648"
        ),
        "receipt_cid": (
            "bafkreidubbxqf64fciponusdsz4cfkxizrbnseom3rflr5ftws7dq5dgja"
        ),
        "label": "RS 33:1761",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "89411",
        "form_action": "./Law.aspx?d=89411",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=89411",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"align": "center", "class": ["A0001"]},
                "text": "PART V. MUNICIPAL OFFICERS",
            },
            {
                "name": "p",
                "attributes": {"align": "center", "class": ["A0001"]},
                "text": "SUBPART A. PENSION SYSTEM",
            },
            {
                "name": "p",
                "attributes": {"align": "justify", "class": ["A0002"]},
                "text": (
                    "§1761. §§1761 to 1800 [Blank] See, now, R.S. "
                    "11:3841 to 3870."
                ),
            },
        ],
        "document_blocks": [
            "PART V. MUNICIPAL OFFICERS",
            "SUBPART A. PENSION SYSTEM",
            "§1761. §§1761 to 1800 [Blank] See, now, R.S. 11:3841 to 3870.",
        ],
        "document_text": (
            "PART V. MUNICIPAL OFFICERS SUBPART A. PENSION SYSTEM "
            "§1761. §§1761 to 1800 [Blank] See, now, R.S. 11:3841 to "
            "3870."
        ),
        "heading": (
            "§§1761 to 1800 [Blank] See, now, R.S. 11:3841 to 3870."
        ),
        "disposition": "blank_range_cross_reference",
    },
}

# The official Title 16 TOC labels R.S. 16:83 ``Omitted as obsolete``, and its
# linked Law.aspx page contains only that same editorial disposition.  Do not
# infer this terminal status for other prose; bind the observed form to its
# exact retained representation:
#
# * retained Title 16 TOC POST SHA-256:
#   a2b6d5576e289568bd9d7770a4adaed95e0895d46eaffb021d63c674dd1083de
# * retained Law.aspx SHA-256:
#   c19a918b4db58bcc026ffcd8faa949a6e635f7dc936cf39c388303be8089508a
_EXACT_OMITTED_AS_OBSOLETE_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=79701": {
        "content_sha256": (
            "c19a918b4db58bcc026ffcd8faa949a6e635f7dc936cf39c388303be8089508a"
        ),
        "label": "RS 16:83",
        "document_id": "79701",
        "form_action": "./Law.aspx?d=79701",
        "print_href": "LawPrint.aspx?d=79701",
        "document_text": "§83. Omitted as obsolete",
        "heading": "Omitted as obsolete",
        "disposition": "omitted_as_obsolete",
    }
}

# The official Title 17 TOC labels R.S. 17:85.9 and R.S. 17:85.10 with the
# dated terminations below, and each linked Law.aspx page contains only that
# same disposition.  The official Title 23 TOC likewise binds R.S. 23:1020
# to its dated termination between the operative R.S. 23:1019.6 and R.S.
# 23:1020.1 entries.  Its linked page retains the same terminal text after
# exact chapter, part, and subpart context headings.
# The generic termination grammar intentionally requires ``Terminated by
# Acts ...``; keep this different upstream form bound to its exact retained
# official representation instead of accepting arbitrary dated termination
# prose:
#
# * retained Title 17 TOC POST SHA-256:
#   72277777c9929a0e31083490a66f68170fa052e2c15b6afec2f6272baeb951bd
# * retained Law.aspx SHA-256:
#   5961a2aa689afe4f6528f7711a7628a1411b97b8c185fa93ccae63ed87017216
# * retained R.S. 17:85.10 Law.aspx SHA-256:
#   d468d444729607a8cae1f029d7e0258e86b06ff119b77f80dd20b46f5895a2b3
# * retained Title 23 TOC receipt SHA-256:
#   5c1177152ec8234c0af349906a1b45b64e574c5b0c4dee8cb697985cd921681a
# * retained Title 23 TOC POST SHA-256:
#   30830a33caccc8f4427909bae95c74f615832fc25f4ce40a4c8cca4b872ad6fd
# * retained R.S. 23:1020 Law.aspx SHA-256:
#   5556a54ffd05e1a7788b50de56e0d174472d9e47e81229937151bf4182a5ab76
_EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=285631": {
        "content_sha256": (
            "5961a2aa689afe4f6528f7711a7628a1411b97b8c185fa93ccae63ed87017216"
        ),
        "label": "RS 17:85.9",
        "document_id": "285631",
        "form_action": "./Law.aspx?d=285631",
        "print_href": "LawPrint.aspx?d=285631",
        "document_text": (
            "§85.9. Terminated on Dec. 31, 2004, by Acts 2004, No. 563, §3, "
            "eff. July 6, 2004."
        ),
        "heading": (
            "Terminated on Dec. 31, 2004, by Acts 2004, No. 563, §3, eff. "
            "July 6, 2004."
        ),
        "disposition": "terminated",
    },
    "https://legis.la.gov/legis/Law.aspx?d=285632": {
        "content_sha256": (
            "d468d444729607a8cae1f029d7e0258e86b06ff119b77f80dd20b46f5895a2b3"
        ),
        "label": "RS 17:85.10",
        "document_id": "285632",
        "form_action": "./Law.aspx?d=285632",
        "print_href": "LawPrint.aspx?d=285632",
        "document_text": (
            "§85.10. Terminated on Dec. 31, 2004, by Acts 2004, No. 718, §3, "
            "eff. July 6, 2004."
        ),
        "heading": (
            "Terminated on Dec. 31, 2004, by Acts 2004, No. 718, §3, eff. "
            "July 6, 2004."
        ),
        "disposition": "terminated",
    },
    "https://legis.la.gov/legis/Law.aspx?d=409787": {
        "content_sha256": (
            "5556a54ffd05e1a7788b50de56e0d174472d9e47e81229937151bf4182a5ab76"
        ),
        "label": "RS 23:1020",
        "document_id": "409787",
        "form_action": "./Law.aspx?d=409787",
        "print_href": "LawPrint.aspx?d=409787",
        "document_blocks": [
            "CHAPTER 10. WORKERS' COMPENSATION",
            "PART I. SCOPE AND OPERATION",
            "SUBPART A. DEFINITIONS",
            (
                "§1020. Terminated on June 30, 2006, by Acts 2006, No. 193, "
                "eff. June 2, 2006."
            ),
        ],
        "document_text": (
            "CHAPTER 10. WORKERS' COMPENSATION PART I. SCOPE AND OPERATION "
            "SUBPART A. DEFINITIONS §1020. Terminated on June 30, 2006, by "
            "Acts 2006, No. 193, eff. June 2, 2006."
        ),
        "heading": (
            "Terminated on June 30, 2006, by Acts 2006, No. 193, eff. June "
            "2, 2006."
        ),
        "toc_receipt_sha256": (
            "5c1177152ec8234c0af349906a1b45b64e574c5b0c4dee8cb697985cd921681a"
        ),
        "toc_content_sha256": (
            "30830a33caccc8f4427909bae95c74f615832fc25f4ce40a4c8cca4b872ad6fd"
        ),
        "toc_label": "RS 23:1020",
        "toc_caption": (
            "Terminated on June 30, 2006, by Acts 2006, No. 193, eff. June "
            "2, 2006."
        ),
        "toc_previous_label": "RS 23:1019.6",
        "toc_next_label": "RS 23:1020.1",
        "disposition": "terminated",
    },
}

# The official R.S. 30:2014.6 page contains no operative text: its single
# document paragraph says that the section became null and void on a stated
# date and cites the controlling act.  The generic terminal grammar does not
# accept ``Null and void`` prose.  Keep that grammar narrow and bind this
# exclusion to the complete retained direct-200 representation instead:
#
# * retained Law.aspx SHA-256:
#   e42ac1ab9383f8fd2dfb37a11cc3311b140141150bc1b834dcd30c9f9bbd6a9a
# * retained Law.aspx CID:
#   bafkreihefla2xe4d7d6s36zxueomgmi3cqaucfilyg4djxgtbspzxplkti
# * retained receipt SHA-256:
#   488e71d60ff3b3fd2d029dcfcc29091b6da5baf61f9c348afa911c417f1e5c56
# * retained receipt CID:
#   bafkreicirzy5md7twp6s2au5z7gcsci3nws3v5q7tq2iv6urdrax6hs4ky
_EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=410448": {
        "content_sha256": (
            "e42ac1ab9383f8fd2dfb37a11cc3311b140141150bc1b834dcd30c9f9bbd6a9a"
        ),
        "content_cid": (
            "bafkreihefla2xe4d7d6s36zxueomgmi3cqaucfilyg4djxgtbspzxplkti"
        ),
        "receipt_sha256": (
            "488e71d60ff3b3fd2d029dcfcc29091b6da5baf61f9c348afa911c417f1e5c56"
        ),
        "receipt_cid": (
            "bafkreicirzy5md7twp6s2au5z7gcsci3nws3v5q7tq2iv6urdrax6hs4ky"
        ),
        "label": "RS 30:2014.6",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "410448",
        "form_action": "./Law.aspx?d=410448",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=410448",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"class": ["A0001"], "align": "justify"},
                "text": (
                    "§2014.6. Null and void as of Jan. 1, 2009. See Acts "
                    "2006, No. 779, §3."
                ),
            }
        ],
        "document_blocks": [
            (
                "§2014.6. Null and void as of Jan. 1, 2009. See Acts 2006, "
                "No. 779, §3."
            )
        ],
        "document_text": (
            "§2014.6. Null and void as of Jan. 1, 2009. See Acts 2006, "
            "No. 779, §3."
        ),
        "heading": (
            "Null and void as of Jan. 1, 2009. See Acts 2006, No. 779, §3."
        ),
        "disposition": "null_and_void_dated",
    }
}

# The official Title 25 TOC begins with the bare R.S. 25 title locator and
# immediately follows it with R.S. 25:1.  The linked Law.aspx page contains
# only the title caption, but the upstream publisher wrapped that caption
# across two paragraph blocks.  The generic title-heading classifier
# deliberately requires one block, so preserve that grammar and bind this
# upstream layout exception to its exact retained page and independent TOC
# evidence instead:
#
# * retained Title 25 TOC receipt SHA-256:
#   964f63dac305e0fb868880ba9cb1791149f573846bd85c7d1788ee138dbf7d8f
# * retained Title 25 TOC POST SHA-256:
#   264af0292aafd5b33728c898fa3ee872c7ad72e84248cf5c57d9636ebbcfc288
# * retained R.S. 25 Law.aspx SHA-256:
#   33768bbfd907447e73e035138ac74e3953ebaaa8c8b46e79b6348fb649c902f0
_EXACT_WRAPPED_TITLE_HEADING_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=84265": {
        "content_sha256": (
            "33768bbfd907447e73e035138ac74e3953ebaaa8c8b46e79b6348fb649c902f0"
        ),
        "receipt_sha256": (
            "136f2a5270dfd83649b84d1afd790c7a1f6b09542d1d1f522b23e8d4d41f0daf"
        ),
        "receipt_cid": (
            "bafkreiatn4vfe4g73a3etocndl6xsdd2d5vqsvbndupvekzd5dknihynv4"
        ),
        "content_cid": (
            "bafkreibto2f37wihir7hhybvcofmotrzkpv2vkgiwrxhtnrur63etsic6a"
        ),
        "label": "RS 25",
        "document_id": "84265",
        "form_action": "./Law.aspx?d=84265",
        "form_method": "post",
        "print_href": "LawPrint.aspx?d=84265",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_blocks": [
            "TITLE 25. LIBRARIES, MUSEUMS, AND OTHER SCIENTIFIC",
            "AND CULTURAL FACILITIES",
        ],
        "document_text": (
            "TITLE 25. LIBRARIES, MUSEUMS, AND OTHER SCIENTIFIC AND CULTURAL "
            "FACILITIES"
        ),
        "toc_receipt_sha256": (
            "964f63dac305e0fb868880ba9cb1791149f573846bd85c7d1788ee138dbf7d8f"
        ),
        "toc_content_sha256": (
            "264af0292aafd5b33728c898fa3ee872c7ad72e84248cf5c57d9636ebbcfc288"
        ),
        "toc_receipt_cid": (
            "bafkreiewj5r5vqyf4d5ynceaxkolc6irjh2xhbdl3boh2f4i5yjy3p35r4"
        ),
        "toc_content_cid": (
            "bafkreibgjlycskvp2wztokgitd5d52dsy6wxf2ccjdhvyv6zmnxlxt6cra"
        ),
        "toc_endpoint": (
            "https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent"
        ),
        "toc_request_method": "POST",
        "toc_request_body_sha256": (
            "1e1ea381f2592fa6853ded3ef707d0fce749cd16a83b1cb69e7915fe404956c3"
        ),
        "toc_page_index": 23,
        "toc_page_count": 54,
        "toc_label": "RS 25",
        "toc_caption": "TITLE 25.LIBRARIES, MUSEUMS, AND OTHER SCIENTIFIC",
        "toc_next_label": "RS 25:1",
        "toc_next_caption": "TITLE 25LIBRARIES, MUSEUMS, AND OTHER SCIENTIFIC",
        "disposition": "title_heading",
    }
}

# The official Title 17 TOC labels R.S. 17:771 ``To 781 redesignated as R.S.
# 11:921 to 931 by Acts 1991, No. 74, 3.`` and R.S. 17:881 ``To 994
# redesignated as R.S. 11:1001 to 1204 by Acts 1991, No. 74, 3.``  The same
# TOC identifies R.S. 17:1011 as redesignated to R.S. 11:951.1-951.88.  The
# official Title 18 TOC binds R.S. 18:1651 to its ``REGISTRARS OF VOTERS``
# entry, whose linked Law.aspx page says that R.S. 18:1651 through 1844 were
# redesignated and directs readers to Title 11.  Each page publishes only its
# corresponding terminal range notice after its exact source headings.  The
# generic redesignation grammar deliberately recognizes only a single source
# and target section, so bind these range forms to their exact retained
# official representations instead of accepting ranges generically:
#
# * retained Title 17 TOC POST SHA-256:
#   72277777c9929a0e31083490a66f68170fa052e2c15b6afec2f6272baeb951bd
# * retained Law.aspx SHA-256:
#   b705d5f62053f2de2bb387d632f7650201b6c85de25a6581db3e9242be9b475d
# * retained R.S. 17:881 Law.aspx SHA-256:
#   be51153efa5fa22b2ceba9b2ff453882dc4834135c298c0b33c22c1201be9ca5
# * retained R.S. 17:1011 Law.aspx SHA-256:
#   fcfb2096a78b6741236e605d92552f05a461825648dee74063cb3fd05df5fb8f
# * retained Title 18 TOC POST SHA-256:
#   b0272cf90cc2eef7c6574149d07aa89aeb058aa53ed7cba0ffec957640a6606e
# * retained R.S. 18:1651 Law.aspx SHA-256:
#   6a6bb2355b6d6ebc868bc6bf48ecd36413dc30d35bcd64123f10fea5fab77d7a
_EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=81194": {
        "content_sha256": (
            "b705d5f62053f2de2bb387d632f7650201b6c85de25a6581db3e9242be9b475d"
        ),
        "label": "RS 17:771",
        "document_id": "81194",
        "form_action": "./Law.aspx?d=81194",
        "print_href": "LawPrint.aspx?d=81194",
        "document_blocks": [
            "PART VII. OPTIONAL RETIREMENT PLAN FOR ACADEMIC",
            "AND ADMINISTRATIVE EMPLOYEES OF PUBLIC",
            "INSTITUTIONS OF HIGHER EDUCATION",
            (
                "§771. §§771 to 781 redesignated as R.S. 11:921 to 931 by "
                "Acts 1991, No. 74, §3."
            ),
        ],
        "heading": (
            "§§771 to 781 redesignated as R.S. 11:921 to 931 by Acts 1991, "
            "No. 74, §3."
        ),
        "disposition": "redesignated_range",
    },
    "https://legis.la.gov/legis/Law.aspx?d=81224": {
        "content_sha256": (
            "be51153efa5fa22b2ceba9b2ff453882dc4834135c298c0b33c22c1201be9ca5"
        ),
        "label": "RS 17:881",
        "document_id": "81224",
        "form_action": "./Law.aspx?d=81224",
        "print_href": "LawPrint.aspx?d=81224",
        "document_blocks": [
            "PART VIII. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM",
            (
                "§881. §§881 to 994 redesignated as R.S. 11:1001 to 1204 by "
                "Acts 1991, No. 74, §3."
            ),
        ],
        "heading": (
            "§§881 to 994 redesignated as R.S. 11:1001 to 1204 by Acts 1991, "
            "No. 74, §3."
        ),
        "disposition": "redesignated_range",
    },
    "https://legis.la.gov/legis/Law.aspx?d=79745": {
        "content_sha256": (
            "fcfb2096a78b6741236e605d92552f05a461825648dee74063cb3fd05df5fb8f"
        ),
        "label": "RS 17:1011",
        "document_id": "79745",
        "form_action": "./Law.aspx?d=79745",
        "print_href": "LawPrint.aspx?d=79745",
        "document_blocks": [
            "PART IX. ORLEANS PARISH SCHOOL EMPLOYEES",
            "RETIREMENT SYSTEM",
            "SUBPART A. GENERAL PROVISIONS",
            (
                "§1011-1128. Redesignated as R.S. 11:951.1-951.88 pursuant to "
                "R.S. 24:253."
            ),
        ],
        "heading": (
            "Redesignated as R.S. 11:951.1-951.88 pursuant to R.S. 24:253."
        ),
        "disposition": "redesignated_range",
    },
    "https://legis.la.gov/legis/Law.aspx?d=81494": {
        "content_sha256": (
            "6a6bb2355b6d6ebc868bc6bf48ecd36413dc30d35bcd64123f10fea5fab77d7a"
        ),
        "label": "RS 18:1651",
        "document_id": "81494",
        "form_action": "./Law.aspx?d=81494",
        "print_href": "LawPrint.aspx?d=81494",
        "document_blocks": [
            "CHAPTER 12. REGISTRARS OF VOTERS",
            "EMPLOYEES' RETIREMENT SYSTEM",
            (
                "§1651. §§1651 to 1844 redesignated by Acts 1991, No. 74, §3. "
                "See, now, Title 11."
            ),
        ],
        "heading": (
            "§§1651 to 1844 redesignated by Acts 1991, No. 74, §3. See, now, "
            "Title 11."
        ),
        "disposition": "redesignated_range",
    },
    # The retained Title 29 page publishes a range relocation rather than an
    # operative section.  Keep this exception bound to its exact direct-200
    # bytes and DOM: the generic redesignation grammar intentionally does not
    # accept range prose.
    "https://legis.la.gov/legis/Law.aspx?d=85614": {
        "content_sha256": (
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1"
        ),
        "content_cid": (
            "bafkreics2dsigq6e2rlwvnuaaiduchq2dt2bfefixok3jkbdazfehfbf4e"
        ),
        "receipt_sha256": (
            "6d82fd87b998ffc29fe9a2657013c502b7315ba3d3d1120a566e90d147ce2fe1"
        ),
        "receipt_cid": (
            "bafkreidnql6ypomy77bj72ncmvybhricw4yvxi6t2ejauvtosdiuptrp4e"
        ),
        "label": "RS 29:461",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "85614",
        "form_action": "./Law.aspx?d=85614",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=85614",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"class": ["A0001"], "align": "center"},
                "text": "PART II. PENSIONS",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "justify"},
                "text": (
                    "§461. §§461 to 468 Redesignated as R.S. 11:1391 to "
                    "1397 by Acts 1991, No. 74, §1."
                ),
            },
        ],
        "document_blocks": [
            "PART II. PENSIONS",
            (
                "§461. §§461 to 468 Redesignated as R.S. 11:1391 to "
                "1397 by Acts 1991, No. 74, §1."
            ),
        ],
        "document_text": (
            "PART II. PENSIONS §461. §§461 to 468 Redesignated as R.S. "
            "11:1391 to 1397 by Acts 1991, No. 74, §1."
        ),
        "heading": (
            "§§461 to 468 Redesignated as R.S. 11:1391 to 1397 by Acts "
            "1991, No. 74, §1."
        ),
        "disposition": "redesignated_range",
    },
    # The retained Title 30 page is likewise an exact range relocation, not
    # operative section text.  Preserve the upstream spacing in ``1150 .96``
    # and bind the exclusion to the direct-200 bytes, acquisition receipt,
    # and complete two-element document shape observed at this locator.
    "https://legis.la.gov/legis/Law.aspx?d=86914": {
        "content_sha256": (
            "f25964dc56625041c3aafa183795913e7ae0b44ed02df33265b31101ec36b962"
        ),
        "content_cid": (
            "bafkreihslfsnyvtckba4hkx2da3zlej6plqlitwqfxztezntcea6ynvzmi"
        ),
        "receipt_sha256": (
            "0e3d3c53bd753fe34f824de56b649ef01d472077d7c137bdc7c46abf2af9606f"
        ),
        "receipt_cid": (
            "bafkreiaohu6fhplvh7ru7asn4vvwjhxqdvdsa56xye333r6enk7sv6lan4"
        ),
        "label": "RS 30:1051",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "86914",
        "form_action": "./Law.aspx?d=86914",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=86914",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"class": ["A0001"], "align": "center"},
                "text": "CHAPTER 11. ENVIRONMENTAL QUALITY",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "justify"},
                "text": (
                    "§1051. §§1051 to 1150 .96 redesignated as Subtitle II "
                    "of Title 30 (R.S. 30:2001 to 2396)"
                ),
            },
        ],
        "document_blocks": [
            "CHAPTER 11. ENVIRONMENTAL QUALITY",
            (
                "§1051. §§1051 to 1150 .96 redesignated as Subtitle II of "
                "Title 30 (R.S. 30:2001 to 2396)"
            ),
        ],
        "document_text": (
            "CHAPTER 11. ENVIRONMENTAL QUALITY §1051. §§1051 to 1150 .96 "
            "redesignated as Subtitle II of Title 30 (R.S. 30:2001 to 2396)"
        ),
        "heading": (
            "§§1051 to 1150 .96 redesignated as Subtitle II of Title 30 "
            "(R.S. 30:2001 to 2396)"
        ),
        "disposition": "redesignated_range",
    },
}

# The official R.S. 33:1421 page contains no operative section text.  It
# publishes a chapter-level relocation notice followed by the exact section
# relocation to R.S. 13:5521.  ``heading_and_body`` correctly reduces the
# final paragraph to a heading-only redesignation.  The generic grammar now
# recognizes this exact ``pursuant to Acts ..., No. ..., §...`` family only
# when the target identity differs and no operative body exists.  Retain this
# additional source-bound contract for the first chapter wrapper so its direct
# bytes, receipt, navigation controls, and complete DOM identity remain
# independently auditable.
#
# * retained Law.aspx SHA-256:
#   a3111e4353d160641af9c069e62b5cf996cddc0927055532625526439be7b9cf
# * retained Law.aspx CID:
#   bafkreifdcepegu6rmbsbv6oanhtcwxhzs3g5ycjhavkteysvezbzxz5zz4
# * retained receipt SHA-256:
#   3d71b45d7d2050be870c390da7bf3fa7e6dac025738c7b2a7f8d44dd255dfe55
# * retained receipt CID:
#   bafkreib5og2f27jakc7iodbzbwt36p5h43nmajltrr5su74nitoskxp6ku
_EXACT_CHAPTER_WRAPPED_REDESIGNATION_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=89224": {
        "content_sha256": (
            "a3111e4353d160641af9c069e62b5cf996cddc0927055532625526439be7b9cf"
        ),
        "content_cid": (
            "bafkreifdcepegu6rmbsbv6oanhtcwxhzs3g5ycjhavkteysvezbzxz5zz4"
        ),
        "receipt_sha256": (
            "3d71b45d7d2050be870c390da7bf3fa7e6dac025738c7b2a7f8d44dd255dfe55"
        ),
        "receipt_cid": (
            "bafkreib5og2f27jakc7iodbzbwt36p5h43nmajltrr5su74nitoskxp6ku"
        ),
        "label": "RS 33:1421",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "89224",
        "form_action": "./Law.aspx?d=89224",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=89224",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": "p",
                "attributes": {"class": ["A0001"]},
                "text": "",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0001"]},
                "text": "",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "center"},
                "text": "CHAPTER 3. PUBLIC OFFICERS",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "center"},
                "text": "(REDESIGNATED AS CHAPTER 35 OF TITLE 13)",
            },
            {
                "name": "p",
                "attributes": {"class": ["A0002"], "align": "justify"},
                "text": (
                    "§1421. Redesignated as R.S. 13:5521 pursuant to Acts "
                    "2011, No. 248, §3."
                ),
            },
        ],
        "document_blocks": [
            "CHAPTER 3. PUBLIC OFFICERS",
            "(REDESIGNATED AS CHAPTER 35 OF TITLE 13)",
            (
                "§1421. Redesignated as R.S. 13:5521 pursuant to Acts 2011, "
                "No. 248, §3."
            ),
        ],
        "document_text": (
            "CHAPTER 3. PUBLIC OFFICERS (REDESIGNATED AS CHAPTER 35 OF "
            "TITLE 13) §1421. Redesignated as R.S. 13:5521 pursuant to Acts "
            "2011, No. 248, §3."
        ),
        "heading": (
            "Redesignated as R.S. 13:5521 pursuant to Acts 2011, No. 248, §3."
        ),
        "disposition": "redesignated_chapter_wrapper",
    }
}

# The official Title 18 TOC labels R.S. 18:221 ``Redesignated to R.S. 18:66
# by Acts 2017, No. 176, §6, eff. June 14, 2017.``, and the linked Law.aspx
# page contains only that same disposition.  The generic redesignation grammar
# deliberately recognizes the established ``Redesignated as`` forms, not this
# different upstream wording, so bind it to the exact retained official page:
#
# * retained Title 18 TOC POST SHA-256:
#   b0272cf90cc2eef7c6574149d07aa89aeb058aa53ed7cba0ffec957640a6606e
# * retained Law.aspx SHA-256:
#   2d1ce863e326ba4fc80fc9157e3bc4b954c7c86b302f80cf10c44ed24c715ce4
_EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=81535": {
        "content_sha256": (
            "2d1ce863e326ba4fc80fc9157e3bc4b954c7c86b302f80cf10c44ed24c715ce4"
        ),
        "label": "RS 18:221",
        "document_id": "81535",
        "form_action": "./Law.aspx?d=81535",
        "print_href": "LawPrint.aspx?d=81535",
        "document_text": (
            "§221. Redesignated to R.S. 18:66 by Acts 2017, No. 176, §6, "
            "eff. June 14, 2017."
        ),
        "heading": (
            "Redesignated to R.S. 18:66 by Acts 2017, No. 176, §6, eff. "
            "June 14, 2017."
        ),
        "disposition": "redesignated_to",
    }
}

# The official Title 30 frontier retains the former environmental-
# education sections below as a contiguous redesignation-only family.  Each
# exact page points to its new Title 17 section and contains no operative body.
# Most retained responses wrap the disposition in ``div#WPMainDoc``; the
# remaining pages use the official indented ``p`` representation.  Bind each
# exact body and DOM representation instead of widening the generic grammar.
_EXACT_TITLE_30_TO_REDESIGNATION_RECORDS = (
    (
        "87487",
        "2501",
        "200",
        "e8d9708713db792297a2a6709c839e9c7da41cd264e30ab392f7d6d8a0915916",
        "bafkreihi3fyioe63perjpivgocoihhu4pwsbzute4mflhexx23mkbekzcy",
        "e76aa08a479de8a19ff8babf7d24862c42657bb8577435444347b07783b2e774",
        "bafkreihhnkqiur455cqz76f2x56sjbrmijsxxocxoq2uiq2hwb3yhmxhoq",
        "div",
    ),
    (
        "87488",
        "2502",
        "201",
        "12259bc5ec97f11654626ad71668da24cca26a54c5fc7153398411eca6d0646b",
        "bafkreiasewn4l3ex6elfiytk24lgrwrezsrguvgf7ryvgomechwknudenm",
        "7ffd5a156060fd5642eeb27b4de21bd83004941b73795298577f3585f1825038",
        "bafkreid77vnbkyda7vlef3vspng6eg6ygacjig3tpfjjqv37gwc7dasqha",
        "div",
    ),
    (
        "87489",
        "2503",
        "202",
        "f5ec65b7fc7f753f22db6df25062c0bd614fb704904c74e605bb9c57d3e3528e",
        "bafkreihv5rs3p7d7ou7sfw3n6jigfqf5mfh3obeqjr2ombn3trl5hy2sry",
        "bf9312c4fe2d7ca386ddae1a8c9c33699f4268a9f6b3411d3159ea801c965df0",
        "bafkreif7smjmj7rnpsrynxnodkgjym3jt5bgrkpwwnar2mkz5kabzfs56a",
        "div",
    ),
    (
        "87490",
        "2504",
        "203",
        "f64423862364c0725f8075a2b8c86f82f749e1013db6474f891b9289b6d25d53",
        "bafkreihwiqrymi3eybzf7advuk4mq34c65e6caj5wzdu7ci3ske3nus5km",
        "f33047b49cfc05e063a3175a4355150f7e390234b98c3149b6b8ae68acf91cc1",
        "bafkreihtgbd3jhh4axqghiyxljbvkfippy4qenfzrqyutnvyvzukz6i4ye",
        "p",
    ),
    (
        "87491",
        "2505",
        "204",
        "c7ecc36c849ec523c9bea439358e92d76e67960beaec528025d11dfe329f6820",
        "bafkreigh5tbwzbe6yur4tpvehe2y5ewxnztzmc7k5rjiajordx7dfh3iea",
        "6ba5e1ef8a6e4ad3346d7a67bcd1efd92130ad1773385cf16e4d3237aa9eddc3",
        "bafkreidluxq67ctojljti3l2m66nd36zeeyk2f3thbopc3sngi32vhw5ym",
        "p",
    ),
    (
        "87492",
        "2506",
        "205",
        "daac579f083be4c00792a07de5cbb4b48a1f2ea17389be434d9d447dc528dadd",
        "bafkreig2vrlz6cb34taapevapxs4xnfurips5iltrg7egtm5ir64kkg23u",
        "a3b3fda1ad38a36490ea3775755f12df5537058b69320641cf15e0ad8b6dd456",
        "bafkreifdwp62dljyunsjb2rxov2v6ew7ku3qlc3jgidedtyv4cwyw3ouky",
        "div",
    ),
    (
        "87493",
        "2507",
        "206",
        "dfdfae987b274a938ded7e14b06891b295da6a51e03e54260631c5fea29d40d0",
        "bafkreig736xjq6zhjkjy33l6csygrenssxnguupahzkcmbrryx7kfhka2a",
        "724f80828604646cc3f109ed98bb2efb8d8e999a004151b59c1fbb79e0f2f42e",
        "bafkreidsj6aifbqemrwmh4ij5wmlwlx3rwhjtgqaifi3lha7xn46b4xufy",
        "p",
    ),
    (
        "87494",
        "2508",
        "207",
        "5e7b7dcb978e83c5069800b0a67884c11078d22d510f7ea7feb740780c3dc2d6",
        "bafkreic6pn64xf4oqpcqngaawcthrbgbcb4nelkrb57kp7vxib4aypoc2y",
        "7743930066d6391eac4353339f79987e8eaf1509908c6c0b15abcb40a00e024c",
        "bafkreidxiojqazwwhepkyq2tgopxtgd6r2xrkcmqrrwawfnlznakadqcjq",
        "p",
    ),
    (
        "87495",
        "2509",
        "208",
        "a4b84e2d1d0a4ca425e6aa2b9d0a3c717d6fedb78c725a274257309d4ab69991",
        "bafkreifexbhc2hikjssclzvkfooqupdrpvx63n4mojncoqsxgcouvnuzse",
        "7861432e25afce167077f7e245ea917ca1bf4fd0065750508bd6604168b1bc35",
        "bafkreidymfbs4jnpzylha57x4jc6vel4ug7u7uagk5ifbc6wmbawrmn4gu",
        "div",
    ),
    (
        "87497",
        "2510",
        "209",
        "e671e26f0340fff3e25c202cce20e3cc6c2f000fb4062f41fca33c2c872b7917",
        "bafkreihgohrg6a2a77z6exbafthcby6mnqxqad5uayxud7fdhqwiok3zc4",
        "1dc78d2be62b45f692de183c25900e82836177edfcb429c3a57168650ba15929",
        "bafkreia5y6gsxzrlix3jfxqyhqszaducqnqxp3p4wqu4hjlrnbsqxikzfe",
        "div",
    ),
    (
        "87498",
        "2511",
        "210",
        "176dc45c581554c26dc818d5d64615467fef34584a5034014c57aa3d9f376940",
        "bafkreiaxnxcfywavktbg3say2xlemfkgp7xtiwckka2actcxvi6z6n3jia",
        "bc8321dfc2dced747ba9a8c6831bd5d5e8a4f02f1e35c3e1cac1804281ab1259",
        "bafkreif4qmq57qw45v2hxkniy2brxvov5cspaly6gxb6dswbqbbidkysle",
        "p",
    ),
    (
        "1108213",
        "2512",
        "211",
        "30f3d685561646ee4a1370302cb54979ab7fac9eacba40d33ed5f8900d3b9f72",
        "bafkreibq6plikvqwi3xeue3qgawlkslzvn72zhvmxjangpwv7cia2o47oi",
        "4b13db6d4b8b0eba3b4f665f5e4f4b5c0f626dac7e937d50fb7904c728c6b44e",
        "bafkreiclcpnw2s4lb25dwt3gl5pe6s24b5rg3ld6sn6vb63zatdsrrvujy",
        "div",
    ),
    (
        "1108214",
        "2513",
        "212",
        "d969e194341f2ac4528fd7f8d13346584893968cd7bae6f788112bda71c3e86b",
        "bafkreigznhqzina7flcffd6x7ditgrsyjcjzndgxxltppcarfpnhdq7inm",
        "e6baa2ad229926189ec4376619076fcf941fd712ca563540fd2c973d61a8918f",
        "bafkreihgxkrk2iuzeymj5rbxmymqo36psqp5oewkky2ub7jms46wdkerr4",
        "div",
    ),
    (
        "1108215",
        "2514",
        "213",
        "71160af92823d46c267b8dbf2d332d9bd02a73dab04ca65d050a0dd0e5183dbd",
        "bafkreidrcyfpskbd2rwcm64nx4wtglm32avhhwvqjstf2bikbxiokgb5xu",
        "9fff175a927f760e0c94392d61b7f48ca6e775c79ee91694672000162b474de1",
        "bafkreie774lvvet7oyhazfbzfvq3p5emu3txlr465eljizzaaalcwr2n4e",
        "div",
    ),
    (
        "1108217",
        "2515",
        "214",
        "13e7a83e7a698566d31c9d670e0c1d3bf72fc722cd4a26779ac2f954676e0db2",
        "bafkreiat46ud46tjqvtnghe5m4hayhj364x4oiwnjithpgwc7fkgo3qnwi",
        "4e517c29cc092277b4014ca0e587a1b159ed467d911c87b4261ef436287e6321",
        "bafkreicokf6cttajej33iakmudsypinrlhwum7mrdsd3ijq66q3cq7tdee",
        "div",
    ),
    (
        "1108218",
        "2516",
        "215",
        "509ea411c7650d5eb2499abaaa46fe2f461b69e26807d0d276fb4b46f98bdfdf",
        "bafkreicqt2sbdr3fbvplesm2xkven7rpiynwtytia7ine5x3jndptc6734",
        "ad39fd633229cf5beeec7554c54a05a4cf18e0ca88bb39988f2f485395fb0210",
        "bafkreifnhh6wgmrjz5n653dvktcuubnez4mobsuixm4zrdzpjbjzl6ycca",
        "div",
    ),
    (
        "1108221",
        "2517",
        "216",
        "fc52f11ef6f3a3836f6b5843bf8b5002f1476bdd93bdc54ddb833ef15ef019b9",
        "bafkreih4klyr55xtuobw622yio7ywuac6fdwxxmtxxcu3w4dh3yv54azxe",
        "96cb5f50b970f417b67d8c43ac24db1caf4aaf5815af50048b77570d6fb73e33",
        "bafkreiewznpvbolq6ql3m7mmiowcjwy4v5fk6wavv5iajc3xk4gw7nz6gm",
        "div",
    ),
    (
        "1108222",
        "2518",
        "217",
        "dabca0faa42ecf21d86ec9f2060d89f708664244679f61f676413ff743b088d2",
        "bafkreig2xsqpvjboz4q5q3wj6ida3cpxbbteerdht5q7m5sbh73uhmei2i",
        "a51681c6ecb610785fe30d3efcbf65603719404349261d05563bdee03da44835",
        "bafkreiffc2a4n3fwcb4f7yynh36l6zlag4muaq2jeyoqkvr333qd3jcigu",
        "div",
    ),
    (
        "1108223",
        "2519",
        "218",
        "a13ed2b809fc54aab78ebd9230f373c92d99897e7507656006bd633477c70c09",
        "bafkreifbh3jlqcp4ksvlpdv5siypg46jfwmys7tva5swabv5mm2hprymbe",
        "42acf91b02434491d0c41017934dbf66cd6de5e041f655ce9cd4efea6b033f8d",
        "bafkreiccvt4rwasdisi5braqc6ju3p3gzvw6lycb6zk45hgu57vgwaz7ru",
        "div",
    ),
    (
        "1108226",
        "2520",
        "219",
        "fa172d644386c0b0b0d863ec339c2c3d1a56a63727641f33068dfdc1d7abefec",
        "bafkreih2c4wwiq4gycylbwdd5qzzylb5djlkmnzhmqptgbun7xa5pk7p5q",
        "40a9bbc2fbbff93a4a87b28e9c0f2e1e822c6079ac4dc46b6c30210a80ae5ef4",
        "bafkreicavg54f6577e5evb5sr2oa6lq6qiwga6nmjxcgw3bqeefibls66q",
        "div",
    ),
    (
        "87500",
        "2521",
        "220",
        "18be4cc59495500eb715d59fa0f035f3da803a6c0532d6dcfb19570b9a157dd0",
        "bafkreiayxzgmlfevkahlofovt6qpanpt3kadu3afgllnz6yzk4fzufl52a",
        "06a9403af3e8f448831ab280a92e209a5299e57375fc087a9b911806ba6a2e2a",
        "bafkreiagvfadv47i6reiggvsqcus4ie2kkm6k43v7qehvg4rdadlu2rofi",
        "div",
    ),
)

for (
    _document_id,
    _from_section,
    _to_section,
    _content_sha256,
    _content_cid,
    _receipt_sha256,
    _receipt_cid,
    _element_name,
) in _EXACT_TITLE_30_TO_REDESIGNATION_RECORDS:
    _document_text = (
        f"§{_from_section}. Redesignated to R.S. 17:{_to_section} by Acts "
        "2020, No. 317."
    )
    _heading = (
        f"Redesignated to R.S. 17:{_to_section} by Acts 2020, No. 317."
    )
    _element_attributes = (
        {"id": "WPMainDoc"}
        if _element_name == "div"
        else {
            "style": "text-align:left; text-indent: -0.5in; margin-left: 0.5in"
        }
    )
    _EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS[
        f"https://legis.la.gov/legis/Law.aspx?d={_document_id}"
    ] = {
        "content_sha256": _content_sha256,
        "content_cid": _content_cid,
        "receipt_sha256": _receipt_sha256,
        "receipt_cid": _receipt_cid,
        "label": f"RS 30:{_from_section}",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": _document_id,
        "form_action": f"./Law.aspx?d={_document_id}",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": f"LawPrint.aspx?d={_document_id}",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_elements": [
            {
                "name": _element_name,
                "attributes": _element_attributes,
                "text": _document_text,
            }
        ],
        "document_blocks": [_document_text],
        "document_text": _document_text,
        "heading": _heading,
        "disposition": "redesignated_to",
    }

# The official Title 22 TOC labels R.S. 22:2.1, R.S. 22:4, R.S. 22:5, and
# R.S. 22:6 with the effective-date redesignations below, and each linked Law.aspx page
# contains only that same disposition.  The generic redesignation grammar
# deliberately ends at the act section and does not infer terminal status from
# an added effective-date clause, so bind each observed form to its exact
# retained official page:
#
# * retained Title 22 TOC POST SHA-256:
#   922a22c49042891f70b431bb9bbe97582decabb5bbe130c9ce7e416740bc8788
# * retained Law.aspx SHA-256:
#   52647a9b0b01de722ee3aa6b44292509a8dc52e5fdf2ca2a654c5fc64faf0129
# * retained R.S. 22:4 Law.aspx SHA-256:
#   a9071cb23c221ffbc9d71464408f069829e1b4ce7bd85799ab8af53b2ae519b5
# * retained R.S. 22:5 Law.aspx SHA-256:
#   cd7a3e48ab2167fc9f9e6d19f6141973ad92b526c7f7ae6c93c5d7ed2892e6c5
# * retained R.S. 22:6 Law.aspx SHA-256:
#   e03c10fd55eb35efd6594e3afe3cdd4414c470e9fff32f794db3e678593e5995
_EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=506659": {
        "content_sha256": (
            "52647a9b0b01de722ee3aa6b44292509a8dc52e5fdf2ca2a654c5fc64faf0129"
        ),
        "label": "RS 22:2.1",
        "document_id": "506659",
        "form_action": "./Law.aspx?d=506659",
        "print_href": "LawPrint.aspx?d=506659",
        "document_text": (
            "§2.1. Redesignated as R.S. 22:42 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:42 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506671": {
        "content_sha256": (
            "a9071cb23c221ffbc9d71464408f069829e1b4ce7bd85799ab8af53b2ae519b5"
        ),
        "label": "RS 22:4",
        "document_id": "506671",
        "form_action": "./Law.aspx?d=506671",
        "print_href": "LawPrint.aspx?d=506671",
        "document_text": (
            "§4. Redesignated as R.S. 22:12 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:12 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506672": {
        "content_sha256": (
            "cd7a3e48ab2167fc9f9e6d19f6141973ad92b526c7f7ae6c93c5d7ed2892e6c5"
        ),
        "label": "RS 22:5",
        "document_id": "506672",
        "form_action": "./Law.aspx?d=506672",
        "print_href": "LawPrint.aspx?d=506672",
        "document_text": (
            "§5. Redesignated as R.S. 22:46 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:46 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506673": {
        "content_sha256": (
            "e03c10fd55eb35efd6594e3afe3cdd4414c470e9fff32f794db3e678593e5995"
        ),
        "label": "RS 22:6",
        "document_id": "506673",
        "form_action": "./Law.aspx?d=506673",
        "print_href": "LawPrint.aspx?d=506673",
        "document_text": (
            "§6. Redesignated as R.S. 22:47 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:47 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
}

# A retained replay of every available Title 22 locator through R.S. 22:41
# found nine additional historical renumbering-only pages.  The official
# Title 22 TOC and each linked Law.aspx page publish the same single heading,
# without an operative body.  Bind the whole reviewed set to the exact
# retained identities instead of expanding the generic redesignation grammar:
#
# * retained Title 22 TOC POST SHA-256:
#   922a22c49042891f70b431bb9bbe97582decabb5bbe130c9ce7e416740bc8788
_EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=506674": {
        "content_sha256": (
            "22106ce408e5214c2f33ee2f6d68c3d982e4b0f3e9bb09970aec0b9f47725224"
        ),
        "label": "RS 22:7",
        "document_id": "506674",
        "form_action": "./Law.aspx?d=506674",
        "print_href": "LawPrint.aspx?d=506674",
        "document_text": (
            "§7. Redesignated from R.S. 22:13 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated from R.S. 22:13 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_from_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506668": {
        "content_sha256": (
            "6b4e38bc7e4607709a5a7c7fcf4145ae3f7ccc5a49c67c11985547c2e2ecbb43"
        ),
        "label": "RS 22:8",
        "document_id": "506668",
        "form_action": "./Law.aspx?d=506668",
        "print_href": "LawPrint.aspx?d=506668",
        "document_text": (
            "§8. R.S. 22:8(A) redesignated as R.S. 22:3 and R.S. 22:8(B) "
            "and (C) redesignated as R.S. 22:2(J) and (K) by Acts 2008, "
            "No. 415, §1, eff. Jan. 1, 2009."
        ),
        "heading": (
            "R.S. 22:8(A) redesignated as R.S. 22:3 and R.S. 22:8(B) and "
            "(C) redesignated as R.S. 22:2(J) and (K) by Acts 2008, No. "
            "415, §1, eff. Jan. 1, 2009."
        ),
        "disposition": "split_redesignation_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506675": {
        "content_sha256": (
            "cc4df3dea5511c963f73507f0e0faab1578fcda1483f1bc1d66b16a43c76e0fd"
        ),
        "label": "RS 22:9",
        "document_id": "506675",
        "form_action": "./Law.aspx?d=506675",
        "print_href": "LawPrint.aspx?d=506675",
        "document_text": (
            "§9. Redesignated as R.S. 22:2161 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:2161 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506676": {
        "content_sha256": (
            "4e91897d0abdb5e0e861ca15fdedd1159ba016dcc08664e92d6a071b1e0b5e50"
        ),
        "label": "RS 22:10",
        "document_id": "506676",
        "form_action": "./Law.aspx?d=506676",
        "print_href": "LawPrint.aspx?d=506676",
        "document_text": (
            "§10. Redesignated as R.S. 22:971 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:971 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506687": {
        "content_sha256": (
            "14a19c740fe82d6965646c26a18a55ea00bf887a49a4e2bd1fff584893d75503"
        ),
        "label": "RS 22:25.1",
        "document_id": "506687",
        "form_action": "./Law.aspx?d=506687",
        "print_href": "LawPrint.aspx?d=506687",
        "document_text": (
            "§25.1. Redesignated as R.S. 22:2231 by Acts 2008, No. 415, "
            "§1, eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:2231 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506689": {
        "content_sha256": (
            "3f0480186f4a21e33222c2c7156cc969f86c1ec9e5113f897fbd988ad5467dbc"
        ),
        "label": "RS 22:25.2",
        "document_id": "506689",
        "form_action": "./Law.aspx?d=506689",
        "print_href": "LawPrint.aspx?d=506689",
        "document_text": (
            "§25.2. Redesignated as R.S. 22:2232 by Acts 2008, No. 415, "
            "§1, eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:2232 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506697": {
        "content_sha256": (
            "980bea91be540f9b08e17109eb31603949d6a254f53222a0f1eb8f5c9a11c2bd"
        ),
        "label": "RS 22:38",
        "document_id": "506697",
        "form_action": "./Law.aspx?d=506697",
        "print_href": "LawPrint.aspx?d=506697",
        "document_text": (
            "§38. Redesignated as R.S. 22:67 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:67 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506698": {
        "content_sha256": (
            "1a2a677723e96f4063deeaf1f2d150bee941afc787fe481c81310d807a9f0c9c"
        ),
        "label": "RS 22:39",
        "document_id": "506698",
        "form_action": "./Law.aspx?d=506698",
        "print_href": "LawPrint.aspx?d=506698",
        "document_text": (
            "§39. Redesignated as R.S. 22:68 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:68 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
    "https://legis.la.gov/legis/Law.aspx?d=506699": {
        "content_sha256": (
            "262f45157a6fed47e01b029682da4f5e2986efd6167679ae9b5ad3c832185301"
        ),
        "label": "RS 22:40",
        "document_id": "506699",
        "form_action": "./Law.aspx?d=506699",
        "print_href": "LawPrint.aspx?d=506699",
        "document_text": (
            "§40. Redesignated as R.S. 22:69 by Acts 2008, No. 415, §1, "
            "eff. Jan. 1, 2009."
        ),
        "heading": (
            "Redesignated as R.S. 22:69 by Acts 2008, No. 415, §1, eff. "
            "Jan. 1, 2009."
        ),
        "disposition": "redesignated_effective_date",
    },
}


# A complete retained projection of the remaining official Title 22 frontier
# found 751 additional heading-only historical renumbering pages: 750 exact
# ``Redesignated as R.S. ...`` notices and one split-subsection notice.  Every
# record below is bound to its unique official URL, retained content digest,
# label, ASP.NET document id/form action, print link, navigation controls, and
# exact single-block document text.  The generic redesignation grammar remains
# unchanged.
#
# * retained Title 22 TOC POST SHA-256:
#   922a22c49042891f70b431bb9bbe97582decabb5bbe130c9ce7e416740bc8788
# * reviewed retained-classification audit SHA-256:
#   bc05fe490e0dc214b8684e9501236827128ba3d738260efa717f5a86a7427674
# * 747-row common-form manifest SHA-256:
#   77f9b2759bb273dc52376cc6b455e7e1f070aefa019bd1c0cda87a7962419feb
_EXACT_TITLE_22_PROJECTED_COMMON_RENUMBERING_ROWS = """
506700 d5819cf7160cc0abb7b16eb185be40520410efe221a5fe5ad940b683a646ecca 71.1 82
506701 56ece8a3f394747a53960e5488bb68ff9b40ba7d3ac1dac41ba8a75d546d908b 71.2 83
506705 4d5b1b6e7a20855fc4c90e6545fb81b7aaf7abb58d6d161433ab03fcd0505911 77 89
506706 932dd6951401ee494e80ab8eadde4f7d12ac88f0498b72ddd6c2d0bb289ad2c4 78 90
506707 d650a72ba36ee154828459783c11942e068a65a8196c4e3670a82a51b38b63cb 79 91
506708 1e89745366dc79a21cbc412be6d0cb7c57e43e1f6b6c0b9bfe66249ea7994370 80 92
506709 70777a01ce17a543dd4c146945a10a39f1874410ed2c44de8e7040893c73f98c 121.1 112
506710 21f50281bd9e858127534edce037125eec871d43af5f94cd642a03a1ca542fe5 121.2 113
506711 438088f79d7ca85c6d37c9ebd8012704d92b6f973b2ac871f460638704449ec5 125 117
506712 721f7828e521b30ffac861f8f872a7c4474b6d95165fbfe98867f309663b761c 126 118
506713 6431ab422cbf083618c62ef374cfc2b14bc56191ee3489ec632e575534e2bd94 127 119
506714 661e2251296780b8818b7157d89b7100df67c35fb9772d8f37f1aad868761ec0 128 120
506715 0f88a3af2a7b5207701a2c1887493e2de38070ec980ef5c6d7df8853083c3fe2 129 121
506716 842cd5cd12dcdc7b2201f9c3d3af57fa11d2f9ae388915e49c24141ebb6a13d5 162.1 752
506717 218dc242e042addcba21a11d343cec3408963d93affa890625e7dd390e12f2c9 170.1 932
506718 c8e15542572fd12274150a3e9b4d635b7d7e580e144cd94fc257219b56e3210c 173.1 952
506719 b2db6b084ff56fbce80eb29947fcf4ed252e9666ee6b686d8dcb6110ea2d0ddb 176.1 943
506720 90f966b0ce406e1424375aa59a8715bb692833e7fd11d3a54566787ac75730e7 191.1 1792
506721 48cfff39a9891d35b1c85a40bf140f1c60a7372c74f78cd6767265444802da98 192.1 1794
506722 9c3d7a8762be9a1f048b1efc9e5718abf464a09dcbc71958c951cd1cff9c20ec 193.1 1796
506723 40cb048f13fc4caa006ab0f7cb486cc6b0d2e6e9b558f8f750c89a76dfcc166e 194.1 1798
506724 a827da2edbb9a4013b7060b8c6d510378b97bbeda908d52280be677ac7bfedd3 200.1 1805
506725 7ef8ec267ac558245c448a7414c7adf79a809ec91a0560fdbdf3d3b1819c813e 213.1 1021
506726 b010f4bd15dad0e97657bdda473c3e36fa8a9527a8e23076ace651ce1cb71de1 213.2 976
506729 8e559382539bdf9517237003aa312a7d30cf9a0b902143721fa86fff3ff2091c 213.3 977
506730 0e17883d94b4bc368e8542032d2afcbf413e6c01d6ed49591b46ca57673c85a9 213.4 980
506731 64304df9c2aee2be847c7f30006fd4cec18cbdff9035d9b62c17d378480b2327 213.5 1156
506732 defbbbaf6f07a8f5aad3e08582f698545e6e8a2b87d6d2588b57a6a5e4f87e7d 213.6 1022
506733 557cfea34ce42becf13cb85debd6ce6784861318be748f7bb8361950e163787e 213.7 1023
506734 f6a0a0fba64b1320152e8406344c89acb2a79cb07749349d4ecbc89f3fb26528 214.2 981
506735 787ef59039c466bc963bb2bc131bad2d7e3850551af00c8d09a0dd16cc9fbe84 214.3 982
506737 0be02b348bf2e348bd5a1aaa7fb71ab427e33a45e0ebbe02b5b283c7e33776cd 215.1 1024
506753 b731c46ad6d6b7dad6cfe8afd464973ac72eae19337f5f1c48a52d77749b09ca 215.2 1001
506766 0a66a7b471864d730b1596603587c8e9e9047d314ce85ca004c53c57e30b266a 215.3 1002
506768 a3048b4eef5bd4e760a2fb18be6e5f5fe3cef594e7c54f989a5c957de15d216a 215.4 1003
506769 bf27e267e88c81db03bd2dddbdd20e7307a78b9b02c98ae8e198b49dbeaedabc 215.5 1025
506771 6f598a8e9ae3ed845283ce8b0a9287fca12988728fa69559d001704e8978e086 215.6 1006
506773 661cf13c7e96b6b948fb2bfbf39a904e097e3da607031a3a0898d4ad0591f994 215.7 1045
506775 f5a5e1a24f6f21ef3078632b64e52efdbd1455a4ae90f7cfd36ed2addae5e588 215.8 1026
506777 76d2cdcb91b271ca7626eb48fd3863fd62fdc91a5ff00339ac0fc29335fa662b 215.9 978
506736 962999b5b8914283ad91479529774daf47813e4072c4a1edee4bdf5010f22abf 215.10 1024
506932 7b6dd739303d3ca5c54befab6e983ba4d9d7bc4fa63185e1cce8c23dee3e375d 215.11 1028
506738 a4417556d82d7f1b68869eb2c5fda2e46e78f4513e8265c2da96653f21766de2 215.12 1029
506739 9ef27b28ec84eb8144fe50513f6ccc6d51c150ae67f697d11f159f6e8b2d7ece 215.13 1046
506743 0d68cebe82df4056ddea56fa6bc58b34c032d15afc2785be5498a6a98e4dfdb9 215.14 1030
506745 38925e9693ed6125ddca54710b1b955af355d1438f95f6a43871515416dedd76 215.15 1031
506746 a90a2c2f91f959006d99a0f5e7618ce6f02db06212a8541d93b87e7c44913f3d 215.16 1032
506747 b555e0a48bb0a4a8166ef7f61331347af2237933c49819f482f1fd36974273e8 215.17 1033
506748 965b2a5e2ce439129e865c2652917c3079f859984e90af431d67de1efa68bd95 215.18 1007
506750 7a7074faaaf8b262cdb52dc5da529287f823f7c0acc37a0cff45cc27314f4b07 215.19 1008
506754 c413a182c88ca43bbef4f86b4b298286eff057d7dbad5e46b458bca3d9754ad1 215.20 999
506755 63c74e8fe738bdbc26ec69448969b6dba5d3e21ee56ba4f52d9e55b343d0740e 215.21 1034
506758 b0cd77867830f2286015d3eddddae78cc92f216519d08192b95d3c7cfb81a49c 215.22 1035
506760 d023a3d42bde3478be01a88e69e8394fc1bc0ebbc938d77111fd1622efc43a14 215.23 1036
506762 ccf31460128009fda68f22b6f1ab18984a68de6a9d380098d93941c5b88abe6b 215.24 1037
506764 c7e7e01d44fba9a1fe40d329925c4e8691de61d8746b442634bd2bae362cb85f 215.25 1038
506778 10516271855600ee518c457d4d479d0c6b7e73c18993e0dfea61e91671b9fbd2 217 992
506779 0165a22c7551894ede9d6b554acd41d90166ccf3a47f6239b9c75fe16e19da15 218 993
506781 6a4d14f297f608ab48f2974f658f9105b21b5cebf9cf4ab19083eb6d75cd2eab 219 983
506786 284c9559bfd92076e8ff1b9e43132c81be64539797e95bfa2d6f9f376e8622e7 220 985
506787 ec3057794605dd4e82e4c9d21650de37394160e6a0e38dec57b04db37768bdc0 221 986
506789 3df08cbc500dcde6b7cfee8d478f15340f92ddb7c63a40de285a0d3e4eab873a 222 987
506790 52dd5c36fc6226fc8e6d6b6ed3abe4a013444ec6635d03cc70d44fdfbaed828a 223 1039
506793 664b98ef0c3c75908626d6015f53fbb0f7eb3f07853cbd343083d6b599da90da 224 1111
506794 cef39d0d3c64d01f842592ddbb208e672166dff982a07d4ba333afb2fda77214 225 1010
506795 e63ebacd35730758a0baef553dde22db0788cee9cbe9c502dc84d780dc341000 226 1011
506796 99cba65bff4aa4c2c91a485ddc7c6582fd27bed4fd58b212a14a7bad6627b11d 227 1004
506797 ab05ccd2cee33b974e01ee5c4259ef20d89a4cd1156db5124cc8671fe94f0e54 228 1012
506798 9a3192bf6832d5bc07eb3429979e02eb56fa488af8a18c55024771aae1118ee3 228.1 1091
506799 833a838f593741612cea5c3b1eb522c77a460947d5abff2d12100182e1bafbe6 228.2 1092
506800 9362a7ee7f93e6c1948c503f3a5e952ee1c91f6b20e02f4669c6240e14f31aef 228.4 1093
506801 70e00aab5e97f45a98821a9df80fb8e5ccff902ff73222b72f4e2a37d9102f13 228.5 1094
506802 af4f6ada6694d4cd05e31409fd4d6184f0204e60767436e197cb72e7f9c273d4 228.6 1095
506804 be2c2493ac82838923371988a818e3290193d4840a18cdd1b2a06fa4f50fb2b1 228.7 1040
506813 1a4815132516c45c88ab95b47d716dc6da824b512399fb456f888ac20e38925d 228.8 1013
506814 3bc8fd0bc8ec7c59a5a76def57267b1e79cea3b9bf57bb6d9891780094eb19e6 229 1096
506815 1689efc0cb6a2e8aed1b3773a6247f9951f825d58f54e1b454d938b13bffcb95 229.1 979
506816 949184bd864ef43affd7514b92f0ce16dff9618cc084f632fcb26d3451af6d6d 229.2 1041
506817 5a267af7663a9854c3efa3ef369215c567440c4784a78e8eb6ad8c8cdc2a1d0b 229.3 1014
506818 80d3570a791b577656ed8524dc2cb04d12f4a822850e257052dea0fa907e8f0e 230 990
506819 dcb9e2c49ad85d2ce0a2e8aa4d6411545a07b21585d82cf3968e9f2321e6778f 230.1 1042
506820 7915b0c0558e65fea39430929e656c8b3e841e6735d14695c0dcf112966a8215 230.2 988
506821 9bda941cafcf0da903e3583c58310bdfb285d4db3d529f357c38209c5d20ad07 230.4 1044
506822 33389841a089fcd0272195e8c420b2d149121e203b7a19ff0bb0e748ea4ce7de 230.5 1047
506823 bce53a085e407d81c334fe33d63f59f890246d052ecc6f482aca86ff65cc9d60 230.6 1005
506824 373f2eaee76c52a491dbf67ad4ac9a46c44d5be691258e01fdf453829dd9ee75 230.7 1048
506826 39c8e0f625a52b678f6154ee66ad2495b54fc9968c67e8d9619c4d640431c457 233 1203
506827 40185ca1cc9edd4189787b511324f50aae63dc051bfadab93536ddec3f52ce2a 234 1204
506828 992c07ffa51dd21bf98c1f917c6a432394e170378c6bcbf00b6d31ef152ba380 235 1205
506831 e0c734dcd1f3bdc07c37e55c1e5a0a3afec39a4436cfc7949f7bb8f54bf58c7d 238 1208
506832 3bc5b3049eb7c3f21f8a96a8e0748b321bb4f8d41e239cdeeff5c262aa4f055f 239 1209
506833 f37256237e0385c18ffa6ba9b7424fd40594d62740b5e8391b10a5f3bfc75ed9 239.1 1210
506834 2dbd2bfa11f75bac71f5a263cac8cc9d4faf215dae65ff03062aa2f1da89b296 239.2 1211
506835 1a38b1baea8b32f16b1a396ba0187d6ddce7c1f911ff2c6d441fff469e4a17a3 239.3 1212
506836 9f8319b165f30427f132ce380a163b4d992f9b79462b1e9943c9e0012a74108c 240 1213
506837 831f47684d8881109ba5b3f94972ab5d4151b398a3b6ee29ce62dcf89b1d4e8a 246.1 2244
506864 8d2bfb00d82f75ebb95f284a239057b12b50df54a4995d73d0d4fa7277058df3 250.1 1061
506894 0472a8167a566c171d8b8158e7fa7ccb22772c7761c3fcd851a06a8500ee5d0b 250.2 1062
506897 3228f78a33a13415293b559cd29dbe3c6ba85495409ad1324b53a9f905f6f68c 250.3 1063
506906 713180f7b6cdefd97f923c9fde6db42bfaf1b9b51cf3b679f2c49392173c2ea4 250.4 1065
506915 7e19e6f3da834c13786ad0b03ed11ba4dc7484df41dd31454de01166f1b43f92 250.5 1066
506926 eeca6e346d72de74b607f47b16bc0d54f07f7b8eb6c33221107d107176c77159 250.6 1067
506929 337a8dddcc30623277bfb286ee7fbd56a6d8456723ee3b84c30208df8c2a0ca1 250.7 1068
506930 1e11ac1df39519da5a8750b65b02b3c3e699e099bf4425e88de39c793315f3a8 250.8 1069
506931 fc3ef528d5415bd2fac98bf55139984f48ab934e2f01940613ae30564d5ccd27 250.9 1070
506867 c4e87935ab59e360523193f948e9eb985af2f793c8a8165db36c10a9ba17ab49 250.10 1071
506868 3643a4f12a799534a3acbcd4aafe2d9b60cfc88ce1cc52d6a942cdfda0092bd0 250.11 1072
506871 01f7af828d6f46affb76633bcfe372511de3bfbd0f28c3b0a987bf1f8b194728 250.12 1073
506873 9f9fbf6720f289f21fffa874f997ce69f98fa980bf97c915f4b15d8b333c10b2 250.13 1074
506874 2654485954c21e6a89674ea51cd3a2de2750141f1ca699a6deeb74cec512f385 250.14 1064
506876 16b12d3e83514128dbc741cbebb844f2a0920b9c5d452a80f9f9eab5b91e1e09 250.15 1075
506877 b8f7c91535379af5855b1ebf547b0dbc38cafb9be299032fce2f7591740e4b01 250.16 1076
506886 aec4c1d71c54e378a194aeae4ec08208752e1d759a9bbcd0d2c192161e576424 250.17 1077
506888 2437c68bc293e0a1b67d490ab38907e5b62e788fbe9ad17ecf0cb78d42878148 250.18 984
506889 fa336f3efba3ea90bb8d8a8721f44a66f25681d20d911c85ba74e61b84cbdfda 250.19 1078
506892 78ccb6e904bbc8de95fad7f3809d77fae2480b5424a6503c3476dc22a329889b 250.20 1079
506898 7fc16fb90a33549a7d119bbd0fff75e65501eee541e430cd12a1f5b463903dde 250.31 1831
506899 cd200c66e9dff3a07865dae6be88b40968846be2ec8da60dc86bec337533099f 250.32 1832
506900 a0499bb83eb00e25665691da81b742f927b2b3b7062e55200b0f49019598478a 250.33 1833
506901 068b894d4634290904562a70f24a322509cf1a3421281d3dd5a0b7be68cc0a46 250.34 1834
506902 ce1a36cb65faf816f3c23baa4327c3c20ceea58b31b39e2ce9349d65c8ec793f 250.35 1835
506903 e8b4bd6d454e780e4b6548bf27ab3fc0ce34cc26f6f266bf17bb047ba24f3f41 250.36 1836
506904 071d93c43e331e03095a11f7159d48845b4162fa1386f3b5954c43bdcb6fbdee 250.37 1837
506905 7a16b54e66649f6c2ac813c8340d31bbecca5df205d8e223afbfd17a229322c5 250.38 1838
506907 042b1872af163887caddc1c487677c455196e600821e3fb37d6d0a2ce1dd3a87 250.41 1871
506909 5ea69ec097be5c23e35631fffcdbe88ad9c5cbacf4a68f2e12932f3bb40c3043 250.43 1873
506910 ef0a2e5d4329a3d1aa057cd29072ce87337287fb54aeaff22613aace38fc1df2 250.44 1874
506911 6e9fe3864f0727a882dded2de26dba559ac294fce59bf3d8f7659eb0bffcf1da 250.45 1875
506912 e143c712335dcbec75a8481583cdb49627aa6e006eff9442648ff97181c74dcd 250.46 1876
506913 a047da02a14e7fe84428641457717cae207afae8e0d6d85c034b6b86a2cb0e9e 250.47 1877
506914 51d7b6b5994a63312fc4bf30557890228c203e9b24f4ce122ddfb17ccf69223f 250.48 1878
506916 5f0f2f3bc1d6d21ce44def680b0e77e2220682ce7c9938ded8671919b3383321 250.51 1851
506917 7c9e7c8bd13c72f10d881da25265f2943ab65af244edae99cea5a7d0d000a4ea 250.52 1852
506918 5f5014eae6d21dd2d3c3e0a9ab55b25ee12950db284c6773015d9879f8fc1ff4 250.53 1853
506919 7fb5cf2d76dce6fd94e823f5d622d74cee89ab9bca7290af71de9f3450e3e6bb 250.54 1854
506920 a1219e527003507dac115cb4282af4716d64c6176a91a0fd6457609f7d6a28d8 250.55 1855
506921 c247d321ad5954cdb957ad61af07f979f76a356504b54030faadfe80dfd42c97 250.56 1856
506922 b5c2a11ff0543ec65107aca26031455a23dbc15a06035bef3041ced1ae455701 250.57 1857
506923 294ccb25bc538e1b46aa0e10684eb40c71332786abcff51abc306307e820917c 250.58 1858
506924 bda9ebce26740bf7d3b1f65c6ee4444746fd64517574d0c109fbd2e9f0423ec0 250.59 1859
506925 d45b62f3a5623cd30b805846f09492a6972645797acba372cff674381e600874 250.60 1860
506927 715e97a7f3ee6553aa5699a221acbe4bb0705c8dd7c45c016da76153821ecc73 250.61 1861
506928 998716a9f118aa55df330e037f1574c4f79b955b2ced10aef1c089b3c2b67482 250.62 1862
506937 dcace156821a8a0be63ee69dcf3362586b77f73d74b44b9ec8badcef195d3e0b 350 210
506940 315da42abfc4abb63cdc7f54a7163e70cf0a9fe2d75f19802192929e8ccfb1a7 351 211
506941 0f8df3a6f72cb0bfeab9ef56241c4689df84db804a80ad72c1b1e52f795331cf 352 212
506943 fa6b0d2410072bf78825ea64ab8a033ca91f1d885ede7f86c7c2bd17bbdd746f 353 213
506946 5ec1573978b2a1d8edac80917a852dab225383111a062e53ee65d532cd8a640b 354 214
506948 c4b367dbcf453b9ee03ebef0ee173646a5504be4056d3d3d37fa492da7910573 355 215
506950 a1e774c784c22b4b01f736584c9b4b879f1a0eb2117ae34ec4de9dc4d08a0cf1 356 216
507046 58343dacb4ff7af9d46a952c2cbb34550911ac94b8970f5c0988fc9a8ce9cdf9 421 1221
507047 94311dbcf4ab22d29584dc1a62ebf9af8b75550441014707d47a3b0f0f21fd65 422 1222
507064 57592eba9e98c2fbe788e9b21a3862c83e80701e7580490b4de6a0a3d8b1cefd 447 176
507065 71873d5a8d1f00d534bcfbcb6d8f6e2491c19c63f10ba5ca7e359b09c60728f8 448 177
507066 ef8b26cc77e8d2d88c5da8ca544de66dcc2e35c6db6f29fe763b283933ab2a41 449 178
507067 1e66a9ef9b188069fe53dceef82dac4596a0cc7affb203da53bdf37086071e12 450 179
507133 e3712bb63783cdbf3f32df243366e284e4ba3ca0300ce75e2de4593e17c2f989 541 281
507134 c265ebc10a00c4a0c0302313a2a207b3d7c353848e793135eaf176fa042b75a4 542 282
507135 a58e748ee881f36aa08df3a8ee72b8701ea166edc44782b9282b4e1cbebe07ec 543 283
507136 246aca13f9902ff7557641cad771695de455fb05e4afed1fbf0c5cfe8d1d62b6 544 284
507137 f1dd844244f6fac5658c70ed10f6a84fadae7d10380e1f6c53cf2b3adc7f6a66 545 285
507138 aec5e998c94baa3a1e520dc4f126f4ecda8d95a82878ee24a1e0a38224f38166 546 286
507139 97fd10429f8f62a30babf5b9481fef3e30768ecb98d6ae77a12cb6b14a180739 547 287
507140 5ffe16ede9e6ee5d24676a6993a87d3c252a8014859c72f760155bee3e1cb505 548 288
507141 cb24250b9694fda450ab8ca94340e80cc727df91b728ab11d8c2f3e2e275dc57 549 289
507142 2dcc6a893695b1b1a673c7e75a6a0749e1524bf6c86b3b7c9cd752512d665fa4 550 290
507150 6cb1c0b199f2096361b80b766f9bb8083f8a00911bf091a4db4eebdab3f40d83 557 297
507151 6d9d63cf4c37114af1191115747453500c5a75368450541b7c8eeeb1ac830550 558 298
507152 2d31c62c70228e17ca3d2561575b4d74d7085f39145844fb63b0f9b7c32532fc 559 299
507153 7084c20187795ba2999786bee679330ff9b1dd8e6f7a0a38c8dcb5e2aaf784c4 560 300
507154 502d3103bfd9c693a9ba4b1a3770ce7f3e24393931bdeec908ffe3fa87964e45 561 301
507155 4fd8c84a803729d43d0b9a08fbf3d85d09d91b731fd3724f65dc50d9db2aa64d 562 302
507156 3acd6b314d7c5c2b2d60a1aaa20802e2ca8d93481299d185c5b3b3d129609d41 563 303
507157 2f0deb6945ec2d2649f6bfbd62884c087a844fb8400dc899fae79a6676e570e6 564 304
507158 d6ec92fb6d1590a1c07be22d799c8e0652ee99bf2a3a2995dddee94f6bf6ed8c 565 305
507159 594333685e393d1ace5e39e66d6f20e02818207a7b8e4c580be440d9c02e441a 566 306
507160 06c087e92c132fc0979674e3b4fe2d37a2cdd9e302701fdc2f841684940bd0f5 567 307
507161 189b718996c7fb14923274df9ca21afcf334e4ce26316ffa93ab23dbe9e578db 568 308
507162 f73dafdea37befaa237cd902317c3214eb719c61a5115fa6e40388a71da67a64 569 309
507163 2e49e8bfd8ee45e99f666b13cc0c57b7355f66414451fb85fe3f817313b60b0a 570 310
507168 b007c3c7db581a8fa177dbe81897168dcdf6ea26f4bc84db223b9d9597710aa8 575 314
507169 40685929098d1160bcefa410c935f4656d192396a56cd814d41f94c368ff5700 576 315
507170 b7e6e46f479e9ef314a120b78a40d82af45f21b3def26df1efcc024c969a4486 577 316
507171 aebe74a2f4de0300c0e18e2503116fc66e06018a746dec825ae1beda3f3fe7a7 578 317
507259 1d4b8e81d849f1bffa018a2c9f6a3ef6f6fcd573aaf1930775ecb4374fac2951 614.1 902
507269 51f4ab20195942f1288127fa274c6f08d098cc93bff2efaa03575167309ed092 616.1 858
507285 debb741be08d066e716cd165646933366c92dfa83b016f1b1198c3b236090c33 621 862
507286 b4d100985b7c2e9f30438ee0ff8790d07c97ac2b3598505458526cac787d1fb6 622 974
507288 4dd6d46875a98b0b536843b9f090bdb5927ed6f37118080b44b11bf506628eff 622.1 1281
507289 06eb145f9a1e44e79bc3c17d4ea06a18ad919a7328a1758f146f629cf479c49d 622.2 1282
507287 9e9166a9c6a36ca3e227021629e23b3eba327fb8cdce4e91ee1fc05ad87b6eea 623 863
507290 ffe498407f12e26718b7b08309fb566006bbb22123b8560524e6b2d0707413e0 624 864
507291 2663a943c905398659889db6d2dae935d870c5f50e29844a7711849067c90366 625 865
507292 3313a9e031e0bad784ccee172340cf3fe27fbbeb99865f6386d94e55848fcb48 626 866
507293 618a0fb36c66e2766726b67b8cc7b53c855f8a846d6b4d356231cb63efa0ac28 627 855
507294 cc796c8ae9c498e3f3a49a47827058a3caa6f7bdeb7f7ef9890eacda8a10538a 628 867
507296 f978229bee2e3084e84e392f81e3ca3b935496573e4baeb031fa5c884e67df5e 629 868
507297 6d190c3b094484027e1b39c65390f758020e0786f8b652ba9d3a3cc2399c3c34 630 869
507321 9ae21f5cd5c7500ed304a47b47ca5eb8ddc5facdc3ae51a1f435ebda8e3101c4 635.1 1285
507322 5d50b067f7aed4f0574408b692ebf922d56508f50918f472c51ed7c52b61adc6 635.2 1286
507323 0c9bf92c4a5f35b2f4f6f046a74a69e4f64ec9cba4242519c771b320603813a6 635.3 1333
507326 3f76e2cff5a46998c1b55a53ff422aa3868d8a24b976127bfdcd34b261cda30d 635.4 1334
507330 ffe12e805f93b139fae11043b3d4371733544a7837ac3616710aceeadae783ef 636.1 1266
507331 cbc6586a58cf6a2fd49ae2b12bc8a2a46fa5c9668df3ed3babe93131c9439d5d 636.2 1265
507332 22b4ad6e52a08d2163065161fdb60e167a1f0feceadc4eb9ad3c2c998ad705e9 636.3 888
507333 2e09e4066c2f07027890df15b70c4e71184e74e659af9e2518ed8d8bcc133950 636.4 1267
507334 612b4fe37775d60e88374015abcb90a77a9b5ef0c17e0f0abf0f68c30cb74e90 636.5 889
507335 7d86352499c185d8105e69fd0f79cb00e5fdb33dde8df947e2c01c7c9a967447 636.6 1335
507336 debad5818a179503f02d78f6dded1268af2525b34d21760ba0b24000c8674fe4 636.7 1891
507337 48dd64d6464dcd04339cc6762fcb4fec75a618f3c1d79e8b71120be7562d4c11 636.8 1287
507338 fb19508b0ae3ca24d32a55d1f6127bdd32fc4946bb9f5fd0e7eeec4dc9a08caa 637.1 1268
507346 1f14668049daa626dc19acb87fa3231985a2eca73fc02330c2054438ac3a14d0 643 877
507347 019319745b0370df8f3e6b903ccc5e8cbd79b0b0682dbfec02c35425b8dbb0c9 644 909
507348 0cf19f2473ac05ed0b6c9c01fde1856a482f46fc79d257bbe13330217ac783f6 644.1 910
507349 bf202fdc6419e46b93e66eca42ba50793e5a027a1f7ee45e443c30b9ea506858 645 911
507350 8a69eae305a5dc810259c8683469d895aefe2d13e3a7df94fb0e42ec986e3454 646 1015
507351 0f5b39ebffadf1917f27a607de9ec0353f708860ea31ac7defb9ad2e6a7c35cf 647 912
507352 0521ece68506b9dfbf192305f6709570156677083f31e0715ece7ee509213c27 648 913
507353 484cab0af2e44d21a9937f031b0afdda8bf1eecf344617247e74d622b2e577a9 649 944
507354 bab59ba2f4502fdeab7fadcdf09839ef5dd3421b8e3c7fd813ad32d740b1112f 650 878
507357 4b504a9ff38866ca5a1ae3ef18db34eb06b6dcb48628d796dcfede0d6d0a96fa 652.1 1097
507358 7456756af86e31f000d54fdc7f6b14bcac93209e45745b8b588656fb6264d895 652.2 1288
507359 4bdea4508d4405edb937f1ede2ef26d2c09297184289d5e7d4c4dd2fd9543626 652.3 945
507360 7ad26a78c0513047850fe5cdbaf39e1d25edcad6943e8438eff3929a94017b72 652.4 35
507367 a96b91b46ec8e50e07f1adaeb8898eed289c966597fb56e5746042bbd81aa4fb 658.1 1441
507368 f71fac3a788d40481030e39bb9f182b963cb2d5b44d4ba04cff1005eeb020bf9 658.2 1893
507369 c3be41f9d451205c44e54e7c43c2eaefd920a412c980547da7e9797795f7e8cb 658.3 1894
507373 e43616fa1f5cb0e5e5771cf0d7c2c6bad7174a95ebf1dfa2975d2905e1b6b780 662 996
507374 4a9c1d32a8636156217515f97f01ad8fc3dfd040d635ac8a7dbe9ded2c826c7d 663 994
507375 7dc10ed0a6f2adaf023d178a009e4b344b3a31bf693ee52eba930d2329403df1 664 997
507376 e04cae71af182f23dfd473a4d8e0d7b3f55e0f0d8111d32d8594c034db0d02fb 665 998
507377 28a1d872d59423726f10c6d9eef7e859fdcee767763b818a690d55d8502cfa7b 666 882
507378 a90374adb425208dd1e9312f32f797043e6bc276d3edebb35ecf93893cfffe05 667 1270
507379 988400c0d47673622f5239f7d1682f7677d9d8405eeb0e2b6ffafa754eed9eea 667.1 1331
507380 cf4ec6b03281b65e4200ae2d9c760baebfbc57f5f679fa25642284dc133b6754 668 995
507381 3c1a9f79b401816c8634b37912513190f505abc6dcc3257c3d07ed5be1cccdc6 669 1043
507382 55c6e9d9d20ee225c585a091930baf53e5c8c5eb836c87dbc18588e1ff31027e 670 1263
507418 bb5d5bde52e0ec7d377aa69562a04857e2ac815ed3dc590f5361407f88ecf9d4 676 1293
507419 453f17329868e3b62086ac468cb8c8a7b5f330769910410786f62c028dac49d1 680 1295
507420 616b00614bd941a6358e4fdf8c3706210356b5458be34ab3ea6fca1933200cc7 681 1296
507421 6776ae827370a7011c67519d0eda1f58eb4e987e4966aebf95e72142d382c2c5 682 1264
507427 d20f792332f075805027154911a2ab3511251d68184ddf7c38e3b29ab3f4b8b4 692.1 1315
507496 296411f2ce4e575896d2d873d8b598ae2e07847943100b440ff85d5484f042bd 732.1 2002
507497 f4fcb7cf9c38e4cce2f66687ba5f9a1dec863ebb6c3a9cabde4c962913aa83aa 732.2 2003
507498 22225c0eda60846cc10afcf43e78cb06d03f3c946ed64c8e3e5429e1f2dc8b6f 732.3 2004
507500 0808e082ca819617c758cc6a28ec76d2a84ed59f3eab55f1caf91f11cae76bb8 734.1 2007
507506 48faced876e741cd588ca21d048d40cbe244c51fb8a20ef8399083cdb721aa0c 737.1 2011
507507 e7094cc5c55ab580c8dca0ed2c4afa58a9c177896062e85f069b48b165db0d5e 737.2 2012
507508 9ac41dc2846c1771f00cf04252082332aade9f02308696a3a3a8787d00118117 738 2013
507510 e311f146e945ad02d58ff43e501c9ba099445b93297ec30ba1bab9023d1a5e49 739 2014
507511 74cc1ba90195feed5f106a72d83d66d9d313388e7155b5cf096eaa3204483d69 739.1 2015
507512 8b8de726cb9dc87d17be1cab516947e97b4c8834d4ebc6757269ddb655d8277a 740 2016
507513 0310863e95102aa14fee3f0231e9706ce61e13787c2d64d8f819acc03f303b91 741 73
507514 df0995830677a139d125f781edc670a76e57d63693caf60dd8b97c309cdd0a91 742 2017
507516 6ce704a291e22a73d6b5f6075ae89171c1164eddf7ea482d1a4c2e9b3786593e 743 2018
507518 1904647726931e1181bfb40580a2d0bd13253f62d2cbb792f2589b8f5561fb4d 744 2019
507519 b0f887615cc231d1b72bd19afb0b8a2f481cd0833db706617ddd139b64209505 745 2020
507520 91b2f3381c62b65ac62edebe39c2c4318917d6deefb38cbcc28723d5dc989e4f 745.1 2021
507521 f7423d92b0c6df0726c07115865f2159ad7fcfd4abd681990ef2eb73a3be3bcd 745.2 2022
507522 883382e213461749437d4914143156904a2e31958fb0f0d9b6639f60411f65a9 745.3 2023
507523 58713ee91937aff50b1715ee52dc03f6ffc2f8ed534f469e74bef54805d77a1a 745.4 2024
507524 c6a11fefd949093528bbc69b3b7f228fc9ba7d6e4f19ca5b79bb7ccaf9761588 746 2025
507525 bf26d92741a466a2bbe54407bc4f863eae0bf72a0ebd8e72d9958c07b588db78 747 2026
507526 e0c1f722f19dd9ae138fbe60cf7725aa35197743f82cb4c46dcba19cf5f77747 748 2027
507527 a45b7b0b280297ee4d4f29248bf7d1fce60bd3cb79941cbc38e6e581ca325853 749 2028
507528 f013162a87da5fe37771dbfff06c0c1e7edc355e609939640ad24ed443048db4 750 2029
507536 03fa8339a575b2f3e9415c496bde05fc55a8017076427aba97559165ef09cc94 756 2035
507537 9837a5cc73aa98432e942591d06b9cbf437395f70cf510448c50ed7932a661f1 756.1 2036
507538 1d053d5a6c63a322334a08aae526bfd3be3dcf7eb34c0949aec822d0cb9e7b82 756.2 2037
507539 0a7b9130537dec269c715d5774c36982f9b292b4bbbeeb0e4e47cf367c0bc2e3 757 2038
507540 0a9f24ca6c7a9783e20edefa647f3751e06aaaa1aadf015e55cd5b8705d5d9fd 758 2039
507541 b25d6d1cba8801a2841855266f054a3a2a14b973a11d405b6a906a82a385abed 759 2040
507542 ebcda8e37fcf7a05a713428f58a3a3f29af0e6e3179d357db64f6d6f056cad59 760 2041
507578 8348a4bdb62e892b7a9b856f30312e115d3a3d3547cc1153c8a472eb9924bc56 772 735
507579 dc84d69b013ac5616bf967c1ea3e6cc08d1d1e828db2b122a9a01d5831340d6b 773 736
507580 26c44b6545eb67c65643f898a96f75b22219a4d60994e17df416439a87d039d1 774 737
507598 bde284fc282b36febef9c0a9ae899e8c814078de1a5cf17f6f4ad0b01869e7c9 820 231
507722 40cab1cdcd97c8bdd89db0aa9aad2f950748b95d72b1293bc55b03b8325b2354 844.1 585
507723 6059ab791646c1d106ec7b14beeabeedf331f38003c835eadf8b32b2098d91d0 844.2 586
507724 4379aa406f3d5a54805850dfea5dfe92d20f3d9fdf1532ca78789541147a474a 844.3 587
507728 8a941122ad4418bee5b0d61644170a4ff74cb4684e01317bb8cbf6d7762b0c20 847 590
507729 f54947c60dbc64edde77391739ac28d7086bec630e5953b56dee452f15130b15 848 591
507730 4b9437e3a5f988eb920467e32027f9fb2d58f3aafa0a1ee7366491e13f4ab554 849 592
507731 36a190c60b08e5117333d16a0b3e5c7b508c80cf3f23bca9548dbdadd2d76944 850 593
507797 0fe93f3f247d1730297921ced94ddddce0c07012a86f40596793b915114fcd78 941.1 652
507798 896e969629fd9c5b3d798aa3698eb6fb1929dee402ce77779c7592076e1898df 941.2 653
507799 37a9dd8c9a761437f2b74334aa74716beb950a129be11bb843399f00f655d4d4 941.3 654
507800 ea2c808a3b4fdb0b65f9e765f2d7af77c83bb210eb3d7a563708acd28e5206b4 941.4 655
507803 2667a2648a9dca607fbcb58392673a5825752d5e55427b6a0dc6df0fe9a7544d 946 660
507804 ed7ce596a6cf2257e5c0d96ab51a02123658f0ffaa5b6164b5874307b4922523 947 661
507842 63f57f427933fa63298f7423c634989e89d5da749e77b420b004b4855f31ae53 1004.1 695
507843 537c17a99ad7fe98d65c5de3d702f22543685e65188a9c09309bf6269e1213b0 1004.2 696
507844 37fcb6153c946bf1b73b0c0fe07becaff062762fd3dfd31722a6433a364d1680 1004.3 697
507845 65f4dc18dbd64d389d7b0c71411c1c96cf02ad0b7d24f21bf59ac9b9676c1c19 1004.4 698
507846 8516ef5d7fec495768e50d0401a29c7e0aa439c64a420ff4d3a2652c98bb2710 1004.5 699
507847 cedff393287da6379bb0250097175d875eb7820a33d95912de904d4c155f7c21 1004.6 700
507848 a37ea231cca89352fdf16701f824c595135dbebe331a9bdadfc882440c82346b 1004.7 701
507849 ead16fdd6196b421a1fce28c808a9b30b5bb4a5b7881cab0d21e9a0688e70719 1004.8 702
507897 748bec858e9705985dbd71322cc4262514959015598c12981829337c1a4aaff9 1065.1 822
507914 88d370489c8ae5707a0f6cde412f6ffd6e2eb7c06fd3ee42eef09f9766949b64 1081 796
507941 9155cc46cf47b7f583788712f5ba87c8f7af57460c09bbc5748c93838ff280a0 1138.1 1549
507942 29d1e6ef1efafa44d049d211de00189eca2d36e65598f9f313f88b10121ada98 1138.2 1550
507947 655b48b36fd42aba436e5d114df27e2fc2ac5d9af7730e9f1f14290d089188d5 1142.1 1556
507950 11d9e767c0e86933c9512dbace006ca64d9efecee89324429efe22b1a29937d2 1145 1559
507951 7472cd82516799bd13942b80bc04637ae1f31e9d800c0a3f85000a10adafa626 1146 1560
507952 55a51beed015a7130ca1c6189fdb338f49485d99e33c68d2d4ad6800b55747f9 1147 1561
507953 a50f6f8266fc43755fc7b8f81efbe896e8b445ba5aa573265b588ffd6b58f275 1148 1562
507954 f50a7a4bc861b04d29e78647893e363cd37346b9c5358e9bef423320790ad644 1149 1563
507955 3a1924523acb5c4137de2ca2e47a607c0d7d01bdaf97b1eda8f6afefc64da6d4 1150 1564
507984 bafa8c6eb5d6bc2cefd3814769914ac58a2f55d0a1dc1855345ce8a05a4b7955 1192 1572
507985 8a2cea43c69a2663eda89e22bb184f5e7cc5db5b66ac25c2c59a96cc8c8acbc6 1193 1573
507986 9fa42193e25fe56b958a13c63685485ab3854ba5009a241b8e8366c3b501a9a2 1194 2141
507987 afc2cbc3149510c8aa11216a43f3a9c92a774bb17e6d21ee8ec7780c2a4457b6 1194.1 2142
507988 36e166035ce80115e7f50e13aac08584fa165b1f95bb2bff4f515423a0700f93 1194.2 2143
507989 950301f28e08e3ae0d540709218665c9cd3ba2cce775cde428bcda46783dff7b 1194.3 2144
507990 707bc37d0dac51a9eaf0fff88203c795f95affbf0d6f8013b7af7ec9b9351353 1194.4 2145
507991 352ef9ded55b7ec82e1798d1da1b6b851c121a32b08556b567d33400520be951 1194.5 2146
507992 ba420e3500bc2f589704e543b18d98fe571706b606e9493ca6b3162da431d0ea 1194.6 2147
507993 5eea0ad90fea65fa2df6d2cc09d431d350a744c4c8ae29347fe67429e3e2d9d1 1194.7 2148
508017 15b4af249d03d8b5b4654e31846e21761a20c1422e546d086b80dddefdf75e96 1210.1 551
508028 741c90c74a7243b3329ff45ac31161e42b351df607ae33b9649b9441bceddfaa 1210.2 552
508041 0947e58ef74677a52c415863ad3b4518d0180883616bcc814cc941a95ee4d417 1210.3 553
508047 d8edd1b8592418da60378a8822c1cd4b3eb29547be6fb95e67b781de4e9a4f19 1210.4 554
508048 b85480f2ae1b5fbd0c90aa3b596b53db861524a3d375492f194c5294e36b8ddd 1210.5 555
508060 cae4d76f64c849081eb96d5c69ab5deee705a59711a5f0744b552aec85bc7322 1210.6 556
508029 5cfb1233bb9c8e2347ee387e9f9139ea70f9eefb31e3919a447b34667a030c20 1210.20 1721
508031 52c9e7eeef41e66f0ae68c54fc552c67193df192ebe1eeadda3dc3ccc7a9518b 1210.21 1722
508032 bd29ed91198bd2ae85f1c480639145afb2c8e670355e0e5ef436a33fc3959e8c 1210.22 1723
508033 1298d566e39fa79d3abc37c05b9c5cd183a106fa27a3b6edbcc427b6a307a494 1210.23 1724
508035 e2de447bea41e84d2ade9f0af295f77bf83368f15a207e92962a3c74ee702208 1210.24 1725
508036 1681714453bd99d2f009a17559511198f6b2a63a2a96812dd0054a5fe007d9c6 1210.25 1726
508037 b08c9b8b238a84939902e7315e16e89fe49e0ee2d051e40dc8c7afe6cafbafb3 1210.26 1727
508038 290efac60d52be36b6e3266c094c2d5dbfde8b9b95853103dbf809534abbbe52 1210.27 1728
508039 11ace41d72ed2e60b6190ed8e1ad410736f39d0e198eea537d9069685ba05f28 1210.28 1729
508040 7d301fb52a91052d1b0fc65101f2d2c18550bc89b93a0cbee0483d3434acfd47 1210.29 1730
508042 f5114b13fceafb5377b31aae13b2e78ec220fbda31ec8635daddb389698c8d2b 1210.30 1731
508043 dac98008eadeba0631e1937cb45e21ecd33fbaf37c5c710cdbc8d7accdebb8f8 1210.31 1732
508049 e98b4dced67287383f4da31bb69e57049a6c827e15253f45e7e1a1d2a3860180 1210.51 1741
508050 b6b96eea84be907d4105651837a15f00723da86a0897544c738e9d6838a1baa3 1210.52 1742
508051 3e652ca971ee8b1df9f926b850e203107bccf9f17e44c3d08c7ecaec693aea71 1210.53 1743
508053 0da1e1f869e0ecae0bedbe00a7c3c449d76d90bcf0061fb0ae3372001b4757fa 1210.54 1744
508054 bc3c5ea8e76005768443c7efa27427c5875f410905989987da7a00f8c8f53493 1210.55 1745
508055 5eb5bf1ec8898a2f917fb6567ea318a6e76747c357a28b40dd39fcda0f2f0d55 1210.56 1746
508056 5d09a075a26ae6860a123d4c544cd429b415d730249437ed5b774af44dbf24b3 1210.57 1747
508057 b85c4a22cb54dac17d5b4596716d08bcac70a4e7d9ff80f3ca1e405e2152ea97 1210.58 1748
508058 1abb2c1885475acbf85c1b1f7e8cf9934a9221bafe17a442668c07c39b5a2f41 1210.59 1749
508059 6f29af27d4067cb7e5eb2abe3c29858061e4889cfbf4079748482ecad021f9c8 1210.60 1750
508061 9cbeb1ef76f674c9f33da6b4a4ba7c2007917304c9841558840dda09cc0f6d42 1210.61 1751
508062 06487d4f0e9dc710c6f31d93d6ab9f52e0594299d986381e676cb13786e46662 1210.71 1661
508063 56125fdef11f960bb51c8fed42074496c6435cdffa8909b69309233fdad910da 1210.72 1662
508064 3eb0f35a9bee301eca60c0e0e4e0ac6496e19e8c3bb64953a0d96c2887414343 1210.73 1663
508065 94124b68b0a330d5711b3fe6dda3d79240b7ea16c454353f85ccdbbbf29322a2 1210.74 1664
508066 5333379ff94140a3973f3230deb062dab3381fe24d795748c981a08c732a348c 1210.75 1665
508067 19ccb4af4e172924d0dc1eec629bce21b6c917fa07dfc8cf63f0b0ef23f33d82 1210.76 1666
508068 aa43ced8ac3c04075a92efce79ff7eec88ae71c08fb218965daf3956ff255d5b 1210.77 1667
508069 1515fe7db89e7d9ba4a38ecc41c41bc7bd111bfb19bbbdbe7b3c523baa2ec822 1210.78 1668
508070 c05c59eecd30db52012a7ddd7f8ecac6dbfa4166748c06b4d9b2b028fb4c7cea 1210.79 1669
508071 35184a1eeb5ed17b758f3d85e46487e2a7acf729295ed1d739a7324b428d101b 1210.80 1670
508072 1d085c544db3550404c632ad491f49fc300e37e25ebb362a66cfc9df17ca433a 1210.81 1671
508073 05ea7886a51a12455e2072bfc9e5b462ae80fb823d6c322e5f8ad10bf196e18b 1210.82 1672
508075 805ba401813f3a45f0a77782797a8d704688d7aa77deb43b086f52dae275787d 1210.83 1673
508076 cc50f57ba9c091839d4e26684cc3095730cb88e1fada62e86d1656040dc30030 1210.84 1674
508077 e56257af5ed09cf37a4ab167ff1fe7a26540df3f57ed814b76f854bc832858cc 1210.85 1676
508079 d79e0243076bbdc0b03b051c1636c336cb553c936ad058ed0f5318b0e94ec050 1210.86 1677
508080 efe30fcaa6dd2cd9ca19d63ba7fcb1cf838537cc69ae1679f461ecea75b3897e 1210.87 1678
508082 77227a4705b95e5d8666780b62b1035accc5486349ebb81b5b9eaa4e67dc7987 1210.91 1691
508083 aa3cd86b5808c99bc9fbe5234972e30f40e344bdb04c4262dfd00e77212f49ff 1210.92 1692
508084 1bb415902e964f1ceb0fd997611e7988b58b90171235493e8e99c2007dfe14af 1210.93 1693
508085 a1a55a03fc854e3fbea843c6911e134a9e4ceb1db876f8dd818ef60311c27f2b 1210.94 1694
508086 fdd645dc74110e85e49b4cae4acef80ace6670b5f9c1484181337c12cf01d9a1 1210.95 1695
508087 4fa7c28643d62019f09c5f6cdc857385ba63bf5356f41bed8e0499e35e9490a0 1210.96 1696
508088 3d04bc3933798a94d2da750875c4a3910d7527e909e46ffaa7a76b8415693aaa 1210.97 1697
508089 d163e58bad06afca909294b86e6ab60ddf04117c8ce218ccda8182db5fa902a6 1210.98 1698
508090 710cf9de4e9a484dd4174733eb01db32dd33906f06609d44f31b4733190a8b95 1210.99 1699
508016 93703343d30fff62e89d099fbc30294c895f4c8dbbd94510e03bcc7f9a9dc91e 1210.100 1700
508018 8d28ea79d98b3057b0f9a465b1846653688eaa686c26218f5da494ce2787e39d 1210.101 1701
508019 1e7b9bc078118f220b8be7b7ffa7462793d238812cb493640ad99a3c1b8ca9ff 1210.102 1702
508020 9100cd2c133d6ab16b90618dc218d80ef87c92903bfe92518cc9f66e9d6e754e 1210.103 1703
508021 d5eea49d33049f2e1811822c378ceee86de65133f8014d17983d1e27269a6ad9 1210.104 1704
508024 aae6bf559902272ebd57a6fac9b7f243994707515829e9957b9b5c206b8d520c 1210.105 1705
508025 085cb2a8c65945ef56bcbf30a740b0c774e0a30a17e8a75b55b0b864e98dd83e 1210.106 1706
508026 4ba012885c4cfb27ccc34616a5a4f2512a12653382bc7723c41e9e80dfe7fb7f 1210.107 1707
508027 7625d22bb815f3468a62b2b0e487135e7045edf0840924792b5a1a6d51ce7e66 1210.108 1708
508092 fff6f08f8c738ab36d99fdcc92a5e6acbfe18556b3bc0363618f0187b18c1e2c 1214.1 1965
508093 64aef00b8b6b0f3461721f8734b97d7cfbc1302c9b2e62d9b2dafdbc45d998da 1214.2 1966
508099 de4967d854c439d960be3788c1453f1239948feefd9156d5554e294c0211de4b 1217.1 1970
508097 e1cac853a9413b971faa407c9d27185b6556afcb9d05e2dbdaef1df303ec39a7 1218 1971
508100 c2fc9852e07bc17ac11f0482c39f4a72cb329c065b5294c56f991d171bf690b3 1219 1972
508101 59b4f7b7479ccd9279c1a527a3edec9375151d8cca53e5bd2deddc3c3ec57a24 1220 1973
508108 68f4f1574a8f68f6e91d19566922fefbbf3db367081944ea53182e08aed8f3df 1234 1944
508109 c9b140f0d29e54315cc336e71a78d10ca441c12649e83c24c4e1b43102c629f0 1235 1945
508111 2d3242f6fbd3762bc02d326e441f7733091d84ff762379ae04c46560ab6c7139 1241.1 1922
508118 2f45b67b2d49d61d1dc2b4c53743d3f3d44c167faed45c16e5ac4cc80c5ea253 1247.1 1929
508121 386c7f74dc0a9a504c59fc04f7fe2ca8a41f033d538c7101de9837a23e22a83d 1249.1 1903
508125 60b7347e9ef8e8f3b71cfa491c3f4306bfc29bd3e1b162e98e19d21aa758dd77 1253 1907
508126 3d0be2859bb786d87ef5e1aa15151467b1dc61795393fa73ff88ccdc4ce3f714 1254 1908
508127 ae52d868779bc26c08553af4eafcbdf99e7964ec18261ae5b94a5a49849fc685 1255 1909
508128 043ba22e7b5927b89041d82870a927c8ec5b1d82d7290112ac22110a235d8166 1256 1910
508129 7b2fedb9d66ddecded5d222c631577389717aa932f0ca2a8e6ebc88e3c83fe66 1257 432
508130 f80e6f1af90b76ccdc2e66c21d08efa3207b2a4cd6edf0a95a71a55f7cd1d603 1258 433
508131 9088e464ed8119ceea277e2f58effdf92f12bf1d0b2f3f02a325f329742d5cc1 1259 434
508134 360a4c5dabf2812161e748387b34b793410e359842ce04439e0f99ad2b59e543 1262.1 436
508136 bd6c29bd3a62e0e176116fd6f205d72cffaf83277b5fce831f53005e344986b7 1263.1 438
508164 3b9f6e9e6cdfa1deb314a3401ecb57d3b6097f7419d845d546633314888724d5 1301 1981
508165 71324df3400595d5b99c9f58ac808a0254bf9c210965ff61af9b45d726bd486a 1301.1 1982
508166 334f44444d966926efd35389e2ee69558d142e322eeeb868ba4637059aebe7fa 1302 1983
508167 efd6f3e7bfb198a5085952b3ac73233c3a063027d450580f008f7d65e823aac2 1303 1984
508168 076f6d1d1c25a1cb4f0a84b7c59d91e6fff6940190b860a9284f3d35b87033d0 1304 1985
508169 701255a653e66ddf053917915b41e042992abbcd000441ea0395c1d967a81b4f 1305 1986
508170 fa109fdb2c7ab03a664d533aef73a5cf375f1e324f098c381a98659cb3c906fb 1306 1987
508171 8649392f5fb1159859afa73fa8851c3177fc9a4431a079d8671105a2d86cd089 1307 1988
508172 d83004d98fa51a013822dde2061a3841ac9c22ca73de50feab9814d715e72291 1308 1989
508173 76972db4ab0ff38c2c0d6d54c206a4b2996577543c1ed6bee09dabd41b7f9a50 1309 1990
508174 bdbf9979e48cf8263fd0d014f54a479bd5f76054bfb4ef6bad98ff28c204c187 1310 1991
508243 8e1a415989ea24cb9bb031915ca9ffe63cceb6c833a9e5e50e1ac94c37f016b6 1321 671
508245 3bb6b8a8a6205919611354f4ebd7190ad8f045c7ad78b2bc08bc360c28993730 1322 672
508246 d0ebdfb1523cf7bec9bc0e61608cb04d8940c57d93e84d34dc5d1b82ba9a633e 1323 673
508247 74cdfc8e43c979425abab9db01e918bad948ae2ecf3e75cbf458d63ee0f4145e 1324 674
508248 d6bd4f222db72ec235cc67bc3a62fc74d541aab7787c41d72afa777efac427c9 1325 675
508265 d0dc793fb56ae34eece57df27c10e2b6e9d75fa024914de30966cbb06f9a5c2b 1359 2199
508266 e83d9544ee31439a557f5d8445f927b3642c883dd099282dcfe94626e076e2f9 1360 2200
508267 288efcbbe60471ae7955f7108e1d5e6509ff2d93c87728240d40aa42c2844993 1362 2202
508268 865e18bf3793447cba7500725c6e904c0ca7431a9b2c0dea2a92ebc6b6456813 1363 2203
508270 600e3dd1978bc4fcd893405b76a47c08861830d3fc89286ca0c1fe0992f9c0b8 1364 2204
508271 a11595dad618db882aac3824afdeb42ffa3b0acc107345f80b0df267c8de4780 1365 2205
508272 6d28ea13758bb520d5b7ac8d2774e95315bf413aa41c5126983fb8d07958e8c2 1366 2206
508273 df7b6a1b94fcd0e161cde7521da3c493affdb712a93b11e534e9ab8be660cc99 1367 2207
508274 bee71e90e2a131bce875b8ba49df1440766cb35928992ba5f5fa7bed04fef0b0 1368 2208
508277 31929e9c850b9b00baadf91c86427689a23ce5624410974c50f8cd516fe62b94 1376 2052
508278 226e1a7744d20ea4e976524c199e91ba095dfe55a45d7f429ed9370bf7edbf78 1377 2053
508279 aabc9ae13b0d86011c61817e872ff414f2deb8f107487a405ce87357894a92af 1378 2054
508280 0021b19fa97c19e2b3ad5c7d692b9388ed7fe6a719142c61215d1983a439280c 1379 2055
508281 364aefd6174ec0a51ac6f197b2370823d91de1bf28a29ce9e500a8eb88769f12 1380 2056
508283 e0e044c9225d62bac2a8d6da74cdd8e1e19efbd07eb60332c21310693f3046a5 1382 2058
508284 1c3db8c8b69f9b17ef5c17c628aa8d16f3448684af58b859a252df96934b997e 1383 2059
508286 c321240fa1ad9bd6d067a0231a1eeb6a0fffc401bb0c7563d59087d3f1418b66 1384 2060
508287 d35cf6ac43f11de9c6f8b7ec42178a5b591122a57758b8975025ef38c8ddadcf 1385 2061
508288 8427fe15e8068c51d7c9c650abc4381cd61a29828df4eee9f72aa3713c1874ee 1386 2062
508289 c1dac208aa462dde163f50bee05e09f012447aba27c5033bf1c27c6be6ed19bc 1387 2063
508290 d8c8a7b273977984567e7b9d439d255b67f6535a5be6e43c4e144bb5f1b9e548 1388 2064
508291 53f32edc2bda1db64f2c8c101da37b6d9dc14c1edc7880dd52a39938d4c34680 1389 2065
508292 a475efb007968096bd6a89f3f624636d8f896482d6721c9b192bb6fc0b0ca929 1390 2066
508295 ecb19cfc8757b27233e70e7ffe19391986301625285446b15be60b515a5cfd57 1392 2068
508296 871435d9e1db0430a13f16b0e7c8e6f8f6580375b0d69ba126451a5d72618a3e 1393 2069
508297 d840b15830ec76ed01121bd47f1a7472ef656a33a6b4e5fb4017b8e6400da1d1 1394 2070
508310 a5130170fd005195cf8519d218db7557dd0e46756f25ed83577ca49b1280102e 1395.1 2081
508309 a40c7f3a6de8aa345adf3f21810449c0916b10a0ef6fdab7e86f55ca7fb075c0 1395.2 2082
508311 c0d0a68233677d3039a6da17e7bb4cce79812ed659f737492d9e803ee76732a5 1395.3 2083
508312 044109fdf4dee124b8770c8cd8d3d7d555c6bfc1c6ef907f060360041c323478 1395.4 2084
508313 674e3cdb2a3039c00e5294c5d0f495065e719fef6fa021453ace96a7b49aee0a 1395.5 2085
508314 dd30a372d7618a5aed8bdbb9686097c040c5291452f354023b9b94cf153ace57 1395.6 2086
508315 54969bb700ae6fc67d3d991ef6087458092a4754cdde6e7f07f02688008be567 1395.7 2087
508316 9a227592cf73a43f5fc8be195dff82d38637ef88e15a97c1c4220af2e40c29e1 1395.8 2088
508317 2d0d5c3325a1bc67ae3275821896aa3b2abe8401d7c423bda73e21838a28541e 1395.9 2089
508299 fcad02b6806fc7aff80c48421e95985b5e890b47794521e711bce12e0800aff0 1395.10 2090
508300 70248d3d1c984b7e0e2bb698d32ea5fcf7d19d41d66511d9a9b196b50827a23b 1395.11 2091
508301 1b8ef0eb73a35d2e207ab8cd6e44cfb390d088c08a6ceedb2cf3d37a08dcd3ea 1395.12 2092
508302 d0173a69d548f48a050a3c70c8388509de9285423cccaa15b4c3a779592d1be5 1395.13 2093
508303 e4bd05b86b644c94f930d234a2df22fe3f525e7b6c7ebcac8140563e4dec7368 1395.14 2094
508304 d147c1ce8725a2db8a5412af400d5d6903c88bab0eef9b7ac0ca2d273906ae0b 1395.15 2095
508305 9087b10d5d13eebd6dadeb2893802022b896ae9a804c287f12431082f99e49d4 1395.16 2096
508306 3ba73bef42a647e4abfec005f764243d3e9615eee75734578ca8d78473155de9 1395.17 2097
508307 e3775760e3d8761e375850e50b2c55a5e7c87f51006e5d0f5159b2aa327ffd8e 1395.18 2098
508308 b0f0f17010773cd679292a9bf3355ac27272911a98053ebc2e21833efe71b00c 1395.19 2099
508319 a39155ae30c5967f8159294b4772e0b8f5508f2d98cd885429624d71082c5eed 1402 1452
508320 563b4b43c46b7ddc1aca599f040545de4cccc280b35f1399c55d924fafc9df8a 1402.1 1453
508321 c455d53883d085d2019efa75860cc4665ac26ba213963d89ae6f85d7dfc7e9b5 1402.2 1454
508324 1a280e7ceecb50adc781d172602a4fa780ef8a8db2b2b82fdf7e8823d6072f8b 1402.3 1455
508325 b566f032f783abe334be1497048b1b3ed36b4a310f6ef9f5189f3b0254ea251b 1403 1456
508326 1b0caf922bb763f7dc76b318497b7beb5fa065ca4d4a9647c16862432a042c52 1404 1457
508327 27e0f23a0545979ca974566448c9ef6a463c40e5c2e257895109b9d6de86c7f7 1404.1 1458
508328 f6ebbfcfff4a02bc2ae24f78ca1b1ce1457804e0edcab52191baa8943baffe3a 1404.2 1459
508329 e5cfed1bd68f237fd9273b6cf0ab94708d86c126bc50eae62ce3421cdda7acd6 1404.3 1443
508330 45a208914d1f336fae41f1362a9364c1c401bff561881109a033aa0e8eb94a3e 1405 1460
508331 0289c8c229109eb0f5624cbe296d00e868e1d15d699fcdee2dc49752ca9bf112 1405.1 1461
508332 e9edaa2a469536469e042d4f9bd2e38e1945fcc069fdaefde35303f04e12e86e 1405.2 1462
508333 4e51db627105fb2718864bce6d70a6bd82c2d49d096164f17773039a4a1b8a92 1405.3 1463
508334 2c9fddaaf8a01a27736cc0eafd5e8883548de1fe5fe55856e917025094fb0954 1407 1464
508335 982ae2eb7addfa24766b959d43e607777550b8d9f23e93e098a0e0378fc9f765 1408 1465
508336 24454f6ed1bb282bb67f99422654e75a3c6f9e7f3fa26e815afe7e1fa8d9ae43 1409 1466
508337 0f637ddf7865f55674caf52ed0167c7ba60a1059960d69d4daaff269407f1c9b 1409.1 1467
508338 ac31f8fa6adfc9a390aa5ac7faaa44bff5bda755e06162116e5821f777b798b1 1410 1468
508340 99ec09ea31a1d5ea283ad2bc62cea57409be0b9b9289c79f83a65f554d7139d6 1412 1470
508341 0d965c08903e85c191bf9e70eed70bf0e65dfd23a3bfd48f9fd82f8b8db29d02 1413 1471
508342 2f9a92f35d67a42a98cb8ca013e8df298118a18f964c25f223b89242f7c705d1 1414 1472
508343 03ba9b9091e40797da42fe556f0d400ede574c018feeda129278b3c0a76ff3b3 1415 1473
508344 d6a22859eff78547eaa0a2ce0c8aa83e0c6d2adf79b4a95391b7201379d33e64 1416 1474
508345 f56d1beb704ae677d5d80ab859ac315ea44965b6923bd125a719006cfda35748 1417 1475
508346 94b90f533ada2c51631f4287f07fe63aeec6b54274d9f9cd6cf0f4cc3dee7815 1419 1476
508348 53f75f07e67e6ef477edb70fada9b4e7be93ea2e062c542f5e68daddd63c3a1c 1422 1478
508349 7c3eef3f913fb1c13c8e7dc8e4502a0d7778cd67c38f3ecf1de3777b402c65a4 1422.1 1479
508350 9fc7c91adb4a1e8130d52c75ed4a4bf75d29af9be9241c26efc7addd8a69aee6 1423 1480
508351 1b8ec1838a859674bd7c4ce24c5a6bf2f9018fc18fed55780a393d35d38ac04f 1424 1481
508352 b4637588bdb92b2f87cf0f372fcdbf716492758be48840bc6bdd8fac5f578062 1425 1482
508353 502c55d39437219e347daa43402a3f28e0750494e0efd5239c4c1958142c6bc2 1426 1483
508354 fd9c4733a8b04e22df5b673bdbd0214dde6cbec324cca9ace71aca6d22da5bcf 1430 2291
508377 ed5e4e2b9a77f3f662a84e035e9c492c028273b2ec2242ee1ec781269f4c6610 1430.5 2296
508378 3f7d02985ef8868b31e3f21bd024e8ad2c6e08a500e661402d4abd1881f225d5 1430.6 2297
508379 2adac4b04d2cd845947092146ad06749715a8e55d5abcf8113fa07c1e86091a5 1430.7 2298
508380 6c9dfb6d921b568d27618a73aada2141ec1bf426a1e3527f84d076cf2699f038 1430.8 2299
508381 d1e9c4ae45c9188071b164cc4746f3fe32d3de1c7350d1f2dabc4cda9ae19f75 1430.9 2300
508355 cc9d9e3a30ee99bb3dd5789a59d149360df842120daaf578ee9a17a2c244e042 1430.10 2301
508357 33a3c04339cb8438ab6613f2768e73f0c491bd1b813623d4a187b09e7cd4da75 1430.11 2302
508358 aada58eb959f47fa67671c1ea0038360b0ee7aa15a70ded540272cdc7dc81900 1430.12 2303
508359 5d9be865e2bda9727afa1a22354208bff394543943d3a0c8823c0434e4d2d333 1430.13 2304
508360 57e102dffa46f152874ed40db0f328c32126cf49c746deaed6f4002ade7fbbeb 1430.14 2305
508362 f12e6675fde7a46339882cd86062101bebb81803d5296a4d2db4990fef519837 1430.15 2306
508363 aec857612a79a007a1fda3a6b06fdb85d09c2fe0938606836e42248b5c3b3d8e 1430.16 2307
508364 9f4b2e78d874e176a02fb4b18f72b812f0427bbe9b9c05f625f337fbb60f6a7c 1430.17 2308
508365 38cc2ea4cc6207d61a5a29e0f1d68fe7a4dfe6f9a41ff3c35b9473c835344ad2 1430.18 2309
508366 041c0b206adbd003874b572c16725c6c4abfcfe5bd6e07d45a1515f10ab246ae 1430.19 2310
508367 224f9b6b27cb155c185a7135ac3a05bc19cc78ba291e9c757f3e9f60ce004a8c 1430.20 2311
508369 7506f4395b3958680041c39022372e52ff97e09f2b5281b38ce2f1866ac60b7e 1430.21 2312
508370 c5829a77c77f56cde32dd498cf47c20d8ca9126478443372defd213400ea5e6e 1430.22 2313
508371 61ae6fa218f141f55911f824d75767afe46f62ecd5c799d4fb9f2279016a514a 1430.23 2314
508372 272c504071470ff2a50cc9bbd08cd03a669eaa75523e1414d21c03873f498042 1430.24 2315
508386 58557dda70be6e6506977d00a129c942f8ec873ae8cad595e1c0dcf80bdfc6e5 1446 15
508387 5cec8ba9de39d1994687fd462103fee7e85f9c1218f9661654c2b2777c723104 1447 16
508388 12dbc213bf63506efed349768a39d83a46046f9a3697b1ab994f51924fc4d90a 1450.1 2271
508389 84da1443ac52dababb725282886d7912e08821d5fee5d88b354760d994a13870 1450.2 2272
508393 635bfc12a98781266bfbc718c95d51315c08d16ac2ce286ba228e2601a318db2 1450.4 2273
508394 62bb6a6a72e052f8af05e586dd79f13b7c7adba05d8bdb58ed23356493bdbb3e 1450.5 2274
508395 1065c4b2d47985c2d5ee473b2a6d0c1b715c083a6b9f9498f65e9a9592b15ad9 1450.6 2275
508396 187e7702d3bb4f1e37fb226aae3be8cc385b745ec27e2edc49333eed407d4cd7 1450.7 2276
508397 7ac7a5eb4a21c27f912fd3a8430404bbb428ec527fa950eb492364d83d4e48db 1450.8 2277
508390 6fd126c8e6230fb4659de41eaf00cc03797bc7421f148aeb1f2229943493f528 1450.21 1231
508391 db907b5d2cee325f0d5d826fe4b59cc13882d0dd63c7f6abf8439e5ed191a551 1450.22 1232
508392 2024667cee8ca0b06ca711d54ebbb33b4a7a79b046f2639647165e08e9e003d2 1450.23 1233
508399 efc4a93b68e8a81db8fc3898a95c35f9910f5c3402cc92b627f570d55ce7bb89 1451.3 574
508410 808a6c6ff8821618dcc67562904f4639037c3f43d8c5184481749f5371e89634 1461.1 1486
508423 8c3d99bf9289329e05b6201e1059ce4b1ebaadfd68efa19b468b3c0f348b526d 1471.1 1895
508474 2f34053a701c3d94c3a337a64d8bf5e407e83c712446501f4a0df4a37f6519f3 1489 1509
508475 d59e45d68e85a2d54b934caba2d1a2f036603586d30b75fdd5c423f53fb88cf5 1490 1510
508476 d0187db9688ea196b3e8453f3974ffcbd82ed9f0cf3adde4f608ca4ab3e890dc 1491 1511
508477 c1a32c73cc87e44897957a875e39a4608f76e13cd5e46b0ad531f1c02a8c0f2e 1492 1512
508478 6785244677c14abdc2a9085e831ea921c91cf431c448394cda4a37bb2a954f58 1493 1513
508479 6f0ebad2c709990d28228d431eccd3f6dacf92162d38e71af2c4ebb844289ccd 1494 1514
508495 ff376bdab64649454a0a2c6b6433f08ae356ae24618d49b10e47ff0524c0b63f 1513.1 1155
508497 0d937aff80bab52a096609359a5f598357c936a8814f2a2458bb89337b46ff7b 1514.1 1582
508498 a872d98780374b8a88986c879debcad65909a1993d67744c204de91725b2acfb 1514.2 1583
508499 7569b5a2991d879c8bcf30ec893a0f38764f61f40e678666cb93136ddd691442 1514.3 1584
508500 a1084751193d9f0b6ab54b5675cdaa4aa37907c97b802a7d67aa358fdbbe11a9 1514.4 1585
508511 111fec99b89cddfea9d3891d231ab15828ce4cadfe76f4dd04e5d7bb3907794f 1531 49
508512 ecf05c26048867ca68808e98293af3e5162aa049d9ca9d3d8e784dd8e837ffa8 1532 722
508513 67c9ffc2854a242a4c1ac6ef8ac4f196f9f836ae58565dd63c8672b3ea9ec54b 1533 723
508514 5a2ddc0e37b70752f80e80cb786dd09da0c6a21651c99d2ce1d9db68d18cfd11 1535 991
508552 95f1f36225f21322d2b51891d9293084ae6acee939ae3562eff6d9acd6c8a663 1580 342
508719 73d1a983933c2c1f5d5e43b92a9b2c3fc75ff769ad8837b2037c705567a8d925 1733 1183
508720 884aa4fd51668efef08f7f34804f22442799810d6b2803d38c3a2c60527338a9 1734 1184
508721 9beb19a9304c6b0f8b2decea114c1073fd40ebd94cd643f34ffb27d7374ad0c2 1735 1185
508722 304771c41550f78983db4291df822420c3bb9a4fded86c92660bb3cae0ae61c2 1736 1186
508723 21002db90df5a80400419e463a32134fd4858b8e7b0fc5037e8e6402c259340c 1737 1187
508724 91805a2a7fe19159c553973a1b2b0ef1af1797e103b919356210d3347cbce268 1738 1188
508725 be33d95925cb42b47d7c825dd0380c49e7c6b7ae62f2afcc925f913709946c1c 1739 1189
508726 b8fcf272d7d13e43853f6560ec5557dffd77058ae806f7329f4d750a22985c2e 1740 1190
508972 e13e57d976dbcb35fe5ac2cbeef8134656a6bb0c4540f1f2463db897ad4b9b71 1806 367
508973 ca560233f6eecc266258aaf501bd050d4018ebaec521393710e16ecb38f71c9f 1807 368
508974 33fc341d52f7c96ef46fc585a3bc7e703224bae6089e43157fc16e161dd63f63 1808 369
508975 fd1bdf7519290b86e0c943bbfef78254e1057790596b713413059d82ae2f9f51 1809 370
508977 f0db54903804faefb14adcbed41c5019159b65a4bac42ef7916114ede798c9d4 1810 371
508991 0e1f7dfcc02ff22d354608a9cb2ce90f77d4a249770048c0e4d7cff560173066 1812 373
509046 e8bc7b7a7b87abbd6b650b89953b6798c1156ae07452fefcd2559d27ec17d065 1900 381
509058 9db1462af2b8266ad151d3d6695e8f1ab38af7a46f666bac62a4cf96648c3c9a 1912 393
509108 3c1cff2a98995828dc4fcd80b482c26f7a636bca5a126cd499897e50e20a2573 2004.1 245
509109 b2447dca1f3b91d32f3018b78b58b347e52c6b7c0003bfab43a7483f5578b4bd 2004.2 246
509110 c334bed5ec2bcfc6cdaa373ad74f86c62f233bd76d62ca155e8bbc706e16b764 2004.3 247
509113 c7a035d7efbb82bf7d65487d081b0512ef951d29ef04d1744f8bf9c858a0d3cf 2007.1 251
509123 ff653f15b510706be9cd04f8ddb8c5cb119baa3805c52a9d6f5763cd089099ba 2016.1 261
509144 437a1f074d35e3a25216382eb95c0589aeb23a236d1e973c4cee52d6e6947481 2036.1 631
509148 72de3b1df0ebc425f06fb5393f997e1612a6da924d1f08d006361f93f22d7ca3 2036.2 632
509149 6109475d8167de1003c54e00ed398e566f95e424aa44640b20bfd967d0736d79 2036.3 633
509150 18f2e1159da5303e1bce9eeca009d2159f220ec7a8e2b81d60bc247dd0b38d0a 2036.4 634
509151 09fbee604d7c7e1fe5a358b28237886e38d8c3c224ba56b12b9fbea0ff47e03f 2036.5 635
509152 7eefff92e78a4ca373f669d8b0740424595ae87745b4f3df1e47e00e5f5866dd 2036.6 636
509153 17cc60b0a2e38bec5dc96ac9196f6b4a58e301d90e3697123b3d714609db2129 2036.7 637
509154 466f2a17395b79dc7371ed198a5b146f8c9b72f2c462ff03983f0a656e654447 2036.8 638
509155 42cbee3e450e6c13afa9882ce43d26e59b93081238be7c23b7d9d4c7f513cddf 2036.9 639
509145 138aaad6a4837d36b703a22acffb0c8c79fd4c81e58f5fcc65f2ede5fbdbd083 2036.10 640
509146 3c2867cc8052a5dbc89cf29cb7fbbf68fd83d85ca62549053d60beb7b998e642 2036.11 641
509147 43c02bb12d66668909eb5db7dda65c269de2418991f4e58612d56fec30142980 2036.12 642
509165 f12ae862c68d713808669cf97f141789d1ea8bb86d8e4bba1b580d160548e7c6 2046 406
509166 d295705745d92c43bc3370c933f88f39ae3fb5a920fdf494c0aaca6e2b44666c 2047 407
509167 250beddb2e1f77678e940f37f697b1b22377d6ac904ef4f2401b327e4f8835c3 2048 408
509168 31fea964cc09424e5153ac482d2e048ad8ed027870a635168c8a4b50cba4e228 2049 409
509169 8d3390a002fdb904e038219f90edc1710b05f0b8484887834fccde75e4f80141 2050 410
509190 8fb14a789da06a1f742f7f54cd240318417eacbc9113ca5f4284b70a44cf2694 2071 481
509191 b2fc5e3da3de440df75c229f7fad2286c878948417b7cbfe92233b8b9c3f3520 2072 482
509192 7708f5035f658a1749fe2e99de5259e00ee5ea8b200d56234d6e6a16570d7661 2073 483
509193 8f6ec3eb936bb1e74f5d94f741a93ea9fd4718688893d2c4d2b50c47f2d79c04 2074 484
509194 1d7e756872edcf0698057b39beca16d4fafffd6b4f995c45b2b02d18788d06f5 2074.1 485
509195 76a6af578991e2d13e6e6ca4e5b6488c1b493877819523bd40db9d7b058805b6 2075 486
509196 525e4160644b2215aef29c4d8d27304a559f9b655a5a5d2f65b4bc6ca1dcc8db 2076 487
509197 07aee926d9b5ca1617d56d4c418fb06aa1fc26200bfed30b88104444f568d879 2077 488
509198 05c62050ea8724b980d5548a8c8522c85284b31b1fa35ee9e339836afbfe431a 2078 489
509199 12b7394b3a3380dbf9f5224ee8c1e9eefc89bce55728b722581cc64d8f3b43a8 2078.1 490
509200 ff9f532967aba6f308206edc61e15cc3fb1560a9e350dc3a0e1b160a4b74e83d 2079 491
509201 c3fd626494576555c32a8187df63dce6586b0b07db30c01ce7a5760fa1a1e3f5 2080 492
509213 cfa65322546a2e7f36c1238b47eb8447b137b63213962cdb8dab6b9b8c4eb43b 2091.1 1521
509215 b833563b0fb4ab3d5f7c8e40eee633db3e21e3701d77e558c6df03184a839912 2091.2 1522
509216 8191a09007bf93fc91e192e913d0dcb98b260b521a841bd03d694011fc0c99e2 2091.3 1523
509217 3db72a25ec0e48188e94e4f061cd06f69f01dcc3fd95d0881b3fd8366a656a0c 2091.4 1524
509218 8b7188a543940449a1cfadf13fdfcdc573d569da833f6d4ce3f0afd7e66eb2d1 2091.5 1525
509219 f5a85bfad9c3b51e97972272ea7ad661b30e5ef9b77e247d5a4a01d8c0ff8fc3 2091.6 1526
509220 887cec2526957d579eace19e63f4655b37e5972ada6f21245f2758748ef54b82 2091.7 1527
509221 0121a4d0ebad6b081f06c354cd25d949396755d85d6825db28d91f462e28d164 2091.8 1528
509222 ec7462955bd0445bfaec914e3cc54f5e1d9e32240bef384b2a08dd656fff8dd8 2091.9 1529
509214 b09c3ae12d43fa92f3ac60c81396610f01564f34806397c0981f92e08226828f 2091.10 1530
509224 845d072194cba9396b1c134dc04153675787e3c8ed394829c7a8e98ae9428d84 2092.1 511
509232 0bd8e042f260f370680656457873e0b097546b4fbf59edb70180b7b33b3537f3 2092.2 512
509233 872f316beb2fb13ff739145605d88968a6373193482f56ba83ffa41036168ad4 2092.3 513
509234 71e22545a022b383e144c7aa51a1f060461da7985319a2b45276a9e1dec48e44 2092.4 514
509235 973b2ebb8574e332a840ccf8f5af9a2d948077a121c9ee55eae2bf453d29d439 2092.5 515
509236 afb3fb9e2075c8b8f05bd71857a19064401f619a7187ee0cc8558358fad37d75 2092.5.1 516
509237 174dbd3d46d0f9e509bdcf87ea7ab3ac6133984790ac9175e49c1ad5f1a92d04 2092.6 517
509238 ca0b9cbfb068e7ebfccc7d20fa4a5e31ab01bb9a07fce2d0de2dab585c8645b2 2092.6.1 518
509239 b2483989e5022102ed53f7675512e3cabc57319f78bccc747a1c317f1a3ea066 2092.7 519
509241 1d3153ed8ed9d8fb826add69ce79e6a65276c3c22dba4ab7c09317c3ed3dd5b0 2092.8 520
509242 96bbe0f41c960cd697419f3ae657553b5c00999e3e805064fff477e54f3d1fa4 2092.8.1 521
509244 68dc26731aff1ccc917a62139907a193e3a79f2f9e417b0747b10e441a5101d4 2092.8.2 522
509243 b8bd48ff34305bef5aade84e4c2e73570d6609b13c3968f2cb73f312c8c3fb19 2092.8.3 523
509240 0772bd553d64d4aa4e70f912419ef458b413cf46fdcac618a34cdf7c15b8dd7a 2092.8.4 524
509245 e53acd0c8461c73741b5f26bb03adcba92777b4689e2d7bfe6332fc46c028f5d 2092.8.5 525
509246 142ff8e91f75df3a9b8eb334486b159f5b1aab8fbe243b50738135fc82ab347e 2092.9 526
509247 724977fb8c92c986e45c63872a36d0b3b504962ef2450e2e41c409b9050cc94d 2092.9.1 527
509248 26a662be10f5fea6bc0d792e785d73314731b9800d16e46ce0bde1068f9c3ee8 2092.9.2 528
509249 240bf7f242578e91fefc8a6d62bf0e24d4374d84c28320b3cb63e33842ed56ce 2092.9.3 529
509250 61baf0898180714a0f7fda6b87d627ad5a6ea590c8fca3416b90b393f28bbca9 2092.9.4 530
509225 1d6ce399e3a46992eb924f42e73f08143d47aba8c35e9facc84cedfcacd07a06 2092.10 531
509226 cf3321c57148ee96459366223ce496f7a51a629c49e2ee5103aa3b946bae753c 2092.11 532
509227 4d11d0020398acdee171cb20b6cc2a9c377403bbaa774afffbfb9f820bf709e1 2092.12 533
509228 d874898dcf6d78bad7feaf61efa71ef980f5a7153cef80a056fba86902d95ec0 2092.13 534
509229 b95a1da6250d0d4a9003096eaaa4ea31e2f1711f68e703f2ec035c98bd429523 2092.14 535
509230 50b4b637db181e62fc2087bc59468e56482c13165fc30dca4af6acd4b18fcfc3 2092.15 536
509231 528aee0c799e003a3893ba3e21406257eec27e6c9024240693479982e2252078 2092.16 537
509258 7a4e56972e9b5a92de13d49537bb574bcf6bb70f607704f2fd31a135ce641176 2101 1761
509259 25ad06fb829670baeaf54f2d5d76b72f9455644234c69fb02b222618ce5e30a4 2102 1762
509260 1227d5c0939045159a18acd672e8b65f416585cebd0fae156bafaa494fad48f9 2103 1763
509261 e91ce1a296098b8bec93d9f1704e5bcf3ba4adf1dc9d88b3aecc6d2054325347 2104 1764
509262 a96a388d1a1a19c9da79bd1e3386c9cba8a605b8e8fcca8ae5a081a4bbbfbb32 2105 1765
509263 5672f5115ed75fecbcccb2fe4b83295a91e9ab572e9ca8b3c9b2659379f27b6e 2106 1766
509264 2e0fe1d843f9dbcbad6254335b3edf7b4000d0e1097e7bc83521275eeb11e24c 2107 1767
509265 1546185c47dba088876267b6286690075d26a5ad6fe0d778d9f56169276b5649 2108 1768
509266 e3aa6a7f0668d02ce86b0cdc1525a5bf490e9e352f9f03095287891bc27c7475 2109 1769
509267 e29ee2ed2c1981d80ba94f5230821ce0eb76e88ed3ec0072f77521678f0ad947 2110 1770
509509 2fb64045422eeff2dac3c30792255b50ca4531f16393eca39e0d8f9907ec2b76 3001 451
509510 ff0289841458c758a1db676c8f9e93905128ebf9973bbefb8fd3cb5cd56e043c 3002 452
509511 f2ca7173081ec58a63473e0491a58619d95862f2eb4cd837b449e34a0027eeed 3003 453
509512 48b43aae8081603462d61d00a4a1d8aa29a50e3b6dee6a4f80897f090bd41b8e 3004 454
509513 605f7454e454ab0f6a4276aafa0ee0776fb529705768027dffa92e4d4faff95c 3005 455
509514 b87a55cccf9697187ef3bbce3417e3954fc8afbb5384adab0096dd54894ce223 3006 456
509515 04ecec9c52c3d695dc10a5199b4ad4655710fbef23f1e38b7e6ef9492f053ac1 3007 457
509516 ebb88ae60bca58786c0dbcc2e4752887d2131cb569a1763eb4f49747a73130f5 3008 458
509517 7e42551306d10101a80a65eb956e5ae41cafa939fa67c35c624d57b66d47f587 3009 459
509518 41fd80d45c6be6fbfc9b873854ebf1159dafa71f0338f6bb5fc6c779700bc894 3010 460
509519 df409f61c27571877a23a7f1267a3856f6b0791d3cbc5e02dc8be04fddab48e0 3011 461
509520 74573e55b318e7618a8fbe29fc4bf766a4924407bfcb5d9a34d855aaf5594138 3012 462
509521 45d6e447ce52990cb0d7998a4b31537bdd68c15ad2c8cceb5a52fecf92df6201 3013 463
509522 0efac72ee78f64412da220f69914e1959af4b3bd7f773277dd85032eefbe785d 3014 464
509523 5dfe518a85c533c039a0a6130ef7e8b262d3310ba85a086e56553d8ce795b74f 3015 465
509524 6854e5e883d50973ca00afebd57a627c167b5509a824926e6559de3a0115c9bf 3016 466
509525 62fbf3ccb70162556ed35901ea1b46c733db09a05f68588190bbcffb4f7870e1 3017 467
509526 6cb09f4226d0e142d8e9bbc7b19fcaddb13de770c4276cefd4697788407f86b2 3018 468
509527 04f72b020dbbad80fe3516cf0511bd73083fcfede46fa35a5b8656b9b69d239a 3018.1 469
509528 84468f221eda60e378c0f52f4c3bab04e3d8cc3a3a85e4589276e27eb699cfa2 3021 2181
509529 6114fd2e87538e9d69c8ee0a968c4d85c4d2a2a881ee42d1d20fbc9fbecc6fb1 3022 2182
509530 fdbc808c67fd859ece94fac960c489e088288bb0bc4aedb11844ede98113be04 3031 1641
509531 49a39506966003dbfec9c8a1f231bdcdc94d5b117a9c77373d7b72da6ae46dc8 3032 1642
509555 4e0b3abd184667cffa6872f2cd59089ed7672035a89bef8cb2f202af786a05fc 3033 1643
509556 15b6a40ca526136e370fdcd3cf5651d8616de86dd6e921609fd8ef99c2ad1339 3034 1644
509557 28b83649c39f2c6ba3e4c354b31887f9111fe558df15d16424d658b8af856cb1 3035 1645
509558 fdc466d8cd8c287a03595105a48e73b611785d5f0425bddb398b00adb1cf3c57 3036 1646
509559 836f1297ef4142bc09375766bb0886050692cd451e213797178e5f5d31198b2a 3037 1647
509560 c43bd19639a31c9720796093bf968535ddc33b7f9fe4fd3f37f2de87f5efbecd 3038 1648
509561 03735b9f393a8724cdb4947b49f141821e13e8f2e6da66d9dff1efae3a744fe8 3039 1649
509562 f3bbb7525c62045a8d0391ae653b0802991d5166ffc53cdd61a00d47cdd0f39a 3040 1650
509563 7224354e6735e44ad479ce6086f581575c388649f4eddc0ddf082d428eae2b44 3041 1651
509564 7319d822aad67528b735eccbbcda93e1ca60c327f0150fd3e7e2165659617692 3042 1652
509565 dbc1176daf210209630d4c5c7b8bcab0053a90fd19fecd70e83b73e4a985f430 3043 1653
509566 00993e506bb3d7af5a7588e41ef92c6c3eec812a50872f2f8f116e1fff0c61f7 3044 1654
509567 8c92774e0aa84f8bcd292def1592c875510ff445be29b79de7fc338f67bf6e29 3045 1655
509568 f4a4b0bfcba581d2f00b60366cfc62db41357eba9df508200a5875ffff607588 3046 1656
509569 34398c97c909f2afd0bdf91c56d6fe83e404d503223f34c45bb9b6c1740d50d2 3051 1591
509570 ed8432bd207032bbadc21d278b44ac57af79ec5f048e12a541932da192fdbaa2 3052 1592
509571 15d1f207707d01b4eff17a9a1d044e4458176c24688c8476069ed23cbc02aefd 3053 1593
509572 a7616dc16e2e0fc8050be0231c4107f08942e90ff015459cd1440c0fd201a7c9 3053.1 1594
509573 a7c73c18e54fe026a663f269cfc7541a87ea400b3193a520aef44641f319b660 3054 1595
509574 393dc6a54630b22bae43a8c22a54b47c680ebdb9da80e9d6d5cb0ad129c7b45b 3055 1596
509575 76843e96a986495526d2c6130a947860ef889486ac83dd9ea70cc0260716aece 3056 1597
509576 1f1efa720939227dd6f758e2c7164a26817626831fab4a6cd899c23e7a6510f4 3057 1598
509577 f3323a7c05e603b6dcc39d969dde0c3710a87c577290ccec16dc3b865d6a5a7c 3058 1599
509578 20e460dd14263568aee854160146352ca0505fc393eb4c646861f4c8d94f57a1 3059 1600
509579 d321ce63907a1cd5a15cd49d532b956fe276fb30232182cf84969dd87691ed11 3060 1601
509586 c331d8d0ecede5e55c9547f17497b8d3f1d47c05457848fe34c1fade35afdbfe 3061 1602
509587 b9a934e6136cfeea763a04eebc286f9eb8da6e2fcd06b7fc59824ce0f0f8ad0e 3062 1603
509588 d95739448906b1f12b04ad34e3c32269d13ec1340758d9d7617ad606801a2b2c 3063 1604
509589 8516b4b2bb00573e876b9e22871b90547b0e20f63446e6aa5075cd78119c0215 3065 1605
509590 ef0ae46689f685c8aabf7c46abf1ce3249f0f465074aa0f29800b22f93eca557 3070 1121
509591 f82d5e3086b8286a3d33e7b492d6d71a0e8eaaad4ffc9d740e19463448d67a48 3071 1122
509592 3d211c705809ada270a896a719409c5425c2ec6b5b5cb40dab2ecd9818bc951b 3072 1123
509593 72ab169c29ec7d6e63c6cd03c7ec7d504722aac2478ec7cedf91aca4278dfdbd 3073 1124
509594 425db9454a21a352b57d366599e8ae970ed8c27f5d97b43d1c2002b04f7d60ea 3074 1125
509595 e9d8ed75c13c2be99be7e01138c34f98f1afe65bb5ad5a5f0a91502ee656160e 3075 1126
509596 29694ab9647f94b5211bc4ca34392e8509fa6869b07c411137ea20359b89726e 3076 1127
509598 46a29e533be0a92c2cdae810ce4b14c1e520eb619edc3b1fe710fb505fb5d8b2 3077 1128
509599 acfa1792943fc660ce156b065227060e9f3aaa5b64cb26a6e27bceb784ad7f2d 3078 1129
509600 3063c0cf0c0894930504bbfe364522d6e7ef4661ac0ef7d0b8025c75cd488042 3079 1130
509602 235c8c0135806ffa5e7c1330364bf5b78d975751d1bb11543c81c232bd11da17 3080 1131
509603 2aea935ce1dbfac969d5c77b11d8f44d3daf5f019fb848f706689ddb7eaa0d6e 3081 1132
509605 0e2dd1a467ceabbc28301454eaef9817a089d51ea7cb84070e66738fa35769b6 3082 1133
509607 85de9f1594209cde97d1be98db2b9f50ea72917a367780a76baeef50ff27f878 3083 1134
509609 99ff35427e861092ab68a8d4e799140ebb87481c7753b552dad57837ad52a504 3084 1135
509610 127cc015ab88ecb4df3adc1ee35a42e2d01f09af1f67c6ac75b1539e48499348 3085 1136
509611 c21f29349ea0935152b160502bdb5adcecdfabb7c7c728349ead0e7860428462 3086 1137
509612 1b45d1c61e74e6a350934ed90717e0b1fb2706fa65511726b2dcfe2eee0cf7ba 3087 1138
509613 5ca82e29d7982dfa5fba1ca124226b28ce164af2f97e9604d53ad5d2371f1c21 3088 1139
509614 2e2a386824e77d0d2526ce0acec07d3ad008d81cd553e80b30b2664d75006d14 3089 1140
509616 8f7054c046ee7b82920a86e431df4af5da3fc640d005acd81b1f290ebd990d51 3090 1141
509617 063f6280c2ecf57f32d17d78fe87911ec381357db7ac3fdc53108cc592dd05b0 3091 1142
509618 4a760d733844e6ad1ec586b18be0e74ae43b1e99bde921aa15fecda1896a8126 3092 1143
509619 bafd8341c4c6e2b4d308b3212a7313c9f10cb276af4013368c906d8787034b9c 3101 1241
509620 422ec3c326cd9bea18e78f77252a6da31563b51b55aba2034b7492a0b2e1913a 3102 1243
509621 663e34797c3d23ae2c00d4bd10cc7ad06cfbac005a99eddcb6627add24857624 3103 1244
509624 8a5473401d86d4c36f56d6418890df0434f7df6fb32ca4754234feef31434dcf 3104 1245
509626 3f054e5b3f1c2df04fba442f720616fd635cbf68be97b5b4bf49009f3bdf8946 3105 1246
509627 eff72753e4f094cbf46cce04164650b50a112611f131f88b341738c7caf5f016 3106 1247
509628 d80724e74f69cd89d4d94f26c945267293be9343d03a1d4461b621f36d7fcc5e 3107 1248
509629 e2c529b33b7875af076b1b5ba2f38f39be1e1c92ff4aa37c213ad7e59753a1fa 3108 1249
509630 3a2acbfc2b59fd91a6277221809883333121b7baf0a460160cf7b7770b10ea60 3109 1250
509632 f0e30464ec9dd4d46bd62d0b612b910024f32d717da8c1a9a22fd795503cc010 3110 1251
509633 9ef773f48672e53b6832a9854575ffa8b682db8c2da85e1893e454273270a687 3111 1252
509634 eb72648e739bac7d868bdfde491f6fb51a3dd2f1a1993de16839e812818d82f2 3112 1242
509635 ecee586b6dca8b7e7d026074bb43cdb0ea283462cf0fbd630d859eee83b4db6f 3201 2131
509636 ee8ae46f22b71ea0eb106a624adc7152801adda0b27b080687732d68c62703b2 3202 2132
509637 53780efc11ef0da0c3fbe0901413432ba406b1a5b0d6532f457bb86eab1df52c 3203 2133
509638 1d7e0e54e75ecd612672b4322cdd9962965a48eb3cc10c281a794b66bdb8cd74 3204 2134
509639 6995cbae801725db89460e4080e7d49ff3b24512301cd73060e9633ad21843ff 3205 2135
509641 7bb1cf022901de8457a4cfcdf629f82a5cde68a2176e01f9468c14bb75c11656 3301 2361
509642 c00f17941eae420813480edeb606e7c4ad0499292c6a8a61984221e1446f5ebb 3302 2362
509643 f89c6c30cade673180cdac54f3d17805e3781acb43e9d0a972406ab7d0160ff3 3303 2363
509644 daa5b016c11c03625c41ee44b7b80224d15fa5114b601a50b861d2fd7da0a40a 3304 2364
509645 99081a9b2f312f5c65ad06124906020ce773221c6dc410ec1599e1fad868ad27 3305 2365
509646 ea27853226ee50e42c62dedc34b4d30b83b61a17b639869077395ce8b3c2a8cc 3306 2366
509647 041e9df7f567b678998def67dcb8ad58a4998d9337cc547db3310e0698d12e18 3307 2367
509649 9a5dfe655a993ff809a69569fd32a9dafa8fb49ba6aca116ac6bb5340b80130d 3308 2368
509650 de2b4738d00494626beae4f3ef21ce81d7c7eb899f6d983fa1879d56d5c27f9c 3309 2369
509651 459ebd1c933e0a1c7849aa550990c585bc2e732eeb0567ab4dce38fbaf827ff3 3310 2370
509652 3eb471a153322f27f582f494e863b695d3e8dece5420a4df5bd5667fe8397a88 3311 2371
"""


def _build_exact_title_22_projected_renumbering_locators(
) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for raw_record in _EXACT_TITLE_22_PROJECTED_COMMON_RENUMBERING_ROWS.splitlines():
        record = raw_record.strip()
        if not record:
            continue
        document_id, content_sha256, source_section, target_section = record.split()
        source_url = f"https://legis.la.gov/legis/Law.aspx?d={document_id}"
        heading = (
            f"Redesignated as R.S. 22:{target_section} by Acts 2008, "
            "No. 415, §1, eff. Jan. 1, 2009."
        )
        records[source_url] = {
            "content_sha256": content_sha256,
            "label": f"RS 22:{source_section}",
            "document_id": document_id,
            "form_action": f"./Law.aspx?d={document_id}",
            "print_href": f"LawPrint.aspx?d={document_id}",
            "document_text": f"§{source_section}. {heading}",
            "heading": heading,
            "disposition": "redesignated_effective_date",
        }

    records.update(
        {
            "https://legis.la.gov/legis/Law.aspx?d=506908": {
                "content_sha256": (
                    "76e53704329dc64aa4caf9c15c78d81f862d03a432702eadb964140df2a5010a"
                ),
                "label": "RS 22:250.42",
                "document_id": "506908",
                "form_action": "./Law.aspx?d=506908",
                "print_href": "LawPrint.aspx?d=506908",
                "document_text": (
                    "§250.42 Redesignated as R.S. 22:1872 by Acts 2008, "
                    "No. 415, §1, eff. Jan. 1, 2009."
                ),
                "heading": (
                    "Redesignated as R.S. 22:1872 by Acts 2008, No. 415, "
                    "§1, eff. Jan. 1, 2009."
                ),
                "disposition": "redesignated_effective_date",
            },
            "https://legis.la.gov/legis/Law.aspx?d=507793": {
                "content_sha256": (
                    "4e3199edb26568d9f13633abe314bfca3c6dc26f83cc3b1b9ded2cf48ec42234"
                ),
                "label": "RS 22:937",
                "document_id": "507793",
                "form_action": "./Law.aspx?d=507793",
                "print_href": "LawPrint.aspx?d=507793",
                "document_text": (
                    "§937. Redesignated as R.S. 22:917 by Acts 2011, No. 94, "
                    "§3, eff. Jan. 1, 2012."
                ),
                "heading": (
                    "Redesignated as R.S. 22:917 by Acts 2011, No. 94, §3, "
                    "eff. Jan. 1, 2012."
                ),
                "disposition": "redesignated_effective_date",
            },
            "https://legis.la.gov/legis/Law.aspx?d=508471": {
                "content_sha256": (
                    "b7178ab3d506bb7f820809ac79b11eecdc29259f9f0821cd965e2f4b7e188422"
                ),
                "label": "RS 22:1486",
                "document_id": "508471",
                "form_action": "./Law.aspx?d=508471",
                "print_href": "LawPrint.aspx?d=508471",
                "document_text": (
                    "§1486. Redesignated as R.S. 22:75 by Acts 2010, No. 703, "
                    "§3, eff. Jan. 1, 2011."
                ),
                "heading": (
                    "Redesignated as R.S. 22:75 by Acts 2010, No. 703, §3, "
                    "eff. Jan. 1, 2011."
                ),
                "disposition": "redesignated_effective_date",
            },
            "https://legis.la.gov/legis/Law.aspx?d=508480": {
                "content_sha256": (
                    "53d10825b8ed7dcdfb9b32de609d54cedd8d24ff35a98429992f1a890e36f252"
                ),
                "label": "RS 22:1500",
                "document_id": "508480",
                "form_action": "./Law.aspx?d=508480",
                "print_href": "LawPrint.aspx?d=508480",
                "document_text": (
                    "§1500. Subsections A - J redesignated as R.S. 22:781 and "
                    "Subsection K redesignated as R.S. 22:914 by Acts 2008, "
                    "No. 415, §1, eff. Jan. 1, 2009."
                ),
                "heading": (
                    "Subsections A - J redesignated as R.S. 22:781 and "
                    "Subsection K redesignated as R.S. 22:914 by Acts 2008, "
                    "No. 415, §1, eff. Jan. 1, 2009."
                ),
                "disposition": "split_redesignation_effective_date",
            },
        }
    )
    if len(records) != 751:
        raise RuntimeError(
            "exact Title 22 projected renumbering set must contain 751 records"
        )
    return records


_EXACT_TITLE_22_PROJECTED_RENUMBERING_OFFICIAL_LOCATORS = (
    _build_exact_title_22_projected_renumbering_locators()
)

# The official Title 29 locators for R.S. 29:104 and R.S. 29:112 contain no
# operative text.  Their Law.aspx pages publish only the exact terminal
# headings ``Article 4. [Reserved]`` and ``Article 12. [Reserved]``.  The
# generic reserved grammar deliberately recognizes only the established bare
# bracketed heading, so bind these different publisher forms to their retained
# official responses instead of broadening that grammar:
#
# * retained Law.aspx SHA-256:
#   0a94724d1aca9616319d05881afd3b8de0571ba4a432520da8087e002ac5b361
# * retained content CID:
#   bafkreiaksrze2gwksylddhifranp2o4n4blrxjfegjja3kaipyacvrntme
# * retained receipt SHA-256:
#   e093feb86f2994a22d01f67b53c37baf38ef9f74885ee48898fb2486110ccf2e
# * retained R.S. 29:112 Law.aspx SHA-256:
#   fb2fcdced228aa79f43e313316a4079051aa29b13cc2b5e6fea5f93788494a26
# * retained R.S. 29:112 receipt SHA-256:
#   8d37f160198f4851526c580ba1d187483f685b5cb6bf2522c79ac0489ef052be
# * retained R.S. 29:168 Law.aspx SHA-256:
#   b0051d7f20b1f81442984ca1c7ccf559af4bdfdbdf7d3b42bff47a8e475d0f6b
# * retained R.S. 29:168 receipt SHA-256:
#   02fe75d238b6547c2a897cd2373342a947619c0a8c712716000efccda6f97701
# * retained R.S. 29:169 Law.aspx SHA-256:
#   414b022825f804be4ac080704a2bf87085cf711aab45cc45d1d9ad54933bc0cb
# * retained R.S. 29:169 receipt SHA-256:
#   c4d35d418ccc7601f8072a9129046903adf2513071e716edadcfa3d550ab308c
# * retained R.S. 29:206 Law.aspx SHA-256:
#   48669337b481bc9f1fb9ca5d5847601789bd1bb35ea4c8df30cc980a9db09fac
# * retained R.S. 29:206 receipt SHA-256:
#   b04d589d846b63949767df60f6352a35cb386ce3a58ca156315d1acf683f1705
_EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=85324": {
        "content_sha256": (
            "0a94724d1aca9616319d05881afd3b8de0571ba4a432520da8087e002ac5b361"
        ),
        "content_cid": (
            "bafkreiaksrze2gwksylddhifranp2o4n4blrxjfegjja3kaipyacvrntme"
        ),
        "receipt_sha256": (
            "e093feb86f2994a22d01f67b53c37baf38ef9f74885ee48898fb2486110ccf2e"
        ),
        "receipt_cid": (
            "bafkreihasp7lq3zjssrc2apwpnj4g65phdxz65eil3sirgh3esdbcdgpfy"
        ),
        "label": "RS 29:104",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "85324",
        "form_action": "./Law.aspx?d=85324",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=85324",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {
            "name": "p",
            "attributes": {"align": "justify", "class": ["A0001"]},
        },
        "document_blocks": ["§104. Article 4. [Reserved]"],
        "document_text": "§104. Article 4. [Reserved]",
        "heading": "Article 4. [Reserved]",
        "disposition": "reserved_article",
    },
    "https://legis.la.gov/legis/Law.aspx?d=85333": {
        "content_sha256": (
            "fb2fcdced228aa79f43e313316a4079051aa29b13cc2b5e6fea5f93788494a26"
        ),
        "content_cid": (
            "bafkreih3f7g45urivj47iprrgmlkib4qkgvctmj4yk26n7vf7e3yqskkey"
        ),
        "receipt_sha256": (
            "8d37f160198f4851526c580ba1d187483f685b5cb6bf2522c79ac0489ef052be"
        ),
        "receipt_cid": (
            "bafkreieng7ywagmpjbive3cyboq5db2ih5ufwxfwx4ssfr42ybej54csxy"
        ),
        "label": "RS 29:112",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "85333",
        "form_action": "./Law.aspx?d=85333",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=85333",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {
            "name": "p",
            "attributes": {"align": "justify", "class": ["A0001"]},
        },
        "document_blocks": ["§112. Article 12. [Reserved]"],
        "document_text": "§112. Article 12. [Reserved]",
        "heading": "Article 12. [Reserved]",
        "disposition": "reserved_article",
    },
    "https://legis.la.gov/legis/Law.aspx?d=85397": {
        "content_sha256": (
            "b0051d7f20b1f81442984ca1c7ccf559af4bdfdbdf7d3b42bff47a8e475d0f6b"
        ),
        "content_cid": (
            "bafkreifqauox6ifr7akefgcmuhd4z5kzv5f57w67pu5ufp7upkheoxipnm"
        ),
        "receipt_sha256": (
            "02fe75d238b6547c2a897cd2373342a947619c0a8c712716000efccda6f97701"
        ),
        "receipt_cid": (
            "bafkreiac7z25eofwkr6cvcl42i3tgqvji5qzycumoetrmaao7tg2n6lxae"
        ),
        "label": "RS 29:168",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "85397",
        "form_action": "./Law.aspx?d=85397",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=85397",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {
            "name": "p",
            "attributes": {"align": "justify", "class": ["A0001"]},
        },
        "document_blocks": ["§168. Article 68. [Reserved]"],
        "document_text": "§168. Article 68. [Reserved]",
        "heading": "Article 68. [Reserved]",
        "disposition": "reserved_article",
    },
    "https://legis.la.gov/legis/Law.aspx?d=85398": {
        "content_sha256": (
            "414b022825f804be4ac080704a2bf87085cf711aab45cc45d1d9ad54933bc0cb"
        ),
        "content_cid": (
            "bafkreicbjmbcqjpyas7evqeaobfcx6dqqxhxcgvlixgeluozvvkjgo6azm"
        ),
        "receipt_sha256": (
            "c4d35d418ccc7601f8072a9129046903adf2513071e716edadcfa3d550ab308c"
        ),
        "receipt_cid": (
            "bafkreige2nouddgmoya7qbzkseuqi2idvxzfcmdr44lo3lopupkvbkzqrq"
        ),
        "label": "RS 29:169",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "85398",
        "form_action": "./Law.aspx?d=85398",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=85398",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {
            "name": "p",
            "attributes": {"align": "justify", "class": ["A0001"]},
        },
        "document_blocks": ["§169. Article 69. [Reserved]"],
        "document_text": "§169. Article 69. [Reserved]",
        "heading": "Article 69. [Reserved]",
        "disposition": "reserved_article",
    },
    "https://legis.la.gov/legis/Law.aspx?d=85440": {
        "content_sha256": (
            "48669337b481bc9f1fb9ca5d5847601789bd1bb35ea4c8df30cc980a9db09fac"
        ),
        "content_cid": (
            "bafkreicim2jtpnebxspr7ooklvmeoyaxrg6rxm26uten6mgmtafj3me7vq"
        ),
        "receipt_sha256": (
            "b04d589d846b63949767df60f6352a35cb386ce3a58ca156315d1acf683f1705"
        ),
        "receipt_cid": (
            "bafkreifqjvmj3bdlmokjoz67md3dkkrvzm4gzy5frsqvmmk5dlhwqpyxau"
        ),
        "label": "RS 29:206",
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": "85440",
        "form_action": "./Law.aspx?d=85440",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": "LawPrint.aspx?d=85440",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {
            "name": "p",
            "attributes": {"align": "justify", "class": ["A0001"]},
        },
        "document_blocks": ["§206. Article 106. [Reserved]"],
        "document_text": "§206. Article 106. [Reserved]",
        "heading": "Article 106. [Reserved]",
        "disposition": "reserved_article",
    },
}


def _article_reserved_source_contract(
    *,
    document_id: str,
    label: str,
    section: str,
    article: str,
    content_sha256: str,
    content_cid: str,
    receipt_sha256: str,
    receipt_cid: str,
) -> dict[str, object]:
    """Build the shared DOM contract without weakening its exact evidence."""

    document_text = f"§{section}. Article {article}. [Reserved]"
    return {
        "content_sha256": content_sha256,
        "content_cid": content_cid,
        "receipt_sha256": receipt_sha256,
        "receipt_cid": receipt_cid,
        "label": label,
        "label_class": ["title"],
        "label_style": "font-size:Large;",
        "document_id": document_id,
        "form_action": f"./Law.aspx?d={document_id}",
        "form_method": "post",
        "form_name": "aspnetForm",
        "print_href": f"LawPrint.aspx?d={document_id}",
        "print_target": "_blank",
        "print_title": "Printable Version",
        "previous_button": {
            "name": "ctl00$PageBody$ButtonPrevious",
            "title": "view previous",
            "type": "submit",
            "value": " < ",
        },
        "next_button": {
            "name": "ctl00$PageBody$ButtonNext",
            "title": "view next",
            "type": "submit",
            "value": " > ",
        },
        "document_element": {
            "name": "p",
            "attributes": {"align": "justify", "class": ["A0001"]},
        },
        "document_blocks": [document_text],
        "document_text": document_text,
        "heading": f"Article {article}. [Reserved]",
        "disposition": "reserved_article",
    }


# The v40 breadth-first acquisition retained these eight later Title 29 pages
# in the same 64-page batch that exposed R.S. 29:206.  Each page is an exact
# direct-200 official observation and publishes only the corresponding
# reserved-article marker.  Classify the entire retained batch together so a
# replay does not require eight more fail/restart cycles.
_ADDITIONAL_ARTICLE_RESERVED_EVIDENCE = (
    (
        "85450",
        "RS 29:213",
        "213",
        "113",
        "58439ddcb1071ae8d690975a0fd7d52780b2ea14206e8006cd7712473043b898",
        "bafkreicyioo5zmihdlunneexlih5pvjhqczoufban2aantlxcjdtaq5yta",
        "5fafc478b10f6f8a69c4f9fbb1dd63246ef6baf94d554abfba2e207e28c9799f",
        "bafkreic7v7chrmipn6fgtrhz7oy52yzen33lv6knkvfl7oroeb7crslzt4",
    ),
    (
        "85455",
        "RS 29:218",
        "218",
        "118",
        "369988e7ed5f47a6e7d18e031324fbe3d68b26079e792251989362d8d80f8cfd",
        "bafkreibwtgeop3k7i6topumoamjsj67d22fsmb46perfdgetmlmnqd4m7u",
        "3b28c345530656d06a303f7a86ef8645b763abdf8f2a5569c9e685c93b76529b",
        "bafkreib3fdbukuygk3igumb7pkdo7bsfw5r2xx4pfjkwtspgqxetw5sstm",
    ),
    (
        "85456",
        "RS 29:219",
        "219",
        "119",
        "452538d8c6a9e6f039f1debafb05e7ea959b4f3efa68303679a7b3aa8d1676aa",
        "bafkreicfeu4nrrvj43ydt4o6xl5qlz7kswnu6px2naydm6nhwovi2ftwvi",
        "3280553071ce50deba51612e6afb42927f42e46292649353066fe82b545e8f47",
        "bafkreibsqbkta4ookdpluulbfzvpwqusp5boiyusmsjvgbtp5avvixupi4",
    ),
    (
        "85460",
        "RS 29:222",
        "222",
        "122",
        "2a14a19e332edefcfb8b1db5cfc6a0dab51861ca264ca8cefc4bd4f2eba62ea8",
        "bafkreibkcsqz4mzo336pxcy5wxh4nig2wumgdsrgjsum57cl2tzoxjrova",
        "93915311ee0d9e4b4c611c319fabcd5ed8a16c825c5c0535fd2cd0c32e2a5992",
        "bafkreietsfjrd3qntzfuyyi4ggp2xtk63cqwzas4lqctl7jm2dbs4kszsi",
    ),
    (
        "85463",
        "RS 29:225",
        "225",
        "125",
        "a66d6909fc1d1f59c5ef981ec86b207f7cacc61b20de5ecf025c46d710730cf3",
        "bafkreifgnvuqt7a5d5m4l34yd3egwid7pswmmgza3zpm6as4i3lra4ym6m",
        "d57148faaf6259c97551e8eade857799cbe7fef8033b687ab34f72f4261be6df",
        "bafkreigvofepvl3clhexkupi5lpik54zzpt756adhnuhvm2pol2cmg7g34",
    ),
    (
        "85464",
        "RS 29:226",
        "226",
        "126",
        "3c4ceb609cd34368897046ba45bec53c86497bbc78c49eae0b9f8801fae895e7",
        "bafkreib4jtvwbhgtinuis4cgxjc35rj4qzexxpdyyspk4c47raa7v2ev44",
        "057d66439110bd572b7f511f08be83fdb02eaa86d85b58b9c209f56ab5bbe96d",
        "bafkreiafpvteheiqxvlsw72rd4el5a75waxkvbwylnmltqqj6vvllo7jnu",
    ),
    (
        "85465",
        "RS 29:227",
        "227",
        "127",
        "b0150be5dd40bfd0823fd8a3238498207b81cca90214a046b6b0c913b74a0270",
        "bafkreifqcuf6lxkax7iiep6yumryjgbapoa4zkiccsqennvqzej3osqcoa",
        "8750aa5843e82ed8c4eaae19300352a63c448ac4c6501a2b8ac004cdd029ed3b",
        "bafkreiehkcvfqq7if3mmj2vodeyaguvghrcivrggkancxcwaatg5akpnhm",
    ),
    (
        "85467",
        "RS 29:229",
        "229",
        "129",
        "89d4e56b2085a8bd9c36c8ccf0feed58f3445883a402723d02171039d1197af4",
        "bafkreiej2tswwiefvc6zynwiztyp53ky6ncfra5eajzd2aqxca45cgl26q",
        "8b86f4ae9ae3c508b9e022f8e265c461a7183c361f383c8443f8753892cbf51a",
        "bafkreielq32k5gxdyueltybc7drglrdbu4mdynq7ha6iiq7you4jfs7vdi",
    ),
)
_EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS.update(
    {
        f"https://legis.la.gov/legis/Law.aspx?d={document_id}": (
            _article_reserved_source_contract(
                document_id=document_id,
                label=label,
                section=section,
                article=article,
                content_sha256=content_sha256,
                content_cid=content_cid,
                receipt_sha256=receipt_sha256,
                receipt_cid=receipt_cid,
            )
        )
        for (
            document_id,
            label,
            section,
            article,
            content_sha256,
            content_cid,
            receipt_sha256,
            receipt_cid,
        ) in _ADDITIONAL_ARTICLE_RESERVED_EVIDENCE
    }
)

# The official Title 15 TOC identifies R.S. 15:171, R.S. 15:172, R.S. 15:177,
# and R.S. 15:184 as reserved locators, and the linked Law.aspx views publish
# a parenthesized reserved marker.  The generic reserved grammar deliberately
# accepts only the established bracketed form, so bind this different upstream
# form to each exact official representation:
#
# * retained Title 15 TOC POST SHA-256:
#   e75ee6f5532869887e1ddc94038887e707ecaf3028b83904f5b71e175cd62ef4
# * retained Law.aspx SHA-256:
#   2c64c27e8d8215238ef796742f26d0b9102445b9e687cf502e74886e436f36a0
# * live LawPrint.aspx SHA-256:
#   d949c0614682c893fbd47f34a33c6936ff828e5cbc2f7eecc0d534c6f7f91387
# * retained R.S. 15:172 Law.aspx SHA-256:
#   8f90e3d08af22e6b4b2c66b592222ad4b5b81f7088d5f822a6b133a71763cdb5
# * retained R.S. 15:177 Law.aspx SHA-256:
#   5db5797a53f7a0db4d3ca35ba2cddc3d2e94851ee30a30d4496fe836d5539d49
# * retained R.S. 15:184 Law.aspx SHA-256:
#   689c6da918708c70c91c9685549dc11c51ea2eb86d74c2c73e164446d1c3acdd
_EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS = {
    "https://legis.la.gov/legis/Law.aspx?d=78995": {
        "content_sha256": (
            "2c64c27e8d8215238ef796742f26d0b9102445b9e687cf502e74886e436f36a0"
        ),
        "label": "RS 15:171",
        "document_id": "78995",
        "form_action": "./Law.aspx?d=78995",
        "print_href": "LawPrint.aspx?d=78995",
        "document_text": "§171. (Reserved).",
        "heading": "(Reserved).",
        "disposition": "reserved_parenthesized",
    },
    "https://legis.la.gov/legis/Law.aspx?d=451967": {
        "content_sha256": (
            "8f90e3d08af22e6b4b2c66b592222ad4b5b81f7088d5f822a6b133a71763cdb5"
        ),
        "label": "RS 15:172",
        "document_id": "451967",
        "form_action": "./Law.aspx?d=451967",
        "print_href": "LawPrint.aspx?d=451967",
        "document_text": "§172. (Reserved).",
        "heading": "(Reserved).",
        "disposition": "reserved_parenthesized",
    },
    "https://legis.la.gov/legis/Law.aspx?d=451972": {
        "content_sha256": (
            "5db5797a53f7a0db4d3ca35ba2cddc3d2e94851ee30a30d4496fe836d5539d49"
        ),
        "label": "RS 15:177",
        "document_id": "451972",
        "form_action": "./Law.aspx?d=451972",
        "print_href": "LawPrint.aspx?d=451972",
        "document_text": "§177. (Reserved)",
        "heading": "(Reserved)",
        "disposition": "reserved_parenthesized",
    },
    "https://legis.la.gov/legis/Law.aspx?d=452049": {
        "content_sha256": (
            "689c6da918708c70c91c9685549dc11c51ea2eb86d74c2c73e164446d1c3acdd"
        ),
        "label": "RS 15:184",
        "document_id": "452049",
        "form_action": "./Law.aspx?d=452049",
        "print_href": "LawPrint.aspx?d=452049",
        "document_text": "§184. (Reserved)",
        "heading": "(Reserved)",
        "disposition": "reserved_parenthesized",
    },
}

# The official Title 14 TOC and both direct views agree that R.S. 14:32.9 was
# redesignated by an alphanumeric act subsection, ``§6A``.  The generic
# redesignation grammar intentionally does not infer terminal status from new
# suffix forms, so bind this observed form to the exact source representation:
#
# * retained Title 14 TOC POST SHA-256:
#   b07b28eac5ed027e914ffdb7755eae6579cfafe98e57610bb0cc3c5b6118a84d
# * retained/live Law.aspx SHA-256:
#   f2dd8993f7e28aaabc6d13755280451f71eade08e6744b63fc32036b1f3f7116
# * live LawPrint.aspx SHA-256:
#   3d6dd63558e7afc29c5c0978e174e06def0ed3420025ee9dd3607a7abcc5a547
#
# The immediately adjacent R.S. 14:32.9.1 locator has the same exact official
# disposition form:
#
# * retained/live Law.aspx SHA-256:
#   7b66e6db23cf965291206a00ccdb14e8f2493bda19adab60db7d17972c9ce1f8
# * live LawPrint.aspx SHA-256:
#   31bd460fe4fc5542f45d9dc0f94e874ff2a7a225bf6a8af6fe1c7011630a8c22
#
# The next Title 14 locator continues that same source-observed series:
#
# * retained/live Law.aspx SHA-256:
#   cf82c753e0ba0fa288fc1895b15efa2a15248e62e01f095a27e862c1c32208c1
# * live LawPrint.aspx SHA-256:
#   4fb5f6e9522d67e8633746b815d30debd28793bfd883219ddb0da58f8dc55ba8
_EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS = {
    "https://legis.la.gov/legis/Law.aspx?d=78416": {
        "content_sha256": (
            "f2dd8993f7e28aaabc6d13755280451f71eade08e6744b63fc32036b1f3f7116"
        ),
        "label": "RS 14:32.9",
        "document_id": "78416",
        "form_action": "./Law.aspx?d=78416",
        "print_href": "LawPrint.aspx?d=78416",
        "document_text": (
            "§32.9. Redesignated as R.S. 14:87.10 by Acts 2022, No. 545, §6A."
        ),
        "heading": (
            "Redesignated as R.S. 14:87.10 by Acts 2022, No. 545, §6A."
        ),
        "disposition": "redesignated_act_section_suffix",
    },
    "https://legis.la.gov/legis/Law.aspx?d=814013": {
        "content_sha256": (
            "7b66e6db23cf965291206a00ccdb14e8f2493bda19adab60db7d17972c9ce1f8"
        ),
        "label": "RS 14:32.9.1",
        "document_id": "814013",
        "form_action": "./Law.aspx?d=814013",
        "print_href": "LawPrint.aspx?d=814013",
        "document_text": (
            "§32.9.1. Redesignated as R.S. 14:87.11 by Acts 2022, No. 545, §6A."
        ),
        "heading": (
            "Redesignated as R.S. 14:87.11 by Acts 2022, No. 545, §6A."
        ),
        "disposition": "redesignated_act_section_suffix",
    },
    "https://legis.la.gov/legis/Law.aspx?d=451831": {
        "content_sha256": (
            "cf82c753e0ba0fa288fc1895b15efa2a15248e62e01f095a27e862c1c32208c1"
        ),
        "label": "RS 14:32.11",
        "document_id": "451831",
        "form_action": "./Law.aspx?d=451831",
        "print_href": "LawPrint.aspx?d=451831",
        "document_text": (
            "§32.11. Redesignated as R.S. 14:87.12 by Acts 2022, No. 545, §6A."
        ),
        "heading": (
            "Redesignated as R.S. 14:87.12 by Acts 2022, No. 545, §6A."
        ),
        "disposition": "redesignated_act_section_suffix",
    },
}
# The retained direct-only ledger contains 515 additional non-operative
# Law.aspx bodies whose editorial terminal forms deliberately remain outside
# the generic grammar.  Bind every exclusion to its canonical official URL,
# exact response SHA-256, and narrow disposition.  The source-bound classifier
# below additionally validates the actual body digest, ASP.NET controls,
# document DOM, section identity, and disposition semantics.
_CLUSTERED_TERMINAL_DISPOSITION_CODES = {
    "A": "redesignated_act_section_suffix",
    "B": "blank_range",
    "C": "blank_range_cross_reference",
    "E": "empty_official_locator",
    "F": "redesignated_effective_date",
    "H": "redesignated_hcr_2015",
    "N": "terminated",
    "R": "redesignated_range",
    "S": "redesignated_to_see_acts",
    "T": "title_heading",
    "X": "expired",
}
_EXACT_CLUSTERED_TERMINAL_LOCATORS = {
    f"https://legis.la.gov/legis/Law.aspx?d={document_id}": {
        "content_sha256": content_sha256,
        "disposition": _CLUSTERED_TERMINAL_DISPOSITION_CODES[code],
    }
    for document_id, content_sha256, code in (
        line.split()
        for line in """\
89434 b5119493a5306ab0cddb7e5831218d49414b0985a0b70266544c15dc760f0547 N
89449 43c489f86b00edeafdaba2d3f05961e6c3880e9e4056477a5729ebe9335b7916 S
89473 65ca381a4c15d09cbd43363ef84a70ce2e0a3e1cdd6644b7b6f2f8aeb4913aae S
89487 4e5a6b0347a1a125e0a0dfddef7faf2d53baf0d2dcd7b3211580d4d7ff8c2546 S
89488 64f6f12528bcb920ba03f4117a37f010d73967de1b013e1b069ac841ad2537b6 S
89489 d08b6d1aad4ef92df2a14f64129a854c7a7c18c3206afdefebbcc2db67a0e4ba S
89490 f0610ebdc97629190f1f10d4c0fe1873ccf9b8222e37bc95cb6421af1b2ba31a S
89491 7eb1b278b2d6f1f3ebd0abf9d408fdeb718b16f5f330218d0fbe8dd930eafeb4 S
89492 8b7f2cc73d996f7c744683ccd31603767ad45bebf328ea5313ea6fdd0aebec1d S
89493 360e4381e47fd214195440b29819a0f098ffd678204ead1b224622f56af7ffb1 S
89494 661931c9a08bb06f747a56f5fc2e32774b3f0c6da99b8c89b7d093babca89715 S
89495 8431665003e4caa52ecc6272153bc8ff02c9789e10bd6a3e53e1d96db8f5b624 S
89497 4be7bce69ac8a3f765d697cd1e90c99852b5f767964d884086bcb3ebfc2f6f9b S
89543 cddb7fe7b8b753aa307bb63fb87d0f4a74417d2f25bb086609001997886bcd18 S
89558 c8fbcd4b118a4b8d683965a950549aa44e97284902254b699b6f0f2a761245e6 S
89559 0ad8e904b0f2653ed79fda6225182b11e971ff6b16f111d48844b7e83c1eb755 S
89560 846ce81ce0bcf903cbcb8a0ede54ea2e8b28ab4c343857e2a3f245f45f430f31 S
89561 e7a8ab444536d7fce85b873d4c80eca2e609e358f6dcbdc93ccaf64e2d227476 S
89562 e5adda5a6f125b3f6c685809ee4a3d78310da855b9e368c9329147bc8370545e S
89563 d313a29e428da27a87e81c7a794ec89c4b25fc2e21afa6386c695642ef7c646f S
89564 05a5919910181bed2277d28043ec7255bf065465fafbd60609b9ee579629abd7 S
89565 f9681f714072d3013a481aecd89abb62fdc0d07926027a10d03a1621d1e10f01 S
89566 61362aea74d131af4f5a870fa902cb78b9bafe74633f00edbd293f4c642dc8d3 S
89568 67bcd1c5e7dce0ba6132a2088103db8137d584c3c9ad2394935c0bd58a77577e C
89571 3918d9bb966505108df724f692da97f902d9cdb463eff90f9d69d08d23da76fb C
91317 7d85c21ad0de24c1024a344b544ef4bcf6c47b8118f12339db170dd9e8b319b7 R
91375 75b3a08197306984d59d08a86c99a3f75ff95e6178ab8ffb972b1b2ef4d873f6 R
92686 037c8dfc01b287bc5b5bc6159f4f9b0ab06c91d32c2e0d1647012807549f4a08 T
96334 0c671d5ffa22b0489b25218e9b08e967fe746ebf074140b6afebe94ace38b2d6 N
96602 0c1bfc6c593737bbf1a9d62f3f4212839bcca18b62ddcd870f37de91b4d64d47 C
96982 ac35043ffaed8ad18878ff299b89a331ed3a48d57c1abef93d0ec38141de4fc0 E
96983 af93f7734c3d10cdd09ba720babf873b8c927fa72e0079790c13bd53ce30dd2c E
96984 62208f630a8ada82650c920562306f17758f7158fbdf22eb8923998f54424eaa E
96985 ce25437dc21a30d9aa943e1bf51edf68c4c9c1235c6a00079eeeabc44d905bfd E
96987 087dd94f0b8218c3903894d6bcb56e67b654b5690c8a79013e296ceccd36d1e9 E
96996 43fb29ad4ca5b963c7b0f12ff65cf6341ba3b65e6a25b5b76fcb0f97e82ba206 B
97004 8a0d8e60c5b24a415f752dcb1010b7b6543c4a9664784b927a3b2df7b5aba9b2 B
97177 58605df76bb0a428c967d4cc7c4c231684393867c17305c3c1e2c832e1d378b3 N
97178 8c908a5ac491938e5c70cc00bd9ff73fb39ba63d32f06556ea7c1e7574e251d2 N
97221 344c49f7340752f321dd4d1d5e88f762617a9d25b1f0b2cd3933ba81527f1d94 N
97222 78cf27016a44974e856e1cc36bcd99571a136cd6b5326924d1822ffe3af95b31 N
97223 1c4de23761bc6ed7e26eb9a8591be3337149b6a0290f05132812c23272464367 N
97224 4f7e0a7507a9fb40b101e89ede562150a110709415dbad4bb4511fd6a2b2d2c8 N
97225 26c6c3992f22dbb54d93b21894828685d5bf4c5197a8672732b7a3c75463991d N
97226 aa67364ec70926bdb06212ffb305ca4595daad6fc3bda6c1b6c6b42913da75f5 N
97906 4b3940d7db633d8d7eb76ae21b7d8cf01bbafa311702b6e3f0b9cf6d56c02404 B
98215 3d49b0385ad5685ef87a71abbd5e94b809bd93a1f6e754ac930d076b0ed8f687 R
99487 6ec5ff4b928786d6d4b3e4f8c2e4ccae200d3aa3985dbfe6d2cf20ae0c45eb27 A
99637 a07548206eeae5de21e8de9ae606a9decdee5a8c87567c24f59c8cc225ef939d F
101665 0909890605fcc449a8ade91590199e61585dd4fb9d3151d8f6067ec58c6f8a2c X
101676 794232afaad0728a8a28c58658a365c4b875c0d31a031d0f8de51651fe36a898 B
102088 6d15efc997ccbc540e9f610d3b307513749425139d923c9b7c62af15bba35cd9 N
102806 bd5bc0c12a88e2f9fa0b71726bb7610812adbbf718a296ab64c7c3f127538274 A
102807 aaf6875601fbebbc60272b85b9acd306f2bb7a52b8cf8bf6409ced4af704cb61 A
102808 4055b50837c959023806a8501944e32f0000a688c88f88f8ada0947dacb8a127 A
102809 3905b0c5c80074f381bf5743a5dd220fd557331d25c1ddcb9ee5503a7a450130 A
103912 f789223bb306832b096c781b31fe77862fabf3414cd07b7f598b655602d8a146 X
104899 49020943b0fb9d4b0e10b6251ac8243065cfb40015bd7b679ed61059fcd58fa6 R
105521 8c04a68da9f9eba549ebfd34b5b646f521ddb3b22f24907754714c6f1b221a10 R
207379 c30c7973faca3b75170ff0253efc8ce0540a5fa214e852ec1d61d396cfc37aed A
321474 e09411ac36ed7daa60f62aaf9a6087f6c52d8980bd327ba9a8101a2681ce7345 F
321475 c69ff5cfe730be5b66652155db32b93b7e2cc6988ceadf975f911acfaedcbc8f F
321476 c5ef6155442008893df8698f88ae930f91ddb6a9b62a90a22157027e6fa6ae4d F
321477 7e4ae1e5ac08b804b1ea648d2a579acdc7cfe2430c1a38a292382a232d8b93ab F
321478 add60f5ddc8efd5513fe2b71b54d130eed51d1aebc43fa32b9378da33cd48957 F
321480 4b0e8176433c2b9e4183b358dad7393523f3abc34844de3af4985edfa748c408 F
321481 96b784bffdcf2860a72e45621d6cfc1ad578a70f9e62062b830087c2d7715a69 F
321482 326c4fb6fa84b8da85ace4da6d0f92987e4b069c85c3038d33266b656ab9b10b F
321483 1931287f3fad2e304eb4ab5ab4c1355c544338f966a8c8973407ecdf9ad1ff55 F
330459 9443ec02da09c62f583e00582a42f3add917eb106364cb241dfc0a839f57588a N
452602 78a85b296834228775761ae233d494505870f82d7c477cc686e8202f294d6ec3 S
452818 a827fd13faa8392699eee05a26f5485aa904ad19aaaf8456d41e3ae0120baa64 F
727753 1dca0ef2becee087552f0c995a833fdba7d6049702a64e9d5073bb2031b6c5e8 A
861031 0458840c37a693f706149a7072f700c4a90d2a3afc725039e8bdde0831547241 A
920770 8537fbb775aa5a5f690f5bd1bc5c8ba36ed0cacd51b14c4de36aefffba1e6648 H
921412 2e4f14d95399d54de575a4c4aab561b819f0c6dc38ce6bc79c28438f35108719 S
923358 035523b60287de4c0616f416d26cbf3990b6aa91247b1d68110cc84a91a32581 F
965001 9a9b981fc432c837cd397f2e6c456bc3138a2a071622aac5ff281771ee854ea4 A
965002 8db0c0cf178fa1870a8d6d33956f95b857c239a497c6bf4695b10e8cab6149b6 A
965047 a4089a1b0e3fe76d9cb7cef8ef2bff64c9bdc19272eac62f777e1c0cc7aa3b78 A
965048 f2d9f7f794a4d4c0f7739d138df54f4d9b4125381f036ab563d546bff0d1133f A
965049 769e4803815a4810e5221f89303638281f624c2cef79aca6edf0f1b75a1cb6dd A
965146 53ef0433f7ee4a4a3167f32d48104dd6e90bb1d576004bedcce2100e5d088229 A
965968 287361d8354b02f74396955c70b0dfbdf743beff977807d5d80721e7b43c6f8d H
965970 17b819a98b12c229934f91a6cd6e2487989ebdb227f0d40edfcccce683e6426d H
965971 fd99fa024bc47853238a132e48472a3d221bb392d15827fb4a052d33b225be30 H
965972 74aae4e83557c9325af78ae23116e10e61b864f462a55d553426a35c9cb96cfb H
965973 dc3038985ed866a95d98b2fd6c0bcb4abf85d1dee75c50e1ad776650d0a0de3b H
965974 555a51c4a3c312b3f1f829ab49547c39f2c48803fe7371f0ae777d475a30b242 H
965975 3071d3559614e790ad41cb348f044eebf3790077343a49ce41ade01a8ebc62cc H
965977 c45226715963e51f2b56920c41a273fd6582276b51d4a4bfdccbe885ce136517 H
965978 854f653217a145fe871c3ca8240af67910698804c6c3baca3d2a02dd4f4f20f1 H
965979 bde5c4637eb1c9356e4f5a9632c6cc156f61416491efa396735d60bc81160692 H
965980 28265ca826eb22fbd2fa4963c8628b8da3c7e93688cf08c3bb298519d06bf075 H
965981 ced515f5299f7672626e357eea50fc114c17d02040466a259319dc7e1467edf0 H
965982 f0715c704de799a2ce3eba5be231f9a6b3a84a93a7cc02e2b43f0d5ec021dc7c H
965990 6d2edb2be72b1e2870c9a5e3db5c41ff428f8b720e8e77fe3c400c86d70c6977 H
965991 e5911f71275c0dfc726f5d91a2bff7e2e9c242a844d90b2a1312d08eccd1f0dc H
965992 a313ee124dfdd38fb287685ef3f8a6d27e24493002a717beb67ab7c7ea5c4596 H
965993 7345b79c2b7ba0d96137ec747676d4dfcf373848527e0507366362a650995bb7 H
965995 57147c29ae64d0d4937834b59d733d36928a3bafd64137b5900322c02e31c411 H
965996 1afc7b5c26c74446ee8484d5359192043011d1aadf5bade0852b6bf8889c19e7 H
965997 316b3227e2fbbc3a1fb0ef623fe7e252fe61e6e683441783a3a2e37fb7c35ecf H
965998 f9348fdec87156068077c96ea78a83576b2fb7f62d2958affe3dc242bae77a6e H
966000 ff4db2fb282b481f792d15536ffb68fadc7328452a0982d69d00a1b7f38f2d3a H
966001 b91bdebd86a568fe49e6c7f9f418e133af0c905f5f99df90aeecee857860a82e H
966002 7c8e1e0277b56e9c3608823ab8fbe871cf5c343fc60757e9f013665771995d7b H
966003 8f267b809045fe2f1ccced8cf3e4cb940f5573565b4460dce3c0f372504f8d81 H
966004 bb01b021a49c87ccbeb8960156b30bd140476869c40def6018d731f44db86985 H
966005 8961dffaf102f24945f4d42cfb88925c4ad825528aaed9dd320ddebd78919ba5 H
966006 c13eba3631a9ddf7e7ca80cbd307300027c6b859105ab487f2be2fa5621208c5 H
966007 91ef2ea61c4d42fa644058efacc96e0d941a6929c5f217694de3b09b94afda2d H
966008 09aad4840b20aea199853b13f027a2035b296420c735e21ceea2080afde84a71 H
966009 26d75a9bcc9ae8cce9b497caaae3b2f5beb51d115c97954de5247413fdf9ad0b H
966010 22db2be815168ab8dcc9d76ee296a93db0d84e4310b80c9746c45e8164d666a8 H
966011 6bc046e1dc8169e0e3750c468afaa86ac8d48b2444d8fd22ab4dc21efb4e4b8a H
966012 60688d1bd71b9e7a1a1fe1ebece3a84a898df0fba645a961720da0889cf75691 H
966013 07d3312532ba7e921f90028057ffc351eb64876a8600d65f1c7d977e6d3c927c H
966014 690011f94fa68002276b5ce3419c73fe546f480ed98c65937f95bcee6fb12f46 H
966015 714b02e083fe128a06dbafe6b61c3f9381f29e54d6ac589c755799bf673393c3 H
966016 39176019f472cb9a8c43b9827c888966f4ed01f90f40c20ee62965eb24a242d8 H
966017 563ff57e439d3f0204429a773788029eb4813220e5a1531750d3b1a2656e73a3 H
966018 9799ea85f9b997b41fb176fe734e79fd358515ca688523d41760c41b5250ca5e H
966019 cdad2651ffa6eb9c3159d892795d87012331c9d7709477e1e6454c98ce1c72b9 H
966020 fba7119feca1d2324bd1d3994b4f27159551d908bcdc436b3c586d15f8def296 H
966021 489feff11276941a49bce2b9c0933f22b2e1664e70f55c946303362c4f5c1834 H
966022 4b4b7595ffcaa749eed87e27b52feb3f43e8f70c76034fc891c37a2c9f6e46b9 H
966023 1f443a9f8ce8cd42f1104fabc83797f45e3f4c0f1c8252868635e1b25b8f910b H
966024 a5e8346170fc85495cd9f9fc546c8f5f673cb73c5eb0f7fa7819333a759bf452 H
966025 405f79dbd116b180739d8ae4641329ea7fbf1d8f26f0fbe39c5dc27bdd881286 H
966026 e174c8144275a8b13553d84597da5762a936b079ab4b55366adf09af4b867027 H
966027 812727ed4100a583bea5781eb31634bef38dd9634e48b22e80209e85932386ca H
966028 66aeb7ba574afd2705939dfcc274fb6bd7dce8a237cb6d5b700c4514cedaec06 H
966029 566503a8d65a1fb66a1c7897eef7e464114cc3b365b94862ea3bec17092f01e7 H
966030 e0f4c5a6940a9ddb35be1a0d3745747fd841c8cfa29b5014152cd26d15e4a422 H
966031 46f9da465e1979a87fb66a1d8526659d72edf4fc924974e92cfb022bc57160b4 H
966032 e03f4a7744d9deaca26252da877b1d6aaac57d6986bcc7c21fa2dc673a22ab58 H
966034 883f0d2b100020a0799686e2760ef3dd3b8dbf2f1aee623563020aa9b8478b20 H
966035 80ae8b5daa07042a3d1de769a1db67abc5978d69c223b5a6d23e50487ae44305 H
966036 6c383ee60639828aedcee0fd4bbb4495a81eea0f823c19e9ed583e39e6422b55 H
966037 8344fe32a8685b6d8c555f00a4f9318bc40fd7fd40c8cda115718324c341121e H
966038 d18774437856e1488d467e2b92e2e9bf49fbb5a3734bd1570f6e2b171cc051c5 H
966039 5ebbcaa92b11562e85c2fe66984c180ef2abc23432571d0d6e55cbae46c896d9 H
966040 261113692bfbbd83ca03e5d01815a63cd26d4def6fb8861e5a179c8ed95c8862 H
966041 99c768c33ef5b652276a57c80e86957d9afb4ab16023187dcb9b32e684af1135 H
966042 7a967f162bf005d226b36c0033000af58420ae3c65d1eb49e0bfa1a268c8dcfb H
966043 4f76566ccae9965dca3ec4a26724ac91cc45634766b27822c4141b120041f920 H
966044 43944d3a5ed1fe6d096d509d1e7afa8539300ec4ced68e2e7a360f12ccc4fb3d H
966045 af9d3930439588f10c45b2f7bf54b63212259add2f212374e28fd5ba7aa28415 H
966046 aa63e765089ee6dc3697f074b9cacc73b65bcf7c14e790944053309e511a77f9 H
966047 e947a28b9b9cc62c0a450b808f32db41b5eba39e2cc4c5743e68f84f4bb26cd2 H
966048 a3993dabd0b0840dbb8374336b8dfc26b60b2e96d8c0e5f2de1480c75b9ada71 H
966049 ed990272112d7aeb4320e0328851fbff499fd1f76bca46ecf002ce6c13e3d998 H
966050 eb69e20ac93cc5b79e4523b52dd203ff5895499621e9bc012572a0f3d998daee H
966051 68c360679d21cf39dbae1216d88f0486e53c1490493dcc8b0dd9d8c579c1e133 H
966052 3288ac039ab9b59891b9f6bde36ae3ab8c90319fffee8f146204d5b9e6916db8 H
966053 1e1f5712d8721b92ce8129fb756cdb8cd5c49f9ef66861187c25f9209c24c188 H
966054 6d2bef6ad25c64eaa0b73f50117ac24dbf79c0d8c995a665e75423bf5839c886 H
966055 92ad50c7dd19b39ecf7591169fce17110ced6d45c1ef6ed09474ffba11a89cc5 H
966056 05ac3a94eb38c315a1ddf7a4a118603a276c647298e90e0c23406969f3c7f801 H
966057 89e8f5204ac8c4f713f31d42fe1c24a379c306dea325c0eb6ec79baaca92616a H
966059 89ab2eb93f979adaad93a20c7740299a88a42a6e71d21f9b6b53108cd0b631ea H
966060 8abbd7a40ca19d09f53cdbcd277c2b4d01622b37c505ea5848ad083166234e01 H
966061 06944df950728abbc32913bb144cc9f0fcf192480fce7e7dba8b6461ac4241f5 H
966063 d5b4e550c53a667e6c92b3d251d753e5adaa857a9000ac4348ef4438bb34840a H
966064 dbad3dc2c95b57e5200eb53559fe43bebae5867e4fc8135cc60e12b3daf4ffed H
966065 248a535c29dbbb2c8618b4c52cc15593e024f57379ac7dae0657daa3807a1742 H
966066 8bc03352cfd4f34f3d0f634e02d30e5a563ed65d6a32a1c31b380f13df5a0a88 H
966067 da189378ec6f9a0d9512f538bbe99d0ea9a6660db06a819ed5b9629cd6a956d3 H
966068 396db17beec7d83b7ee0b465cca95f389dedd4f4b83cd2005e851bf3989ab0ac H
966069 b074f97e14ae2c65ef83eb2261ba9fd60fb7c7b2257be6c246b7831c281b629f H
966070 20f665f656645e2a9420412a7df680d8a858585edb32663022ad0299fe112352 H
966071 25d8d3184e6f5fe813110547f1b101f77e6026ebb051908c478c174d30c3e981 H
966072 3ee96c9790422776a32b2d9098883123ee231b89a80bca11f4755b5eacaacbe6 H
966073 4521c4b2c33b70047ada35aa910d035b9f38bfba3332a5ebe5386bcd9a190eaf H
966074 41ff01b6f37dff265dbe9b1e83a25325cccf44a78d7824fb17bcec466728167a H
966075 cdbc7fbc37fb2357ffc71eb6aadba12425aaff18fbcac3c07eb2a2b5568abadc H
966076 573b47b990ef5dbc11b244417926ddaaaccb3e58e442f977df12fa2ab8217d44 H
966077 daf21323b76aed410a0b5fe9de99d9020745639296aba31bb77afe0987e9ddd3 H
966078 4d778c23cf548cc972fdfac43e54bacd9fcfb3a049016fab2c0a299643f38f56 H
966079 57f2875afd92eed747ca91e449ce33c8a4765b023def2c8f37a6784a2a83df0a H
966080 6746eb800fd23f61bb4494214988520dfb818e1d96eb0c6f888eb98a50ed63d0 H
966081 13b59f31739f573b582b1bcb88eef8618cd8a49b2ecbd2f02ea34e35b9a1b53f H
966082 47aabd0a66c13c0f374d8f13b2d75113d4b0c6db76c3f78780a0ad4a79d17bed H
966083 2c41a9df02e6246469ec44194b337e6811a1645d5acbf49f090230002f6dc981 H
966084 888b952b73cbe4acf226d900a89178b2c15584deb7f17d18f709bb3b11303234 H
966085 5afec8ecc3233ea955f33063ef5c6674d90b4163f63a39a4feead7dea0f46a9e H
966086 47b85104fb80352aef0cfaabbc520c09c9c3106568e0ddef3831e040b3b0e5dd H
966087 de30d43446feabcb6c1121cca33fae9ec57e7e64e385d4dc1279d8c4d3d2df38 H
966088 1c9dc60cf011eaa06efd17de1eb7858c7c05a9d620bdeb427269136944b45221 H
966089 82073e31da3a59fa6d12650306e42d754493cb79e05d32039f9701b4cb440f1b H
966090 d17a80fc3fdce0d3c5f151888e97745abb69fb47fdc0da29570f082f9b7d9673 H
966091 369c185a63b62d577162f8dccb0bc93377ca803ca5aaf665766ab25dce2fc1b4 H
966092 c33a61d59ee5c65c070d1723dbd2b8512618e2a7816f15c7788159c1affe2ab2 H
966093 1afdbdd8436f2a3033eb30c426a4f738dc60d4fa3fbd76403ffbd8e26ea15cd6 H
966094 379d5f0deb7ccfb3bb2ca34d8d5fcdfd713f1181c6b04d2f04894068822c2a32 H
966095 545c8cbc1bb4cad41249d80be0e6fba26814dc0c12f9800b6593e6178dc0fe1f H
966096 4b09a5034f20a32ee0e9b29b335f0a167a42ba3ef8de15735848cfe65001bdac H
966097 5c0ada9a7a4b3b643a85b13c8235fa54533be4e3a9361cf57dca86b1e5fba35f H
966098 4ef81f557880c9fa6e15cfbaa0ef01d15e838135b65ea7a4e4fb0ecd6a110530 H
966099 f8007118607319ee1f7e308e2350547a746700cefd322d9ac815092baace4221 H
966100 3a51f9c0b673afbdf7a7c502d7327ac795e4c67eed099824c8dafaaa617cda37 H
966101 2ef621d0811d34a8df03ee6d6048a5dbd1be35c9b3795a4bec61b4eccccf578b H
966102 a79dc8f12002ddfb1b6d73d6501a05a5c0727be1f68d4a89c32772657e8d4574 H
966103 1ed73e5e6a7d15f40802ac999ce7db76c5bbc2513cca1d671d00d7356a4dcbef H
966104 f30fe1464c909bd855fc5f28067f125a97b06da8c510d91deea71191fcea6841 H
966105 ae05be16a02d94f695501ad74876f2690d656a801a115efd596e9178645d054f H
966106 d901d108ad2c1af320a30da1b38c2e9131b4122376709ad045cc0d0c2d389899 H
966107 8306a2bc383c20cf257c4dcd69894ed2e12ba1c1d09424587410838dfa12c3ae H
966108 f2342d194f85f4109a549c22bf41bf400f49dcb14bb3ce07e65af487d108bd34 H
966109 87ee3b4a745ba6a3c340271ac51e55f3744eebde19264acfc234d852c18a1759 H
966110 49a6d275526c90f3776d068f98bca7023aea593c4034599dd48ac93885c7eabd H
966111 3c67263df91fb9c43248735034b38bad52900624b1199d0ea3ac4418a6988a22 H
966112 ee8d80a29f1a7d3b8cb07374e8846b6bb1198f9b7f7e29056cfc6be4d527ab14 H
966113 ec7e9e10e08182d06b8e76270f0b5706e9e4869b036ca968261174876173d32f H
966114 5cf4edee4166b7969e3f0def8b3cc44c00b397d502d9e3877cdf33e9dd4e0127 H
966115 51aed8846f1a82845127ed30a3a6271700b4bea46d712235f06757fab9d59f9c H
966116 6ccf4a97a948c807dfa607d78d94fcb1b799b5cd14a749d233c6857e5c25197a H
966117 9c437e774890a951063f9aeefd02300fb258e8c47dd54db12d9fed4c4a9ae8ba H
966118 22c873f843b20c74fd85952d2bbb40daaf9664fc2d31dd4c1155d17f79a06d87 H
966119 db8511c100542cd758e14ff4444bb349da5947278bde6b7f10e198d5371650f9 H
966121 7b0a5c8d9937a006f9e2e5f7efa8cd81fb241cd0d9148cbd5dca2adc803cbec2 H
966122 28fb298c59606315e7fb85a34c247a6e0d0425de825ff5f0da3f5213883f5e06 H
966123 2e25b31fe62b436c80e38e106b6afbae9e79611429b7eee75b5daf7973fe24f3 H
966124 47d9316262e23b8978982e98c59e641da0b6e716e16a53f7c7c7153e4113a8b6 H
966125 3980265dc07f0aaa40e4439d1b8062e13666ceddde411715a65ddf76e0bda255 H
966127 d6c534b5195cfb42218ba0626ca48b5bca9a18d8e6f967c4e55bc5a1d4a11dee H
966128 1b7e987f5b3ac0cfd6cbf1e15a0906677f2db35d7e9be68f4d68168fafd32c57 H
966129 fc1a14283e7213798865ceb166c746b155b726997e2c559c4ed5611ecc909451 H
966130 0c566b4ce6f134e9f442e0b3d7e24ebface2a8430d6e88c7339ce54cde7b2e8b H
966131 4c296a3d702936776efa1515e4f6eb0db0b29cd13a2761358f0fe58b4f845bb0 H
966132 7663fa07f530d53814c808e87d11dceada98d731bd8ac245362488ed3d7a5920 H
966133 84527b8b56ae6a240f880d7e40da4f9346df46a969ba563c22234bd6f0ed8117 H
966134 11f6af1d77b30221c998ef622af8cb47a1c5834c3cc95be930c35d4dd10ae400 H
966135 536c32cf7a4e788a4621159dd306ed0a1ee1edaaaac553e993e64993e0b764b5 H
966136 0a2a9403e159ba64debc281a31faeacf1264ccd12224e4292173607b6133bd26 H
966137 b29050ce2fc0a6119fcf619185cb8e2d6a04e99d3035a67c3f45786d7a36d884 H
966138 99fe34606ad497af3d23c178d3113d3dd429cc63559d4ceca58f8304b18da04e H
966139 bffbb03097c2f4c51bcb5629033ea1148605d5b0aa09b13ae65ca374d341a202 H
966140 0108345d118037f017d82b34da382f023e11c02c2de7f26d420375d0e80ba8aa H
966141 819a942cefb7f74d783c596ecb4852af1a2f249a1e191ee4677fb7eaf33d7f13 H
966142 63c608c00e620bc8ef06d8c7e7d9f0be3bc04994c89decf6a71aee1b48224bc4 H
966143 b1e915751d3b878ba1c758bc6b9815a7c06027c4368054bef7b834a766c843ef H
966144 a934c98196d0ee5730dcd159581c3294ace731f8a886206b3bda19d5bf16a23c H
966145 6d401276d786b5964f59f153e3a728eb431904079b00a48b67217ee3d16a28d0 H
966146 ccec493ab764c29e2c8ea151329169de179ad2695940750ef39830a05fe19ffa H
966147 e41840aece9c4cffba8a599457b7a0cc512556d8556340995ef8dd585a996720 H
966148 b6c9f0bc4973295e6945e752ed7e1858e48c802cf1a31f016a6b7e60006233ed H
966149 0d62e57a5918d7352e83926d7b0b37ba45573355240ed1e14f3b279f2cdfc117 H
966150 1f9a1c509fed742757c303b75badf3fba07b71bba4d3eddda7a263f3005adeec H
966151 0cf86272d50ccf3221e9cbe167903a0466a0660a750cf7fd18a16e624cd8d5d6 H
966152 54d2e8deb8f16948e15b396e5db1e6f5317f5e69414d71ac46c0981baf57f4f0 H
966153 d96f810cb2ace401acb87d1cc72e85f924a1b13db48b2ea3f56fb6c02ec42be7 H
966154 3e8173774a56c801644f52520e9b24a7ecf7391bd26baebcf41e847b0d0121be H
966155 89e26b25b7cfb3ba6275d945b53fd2ded7b2968fab1b8f916d1d777254ac7194 H
966156 b4e3e5c0fa0282e8062455752df56accec95b4ab4dd10a837547a1c23d4c6f3f H
966157 401cbab37d78e4d2468f19b258128a25202388e6f190abe920400e76d660d68c H
966158 65a0632a77038e54a2c030d294db9e38c010152e12e3bb34e94445c47ba13bdb H
966159 74693758c485ef417dc2b5b9d2f2a64824b0894bed1622090771f56cd6fd3dfc H
966160 8b4a3ab927e13c7ee9ba6561b3a648ef1a99efa39baedbeeddd0d664bbc24b95 H
966161 76aff198465953292cdb18ee7c3b8d45a50c40b43596dd5baaca254f35dfa21f H
966162 59f4ccd6169ad8a42bacb28be8e0020e29df99c591bb5c0cb910c82f68307010 H
966163 ca31a8a2957ccbbc670494a5ba3a684f69564d82d6a5284efe2553680ab3207b H
966164 b87a569f98c55ae9173dcbdc7d5c8767f0e8adc814e1481564537e076b501e34 H
966165 ec20ace87b1b9af6626e1ca810141a5226a046a65422e6c9947c4d3b5ca2460e H
966166 e63935c27e62dc15feb4ab5c3bd9252beef5564994d0b6d32ee07445e1f9b4b5 H
966167 c3707744e4c79d1a450f67f379ddad58a0f19d7a58eee6a41584c0671d992dca H
966168 3a1781b5c8092a5baf50b3a0c99ff84b15d919f0145e07ce69a96c1e219eab46 H
966169 5840a1adfdaef776fe1b3a92fad7e02653f73b1ba56b4f399a5110c38852577f H
966170 92413e1e4618e864475f9932103e146e5f08d2a2c54d31c35806596448c7719e H
966171 2310466303a333fb0c6f8f836dc6b557c41156cf86e55c2eb8b712edc3dd1f64 H
966172 84bb21d935211867999e8285695604ea9bab2694755c41d36808dd0d9f9161c0 H
966173 7d9a8a983a2aee8c638449b853eb0a85a79b77d52efc8025b865baf47e9596b3 H
966174 d577d1f971aafe3a6314c1222e6777d53bddeb4762f30a14475f04d9a53d5695 H
966175 e67e1d29395b4a6ab777ffd5d6ec44efe6113bb524a3708a0b9079eff36cd2d7 H
966176 0ed27e4405712571ec348d09af72def1f501bac637bc74c90adbaf0d2baf6ac5 H
966177 3546c52a79451cff074956cdad8acd31f88ba24bc36416cc311e436ad000ab53 H
966184 d0c53c224ca462a4a6759b4501720734203ccd02143c2aa387f069affdd70e06 H
966185 da969ae81651b929f65bafe080712c0b97e8d6f4327585eaaf8358cf6a30cd85 H
966186 583847773be901856090fe7a15a91a2a041abf5e46946d5f67339c00fea5dfcb H
966187 138f5d450d3663a9709818de7bf9c24a607f430d214bd817b4b0dca119dc5dd2 H
966188 93c822df466b5b8ba52b756c61e52b76447e4ac2a3351d5d5f8cc284feace402 H
966189 c84e067b9bd31fe3b3ac837170ee5991f2bc2380ba9457f6a25cbb280ed4e20b H
966190 955bb7a1dfd0c6e8c69133765e015b4982bcaaf449192eb2bb8aa7b0bb1ba8cb H
966191 8f132fb287d93c04f318d7b666bd48aec6354b01d4a1e2951f80fda512184313 H
966192 c5841dd19633b2f9d7b0b43e593f40396a85833e0113608d639811f3da2313fe H
966193 1ed43b66d23729d0fde47968180b132e0857a36467d178d6d7c692a8edeb568e H
966194 f2686fe60e26072d7c68f8b4a16241631308d96fa8e8623a4bd3e91b1e4ada4d H
966195 91dd0815a3621559f1b2ab60b112155c6b5f375bedc6e70dc1563967dd1b5812 H
966196 d7d664cb9d51c20a200463712b563e7965bd94aeeda42c20c5f6ad792b7903ea H
966197 b2dd1fd65bcc319380318c28d9d9d273f259c0b7c4b7694ad79e6bcb66ed04dc H
966198 89e34496253a8e629afcdf3a0fd6bda19ff18fed0ac79327b2c8b4c055a45cc8 H
966199 d8d9fdc4e2ca3be79da28673fb9dcc91f2d60c3ae528c28a45b4e4d54586332b H
966200 f5f57e1f09d11991039a0617b585168544a56e7abd04d852ee72edfe526ce0c2 H
966201 33f9e4b0cf9fe7e9b488ba4d61a34ae11c20ca6d7cdfa51b8e6fe32dbb799c99 H
966202 e4a15df649d8429b8bb48be2643b31c67651c7335ced914807ad55abd6143f1d H
966203 eb7265245025e23e7da26695ebad747ef305c5ddf9a834878cb4fe975f2c5285 H
966204 edae22b252b1fbbe74381f318fcc020d5ebf486b165b903dd92d92e144ed918d H
966205 f50adf3bb9afaed997a965619560d9473b11f115bb5c7ea2e2da37ef4d183994 H
966206 0669a043f360ccc49e4a3272edd8fec7136bc0e0f87e2b79a7093ecee9f1a055 H
966207 b48c637dca31189aef5770292736d0a4897fa3af5b78a441dee598c08fd048f1 H
966208 e01eaaa3c0944519ec7a0d1a39ec6ed5fdc660278863176eb59c27aff17c233e H
966209 bf027934d124aa138c8773cb55b864559b75899f42339ee834d3a074eb7a4c6f H
966210 5cb172dc8bc60f937b867f1702c680309a613be71a13f6f34d5386bdb68d651f H
966211 7682dbc186b560bbb8a32e693d4d3e7116314526d3d64474139f1814e7d0a296 H
966212 faf0854be716b5dd9ff4e9aabde51b869f026d53f6a4a6705d80f7b1423b47b2 H
966213 7fe2a2805a6ef6637012c6f213e5a397e7f6930590141bff8924aec6fcda448a H
966214 d4c3e82ccf194596789df6fac273d333dbc4304841184752f6844d22fa27ff9c H
966215 703b6e881761f7bf29c7611f6b8ab4ec9f8cd447e924e604b1ae0c5dafde1182 H
966216 e2f6ef12880121d91fad923aeb67bb26ec43335688bc9331ead0f2177654274f H
966217 7beed3f175091bf59094d78451eec98203d70c49d1005917a684636571bcffcc H
966218 d2f67cf7b403553978aa04e758f6fbe87d0d1f60ea961f951565fce1243c468b H
966222 fb5f1caf605f56eba865823f84c067572ba5ef7d31027725eb6fc5d1995370b4 H
966223 7f5af2221496923683fe240e39be2ded2289dffb5f917edc32933b2f07545fc1 H
966224 7a00a76166c63d1548deb7470c47066b304ef6a968e9545d83442285b56bacbc H
966225 c1db8e88a5ffeb682af5408f508f8aa78958dd290ca1e4d340bd9fdfe3d290da H
966226 6e6b4823baa721c5895543b340baed6734f58a921f69c2ff82044b1de5863f0d H
966227 1f74aa2f10aa272212d33ee0bf406b8eab458aa6cec4f55f78a981cca03ccb48 H
966228 6fa614bb46e52a74bd9a986e23e936454c837b223eca0a2f678732c3b29fb7ea H
966229 b45749158ac58920e59ccccec8a7661736e5303eeb6697535547bd2bdd5bac72 H
966230 ffe8b689d13db52f7c1e05093255b2e30188eccc3130e60b9b3324dedd109f89 H
966235 8a5f2cd789ac323f660d9c618dc076f3963ca3db693715f32e0e6783a1583137 H
966236 aed7a53499ddacc74bc3560480fe1a6a4cde3d6a0b9933a702d0966d443c6c31 H
966237 7e64763f6ff0b7915d3c73d391f19a1428659ec382ae74816b3f4ec73f0771c1 H
966238 bb1c6eb1dd00b67beec233a4d2003f97be09400fd4d0a1a5316c323536061855 H
966239 f086eb31cd63264833349bfb2c405368cf37c5bc61480b6acbe8ca3736a2fec2 H
966240 20f201c28e35384b405777751db914cabe4faa1d5f4a21d204d0c5f92eb71599 H
966241 190ff0f84735875893f24894156f2c80d73996f9207fe2e13692ddf1ec644762 H
966242 910d27068c646e4b8476f7e37a46b19185da37697b6c40316f36f36761a92702 H
966243 84c3fb6179e7702f31383f10bcb3e6f68b2443654b48037d708d72b4650af6eb H
966244 5115a87fb646603d2d8f372d538593d6d5ff366a8b6cdd375776235e3fe95364 H
966245 eece17094db8c5793545df2acf88d5bd7eed5ade9d7a8e4c77fd9ac9109e83ca H
966246 1295d84b5b123e198314aac1fdc7118df9154378831a0eb8aa10935a1c58c533 H
966247 9952c948eb83b7f7f30558e65680a5916c7f2d64c5735fc9e46caac296366465 H
966248 392f823efd55fc641c3ea1e4441cfd3488ab2f4d7be4453b1a85ef766b2c979f H
966249 b8ff576a1f5858fb0020b16b5759152ca838ad175849fb457e5782396ef7fe06 H
966250 ddfbf39b6601e477211dd74fe47aa94c7e7eee2f9fc547b4fd6032118d2e0b01 H
966251 eec1189a0033d9e7fb0f8126c2001fff4361d940310a9afaa57d2885c92b9de7 H
966252 4cf1031e8756716250ab4acf682801a6d9d29ca660cbedf9128892698b2b3afd H
966253 482f525363883f32057107e2fe103bfa323cda05c1e586641f4f4fa6b8fa0c7c H
966255 8a7ae81ec01bc876bd415dce7ec4cac798e6655143a558f74accfa21228f4676 H
966256 09e78942b1dec4fb5ec88b27da609df316c4dded45610507d1abf86131a0734a H
966257 2804b496e63a7c1b95ca323274602957e1bf07884a31503d395eb116cc8aa206 H
966258 e6baf78d8300c6098c88c3224874bb22c52430dac220fd9d36aaba2e0b106db7 H
966259 d5ac66f610345a40ea435d208141fdfc37267a92f001cbbd4eebb59b1d9eb93e H
966261 8183322d258d3ad87f36e5395a0e1abf1ba80c7814e60549cffb5239ab6bb220 H
966262 1daa6b83554df9aa9e7b66aafe7d539b798142a746603d7efab37badad6656e4 H
966263 f812505af163ffa9e41d48ab4f2b9f891a83aaca59b2539e3922026cd41f6e5f H
966264 e119fa651d72fbffc7f3fedbe6f94fc4900d3e1f1d9b4cf4dbd91fc4b28e2bd5 H
966265 3d1b7895e999bdc2c61d1b7757d7d11e6d7b501454e82f5b4d43c825417c017b H
966266 134a2aeaad715fa9106e93b25cb62163a6976675f7311853dfab11aaeaea9233 H
966267 63fa0d443b3ce8a3ca39e517752670882a26d4650c888ede33cc6ea4c7f5961e H
966269 f4218b2b27f85ca50616a232e98c737995cc543ee942940cf28bb2c14e8706b1 H
966270 720bc653068f61f67b992b17a8173043240aa18f9bb74c9fed61f7111d6cb72e H
966271 e046ad7f016da219b0882da6832f4c13e49b4c78e3793a0f774a2afd66d65b0c H
966272 51e5d58ade5a61a8dbdb7b0890930b88f2cbc0ddf61ccfed6b7e617ede66e36f H
966276 5b7aba5508e36a9ddf7151b314015d782f95dd15229d162c625e75a9b918fedc H
966282 cef9576789f50b2a5c7ef9ac04ccc47fddefd05345d108960d1d77cbbde14217 H
966283 dae5e342c5b832f809c70530cd71ea7e617d09858f69d2da093581fee7c205f3 H
966287 720cc878f803ea4169c3e81fadfe92d53c1939d05cd7dac2bc44af154bf76ed3 H
966288 a1797489fdc625be4ed8b9df645acd67201cbfcd986b73392deb1e459940ec04 H
966289 1c8ae86523a3333d05e80ea9bc8aa7c15597e38cd3c93cd3be7820e51271126e H
966290 0e8b48827a0ae5f55d5cfe0d4bade1abc9bb566d190eda64aa5004a137171b0b H
966291 fd3c3c7a5d2cdca07d306d5b82d6cde49e88633f8acf01a9d383ecb9b2510b12 H
966294 edf3a290628dd370e3a45ab6b2950cda8c91dd45aaceb12322e430206bfffed0 H
966295 37cd9f1bdd942c5d378a5c834feae4bfd9aaa4382699bba1b6cb3a32a608bb0c H
966296 b3a6b92e36278a419e6ab1cf799c2fca2a2cb88ea5190711b70cff2adb47c81a H
966297 5f5c5028404f3359f6e66f61d70fd4ea7852d2ba02bf25521aae42857fe17655 H
966298 acf1690fdbd3cc52b4e90b5de45238ebf09a060378e948f1f776d2b19c62465d H
966299 ac1cb612481e62d46aec8b7a025bb298b2fb9884deb9b2fba177a8af0979c3c3 H
966300 d041383ca5dc9650cfce68c7975586910c2375b3053e5ee56916fd7c524e0769 H
966301 d94cbb76ccc291d346ab5e4e2b201c4c990c47989b7d7bc6709078c9aaa27d4d H
966302 6a49d0e51669a07c1d5f192fea58f4426dba625ba265e971bec1e651d598d376 H
966303 63f05a8723c30322f1c7f1582ca1be5ea3d8565f4437e087748d3ca49d1811de H
966305 549e541b2d6e03f3903f4c742d5b53f5695842709481f8772cb3fb4c4cde15ff H
966306 8729793ab19723242d074a6efc825a086764afae898f3367266bec9272ed97e2 H
966307 99a90f883a3b27c1a97e3f85fd6e24cc8fc4b415ef7dfceea83c81b88c84a88d H
966308 42bac70e9a8f6575db0c65dfee6b08496f468a30adb91105ea948d8d0982873b H
966309 77bf7e3b8d5019b0f9a8c8c3f0358de3ddd13638b0111b7f26902231cfd42da4 H
966310 01aac6a40f195fa1dca43e196df3c235be43464cfb18e093ab94d8e769308db3 H
966311 08946a97fa6334ddc227f7ccb2e8031b1b0cae957fec6af6edcade631501d542 H
966312 d1152090a19f7402b8c9805aa6e8ffcf7ec98a718a9f888db155ffd6340b2f0e H
966313 441f40f94f4dccfb786860f2df3b93b965db51d5209ce0b4759c0b51c9491b10 H
966314 505e2585190cf98dd246bd17a295cbea4ae36800e550ece9c705ebf39f360495 H
966315 c145962ac1645bc45d4dbe0e01749e0b77b240b89bcb51b98975a39de0f54fda H
966316 22282e4e792eb49234d75b80be28c9242ee29d2d0379f3a9ed5f733f2012ac71 H
966317 c46d7b09c8e5277c9c7430f26d6e1ce42e8247496505de0a72b49d65446b1921 H
966318 d82880a94f855822928d09699c221b74e9d68e9205b44b4143cdc3935532442d H
966319 c04f5f47e0e86092cd735573bcd03cbccadc64e7b9ca87792a92fe2d8126fa40 H
966320 310e804b3c6a80786a076f545308274a9d01f91196edb12bfc102e2fab6ec08f H
966321 b111d3d02a3c5baa4842397bdf4f2ccc5c7731869835193b56dd42dbb75a9cff H
966322 0ecea32754f979f3653f2332a0a6257e5c959fbc247a41ed677939d32d9cd5c3 H
966323 07c0b61a9d4fee105f3ccc6c9a2ff68db2542db58b5b76cff2fc1c3e1529c062 H
966324 681ceaed64d8a4adb783697dcc07954fe743fbe91e1a5bcff5751ec3593afa85 H
966325 0588ad0ba4aa1bc5dd526e24e77f5a86aeb668dadbcc64eda1617bb0ff60ae0e H
966326 98189ea44c1fe361186a00617bbd30d50e6945751f600bec3f7e758cf72f9baf H
966327 2e9303884a2bbdee2a41b825813399501c92dd7f8dac195acaa626aff5941c8b H
966328 e463befd9b513343ba6f4d2c5dbb560bb206c39c7292954cd201a29244fcef2b H
966329 78993eddaa61ae85eb53bb5b546e8dd05e56d19751cd27aab3acc9422fd1a11b H
966330 f7a6e0a3f32aa0ce820df4cd27846dc4723e1499a513e20f4068a98260378e66 H
966331 aa24630475e24d02384f1bf21dbf44f6c07377be5c9ebc5872b7e6b47d6b8d80 H
966332 6f2458a86c1ce0782b14cbcfcf3c17ca8b89856418fc70b24cd55a2b55b789c9 H
966333 a354ed1184aeea5a5552c18757a226b146cff0ef1e29d2fe682019e3142861a0 H
966334 c083491dba3285b649362083cdd33fe9736a868035c35e9e3cfd4a89adbbe058 H
966335 cfc9fcfe75442ccba4e43a74940836cda5f7b72b8f6b0a59a22221f263bde00f H
966336 89d21481a66a2e59c775ff0a8f7dd5eb8d8f2950ca3114f01e2b31a18793fa47 H
966343 90a78fc20d500c380bbba16127535fda5216d8267e3852fcf701e93b39ecdcf6 H
966344 0466b55d86dfb385ffc652be436bc24e8ac90ec3d5d37fa5f6305faf02916159 H
966345 7307803c5100fe110d3ccbd43d2ae9884359a0acced145149ce27be6f5cf7457 H
966346 775e03fd956c5a9e91ac4a03afbb5f207fd49ebcb726233afd3be54712799b57 H
966347 af3f950b3216730996a7975d97cd1a90d3b19f43f208aebccf2227daf69e864c H
966348 3d0927b26777abcb61d27c07955c2be5c05f75b79d8cb77886d70ca41cd31723 H
966349 c2d8368d3b149e1be542ded6a833b92627a1eaab13af54dcc2d9a1a49a779bcf H
966350 8f1603c490df49d72440d30fde9f996fab3bfcea3d00bcd2923faf518a77edd5 H
966351 856d3fb79e178da9466a0e119426fa0a27f3b9f38681b5305be859a0e9ae9386 H
966352 b682fba26e5aa2e2567e1dcac57f5659d109af778aed1c5215b60bec443ffc68 H
966353 7d303e2e78c646a2dbea3fe6d898fcbe8f729d02df173bda75c84f9ff95bf12e H
966354 54c86f3f45b3f85f13ae1aa7b376eaa8124ca929261468c061dfe150ae6d2d61 H
966368 ce058c54545ec223e7b2498948cd9f04d0b58c538ce89c273627ef65478fc3f1 H
966370 817a528030c26f8f8910f31e92bb11037eb97a5e9a425a289b73cd0485b087b4 H
966371 8935880c8e877da4014df87e745f049f34b4a3ebdd3cf16bff21add7a201a697 H
966373 73634f91fd08809c8bdb277cf68085cd7e58fd014b737fbcdaf28d40e134a340 H
966375 641ec40be459563f14f23a2e2fad02ae288eedf2a4808eb3170b2d1cf291bf8b H
966377 8353319a2ba8a933f9c7bd68bd152eaf21fc1936351f399095107f2fd09d4195 H
966379 8c544dc395ab77bd938efa5b6012848d91c0fabe1eac1c3b14ee1bbd0d951a7b H
966380 5f488f1075d22cf5b906c0c6087888fca39ec63fb0aa9e97787c2a6384d4fee9 H
966382 de62ff8d5aa8c6809d3d1f796f2706adaa58e2a964bab077111a3a67574cc916 H
966383 900269bfdbc6a9a3a9c31a74034409716c656edfeea27cbf3bf82f07346efe37 H
966384 2ca5eaea172ad20a42f1f87cb714d92f3b82c4032bd9eaffd8d4569fb9b08a9c H
966385 ae2a4d0770629d794330716633ce55f8d8e9a82f67165b46f85a39457337f74c H
966387 273214cea5b811b49d52fd6f27882792d62b2714e74ee8f5baefc9c0ecb826e0 H
966388 1c20664a7edae727afd365fce373f9534269330d6f393cbea734cb52362cd00f H
966389 1a770a6054055c2b9ca3f4905eb8528f0a79f9f71b057cf7458ba57f046f275b H
966390 09756a1bed915cb6a1350f6b02b9461a1fd9908bae140ca54f8a03fb5e368768 H
966391 438818dc0ee9fa75b05ea8ca54e6cb33c4febecfbc6143c507327790b5902b4d H
966392 35cb80c315c3cddac35e23bd6410d7aee6970a191f2965a35dfc058a1fac637c H
966393 c992528a0a9a63ff57f8c9bff5a0ccab3116a891b8e5115bb2a1d8014f4aa59d H
966394 8825736fb6b0f88bc3d78fa641b630acf9641491ab957437452a130f2b3d47fe H
966395 5fee22a2d6b7cb2288495c48ae45e4cb04050d7efff5301791308c5fe488c714 H
966396 c171d0c44db1b3021f7527f803447598f19e2668013ce0ef7cfe5244d67f4a6a H
966397 292299656b1d368198b092f4b1ad82480df17a88b17eeff78bba4bcd3ef2556f H
966398 5f1eca6b5e0848dd92470daaf993782f3e119fd8ce98bab755857afafaf985d5 H
966399 3abf94c09c75fe171aac629ee9dc44071dc386df31fb678ffe5a7c5365bf78af H
966401 828061841bfbb3997fd887b0e507e3eb7652d543d542cf47e52150ccef2c61fd H
966402 ee93b03c0d1c056165f2ce3b94d23541ff5b94b194c4e13a6f68cb8483dd66ee H
966403 3bb7230707b38919643dbcb10c393874aad3488f9e427162b4af1463e1c0cd6c H
966404 02676a4a3d7e0a646a969e4545cdba75b26194a2bf621ca4fbe80f95f9f96a01 H
966405 068fe45542235affc5fa1008d7b2643b4fd8ea91b57af8a6c84560a8c5150994 H
966406 982a01ae0ea4ea87c22b49c263698c40dca22d5c03ffa453a2dc34f5a93e793d H
966407 b945c2a9d0cac403bd6c7e0ecab6cf2b9d2b09fbc5a7941c80c5b81c10f06180 H
966408 0eb1ea74a69672f0f9e326287d0b25b08a784c95708c1dfc22cff0b89dad95f9 H
966409 8be3c9da0ddd30ba7b6f8077628320f8f3e0f04ad4b757420a29c55b3752e213 H
966410 8a30953d85755caac1160a0ab52f4ce3b6170006a73bc35985a1d96bf551502d H
966411 191df5c3df5956776e6206e2b6d464fb9581fc417140d6084d6cd3be021f8bf4 H
966412 84a962ee318bf174bd10d6a89c74fde3e98622312e7c0115426164e26f84080a H
966413 c6c3f0d1918b145f6f29953e9f1b314ab2c4fc17dfddb64e13bd8e6718aaec0f H
966414 733d7032787f5b9d3fa0d62f538682820644b2c9d72a35c2a79bfae1d4430191 H
966415 1d42a0dfeeb44fb1ec8dc9de36ea44c17e4e84a0be4ae299975724fa1d49db87 H
966416 bd1c3fbd9cd7f4aec7c63b4f05d2ff21658fae27bd597da945a86fd9491653b2 H
966417 8b0f1583d837293d44dc839910062ea66cdcb4df0ca7537d1f0f20a185658a4d H
966418 0a2ccf3a9c1a20dc5c63f98363ac41ebb105b59544d5c61637fc6ecc47ba838f H
966419 7ad2f100cee5b8823519b0ece86ec648db31b3beef52e9ba3b072ba3dbce6279 H
966420 40f67a75b5af786132af2ba2151525ef5327d8bd1a717630438833835b13532e H
966421 1a9cfc86629eafbe6d6a1ad339db6c5ef5b461da3c4a53a56cd8dacbd0da34fa H
966422 17a93bf5c1a2abddc936e93b7d7185792a0dd5280b3a043a53c993f3ef10c59f H
966423 56f47afdc94120051a89256a8651f2aa47ba204509cf6e6ff740c1c234a2cd9f H
966424 e6d55ab27f5efaf619f2303c89dac104bc8baedb524d8773206710e07c610189 H
966425 a1ca5df23aa0ee42605bdbe11f3740c6c9ca8b8236d555388c980766c4a6110e H
966426 21a12cd81332d4a7bacab386c557a239d870bbd8d4dbb504b7a610f8860a1f9c H
966428 cc317deb52e3f489920178643e8b4c667358da83f133d9cd080b50986e6ec793 H
966429 48cd12a74a507d4ead87fdbe92b9ff99d4393edd52e1a2d612262bbfb9851f69 H
966430 6848509e4d414a0cd59063c9891aeb81ec151f30f995eba267ef2cd060b873f6 H
966431 813d83311e4c9b0a6fbec94f7c22deb4e9c562d7535227ea99a44219c3175a14 H
966432 3db4351399ea6d7d7f095e8584486a86fc98f1b71666ccbe0d1b9ed37d56b4a2 H
966433 f3c803a6117ed45f532c8c3323c49d8639dc189ac43127851e2cb1ae650b318e H
966434 04694664c45474a1eb59b1665014a3fb5e7ff7d42611d608fdb90f13b1ce95e4 H
966435 291b67059e929c448b0131a21af07cae30df6e84039a10cf37b53df848869a2c H
966436 810fe97d921a88e75cf90bc6f641af044860a1cecf704ad66d4481f68ecbcd44 H
966437 63e283f93c1c03013298a8b92b08f113495c6c1892023f2135ada25ecd784289 H
966438 132ba9510584fcfa9a1afd7412ce89beee41fcdf12aa47597b300d816b5811f4 H
966439 eeb045c3d5da3099f9d8bd8bee1989756c14e0413ffc72e183831b3b73d089ee H
966440 8aafae5239a73ca4e81439ce21cf3f0206ac04452f1998f518a6c676b607c858 H
966441 8383551479445136e99bcd4ca26e0d85604fc9a7ef6f8c42500274ada0545d41 H
966442 d247f8f27969db04932a62781953f2cd6289eb0744a83545a1a0c9640a8fb579 H
966443 6fa90a70b95c627b0b6e934d4fd18dc9591b7b8c9ed610daaf187125d8feedbc H
966444 b6277038977f257567776ffe5ac24ea32c0b6b14b25dbeac70181613b7c773a6 H
966445 62df53811e62f970c0cdba35114627263c1e619481780390afaa179de2331496 H
966446 6a47fbd6de67ecbbf2a3762aa7ddcc56b0d08cda736519465fce543b2f530299 H
966447 a3b6d371780cae5dbbb54d4144b956a36129b11f20e9938da156160e264ae3d2 H
966448 644328267b1d7ab2c9e67d85113d81999b3725641b691acd6522e121c5082b16 H
966449 f8e0e0be872b3d3bef2b27246a6e7304dca229fd97859f4a25abad7d7eb8c1ff H
966451 2982304bc1880c09c735a0b14b5e88deba7773df8e5aabe92a1385299ec087e5 H
966452 00a9f0f3d64a47ab53a3ce0cb67a31ad3650599008a4f445a9956988a559a3ec H
966453 26116c29a4c9f9ceb528ab4b6ef55ac640d42f9ea21d31a316306c781f0f94e9 H
966461 28f7abebc38df862bc55acfbf78e4d031bebaa27526574d38c7c725a16b31860 H
966462 8d36ad375d4bfac87d2c83f98c568b8e7028b19be3a5c16e142538a0c7374a34 H
966464 f8e8da88ad68157e1a557581b876fbbcfa14ff0ea69d7a52de322de94dc5588c H
966465 69bd716a74c26ed8f289b730afeb08c239d5867ca8b6e051b2fcb73a7a966d89 H
966466 e344b4b9f4b047b45a44645cca1308e36fb6084176f9a4ea62cdd47b2ce01911 H
966467 c8428d9bc3ff7a7b70c5253b9d5aaf9fce402c8d2ab8e4d27a95653ba823dc69 H
966469 40c1014a79497614575224f451ba07f43dfcd70fca9c40a2988dc43f141c04de H
966470 ba75126fd10698545dd7048357a6e34afc3e53f10ed2ccc9bc824a166a2a3641 H
966472 0e20dbdaae201c62b8da947dc8552435ffe0efb1f14c374b821f72f2b58e93ff H
966473 130f6b6ef549b133d23ac8efec81be033b3fd8c51fe4b6b2989aee8666b85f26 H
966487 2a7449eaf48cfe285d21a875fe3b2d935bd104afd4c52285738ab2554e702681 H
966488 1f9e7816a1caa9b0035b004e25bdd2094ab5713e355079ebb0143f2d065beb41 H
966490 7d18e229ff8980c2f5123b7b4567dd8784fc1c8235ea3e883cd5f418d917d277 H
966491 b33c3e3e1472e430850f4036dc4614b9b5fbb14c0345d1db1140681f5ff7e3eb H
966492 71eadb3b5bba6d3459ea28e65ffbebb5f2f2e3a5702c04fb0d2bef62d8111b7f H
966493 541a5673b92533aa6d50936564f4791e1efb6f5e70b7c71e03769ca0514c2be1 H
1147686 da4a885e0f12ea31180a919d6b12e18a768906ddd45731dfb5de9f1f6f008bd8 R
1239773 68ef48fa7dd22738b5a3d7105f73771c668edd8f322885d66ecb14d34646a304 E
1239774 e0e5168e65dd568f838a798de59c23a06f9d639913d0ce83f577c0fe86400426 E
1430361 4273c49d13d37fc8790ff8ea572743bfc846d6e4450a6fa01171520956e6b67a F
1432000 74b73d43b16cf905a8926404605067a17cec624d9fc6a1014f8e21ff610b32be A
""".splitlines()
    )
}
# This exact HCR terminal's official label has a duplicated separator while
# its document heading and source ordering identify R.S. 40:1236.26.
_EXACT_CLUSTERED_TERMINAL_LOCATORS[
    "https://legis.la.gov/legis/Law.aspx?d=966045"
].update(
    {
        "source_label": "RS 40:1236..26",
        "source_title": "40",
        "source_section": "1236.26",
    }
)

_CLUSTERED_DIV_DOCUMENT_SHAPE = (("div", (("id", "WPMainDoc"),)),)
_CLUSTERED_JUSTIFIED_A0001_SHAPE = (
    ("p", (("align", "justify"), ("class", ("A0001",)))),
)
_CLUSTERED_UNALIGNED_A0001_SHAPE = (
    ("p", (("class", ("A0001",)),)),
)
_CLUSTERED_CENTER_A0001_JUSTIFY_A0002_SHAPE = (
    ("p", (("align", "center"), ("class", ("A0001",)))),
    ("p", (("align", "justify"), ("class", ("A0002",)))),
)
_CLUSTERED_CENTER_A0001_JUSTIFY_A0001_SHAPE = (
    ("p", (("align", "center"), ("class", ("A0001",)))),
    ("p", (("align", "justify"), ("class", ("A0001",)))),
)
_CLUSTERED_TWO_JUSTIFIED_A0001_SHAPE = (
    ("p", (("align", "justify"), ("class", ("A0001",)))),
    ("p", (("align", "justify"), ("class", ("A0001",)))),
)
_CLUSTERED_JUSTIFY_A0001_A0002_SHAPE = (
    ("p", (("align", "justify"), ("class", ("A0001",)))),
    ("p", (("align", "justify"), ("class", ("A0002",)))),
)
_CLUSTERED_TWO_CENTER_A0001_JUSTIFY_A0002_SHAPE = (
    ("p", (("align", "center"), ("class", ("A0001",)))),
    ("p", (("align", "center"), ("class", ("A0001",)))),
    ("p", (("align", "justify"), ("class", ("A0002",)))),
)
_CLUSTERED_TERMINAL_DOM_SHAPES = {
    "blank_range": {
        _CLUSTERED_DIV_DOCUMENT_SHAPE,
        _CLUSTERED_JUSTIFIED_A0001_SHAPE,
    },
    "blank_range_cross_reference": {
        _CLUSTERED_CENTER_A0001_JUSTIFY_A0001_SHAPE,
        _CLUSTERED_TWO_CENTER_A0001_JUSTIFY_A0002_SHAPE,
    },
    "empty_official_locator": {(), _CLUSTERED_DIV_DOCUMENT_SHAPE},
    "expired": {_CLUSTERED_TWO_CENTER_A0001_JUSTIFY_A0002_SHAPE},
    "redesignated_act_section_suffix": {
        _CLUSTERED_DIV_DOCUMENT_SHAPE,
        _CLUSTERED_CENTER_A0001_JUSTIFY_A0002_SHAPE,
    },
    "redesignated_effective_date": {
        _CLUSTERED_DIV_DOCUMENT_SHAPE,
        _CLUSTERED_JUSTIFIED_A0001_SHAPE,
        _CLUSTERED_UNALIGNED_A0001_SHAPE,
        _CLUSTERED_JUSTIFY_A0001_A0002_SHAPE,
    },
    "redesignated_hcr_2015": {_CLUSTERED_DIV_DOCUMENT_SHAPE},
    "redesignated_range": {
        _CLUSTERED_DIV_DOCUMENT_SHAPE,
        _CLUSTERED_CENTER_A0001_JUSTIFY_A0002_SHAPE,
        _CLUSTERED_TWO_CENTER_A0001_JUSTIFY_A0002_SHAPE,
    },
    "redesignated_to_see_acts": {
        _CLUSTERED_DIV_DOCUMENT_SHAPE,
        _CLUSTERED_JUSTIFIED_A0001_SHAPE,
    },
    "terminated": {
        _CLUSTERED_JUSTIFIED_A0001_SHAPE,
        _CLUSTERED_CENTER_A0001_JUSTIFY_A0002_SHAPE,
    },
    "title_heading": {_CLUSTERED_TWO_JUSTIFIED_A0001_SHAPE},
}


_HEADER_RE = re.compile(
    r'id="ctl00_ctl00_PageBody_PageContent_LabelHeader"[^>]*>([^<]{0,80})'
)
HEADER_TO_PREFIX = {
    "Revised Statutes": "RS",
    "Code of Civil Procedure": "CCP",
    "Code of Criminal Procedure": "CCRP",
    "Children's Code": "CHC",
    "Code of Evidence": "CE",
    "Civil Code": "CC",
}


def parse_label(label: str) -> Optional[Tuple[str, str, str]]:
    match = _LABEL_RE.match((label or "").strip())
    if not match:
        return None
    body, rest = match.group(1), match.group(2).strip()
    if body == "RS":
        if ":" not in rest:
            return None
        title, _, number = rest.partition(":")
        title, number = title.strip(), number.strip()
        if not title or not number:
            return None
        return body, title, number
    if not re.match(r"^[0-9]", rest):
        return None
    return body, "", rest


def document_blocks(html: str) -> List[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="ctl00_PageBody_LabelDocument")
    if doc is None:
        return []
    blocks = doc.find_all(["p", "li", "blockquote"])
    out: List[str] = []
    if blocks:
        for block in blocks:
            text = _WS.sub(" ", block.get_text(" ")).strip()
            if text:
                out.append(text)
    else:
        text = _WS.sub(" ", doc.get_text(" ")).strip()
        if text:
            out.append(text)
    return out


def heading_and_body(blocks: List[str]) -> Tuple[str, List[str]]:
    for index, block in enumerate(blocks):
        match = _HEADING_RE.match(block)
        if match:
            return match.group("title").strip(), [item for item in blocks[index + 1 :] if item]
    return "", [item for item in blocks if item]


def folder_header(html: str) -> str:
    """LabelHeader of a TOC folder page (statute body name)."""

    match = _HEADER_RE.search(html or "")
    return match.group(1).strip() if match else ""


def folder_body_prefix(html: str) -> Optional[str]:
    header = folder_header(html)
    return HEADER_TO_PREFIX.get(header)


def toc_docids(html: str) -> List[str]:
    seen = set()
    out: List[str] = []
    for match in _DOCID_RE.finditer(html or ""):
        token = match.group(1)
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def source_bound_operative_label_correction_from_law_html(
    html: str,
    *,
    source_url: str,
    content_sha256: str,
) -> Optional[str]:
    """Return an exact corrected label for a retained operative page anomaly."""

    expected = _EXACT_OPERATIVE_LABEL_CORRECTIONS.get(
        str(source_url or "").strip()
    )
    if expected is None:
        return None
    supplied_digest = str(content_sha256 or "").strip().lower()
    observed_digest = hashlib.sha256((html or "").encode("utf-8")).hexdigest()
    if (
        supplied_digest != expected["content_sha256"]
        or observed_digest != expected["content_sha256"]
    ):
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form", id="aspnetForm")
    label = soup.find(id="ctl00_PageBody_LabelName")
    document = soup.find(id="ctl00_PageBody_LabelDocument")
    hidden_doc_id = soup.find(id="ctl00_PageBody_HiddenDocId")
    print_link = soup.find("a", id="ctl00_PageBody_linkPrint")
    previous_button = soup.find(id="ctl00_PageBody_ButtonPrevious")
    next_button = soup.find(id="ctl00_PageBody_ButtonNext")
    if (
        form is None
        or str(form.get("action") or "").strip() != expected["form_action"]
        or str(form.get("method") or "").strip() != expected["form_method"]
        or str(form.get("name") or "").strip() != expected["form_name"]
        or label is None
        or label.get_text(" ", strip=True) != expected["source_label"]
        or list(label.get("class") or []) != expected["label_class"]
        or str(label.get("style") or "") != expected["label_style"]
        or document is None
        or hidden_doc_id is None
        or str(hidden_doc_id.get("value") or "").strip()
        != expected["document_id"]
        or print_link is None
        or str(print_link.get("href") or "").strip() != expected["print_href"]
        or str(print_link.get("target") or "").strip()
        != expected["print_target"]
        or str(print_link.get("title") or "").strip()
        != expected["print_title"]
        or previous_button is None
        or next_button is None
    ):
        return None
    for button, key in (
        (previous_button, "previous_button"),
        (next_button, "next_button"),
    ):
        if any(
            str(button.get(attribute) or "") != value
            for attribute, value in expected[key].items()
        ):
            return None

    direct_elements = document.find_all(recursive=False)
    if "document_elements" in expected:
        observed_children = [
            {
                "name": element.name,
                "attributes": dict(element.attrs),
                "text": _WS.sub(" ", element.get_text(" ")).strip(),
            }
            for element in direct_elements
        ]
        if observed_children != expected["document_elements"]:
            return None
    else:
        expected_element = expected["document_element"]
        if (
            len(direct_elements) != 1
            or direct_elements[0].name != expected_element["name"]
            or dict(direct_elements[0].attrs) != expected_element["attributes"]
        ):
            return None
        observed_children = [
            {
                "name": element.name,
                "attributes": dict(element.attrs),
                "text": _WS.sub(" ", element.get_text(" ")).strip(),
            }
            for element in direct_elements[0].find_all(recursive=False)
        ]
        if observed_children != expected["document_children"]:
            return None
    blocks = document_blocks(html)
    heading, body = heading_and_body(blocks)
    if (
        blocks != expected["document_blocks"]
        or heading != expected["heading"]
        or body != expected["document_blocks"][1:]
    ):
        return None
    return str(expected["canonical_label"])


def statute_from_law_html(
    html: str,
    *,
    source_url: str,
    code_name: str = "Louisiana Revised Statutes",
    content_sha256: str = "",
) -> Optional[NormalizedStatute]:
    source_bound_terminal = _EXACT_CLUSTERED_TERMINAL_LOCATORS.get(
        str(source_url or "").strip()
    )
    if source_bound_terminal is not None:
        expected_digest = str(source_bound_terminal["content_sha256"])
        supplied_digest = str(content_sha256 or "").strip().lower()
        observed_digest = hashlib.sha256((html or "").encode("utf-8")).hexdigest()
        if supplied_digest != expected_digest or observed_digest != expected_digest:
            return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    label_el = soup.find(id="ctl00_PageBody_LabelName")
    label = label_el.get_text(" ", strip=True) if label_el else ""
    parsed = parse_label(label)
    corrected_label = None
    if parsed is None:
        corrected_label = source_bound_operative_label_correction_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        parsed = parse_label(corrected_label or "")
    if parsed is None:
        return None
    body, title, number = parsed
    heading, paras = heading_and_body(document_blocks(html))
    text = " ".join(paras).strip()
    if len(text) < 20:
        return None
    cite = f"{body} {title}:{number}" if title else f"{body} {number}"
    return NormalizedStatute(
        state_code="LA",
        state_name="Louisiana",
        statute_id=f"{code_name} § {cite}",
        code_name=code_name,
        title_number=title or None,
        section_number=number,
        section_name=(heading or f"Section {number}")[:200],
        full_text=text,
        source_url=source_url,
        official_cite=f"La. {cite}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_louisiana_law_aspx",
            "source_authority_class": "official",
            "discovery_method": "legis_la_labeldocument",
            "body_prefix": body,
            **(
                {
                    "source_label": label,
                    "normalized_label": corrected_label,
                    "source_bound_label_correction": (
                        "exact_official_louisiana_rs_separator_typo"
                    ),
                }
                if corrected_label is not None
                else {}
            ),
            "skip_hydrate": True,
        },
    )


def requires_source_bound_terminal_disposition(source_url: str) -> bool:
    """Whether a retained locator must not fall through to generic grammar."""

    return str(source_url or "").strip() in _EXACT_CLUSTERED_TERMINAL_LOCATORS


def _source_bound_clustered_terminal_disposition_from_law_html(
    html: str,
    *,
    source_url: str,
    content_sha256: str,
) -> Optional[str]:
    """Validate one of the exact retained-ledger terminal representations."""

    normalized_url = str(source_url or "").strip()
    expected = _EXACT_CLUSTERED_TERMINAL_LOCATORS.get(normalized_url)
    if expected is None:
        return None
    supplied_digest = str(content_sha256 or "").strip().lower()
    observed_digest = hashlib.sha256((html or "").encode("utf-8")).hexdigest()
    if (
        supplied_digest != expected["content_sha256"]
        or observed_digest != expected["content_sha256"]
    ):
        return None

    document_id_match = re.fullmatch(
        r"https://legis\.la\.gov/legis/Law\.aspx\?d=(?P<document_id>[0-9]+)",
        normalized_url,
    )
    if document_id_match is None:
        return None
    document_id = document_id_match.group("document_id")

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form", id="aspnetForm")
    label = soup.find(id="ctl00_PageBody_LabelName")
    document = soup.find(id="ctl00_PageBody_LabelDocument")
    hidden_doc_id = soup.find(id="ctl00_PageBody_HiddenDocId")
    print_link = soup.find("a", id="ctl00_PageBody_linkPrint")
    previous_button = soup.find(id="ctl00_PageBody_ButtonPrevious")
    next_button = soup.find(id="ctl00_PageBody_ButtonNext")
    if (
        form is None
        or str(form.get("action") or "").strip()
        != f"./Law.aspx?d={document_id}"
        or str(form.get("method") or "").strip() != "post"
        or str(form.get("name") or "").strip() != "aspnetForm"
        or label is None
        or list(label.get("class") or []) != ["title"]
        or str(label.get("style") or "") != "font-size:Large;"
        or document is None
        or hidden_doc_id is None
        or str(hidden_doc_id.get("value") or "").strip() != document_id
        or print_link is None
        or str(print_link.get("href") or "").strip()
        != f"LawPrint.aspx?d={document_id}"
        or str(print_link.get("target") or "").strip() != "_blank"
        or str(print_link.get("title") or "").strip() != "Printable Version"
        or previous_button is None
        or next_button is None
    ):
        return None
    for button, required in (
        (
            previous_button,
            {
                "name": "ctl00$PageBody$ButtonPrevious",
                "title": "view previous",
                "type": "submit",
                "value": " < ",
            },
        ),
        (
            next_button,
            {
                "name": "ctl00$PageBody$ButtonNext",
                "title": "view next",
                "type": "submit",
                "value": " > ",
            },
        ),
    ):
        if any(
            str(button.get(attribute) or "") != value
            for attribute, value in required.items()
        ):
            return None

    direct_shape = tuple(
        (
            element.name,
            tuple(
                sorted(
                    (
                        attribute,
                        tuple(value) if isinstance(value, list) else str(value),
                    )
                    for attribute, value in element.attrs.items()
                )
            ),
        )
        for element in document.find_all(recursive=False)
    )
    disposition = str(expected["disposition"])
    if direct_shape not in _CLUSTERED_TERMINAL_DOM_SHAPES[disposition]:
        return None

    blocks = document_blocks(html)
    heading, body = heading_and_body(blocks)
    document_text = _WS.sub(" ", document.get_text(" ")).strip()
    label_text = label.get_text(" ", strip=True)
    if disposition == "empty_official_locator":
        parsed = parse_label(label_text)
        descendants = document.find_all(True)
        if (
            parsed is None
            or parsed[0] != "RS"
            or blocks
            or document_text
            or len(descendants) > 1
        ):
            return None
        return disposition
    if disposition == "title_heading":
        if (
            label_text != "RS 36"
            or blocks
            != [
                "TITLE 36. ORGANIZATION OF THE EXECUTIVE BRANCH",
                "OF STATE GOVERNMENT",
            ]
            or heading
            or body != blocks
        ):
            return None
        return disposition

    parsed = parse_label(label_text)
    if "source_label" in expected:
        if label_text != expected["source_label"]:
            return None
        source_title = str(expected["source_title"])
        source_section = str(expected["source_section"])
    else:
        if parsed is None or parsed[0] != "RS":
            return None
        _, source_title, source_section = parsed
    if not heading or body:
        return None
    source_section_pattern = re.compile(
        rf"^§{{1,2}}\s*{re.escape(source_section)}(?=[.\s,\-]|$)",
        re.IGNORECASE,
    )
    if not any(source_section_pattern.match(block) for block in blocks):
        return None

    heading_casefold = heading.casefold()
    target_citations = re.findall(
        r"R\.S\.\s*([0-9][0-9A-Za-z]*)\s*:\s*"
        r"([0-9][0-9A-Za-z.\-]*)",
        heading,
        flags=re.IGNORECASE,
    )
    target_differs = any(
        (title.casefold(), section.casefold())
        != (source_title.casefold(), source_section.casefold())
        for title, section in target_citations
    )
    if disposition == "redesignated_hcr_2015":
        if (
            source_title != "40"
            or re.fullmatch(
                r"Redesignated to R\.S\.\s*[0-9][0-9A-Za-z]*\s*:\s*"
                r"[0-9][0-9A-Za-z.\-]* by HCR 84 of 2015 R\.S\.",
                heading,
                flags=re.IGNORECASE,
            )
            is None
            or not target_differs
        ):
            return None
    elif disposition == "redesignated_to_see_acts":
        if (
            source_title != "33"
            or not heading_casefold.startswith("redesignated to r.s.")
            or "see acts 2014" not in heading_casefold
            or not target_differs
        ):
            return None
    elif disposition == "redesignated_act_section_suffix":
        title_11_range = "see, now, generally, title 11." in heading_casefold
        if (
            "redesignated" not in heading_casefold
            or "acts " not in heading_casefold
            or not (target_differs or title_11_range)
        ):
            return None
    elif disposition == "redesignated_effective_date":
        if (
            not heading_casefold.startswith("redesignated as r.s.")
            or "acts " not in heading_casefold
            or "eff." not in heading_casefold
            or not target_differs
        ):
            return None
    elif disposition == "redesignated_range":
        if "redesignated" not in heading_casefold or not target_differs:
            return None
    elif disposition == "blank_range_cross_reference":
        if (
            "blank" not in heading_casefold
            or "see" not in heading_casefold
            or "r.s." not in heading_casefold
        ):
            return None
    elif disposition == "blank_range":
        if "blank" not in heading_casefold or "see" in heading_casefold:
            return None
    elif disposition == "terminated":
        if "terminated" not in heading_casefold or "acts " not in heading_casefold:
            return None
    elif disposition == "expired":
        if "expired" not in heading_casefold:
            return None
    else:
        return None
    return disposition


def source_bound_terminal_disposition_from_law_html(
    html: str,
    *,
    source_url: str,
    content_sha256: str,
) -> Optional[str]:
    """Type a retained zero-row locator only when its exact evidence matches."""

    clustered = _source_bound_clustered_terminal_disposition_from_law_html(
        html,
        source_url=source_url,
        content_sha256=content_sha256,
    )
    if clustered is not None:
        return clustered

    expected = _EXACT_EMPTY_OFFICIAL_LOCATORS.get(str(source_url or "").strip())
    expected_kind = "empty_official_locator"
    if expected is None:
        expected = _EXACT_MALFORMED_BLANK_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "malformed_blank"
    if expected is None:
        expected = _EXACT_OMITTED_AS_OBSOLETE_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "omitted_as_obsolete"
    if expected is None:
        expected = _EXACT_BLANK_RANGE_CROSS_REFERENCE_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "blank_range_cross_reference"
    if expected is None:
        expected = _EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "dated_termination"
    if expected is None:
        expected = _EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "dated_null_and_void"
    if expected is None:
        expected = _EXACT_WRAPPED_TITLE_HEADING_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "wrapped_title_heading"
    if expected is None:
        expected = _EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "range_redesignation"
    if expected is None:
        expected = _EXACT_CHAPTER_WRAPPED_REDESIGNATION_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "chapter_wrapped_redesignation"
    if expected is None:
        expected = _EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "to_redesignation"
    if expected is None:
        expected = _EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "effective_date_redesignation"
    if expected is None:
        expected = _EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "title_22_renumbering"
    if expected is None:
        expected = _EXACT_TITLE_22_PROJECTED_RENUMBERING_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "title_22_projected_renumbering"
    if expected is None:
        expected = _EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS.get(
            str(source_url or "").strip()
        )
        expected_kind = "act_section_suffix_redesignation"
    if expected is None:
        expected = _EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "article_reserved"
    if expected is None:
        expected = _EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS.get(
            str(source_url or "").strip()
        )
        expected_kind = "parenthesized_reserved"
    if expected is None:
        return None
    if str(content_sha256 or "").strip().lower() != expected["content_sha256"]:
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form", id="aspnetForm")
    label = soup.find(id="ctl00_PageBody_LabelName")
    document = soup.find(id="ctl00_PageBody_LabelDocument")
    hidden_doc_id = soup.find(id="ctl00_PageBody_HiddenDocId")
    print_link = soup.find("a", id="ctl00_PageBody_linkPrint")
    previous_button = soup.find(id="ctl00_PageBody_ButtonPrevious")
    next_button = soup.find(id="ctl00_PageBody_ButtonNext")
    if (
        form is None
        or str(form.get("action") or "").strip() != expected["form_action"]
        or label is None
        or label.get_text(" ", strip=True) != expected["label"]
        or document is None
        or hidden_doc_id is None
        or str(hidden_doc_id.get("value") or "").strip() != expected["document_id"]
        or print_link is None
        or str(print_link.get("href") or "").strip() != expected["print_href"]
        or previous_button is None
        or next_button is None
    ):
        return None
    if (
        "form_method" in expected
        and str(form.get("method") or "").strip() != expected["form_method"]
    ):
        return None
    if (
        "form_name" in expected
        and str(form.get("name") or "").strip() != expected["form_name"]
    ):
        return None
    if (
        "print_target" in expected
        and str(print_link.get("target") or "").strip() != expected["print_target"]
    ):
        return None
    if (
        "print_title" in expected
        and str(print_link.get("title") or "").strip() != expected["print_title"]
    ):
        return None
    for button, key in (
        (previous_button, "previous_button"),
        (next_button, "next_button"),
    ):
        if key not in expected:
            continue
        if any(
            str(button.get(attribute) or "") != value
            for attribute, value in expected[key].items()
        ):
            return None

    if expected_kind == "empty_official_locator":
        # A changed page with any text, child markup, or even an editorial
        # comment must be investigated afresh instead of inheriting this
        # exclusion.
        if (
            document.get_text(" ", strip=True)
            or document.find(True) is not None
            or str(document.decode_contents() or "").strip()
        ):
            return None
        return "empty_official_locator"

    blocks = document_blocks(html)
    heading, body = heading_and_body(blocks)
    document_text = _WS.sub(" ", document.get_text(" ")).strip()
    if expected_kind == "article_reserved":
        direct_elements = document.find_all(recursive=False)
        expected_element = expected["document_element"]
        if (
            list(label.get("class") or []) != expected["label_class"]
            or str(label.get("style") or "") != expected["label_style"]
            or len(direct_elements) != 1
            or direct_elements[0].name != expected_element["name"]
            or dict(direct_elements[0].attrs) != expected_element["attributes"]
            or blocks != expected["document_blocks"]
            or document_text != expected["document_text"]
            or heading != expected["heading"]
            or body
        ):
            return None
        return expected["disposition"]
    if expected_kind == "wrapped_title_heading":
        if (
            blocks != expected["document_blocks"]
            or document_text != expected["document_text"]
            or heading
            or body != expected["document_blocks"]
        ):
            return None
        return expected["disposition"]
    if expected_kind in {
        "blank_range_cross_reference",
        "chapter_wrapped_redesignation",
        "range_redesignation",
        "dated_null_and_void",
    } or (
        expected_kind == "to_redesignation" and "document_elements" in expected
    ):
        expected_elements = expected.get("document_elements")
        if expected_elements is not None:
            direct_elements = document.find_all(recursive=False)
            observed_elements = [
                {
                    "name": element.name,
                    "attributes": dict(element.attrs),
                    "text": _WS.sub(" ", element.get_text(" ")).strip(),
                }
                for element in direct_elements
            ]
            if observed_elements != expected_elements:
                return None
        if (
            blocks != expected["document_blocks"]
            or (
                "document_text" in expected
                and document_text != expected["document_text"]
            )
            or (
                "label_class" in expected
                and list(label.get("class") or []) != expected["label_class"]
            )
            or (
                "label_style" in expected
                and str(label.get("style") or "") != expected["label_style"]
            )
            or heading != expected["heading"]
            or body
        ):
            return None
        return expected["disposition"]
    if "document_blocks" in expected:
        if (
            blocks != expected["document_blocks"]
            or document_text != expected["document_text"]
            or heading != expected["heading"]
            or body
        ):
            return None
        return expected["disposition"]
    if (
        len(blocks) != 1
        or document_text != expected["document_text"]
        or heading != expected["heading"]
        or body
    ):
        return None
    return expected["disposition"]


def terminal_disposition_from_law_html(html: str) -> Optional[str]:
    """Classify an exact official ``Law.aspx`` zero-row response.

    Louisiana's TOC includes both operative sections and two kinds of
    intentionally non-row pages: section pages whose official heading says
    that the section was repealed, marks an exact section/range ``Blank``
    (with or without official brackets), or contains only the official
    bracketed ``See R.S. ..., Acts ..., No. ..., §...`` relocation reference,
    and bare Revised Statutes title headings.  Keep this classifier
    deliberately exact.  Any other parser miss remains unclassified so a
    strict frontier can fail closed instead of silently dropping an official
    locator.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    label_el = soup.find(id="ctl00_PageBody_LabelName")
    label = label_el.get_text(" ", strip=True) if label_el else ""
    blocks = document_blocks(html)
    heading, body = heading_and_body(blocks)

    parsed_label = parse_label(label)
    if parsed_label is not None:
        if (
            heading
            and not body
            and re.search(r"\brepealed\b", heading, flags=re.IGNORECASE)
        ):
            return "repealed"
        if heading and not body and _BLANK_HEADING_RE.fullmatch(heading):
            return "blank"
        if heading and not body and _RESERVED_HEADING_RE.fullmatch(heading):
            return "reserved"
        if (
            heading
            and not body
            and _SEE_CROSS_REFERENCE_HEADING_RE.fullmatch(heading)
        ):
            return "cross_reference"
        if (
            parsed_label[0] == "RS"
            and heading
            and not body
            and _BLANK_CIVIL_CODE_CROSS_REFERENCE_HEADING_RE.fullmatch(heading)
        ):
            return "blank_cross_reference"
        if heading and not body and _TERMINATED_BY_ACT_HEADING_RE.fullmatch(heading):
            return "terminated"
        redesignated_by_act = (
            _REDESIGNATED_BY_ACT_HEADING_RE.fullmatch(heading)
            if heading and not body
            else None
        )
        if redesignated_by_act is not None:
            body_prefix, title, number = parsed_label
            if body_prefix == "RS" and (
                redesignated_by_act.group("to_title").casefold(),
                redesignated_by_act.group("to_section").casefold(),
            ) != (title.casefold(), number.casefold()):
                return "redesignated"
        redesignated = (
            _BLANK_REDESIGNATED_HEADING_RE.fullmatch(heading)
            if heading and not body
            else None
        )
        if redesignated is not None:
            body_prefix, title, number = parsed_label
            source_matches_label = bool(
                body_prefix == "RS"
                and redesignated.group("from_title").casefold()
                == title.casefold()
                and redesignated.group("from_section").casefold()
                == number.casefold()
            )
            target_differs = bool(
                (
                    redesignated.group("to_title").casefold(),
                    redesignated.group("to_section").casefold(),
                )
                != (title.casefold(), number.casefold())
            )
            if source_matches_label and target_differs:
                return "redesignated"
        return None

    label_match = _BARE_RS_TITLE_LABEL_RE.fullmatch(label.strip())
    if label_match is None or len(blocks) != 1:
        return None
    title_match = _TITLE_HEADING_RE.fullmatch(blocks[0])
    if title_match is None:
        return None
    if title_match.group("title").casefold() != label_match.group("title").casefold():
        return None
    return "title_heading"


def configured_law_html_path() -> Optional[Path]:
    raw = str(os.environ.get("LOUISIANA_LAW_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("LOUISIANA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[str]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return toc_docids(path.read_text(encoding="utf-8", errors="replace"))


def parse_configured_louisiana_law(
    *,
    code_name: str = "Louisiana Revised Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_law_html_path()
    if path is None:
        return []
    row = statute_from_law_html(
        path.read_text(encoding="utf-8", errors="replace"),
        source_url="https://legis.la.gov/Legis/Law.aspx?d=0",
        code_name=code_name,
    )
    if row is None:
        return []
    return [row] if max_statutes is None or int(max_statutes) >= 1 else []
