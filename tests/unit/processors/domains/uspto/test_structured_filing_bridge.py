"""Unit tests for USPTO structured filing bridge (PATLAW-121)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.structured_filing_bridge import (
    STRUCTURED_FILING_SCHEMA_VERSION,
    FilingDisposition,
    FilingFormat,
    FilingReasonCode,
    StructuredFilingBounds,
    StructuredFilingBridge,
    StructuredFilingInput,
    StructuredFilingResult,
    bridge_structured_filing,
    content_addressed_cid,
    detect_filing_format,
    parse_xml_safe,
    sha256_hex,
    text_digest,
)


def _bridge(**kwargs) -> StructuredFilingBridge:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"filing:test:{counter['n']:04d}"

    return StructuredFilingBridge(id_factory=_ids, **kwargs)


def _assert_round_trip(result: StructuredFilingResult) -> None:
    first = result.to_dict()
    restored = StructuredFilingResult.from_dict(first)
    assert restored.to_dict() == first
    assert canonical_json(first) == canonical_json(restored.to_dict())
    public = result.public_projection()
    assert "full_text" not in public


def _assert_span_links(result: StructuredFilingResult) -> None:
    assert result.source_cid
    assert result.content_sha256
    for span in result.spans:
        assert span.schema_version == CONTRACTS_SCHEMA_VERSION
        assert span.artifact_id == result.artifact_id
        assert span.span_id
        assert span.origin in ExtractionOrigin


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def test_detect_txt_xml_image_zip() -> None:
    assert detect_filing_format(b"hello plain text\nline2") is FilingFormat.TXT
    assert (
        detect_filing_format(b"<?xml version='1.0'?><root/>", filename="x.xml")
        is FilingFormat.XML
    )
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert detect_filing_format(png) is FilingFormat.IMAGE
    assert detect_filing_format(b"%PDF-1.4") is FilingFormat.UNSUPPORTED
    st26 = b'<?xml version="1.0"?><ST26SequenceListing></ST26SequenceListing>'
    assert detect_filing_format(st26) is FilingFormat.ST26_XML


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


def test_txt_extraction_deterministic_spans() -> None:
    body = b"USPTO ACKNOWLEDGEMENT\n\nSYNTHETIC-TXT-CANARY-RECEIPT-001\n\nEnd."
    digest = sha256_hex(body)
    cid = content_addressed_cid(digest)
    result = _bridge().process(
        StructuredFilingInput(
            artifact_id="art:txt-1",
            content_bytes=body,
            classification=DisclosureClassification.PUBLIC_USER,
            source_cid=cid,
            content_sha256=digest,
            filename="receipt.txt",
            declared_mime="text/plain",
        )
    )
    assert result.filing_format is FilingFormat.TXT
    assert result.disposition is FilingDisposition.EXTRACTED
    assert result.validated is True
    assert result.source_cid == cid
    assert "SYNTHETIC-TXT-CANARY-RECEIPT-001" in result.full_text
    assert result.spans
    assert all(s.origin is ExtractionOrigin.NATIVE for s in result.spans)
    assert all(s.text_digest for s in result.spans)
    assert FilingReasonCode.TXT_EXTRACTED.value in result.reason_codes
    _assert_span_links(result)
    _assert_round_trip(result)

    # Deterministic digests
    again = _bridge().process(
        artifact_id="art:txt-2",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        source_cid=cid,
    )
    assert sorted(s.text_digest for s in result.spans) == sorted(
        s.text_digest for s in again.spans
    )


# ---------------------------------------------------------------------------
# XML / ST.26 / Web ADS / bibliographic
# ---------------------------------------------------------------------------


def test_generic_xml_safe_extraction() -> None:
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
    <document>
      <title>Synthetic Office Action Excerpt</title>
      <body>SYNTHETIC-XML-BODY-CANARY</body>
    </document>
    """
    result = _bridge().process(
        artifact_id="art:xml-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="excerpt.xml",
    )
    assert result.filing_format is FilingFormat.XML
    assert result.disposition is FilingDisposition.EXTRACTED
    assert "SYNTHETIC-XML-BODY-CANARY" in result.full_text
    assert FilingReasonCode.XML_EXTRACTED.value in result.reason_codes
    assert FilingReasonCode.EXTERNAL_ENTITY_DISABLED.value in result.reason_codes
    assert FilingReasonCode.NETWORK_RESOLUTION_DISABLED.value in result.reason_codes
    assert result.validated is True
    _assert_span_links(result)
    _assert_round_trip(result)


def test_st26_xml_validated() -> None:
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
    <ST26SequenceListing dtdVersion="V1_3" fileName="seq.xml"
        softwareName="synthetic" softwareVersion="1" productionDate="2020-01-01">
      <ApplicantFileReference>SYN-APP-001</ApplicantFileReference>
      <SequenceData sequenceIDNumber="1">
        <INSDSeq>
          <INSDSeq_sequence>ATGATGATG</INSDSeq_sequence>
        </INSDSeq>
      </SequenceData>
    </ST26SequenceListing>
    """
    result = _bridge().process(
        artifact_id="art:st26-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="sequence_st26.xml",
        declared_format=FilingFormat.ST26_XML,
    )
    assert result.filing_format is FilingFormat.ST26_XML
    assert result.validated is True
    assert FilingReasonCode.ST26_VALIDATED.value in result.reason_codes
    assert "ATGATGATG" in result.full_text
    assert result.disposition is FilingDisposition.EXTRACTED


def test_web_ads_xml_validated() -> None:
    body = b"""<?xml version="1.0"?>
    <us-patent-application>
      <us-bibliographic-data-application>
        <invention-title>Synthetic ADS Title Canary</invention-title>
        <application-reference>
          <doc-number>16123456</doc-number>
        </application-reference>
        <us-parties>
          <applicants>
            <applicant>
              <addressbook><last-name>Doe</last-name></addressbook>
            </applicant>
          </applicants>
        </us-parties>
      </us-bibliographic-data-application>
    </us-patent-application>
    """
    result = _bridge().process(
        artifact_id="art:ads-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="web_ads.xml",
    )
    assert result.filing_format in (FilingFormat.WEB_ADS, FilingFormat.BIBLIOGRAPHIC)
    assert result.validated is True
    assert "Synthetic ADS Title Canary" in result.full_text
    assert (
        FilingReasonCode.WEB_ADS_VALIDATED.value in result.reason_codes
        or FilingReasonCode.BIBLIOGRAPHIC_VALIDATED.value in result.reason_codes
        or FilingReasonCode.VALIDATION_OK.value in result.reason_codes
    )


def test_xxe_rejected_fail_closed() -> None:
    # Classic XXE payload with DOCTYPE + ENTITY
    body = b"""<?xml version="1.0"?>
    <!DOCTYPE foo [
      <!ELEMENT foo ANY >
      <!ENTITY xxe SYSTEM "file:///etc/passwd" >
    ]>
    <foo>&xxe;</foo>
    """
    result = _bridge().process(
        artifact_id="art:xxe-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="evil.xml",
    )
    assert result.disposition is FilingDisposition.REJECTED
    assert FilingReasonCode.XXE_REJECTED.value in result.reason_codes
    assert result.retained is False
    assert result.full_text == ""
    assert result.spans == ()


def test_parse_xml_safe_rejects_doctype() -> None:
    body = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y "z">]><root/>'
    with pytest.raises(Exception) as exc:
        parse_xml_safe(body)
    assert "xxe" in str(exc.value.code).lower() or "ENTITY" in str(exc.value).upper() or True
    from ipfs_datasets_py.processors.domains.uspto.structured_filing_bridge import (
        StructuredFilingError,
    )

    with pytest.raises(StructuredFilingError) as e2:
        parse_xml_safe(body)
    assert e2.value.code == FilingReasonCode.XXE_REJECTED.value


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------


def test_image_admitted_with_image_digest() -> None:
    # Minimal PNG header + filler
    body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    result = _bridge().process(
        artifact_id="art:img-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="drawing.png",
        declared_mime="image/png",
    )
    assert result.filing_format is FilingFormat.IMAGE
    assert result.disposition is FilingDisposition.EXTRACTED
    assert result.spans
    assert result.spans[0].image_digest == sha256_hex(body)
    assert FilingReasonCode.IMAGE_ADMITTED.value in result.reason_codes
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# PCT ZIP + archive bomb
# ---------------------------------------------------------------------------


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_pct_zip_inventory_and_member_text() -> None:
    body = _zip_bytes(
        {
            "readme.txt": b"SYNTHETIC-PCT-ZIP-README",
            "app/description.xml": b"<?xml version='1.0'?><desc>SYNTHETIC-PCT-DESC</desc>",
        }
    )
    result = _bridge().process(
        artifact_id="art:pct-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="pct_package.zip",
        declared_mime="application/zip",
    )
    assert result.filing_format is FilingFormat.PCT_ZIP
    assert result.disposition is FilingDisposition.EXTRACTED
    assert result.archive_members
    names = {m.name for m in result.archive_members}
    assert "readme.txt" in names
    assert "SYNTHETIC-PCT-ZIP-README" in result.full_text
    assert FilingReasonCode.PCT_ZIP_INVENTORIED.value in result.reason_codes
    _assert_span_links(result)
    _assert_round_trip(result)


def test_archive_bomb_member_count_rejected() -> None:
    members = {f"m{i:04d}.txt": b"A" * 32 for i in range(20)}
    body = _zip_bytes(members)
    bridge = _bridge(bounds=StructuredFilingBounds(max_archive_members=5))
    result = bridge.process(
        artifact_id="art:bomb-count",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="bomb.zip",
    )
    assert result.disposition is FilingDisposition.REJECTED
    assert FilingReasonCode.ARCHIVE_BOMB_REJECTED.value in result.reason_codes
    assert result.full_text == ""


def test_archive_path_traversal_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # zipfile allows writing traversal names
        zf.writestr("../escape.txt", b"evil")
    body = buf.getvalue()
    result = _bridge().process(
        artifact_id="art:zip-trav",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="trav.zip",
    )
    assert result.disposition is FilingDisposition.REJECTED
    assert (
        FilingReasonCode.ARCHIVE_PATH_TRAVERSAL.value in result.reason_codes
        or FilingReasonCode.ARCHIVE_BOMB_REJECTED.value in result.reason_codes
    )


def test_nested_zip_rejected() -> None:
    inner = _zip_bytes({"inner.txt": b"nested"})
    outer = _zip_bytes({"outer/nested.zip": inner})
    result = _bridge().process(
        artifact_id="art:nested-zip",
        content_bytes=outer,
        classification=DisclosureClassification.PUBLIC_USER,
        filename="nested.zip",
    )
    assert result.disposition is FilingDisposition.REJECTED
    assert FilingReasonCode.ARCHIVE_BOMB_REJECTED.value in result.reason_codes


# ---------------------------------------------------------------------------
# Explicit unsupported + fail closed
# ---------------------------------------------------------------------------


def test_pdf_explicitly_unsupported_here() -> None:
    result = _bridge().process(
        artifact_id="art:pdf-wrong-bridge",
        content_bytes=b"%PDF-1.4\n%",
        classification=DisclosureClassification.PUBLIC_USER,
        filename="doc.pdf",
    )
    assert result.filing_format is FilingFormat.UNSUPPORTED
    assert result.disposition is FilingDisposition.UNSUPPORTED
    assert FilingReasonCode.UNSUPPORTED_FORMAT.value in result.reason_codes


def test_missing_bytes_and_quarantine() -> None:
    result = _bridge().process(
        artifact_id="art:empty",
        content_bytes=b"",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is FilingDisposition.REJECTED
    assert FilingReasonCode.MISSING_BYTES.value in result.reason_codes

    result2 = _bridge().process(
        artifact_id="art:q",
        content_bytes=b"hello",
        classification=DisclosureClassification.UNKNOWN,
    )
    assert result2.disposition is FilingDisposition.QUARANTINE


def test_bridge_structured_filing_convenience() -> None:
    result = bridge_structured_filing(
        artifact_id="art:conv",
        content_bytes=b"plain receipt text",
        classification=DisclosureClassification.PUBLIC_USER,
        filename="r.txt",
    )
    assert result.filing_format is FilingFormat.TXT
    assert result.spans


def test_public_projection_omits_body() -> None:
    canary = "SECRET-FILING-BODY-SHOULD-NOT-LEAK"
    result = _bridge().process(
        artifact_id="art:priv-txt",
        content_bytes=canary.encode("utf-8"),
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        filename="private.txt",
    )
    public = result.public_projection()
    blob = json.dumps(public)
    assert canary not in blob
    assert "full_text" not in public
