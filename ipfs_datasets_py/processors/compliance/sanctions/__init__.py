"""Primary-source sanctions ingestion contracts.

Importing this package performs no network access.  Acquisition is available
only through a caller-injected fetch function.
"""

from .ofac_sdn import (
    OFAC_SANCTIONS_LIST_SERVICE_URL,
    OFAC_SDN_XML_URL,
    OFAC_SLS_HOST_URL,
    OFFICIAL_OFAC_HOSTS,
    PARSER_IDENTITY,
    PARSER_VERSION,
    DigitalCurrencyIdentifier,
    OFACIngestionError,
    OFACSDNParser,
    is_official_ofac_url,
)
from .snapshot import (
    AppendOnlySnapshotJournal,
    DiagnosticSeverity,
    ParsedSanctionsSnapshot,
    PublishedHashEvidence,
    SanctionsSnapshotValidator,
    SignatureEvidence,
    SnapshotDelta,
    SnapshotDiagnostic,
    SnapshotEvidenceStatus,
    SnapshotSource,
    SnapshotValidation,
    raw_cid,
)

__all__ = [
    "AppendOnlySnapshotJournal",
    "DiagnosticSeverity",
    "DigitalCurrencyIdentifier",
    "OFFICIAL_OFAC_HOSTS",
    "OFACIngestionError",
    "OFACSDNParser",
    "OFAC_SANCTIONS_LIST_SERVICE_URL",
    "OFAC_SDN_XML_URL",
    "OFAC_SLS_HOST_URL",
    "PARSER_IDENTITY",
    "PARSER_VERSION",
    "ParsedSanctionsSnapshot",
    "PublishedHashEvidence",
    "SanctionsSnapshotValidator",
    "SignatureEvidence",
    "SnapshotDelta",
    "SnapshotDiagnostic",
    "SnapshotEvidenceStatus",
    "SnapshotSource",
    "SnapshotValidation",
    "is_official_ofac_url",
    "raw_cid",
]
