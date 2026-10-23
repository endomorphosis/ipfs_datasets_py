"""Country-law CID-keyed sparse GraphRAG packager (SkillCenter / publicus-ir family)."""

__version__ = "0.3.0"
# Layout matches SkillCenter HF release / publicus-ir family; schema string is domain-specific.
SCHEMA_VERSION = "country-laws-ir-graphrag/v1"
LAYOUT_FAMILY = "skillcenter-huggingface-release/v3"
ENTRY_IDENTITY_SCHEMA = "country-laws-entry/v1"
LAW_IDENTITY_SCHEMA = "country-laws-law/v1"
FACET_IDENTITY_SCHEMA = "country-laws-facet/v1"
EDGE_IDENTITY_SCHEMA = "country-laws-edge/v1"
MAX_ROWS_PER_FILE = 4096
TARGET_ORG = "justicedao"

# CID payload: UTF-8 bytes of json.dumps(obj, sort_keys=True, ensure_ascii=False,
# separators=(",", ":")) hashed as CIDv1 codec=raw (0x55) hash=sha2-256 (0x12)
# multibase base32 (`bafkrei...`). Same payload -> same CID.
CID_CODEC = "raw"
CID_HASH = "sha2-256"
CID_MULTIBASE = "base32"
