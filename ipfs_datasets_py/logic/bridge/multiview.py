"""Multi-view legal IR evaluation across bridge adapters."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Mapping, Optional, Sequence

from .registry import load_logic_bridge_adapter, logic_bridge_spec, logic_bridge_specs
from .types import BridgeEvaluationReport, LegalIRDocument, LogicIRView

_MULTIVIEW_CACHE_MAX_ITEMS = 1024
_MULTIVIEW_EVALUATION_CACHE: Dict[str, "MultiViewLegalIRReport"] = {}
_MULTIVIEW_EVALUATION_CACHE_LOCK = Lock()
_BRIDGE_CONTRACT_MIN_COMPONENT_WEIGHT = 0.07
_BRIDGE_CONTRACT_CORE_COMPONENTS = (
    "CEC.native",
    "deontic.ir",
    "external_provers.router",
    "modal.frame_logic",
    "TDFOL.prover",
    "knowledge_graphs.neo4j_compat",
)
_BRIDGE_CONTRACT_TAIL_PRESERVED_COMPONENTS = (
    "zkp.circuits",
)
_BRIDGE_CONTRACT_EXCLUDED_COMPONENTS: tuple[str, ...] = ()
_BRIDGE_VIEW_SIGNAL_WEIGHT_CAP = 2.0
_BRIDGE_CONTRACT_DENSE_LANE_MIN_COUNT = 4
_BRIDGE_CONTRACT_DENSE_LANE_CAPS = {
    "CEC.native": 0.18,
    "TDFOL.prover": 0.18,
    "external_provers.router": 0.12,
    "knowledge_graphs.neo4j_compat": 0.13,
    "modal.frame_logic": 0.22,
    "zkp.circuits": 0.14,
}
_BRIDGE_CONTRACT_SPARSE_CORE_LANES = (
    "TDFOL.prover",
    "deontic.ir",
    "knowledge_graphs.neo4j_compat",
)
_BRIDGE_CONTRACT_SPARSE_DEONTIC_CAP = 0.31
_BRIDGE_CONTRACT_SPARSE_DEONTIC_FLOOR = 0.20
_BRIDGE_CONTRACT_SPARSE_KG_MIN = 0.22
_BRIDGE_CONTRACT_SPARSE_KG_TARGET = 0.26
_BRIDGE_CONTRACT_SPARSE_REPEAL_DEONTIC_CAP = 0.28
_BRIDGE_CONTRACT_SPARSE_REPEAL_KG_MIN = 0.26
_BRIDGE_CONTRACT_SPARSE_OPERATIONAL_DEONTIC_CAP = 0.45
_BRIDGE_CONTRACT_SPARSE_OPERATIONAL_KG_FLOOR = 0.12
_BRIDGE_CONTRACT_SPARSE_EPISTEMIC_SHIFT = 0.025
_BRIDGE_CONTRACT_SPARSE_EPISTEMIC_KG_FLOOR = 0.22
_BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH = 0.32
_BRIDGE_CONTRACT_GUIDANCE_LANE_FLOOR = 0.08
_BRIDGE_CONTRACT_CITATION_FRAME_DEONTIC_FLOOR = 0.20
_BRIDGE_CONTRACT_CITATION_FRAME_STRUCTURE_MIN_COUNT = 3
_BRIDGE_CONTRACT_NORMATIVE_DEONTIC_FLOOR = 0.30
_BRIDGE_CONTRACT_SPARSE_SCAFFOLD_MIN_COUNT = 2
_BRIDGE_CONTRACT_SPARSE_STRUCTURAL_MIN_COUNT = 2
_BRIDGE_CONTRACT_CONDITIONAL_CUE_RE = re.compile(
    r"\b(?:if|provided\s+that|unless|subject\s+to|with\s+respect\s+to|"
    r"in\s+accordance\s+with|pursuant\s+to|for\s+each|for\s+every)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_FOR_PURPOSES_CUE_RE = re.compile(
    r"\bfor\s+purposes?\s+of\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PROVIDED_FOR_CUE_RE = re.compile(
    r"\b(?:as\s+)?provided\s+for\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_DEONTIC_CUE_RE = re.compile(
    r"\b(?:shall|should|must|may|required|requirements?|prohibited|forbidden|authorized|entitled|"
    r"authoriz(?:e|es|ed|ation|ations)|permit(?:s|ted|ting)?|allow(?:s|ed|ing)?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:before|after|until|when|within|during|deadline|transition|effective|implementation|takes\s+effect)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STRONG_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:not\s+later\s+than|no\s+later\s+than|as\s+soon\s+as\s+practicable|"
    r"beginning\s+on|ending\s+on|effective\s+date|fiscal\s+year|"
    r"on\s+and\s+after|on\s+or\s+after|from\s+and\s+after|not\s+earlier\s+than)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_MONTH_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PRIOR_TO_TEMPORAL_CUE_RE = re.compile(
    r"\bprior\s+to\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_BY_DATE_TEMPORAL_CUE_RE = re.compile(
    r"\bby\s+(?:"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)(?:\s+\d{1,2}(?:,\s*\d{4})?)?"
    r"|the\s+end\s+of\s+(?:the\s+)?(?:fiscal|calendar|taxable)\s+year"
    r"|the\s+date\b"
    r"|the\s+first\s+day\s+of\b"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r")\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:repeal(?:ed|s|ing)?|sunset(?:ted|s)?|terminate(?:d|s|ion)?|expired|expiration|"
    r"supersed(?:e|ed|es|ing))\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE = re.compile(
    r"pub\.\s*l\.",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STATUS_OPERATION_CUE_RE = re.compile(
    r"\b(?:declared|declare(?:d|s)?\s+to\s+be|abandon(?:ed|s|ing)?|"
    r"transferred|reclassified|renumbered|omitted|reserved)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_OMITTED_CODIFICATION_CUE_RE = re.compile(
    r"\b(?:omitted\s+editorial\s+notes?\s+codification|"
    r"omitted\s+from\s+the\s+code|"
    r"sections?\s+[\w\s,\.\-]+?\s+were\s+omitted\b|"
    r"was\s+omitted\s+from\s+the\s+code|"
    r"in\s+view\s+of\s+termination\s+of|"
    r"special\s+and\s+not\s+general\s+application)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_FRAME_DEFINITION_CUE_RE = re.compile(
    r"\b(?:means|defined\s+as|in\s+this\s+section)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STATUTORY_DEFINITION_SECTION_RE = re.compile(
    r"\bdefinitions?\b.{0,160}\b(?:for\s+purposes?\s+of|the\s+term|means)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_FRAME_AUTHORITY_CUE_RE = re.compile(
    r"\b(?:delegation\s+of\s+authority|delegated|powers?\s+vested|vested\s+in|"
    r"authorized\s+and\s+empowered|in\s+(?:his|her|its|their|the)\s+discretion|"
    r"in\s+the\s+discretion\s+of|through\s+(?:its|their)\s+legislative\s+assembly|"
    r"government\s+and\s+municipalit(?:y|ies)|such\s+authority)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_EFFECT_ON_EXISTING_LAW_CUE_RE = re.compile(
    r"\b(?:effect\s+on\s+existing\s+law|nothing\s+in\s+this\s+"
    r"(?:act|section|chapter|subchapter|part)\b.{0,220}\b"
    r"(?:affect(?:s|ing)?|amend(?:s|ing)?|limit(?:s|ing)?|alter(?:s|ing)?|"
    r"repeal(?:s|ing)?)"
    r".{0,120}\b(?:authority\s+of|authority\b.{0,80}\bof\s+any))\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_FRAME_ENFORCEMENT_CUE_RE = re.compile(
    r"\b(?:criminal\s+penalt(?:y|ies)|civil\s+penalt(?:y|ies)|penalt(?:y|ies)|"
    r"enforcement|violation(?:s)?|sanction(?:s)?|fine(?:s)?|preemption)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STRUCTURAL_FRAME_CUE_RE = re.compile(
    r"\b(?:definitions?|editorial\s+notes?|codification|reclassified|transferred)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STATUTE_STRUCTURE_CUE_RE = re.compile(
    r"\b(?:title|subtitle|chapter|subchapter|part|subpart)\s+(?:[ivxlcdm]+|\d+[a-z0-9\-]*)\b|\bsec\.\s*\d+[a-z0-9\-]*\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_EPISTEMIC_CUE_RE = re.compile(
    r"\b(?:determine(?:s|d)?|find(?:s|ing)?|certif(?:y|ies|ied)|conclude(?:s|d)?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_EPISTEMIC_HEADING_CUE_RE = re.compile(
    r"\b(?:findings?\s+and\s+purposes?|congress\s+finds|statement\s+of\s+policy|"
    r"sense\s+of\s+congress)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PERMISSION_DEONTIC_CUE_RE = re.compile(
    r"\b(?:may|authorized|entitled|authoriz(?:e|es|ed|ation|ations)|"
    r"permit(?:s|ted|ting)?|allow(?:s|ed|ing)?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_APPROPRIATION_NORM_CUE_RE = re.compile(
    r"\b(?:authoriz(?:e|es|ed|ation|ations)\s+appropriation(?:s)?|"
    r"appropriation(?:s)?\s+(?:is|are)\s+authorized|"
    r"authorized\s+to\s+be\s+appropriated|appropriated)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_DIRECT_APPROPRIATION_AUTHORIZATION_RE = re.compile(
    r"\b(?:there\s+(?:is|are)\s+)?authorized\s+to\s+be\s+appropriated\b"
    r".{0,240}\b(?:administrator|secretary|agency|commission|director|fund|program)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_OBLIGATION_DEONTIC_CUE_RE = re.compile(
    r"\b(?:shall|should|must|required|requirements?|prohibited|forbidden)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_NORMATIVE_SCOPE_CUE_RE = re.compile(
    r"\b(?:contracts?|grants?|benefits?|services?|assistance|"
    r"allowances?|eligibility|entitlement|programs?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_FRAME_TO_FRAME_CEC_CUE_RE = re.compile(
    r"\b(?:ascertainment|collection|recovery|administrative\s+provisions|"
    r"customs\s+duties|tariff\s+act)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STATUTE_SCAFFOLD_CUE_RE = re.compile(
    r"\b(?:united\s+states\s+code|u\.s\.\s+government\s+publishing\s+office|"
    r"historical\s+and\s+revision\s+notes|statutory\s+notes(?:\s+and\s+related\s+subsidiaries)?|"
    r"amendments?|codification|effective\s+date|references\s+in\s+text)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_ADMIN_NOTICE_HEARING_CUE_RE = re.compile(
    r"\b(?:administrative|agency|secretary|commission|board|director)\b.{0,80}\b"
    r"(?:notice|hearing|rulemaking|comment|petition)\b"
    r"|\b(?:notice|hearing|rulemaking|comment|petition)\b.{0,80}\b"
    r"(?:administrative|agency|secretary|commission|board|director)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_GOVERNANCE_CROSS_REFERENCE_CUE_RE = re.compile(
    r"\b(?:in\s+accordance\s+with|pursuant\s+to|with\s+respect\s+to|subject\s+to)\s+"
    r"(?:this\s+(?:section|chapter|subchapter|part)|title\s+\d+[a-z0-9\-]*)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_MAY_DATE_SUFFIX_RE = re.compile(
    r"^\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_CITATION_PREFIX_RE = re.compile(
    r"\b(?:\d+\s+u\.?\s*s\.?\s*c\.?|sec(?:tion)?\.?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_CITATION_TOKEN_RE = re.compile(
    r"\b\d+[a-z0-9\-\.]*\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_OFFICIAL_USC_EXCERPT_RE = re.compile(
    r"\b(?:u\.?\s*s\.?\s*c\.?\s+title|united\s+states\s+code|"
    r"u\.s\.\s+government\s+publishing\s+office|pub\.\s*l\.|"
    r"statutory\s+notes(?:\s+and\s+related\s+subsidiaries)?|"
    r"historical\s+and\s+revision\s+notes|editorial\s+notes)\b|"
    r"^\s*§\s*\d+[a-z0-9\-\.]*\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_OFFICIAL_USC_MIN_CHARS = 520
_BRIDGE_CONTRACT_SHORT_OFFICIAL_USC_MIN_CHARS = 160
_BRIDGE_CONTRACT_STATUS_OFFICIAL_USC_MIN_CHARS = 80
_BRIDGE_CONTRACT_USC_SECTION_MARKER_RE = re.compile(
    r"^\s*(?:§|\u00a7){1,2}\s*\d+[a-z0-9\-\.]*\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_STATUTES_AT_LARGE_CUE_RE = re.compile(
    r"\b\d+\s+stat\.\s+\d+\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PRIMARY_AUTOENCODER_LANES = (
    "CEC.native",
    "TDFOL.prover",
    "deontic.ir",
    "knowledge_graphs.neo4j_compat",
)
_BRIDGE_CONTRACT_AUXILIARY_AUTOENCODER_LANES = (
    "external_provers.router",
    "modal.frame_logic",
    "zkp.circuits",
)
_BRIDGE_CONTRACT_ADMIN_RULEMAKING_SCHEDULE_RE = re.compile(
    r"\b(?:administrator|secretary|agency|commission|board|director)\b.{0,180}\b"
    r"(?:promulgate|petition|notice|comment|determines?|phase\s+out|phasing\s+out|"
    r"by\s+regulation\s+establish|establish\b.{0,80}\bstandards?)\b"
    r"|\b(?:promulgate|petition|notice|comment|determines?|phase\s+out|phasing\s+out|"
    r"by\s+regulation\s+establish|establish\b.{0,80}\bstandards?)\b"
    r".{0,180}\b(?:administrator|secretary|agency|commission|board|director)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_REGULATORY_COST_ESTIMATE_RE = re.compile(
    r"\b(?:costs?\s+of\s+regulations?|regulations?.{0,120}\bcosts?|"
    r"estimate\s+(?:the\s+)?costs?|cost\s+estimate|unfunded\s+mandates?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_CONSTRUCTION_EXEMPTION_RE = re.compile(
    r"\b(?:construction\b.{0,120}\bnothing\s+in\s+this\s+"
    r"(?:section|chapter|subchapter|part)|"
    r"nothing\s+in\s+this\s+(?:section|chapter|subchapter|part)\s+"
    r"shall\s+(?:apply|be\s+construed|affect|limit))\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_ENFORCEMENT_PENALTY_PROVISION_RE = re.compile(
    r"\b(?:penalt(?:y|ies)|misdemeanor|without\s+first\s+obtaining\s+authority|"
    r"shall\s+be\s+guilty)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_COMPLIANCE_ENFORCEMENT_NORM_RE = re.compile(
    r"\b(?:compliance\s+with\s+requirements?|requirements?\s+imposed)\b"
    r".{0,160}\bshall\s+be\s+enforced\b"
    r"|\bshall\s+be\s+enforced\b.{0,160}\b(?:compliance|requirements?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_FISCAL_AVAILABILITY_NORM_RE = re.compile(
    r"\b(?:may|shall)\s+make\s+available\b.{0,180}\b"
    r"(?:amounts?|funds?|appropriations?\s+account)\b"
    r"|\b(?:amounts?|funds?|appropriations?\s+account)\b.{0,180}\b"
    r"(?:may|shall)\s+be\s+made\s+available\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_LIABILITY_PROVISION_RE = re.compile(
    r"\b(?:liable\s+for|liability\s+for|scope\s+of\s+(?:his|her|its|their|the)\s+"
    r"authority|acts?\s+of\s+(?:its|their|the)\s+officers?\s+and\s+agents?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_REPORTING_DUTY_RE = re.compile(
    r"\b(?:annual\s+report|submit\s+(?:to|an?\s+annual\s+report)|"
    r"report\s+(?:shall|submitted|required\s+by)|contents?\s+of\s+report|"
    r"include\s+all\s+assessments\s+in\s+the\s+report)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_DETERMINATION_CONDITION_RE = re.compile(
    r"\b(?:determination\s+of|shall\s+have\s+determined|shall\s+not\s+be\s+"
    r"exercised|unless\s+the\s+president\s+finds|conditions?\s+exist|"
    r"requisite\s+conditions?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PREEMPTION_CONTRACT_NORM_RE = re.compile(
    r"\b(?:preempt(?:s|ed|ion)?|no\s+other\s+state\s+may\s+deny)\b"
    r".{0,260}\b(?:contracts?|agreements?|credit|rights?|reinsurance)\b"
    r"|\b(?:contracts?|agreements?|credit|rights?|reinsurance)\b.{0,260}\b"
    r"(?:preempt(?:s|ed|ion)?|no\s+other\s+state\s+may\s+deny)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_REFERENCES_REPEAL_CROSSREF_RE = re.compile(
    r"\breferences\s+in\s+text\b.{0,420}\b(?:was\s+)?repealed\s+by\b"
    r"|\b(?:was\s+)?repealed\s+by\b.{0,420}\breferences\s+in\s+text\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_REPEALED_PUBLIC_LAW_STATUS_RE = re.compile(
    r"\b(?:sec\.\s*[\w\-\.]+\s*-\s*)?repealed\b.{0,220}\bpub\.\s*l\.\s*\d+[-\u2011]\d+"
    r"|\bpub\.\s*l\.\s*\d+[-\u2011]\d+\b.{0,220}\brepealed\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_RENAMING_DESIGNATION_RE = re.compile(
    r"\b(?:change\s+in\s+name|shall\s+(?:on\s+and\s+after\s+)?"
    r"(?:be\s+known|be\s+held\s+to\s+refer)|designated\s+or\s+referred\s+to|"
    r"renamed)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PURPOSE_POLICY_STATEMENT_RE = re.compile(
    r"\b(?:congressional\s+statement\s+of\s+purpose|statement\s+of\s+purpose|"
    r"purpose\s+of\s+(?:institute|chapter|subchapter|part)|"
    r"general\s+purpose\s+of|it\s+is\s+the\s+policy\s+of\s+the\s+congress|"
    r"policy\s+of\s+the\s+congress|sense\s+of\s+congress|"
    r"purpose\s+of\s+this\s+chapter)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_DEFINITION_PROVISION_RE = re.compile(
    r"\b(?:sec\.\s*[\w\-\.]+\s*-\s*definition|"
    r"§\s*[\w\-\.]+\.?\s*definitions?|"
    r"in\s+this\s+(?:section|subchapter|chapter|part|subpart)\b.{0,120}\b"
    r"(?:term\s+[\w\s\"']+?\s+means|means\s+a|means\s+an|means\s+the))",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_ASSET_TRANSFER_RULE_RE = re.compile(
    r"\b(?:asset\s+transfer\s+rules?|transfer\s+of\s+assets?|"
    r"transfer\s+of\s+plan\s+(?:assets|liabilities)|multiemployer\s+plan)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_TITLE_TRANSFER_AUTHORITY_RE = re.compile(
    r"\btransfer\s+of\s+title\b"
    r"|\btransfer\s+title\s+to\b"
    r"|\b(?:secretary|administrator|commission|director)\b.{0,180}\b"
    r"(?:may|authorized)\b.{0,180}\btransfer\s+title\b"
    r"|\btransfer\s+title\b.{0,180}\b"
    r"(?:canals?|appurtenant\s+structures?|power\s+development|project\s+works?|facilities)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_SAFETY_REGULATORY_PROCEDURE_RE = re.compile(
    r"\b(?:marine\s+environmental\s+protection|navigational\s+safety|"
    r"safety\s+zones?|safety\s+of\s+(?:life|property)|"
    r"prevent\s+pollution|clean\s+up\s+any\s+pollutants?|"
    r"prescribe\s+and\s+enforce\s+procedures?|"
    r"issue\s+and\s+enforce\s+regulations?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_SAVINGS_EXISTING_LAW_RE = re.compile(
    r"\b(?:savings?\s+provisions?|nothing\s+in\s+this\s+"
    r"(?:act|section|chapter|subchapter|part)\s+shall\s+be\s+(?:construed|deemed)\s+"
    r"(?:as\s+)?(?:to\s+)?"
    r"(?:amend(?:ing)?|repeal(?:ing)?|affect(?:ing)?|limit(?:ing)?)|"
    r"nothing\s+in\s+this\s+(?:act|section|chapter|subchapter|part)\b.{0,220}\b"
    r"(?:affect(?:s|ing)?|limit(?:s|ing)?|alter(?:s|ing)?)\b.{0,120}\b"
    r"(?:authority\s+of|authority\b.{0,80}\bof\s+any)|"
    r"shall\s+not\s+be\s+deemed\s+to\s+(?:amend|repeal|affect|limit))\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_DECEPTIVE_ADVERTISING_NORM_RE = re.compile(
    r"\b(?:false\s+advertisements?|unfair\s+or\s+deceptive\s+act\s+or\s+practice|"
    r"shall\s+be\s+unlawful\b.{0,220}\b(?:advertisements?|disseminate)|"
    r"disseminat(?:e|ed|ion)\b.{0,220}\b(?:false\s+advertisements?|"
    r"unfair\s+or\s+deceptive\s+act\s+or\s+practice))\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PERFORMANCE_PLAN_ASSESSMENT_RE = re.compile(
    r"\b(?:annual\s+performance\s+plan|performance\s+plan\s+conducted|"
    r"shall\s+conduct\b.{0,180}\bperformance\s+plan|"
    r"shall\s+include\s+an\s+assessment\b.{0,220}\bgoals?)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_SUBSTANTIVE_OPERATIONAL_NORM_RE = re.compile(
    r"\b(?:authorized\s+to\s+(?:employ|be\s+appropriated)|"
    r"there\s+(?:is|are)\s+established|shall\s+be\s+composed|"
    r"shall\s+constitute\s+a\s+quorum|shall\s+meet|shall\s+be\s+available|"
    r"shall\s+be\s+used|shall\s+give\s+priority|may\s+be\s+allowed|"
    r"shall\s+cause\s+to\s+have\s+prepared)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_RECURRING_REPORT_DEADLINE_RE = re.compile(
    r"\b(?:annual\s+report|report\s+covering\s+the\s+preceding\s+"
    r"(?:fiscal|calendar|taxable)\s+year)\b.{0,260}\b"
    r"(?:on\s+or\s+before|not\s+later\s+than|no\s+later\s+than|each\s+"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?))\b"
    r"|\b(?:on\s+or\s+before|not\s+later\s+than|no\s+later\s+than|each\s+"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?))\b.{0,260}\b(?:annual\s+report|report\s+covering\s+"
    r"the\s+preceding\s+(?:fiscal|calendar|taxable)\s+year)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_RETIREMENT_ELECTION_RULE_RE = re.compile(
    r"\b(?:federal\s+employees'\s+retirement\s+system|fers|retirement\s+"
    r"and\s+disability\s+system|chapter\s+84\s+of\s+title\s+5)\b.{0,320}\b"
    r"(?:shall\s+(?:be\s+subject|not\s+apply)|may\s+elect|election\s+"
    r"shall|shall\s+be\s+irrevocable|excluded\s+under)\b"
    r"|\b(?:shall\s+(?:be\s+subject|not\s+apply)|may\s+elect|election\s+"
    r"shall|shall\s+be\s+irrevocable|excluded\s+under)\b.{0,320}\b"
    r"(?:federal\s+employees'\s+retirement\s+system|fers|retirement\s+"
    r"and\s+disability\s+system|chapter\s+84\s+of\s+title\s+5)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_PENALTY_NONCOMPLIANCE_PERIOD_RE = re.compile(
    r"\b(?:penalt(?:y|ies)|failure\s+to\s+pay|noncompliance\s+period|"
    r"liable\s+for\s+the\s+penalty)\b.{0,300}\b"
    r"(?:per\s+day|beginning\s+on|ending\s+on|due\s+date|date\s+of\s+"
    r"payment|reasonable\s+cause|willful\s+neglect)\b"
    r"|\b(?:per\s+day|beginning\s+on|ending\s+on|due\s+date|date\s+of\s+"
    r"payment|reasonable\s+cause|willful\s+neglect)\b.{0,300}\b"
    r"(?:penalt(?:y|ies)|failure\s+to\s+pay|noncompliance\s+period|"
    r"liable\s+for\s+the\s+penalty)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_OFFICIAL_NOTICE_DUTY_RE = re.compile(
    r"\b(?:seal|judicial\s+notice)\b.{0,180}\b"
    r"(?:director\s+shall|shall\s+use|shall\s+be\s+taken)\b"
    r"|\b(?:director\s+shall|shall\s+use|shall\s+be\s+taken)\b.{0,180}\b"
    r"(?:seal|judicial\s+notice)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_ADMIN_REVIEW_DEADLINE_RE = re.compile(
    r"\b(?:review|approve|approval|modification|modifications|submit|"
    r"submitted)\b.{0,320}\b(?:ordinance|resolution|management\s+contract|"
    r"collateral\s+agreements?|chairman|commission)\b.{0,320}\b"
    r"(?:within\s+\d+\s+days|not\s+more\s+than\s+\d+\s+days|by\s+no\s+"
    r"later\s+than|shall\s+provide\s+written\s+notification)\b"
    r"|\b(?:within\s+\d+\s+days|not\s+more\s+than\s+\d+\s+days|by\s+no\s+"
    r"later\s+than|shall\s+provide\s+written\s+notification)\b.{0,320}\b"
    r"(?:ordinance|resolution|management\s+contract|collateral\s+"
    r"agreements?|chairman|commission)\b",
    flags=re.IGNORECASE,
)
_BRIDGE_CONTRACT_JUDICIAL_REVIEW_PROCEDURE_RE = re.compile(
    r"\bjudicial\s+review\b.{0,420}\b(?:court\s+of\s+appeals|petition|"
    r"jurisdiction|record\s+in\s+the\s+proceeding|automatic\s+stay)\b"
    r"|\b(?:court\s+of\s+appeals|petition|jurisdiction|record\s+in\s+"
    r"the\s+proceeding|automatic\s+stay)\b.{0,420}\bjudicial\s+review\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class LegalIRTrainingTarget:
    """Canonical optimizer target derived from a multi-view legal IR document."""

    bridge_names: Sequence[str]
    document: LegalIRDocument
    losses: Mapping[str, float] = field(default_factory=dict)
    adapter_losses: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    view_distribution: Mapping[str, float] = field(default_factory=dict)
    accepted: bool = False

    @property
    def total_loss(self) -> float:
        return float(self.losses.get("legal_ir_multiview_total_loss", 0.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adapter_losses": {
                name: dict(sorted(losses.items()))
                for name, losses in sorted(self.adapter_losses.items())
            },
            "bridge_names": list(self.bridge_names),
            "document_hash": self.document.canonical_hash(),
            "document_id": self.document.document_id,
            "document_version": self.document.version,
            "losses": dict(sorted(self.losses.items())),
            "total_loss": self.total_loss,
            "view_distribution": dict(sorted(self.view_distribution.items())),
        }


@dataclass(frozen=True)
class MultiViewLegalIRReport:
    """Canonical legal IR document plus the bridge reports that produced it."""

    bridge_names: Sequence[str]
    document: LegalIRDocument
    reports: Mapping[str, BridgeEvaluationReport] = field(default_factory=dict)
    failures: Mapping[str, str] = field(default_factory=dict)

    @property
    def attempted_count(self) -> int:
        return len(self.bridge_names)

    @property
    def accepted_count(self) -> int:
        return sum(1 for report in self.reports.values() if report.accepted)

    @property
    def acceptance_rate(self) -> float:
        if self.attempted_count <= 0:
            return 0.0
        return self.accepted_count / self.attempted_count

    @property
    def proof_failure_ratio(self) -> float:
        return _mean_with_failures(
            [
                report.effective_proof_failure_ratio
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    @property
    def graph_failure_penalty(self) -> float:
        return _mean_with_failures(
            [
                report.graph_projection.graph_failure_penalty
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    @property
    def total_loss(self) -> float:
        return _mean_with_failures(
            [report.total_loss for report in self.reports.values()],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    @property
    def view_count(self) -> int:
        return len(self.document.views)

    @property
    def accepted(self) -> bool:
        return (
            self.attempted_count > 0
            and not self.failures
            and len(self.reports) == self.attempted_count
            and all(report.accepted for report in self.reports.values())
        )

    def loss_vector(self) -> Dict[str, float]:
        """Return adapter-scoped losses for optimizer dashboards."""

        losses: Dict[str, float] = self.canonical_loss_vector()
        for adapter_name, report in sorted(self.reports.items()):
            prefix = _loss_prefix(adapter_name)
            round_trip = report.round_trip
            losses[f"{prefix}.cosine_loss"] = float(round_trip.cosine_loss)
            losses[f"{prefix}.cross_entropy_loss"] = float(round_trip.cross_entropy_loss)
            losses[f"{prefix}.graph_failure_penalty"] = float(
                report.graph_projection.graph_failure_penalty
            )
            losses[f"{prefix}.proof_failure_ratio"] = float(
                report.effective_proof_failure_ratio
            )
            losses[f"{prefix}.raw_proof_failure_ratio"] = float(
                report.proof_gate.failure_ratio
            )
            losses[f"{prefix}.reconstruction_loss"] = float(round_trip.reconstruction_loss)
            losses[f"{prefix}.text_reconstruction_loss"] = float(
                round_trip.text_reconstruction_loss
            )
            losses[f"{prefix}.total_loss"] = float(report.total_loss)
            for name, value in sorted(round_trip.extra_losses.items()):
                losses[f"{prefix}.{name}"] = _float_or_zero(value)
        for adapter_name in sorted(self.failures):
            losses[f"{_loss_prefix(adapter_name)}.bridge_evaluation_failure_loss"] = 1.0
        return dict(sorted(losses.items()))

    def canonical_loss_vector(self) -> Dict[str, float]:
        """Return unscoped losses for treating the merged IR as one target."""

        return dict(
            sorted(
                {
                    "legal_ir_multiview_acceptance_loss": max(
                        0.0,
                        1.0 - self.acceptance_rate,
                    ),
                    "legal_ir_view_cross_entropy_loss": (
                        self._legal_ir_view_cross_entropy_loss()
                    ),
                    "legal_ir_multiview_cosine_loss": self._round_trip_mean("cosine_loss"),
                    "legal_ir_multiview_cross_entropy_loss": self._round_trip_mean(
                        "cross_entropy_loss"
                    ),
                    "legal_ir_multiview_frame_logic_missing_loss": 0.0
                    if self.document.has_frame_logic
                    else 1.0,
                    "legal_ir_multiview_graph_failure_penalty": self.graph_failure_penalty,
                    "legal_ir_multiview_proof_failure_ratio": self.proof_failure_ratio,
                    "legal_ir_multiview_reconstruction_loss": self._round_trip_mean(
                        "reconstruction_loss"
                    ),
                    "legal_ir_multiview_text_reconstruction_loss": self._round_trip_mean(
                        "text_reconstruction_loss"
                    ),
                    "legal_ir_multiview_total_loss": self.total_loss,
                    "legal_ir_multiview_view_coverage_loss": self.view_coverage_loss(),
                    "source_decompiled_text_embedding_cosine_loss": (
                        self._round_trip_extra_mean(
                            "source_decompiled_text_embedding_cosine_loss"
                        )
                    ),
                    "source_decompiled_text_token_loss": self._round_trip_extra_mean(
                        "source_decompiled_text_token_loss"
                    ),
                }.items()
            )
        )

    def training_target(self) -> LegalIRTrainingTarget:
        """Return the merged legal IR document as the optimizer training target."""

        adapter_losses = {
            adapter_name: {
                key.split(".", 1)[1]: value
                for key, value in self.loss_vector().items()
                if key.startswith(f"{_loss_prefix(adapter_name)}.")
            }
            for adapter_name in self.bridge_names
        }
        contract_distribution = self.contract_view_distribution()
        return LegalIRTrainingTarget(
            bridge_names=tuple(self.bridge_names),
            document=self.document,
            losses=self.canonical_loss_vector(),
            adapter_losses=adapter_losses,
            view_distribution=contract_distribution or self.view_distribution(),
            accepted=self.accepted,
        )

    def view_distribution(self) -> Dict[str, float]:
        """Return a normalized distribution over canonical bridge contract lanes.

        The canonical distribution intentionally collapses fine-grained adapter
        internals (for example ``deontic.exports`` and ``deontic.metrics``)
        into stable optimizer-facing component lanes (for example
        ``deontic.ir``). This keeps the LegalIR view target space compact and
        deterministic across adapters while preserving cross-family routing
        signals for ``bridge.contracts`` repair actions.
        """

        adapter_component_weights: Dict[str, Dict[str, float]] = {}
        adapter_total_weights: Dict[str, float] = {}
        for view_name, view in self.document.views.items():
            component = _canonical_bridge_component_name(
                str(view.source_component or ""),
            )
            if not component:
                adapter_name = str(view.metadata.get("adapter_name") or "").strip()
                if adapter_name:
                    try:
                        component = _canonical_bridge_component_name(
                            logic_bridge_spec(adapter_name).target_component,
                        )
                    except KeyError:
                        component = ""
            if not component:
                component = _canonical_bridge_component_name(str(view.format or ""))
            if not component:
                component = str(view_name or view.name)
            adapter_name = _adapter_name_for_view(view_name, view)
            signal_weight = _view_signal_weight(view)
            component_weights = adapter_component_weights.setdefault(adapter_name, {})
            component_weights[component] = component_weights.get(component, 0.0) + signal_weight
            adapter_total_weights[adapter_name] = (
                adapter_total_weights.get(adapter_name, 0.0) + signal_weight
            )

        counts: Dict[str, float] = {}
        for adapter_name, component_weights in sorted(adapter_component_weights.items()):
            total_weight = adapter_total_weights.get(adapter_name, 0.0)
            if total_weight <= 0.0:
                continue
            report = self.reports.get(adapter_name)
            adapter_mass = _adapter_view_distribution_mass(report)
            for component, weight in component_weights.items():
                counts[component] = counts.get(component, 0.0) + (
                    adapter_mass * (weight / total_weight)
                )

        total = float(sum(counts.values()))
        if total <= 0.0:
            return {}
        return {
            component: count / total
            for component, count in sorted(counts.items())
        }

    def view_coverage_loss(self) -> float:
        """Return missing expected bridge views as a compact loss."""

        expected_count = 0
        present_count = 0
        for adapter_name in self.bridge_names:
            try:
                expected_views = tuple(logic_bridge_spec(adapter_name).target_views)
            except KeyError:
                expected_views = ()
            if not expected_views:
                continue
            expected_count += len(expected_views)
            present_views = {
                str(view.metadata.get("original_view_name") or view.name)
                for view_name, view in self.document.views.items()
                if str(view_name).startswith(f"{adapter_name}.")
            }
            present_count += sum(1 for view_name in expected_views if view_name in present_views)
        if expected_count <= 0:
            return 0.0
        return max(0.0, 1.0 - min(1.0, present_count / expected_count))

    def contract_view_distribution(self) -> Dict[str, float]:
        """Return a compact bridge-contract view distribution for autoencoder targets.

        The multiview report keeps raw adapter lanes in ``view_distribution()``
        for diagnostics.  For optimizer-facing ``bridge.contracts`` routing, we
        collapse adapter-specific outputs into stable legal-IR family lanes and
        prune very small tail mass to reduce distribution entropy without hiding
        frame-logic or prover gaps from the autoencoder.
        """

        canonical = self.view_distribution()
        if not canonical:
            return {}

        lane_weights: Dict[str, float] = {}
        for component, value in canonical.items():
            lane = _bridge_contract_lane_component(component)
            if not lane:
                continue
            if lane in _BRIDGE_CONTRACT_EXCLUDED_COMPONENTS:
                continue
            lane_weights[lane] = lane_weights.get(lane, 0.0) + max(0.0, float(value))

        if not lane_weights:
            return {}

        kept = {
            lane: weight
            for lane, weight in lane_weights.items()
            if (
                lane in _BRIDGE_CONTRACT_CORE_COMPONENTS
                or lane in _BRIDGE_CONTRACT_TAIL_PRESERVED_COMPONENTS
                or weight >= _BRIDGE_CONTRACT_MIN_COMPONENT_WEIGHT
            )
        }
        if len(kept) < 2:
            top_lanes = sorted(
                lane_weights.items(),
                key=lambda item: (-item[1], item[0]),
            )[:2]
            kept = {lane: weight for lane, weight in top_lanes}

        total = sum(kept.values())
        if total <= 0.0:
            return {}
        normalized = {
            lane: weight / total
            for lane, weight in sorted(kept.items())
        }
        rebalanced = _rebalance_dense_contract_distribution(
            normalized,
            text=self.document.normalized_text or self.document.source_text,
        )
        rebalanced = _rebalance_sparse_contract_distribution(
            rebalanced,
            text=self.document.normalized_text or self.document.source_text,
        )
        rebalanced = _compact_official_usc_contract_distribution(
            rebalanced,
            text=self.document.normalized_text or self.document.source_text,
        )
        rebalanced = _project_guided_contract_distribution(
            rebalanced,
            metadata=self.document.metadata,
        )
        rebalance_total = sum(rebalanced.values())
        if rebalance_total <= 0.0:
            return normalized
        return {
            lane: weight / rebalance_total
            for lane, weight in sorted(rebalanced.items())
        }

    def _round_trip_mean(self, metric_name: str) -> float:
        return _mean_with_failures(
            [
                _float_or_zero(getattr(report.round_trip, metric_name, 0.0))
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    def _round_trip_extra_mean(self, metric_name: str) -> float:
        return _mean_with_failures(
            [
                _float_or_zero(report.round_trip.extra_losses.get(metric_name, 0.0))
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    def _legal_ir_view_cross_entropy_loss(self) -> float:
        return _mean_with_failures(
            [
                _float_or_zero(
                    report.round_trip.extra_losses.get(
                        "legal_ir_view_cross_entropy_loss",
                        report.round_trip.cross_entropy_loss,
                    )
                )
                for report in self.reports.values()
            ],
            failure_count=len(self.failures),
            expected_count=self.attempted_count,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "accepted_count": self.accepted_count,
            "acceptance_rate": self.acceptance_rate,
            "attempted_count": self.attempted_count,
            "bridge_names": list(self.bridge_names),
            "canonical_loss_vector": self.canonical_loss_vector(),
            "document": self.document.to_dict(),
            "failures": dict(sorted(self.failures.items())),
            "graph_failure_penalty": self.graph_failure_penalty,
            "loss_vector": self.loss_vector(),
            "proof_failure_ratio": self.proof_failure_ratio,
            "reports": {
                name: report.to_dict()
                for name, report in sorted(self.reports.items())
            },
            "total_loss": self.total_loss,
            "training_target": self.training_target().to_dict(),
            "view_count": self.view_count,
            "view_coverage_loss": self.view_coverage_loss(),
            "view_distribution": self.view_distribution(),
        }


def evaluate_legal_ir_multiview(
    text: str,
    *,
    bridge_names: Optional[Sequence[str]] = None,
    cache: bool = True,
    citation: Optional[str] = None,
    document_id: Optional[str] = None,
    evaluate_provers: Optional[bool] = None,
    compiler_guidance: Optional[Mapping[str, Any]] = None,
    source: str = "us_code",
    source_embedding: Optional[Sequence[float]] = None,
) -> MultiViewLegalIRReport:
    """Evaluate legal text through multiple bridge adapters as one IR document."""

    names = _bridge_names(bridge_names)
    cache_key = _multiview_cache_key(
        text,
        bridge_names=names,
        citation=citation,
        document_id=document_id,
        evaluate_provers=evaluate_provers,
        compiler_guidance=compiler_guidance,
        source=source,
        source_embedding=source_embedding,
    )
    if cache:
        with _MULTIVIEW_EVALUATION_CACHE_LOCK:
            cached = _MULTIVIEW_EVALUATION_CACHE.get(cache_key)
        if cached is not None:
            return cached

    reports: Dict[str, BridgeEvaluationReport] = {}
    failures: Dict[str, str] = {}

    def evaluate_name(name: str) -> tuple[str, Optional[BridgeEvaluationReport], Optional[str]]:
        try:
            adapter = load_logic_bridge_adapter(name)
            return (
                name,
                _evaluate_adapter(
                    adapter,
                    text,
                    citation=citation,
                    document_id=document_id,
                    evaluate_provers=evaluate_provers,
                    compiler_guidance=compiler_guidance,
                    source=source,
                    source_embedding=source_embedding,
                ),
                None,
            )
        except Exception as exc:
            return name, None, f"{type(exc).__name__}: {exc}"

    adapter_workers = _adapter_worker_count(len(names))
    if adapter_workers <= 1:
        adapter_results = [evaluate_name(name) for name in names]
    else:
        with ThreadPoolExecutor(
            max_workers=adapter_workers,
            thread_name_prefix="legal-ir-bridge-adapters",
        ) as executor:
            adapter_results = list(executor.map(evaluate_name, names))

    for name, report, error in adapter_results:
        if report is not None:
            reports[name] = report
        elif error is not None:
            failures[name] = error

    document = _merge_reports_to_document(
        text,
        bridge_names=names,
        citation=citation,
        document_id=document_id,
        compiler_guidance=compiler_guidance,
        failures=failures,
        reports=reports,
        source=source,
    )
    result = MultiViewLegalIRReport(
        bridge_names=names,
        document=document,
        reports=reports,
        failures=failures,
    )
    if cache:
        with _MULTIVIEW_EVALUATION_CACHE_LOCK:
            if len(_MULTIVIEW_EVALUATION_CACHE) >= _MULTIVIEW_CACHE_MAX_ITEMS:
                _MULTIVIEW_EVALUATION_CACHE.pop(next(iter(_MULTIVIEW_EVALUATION_CACHE)))
            _MULTIVIEW_EVALUATION_CACHE[cache_key] = result
    return result


def _adapter_worker_count(item_count: int) -> int:
    if item_count <= 1:
        return 1
    raw = os.environ.get("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "").strip()
    if not raw:
        return 1
    try:
        requested = int(raw)
    except ValueError:
        return 1
    return max(1, min(requested, item_count))


def _multiview_cache_key(
    text: str,
    *,
    bridge_names: Sequence[str],
    citation: Optional[str],
    document_id: Optional[str],
    evaluate_provers: Optional[bool],
    compiler_guidance: Optional[Mapping[str, Any]],
    source: str,
    source_embedding: Optional[Sequence[float]],
) -> str:
    digest = hashlib.sha256()
    for value in (
        "\0".join(bridge_names),
        citation or "",
        document_id or "",
        str(evaluate_provers),
        _compiler_guidance_digest(compiler_guidance),
        source,
        text or "",
        _source_embedding_digest(source_embedding),
    ):
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_embedding_digest(source_embedding: Optional[Sequence[float]]) -> str:
    if source_embedding is None:
        return ""
    digest = hashlib.sha256()
    for value in source_embedding:
        try:
            digest.update(f"{float(value):.9g},".encode("ascii"))
        except (TypeError, ValueError):
            digest.update(str(value).encode("utf-8"))
            digest.update(b",")
    return digest.hexdigest()


def _compiler_guidance_digest(compiler_guidance: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(compiler_guidance, Mapping) or not compiler_guidance:
        return ""
    try:
        return json.dumps(
            dict(compiler_guidance),
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
    except Exception:
        return str(compiler_guidance)


def _compiler_guidance_bridge_contract_metadata(
    compiler_guidance: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Distill autoencoder evidence into deterministic bridge.contracts lanes."""

    if not isinstance(compiler_guidance, Mapping) or not compiler_guidance:
        return {}

    evidence_rows = _compiler_guidance_evidence_rows(compiler_guidance)
    routes = _compiler_guidance_routes(compiler_guidance, evidence_rows=evidence_rows)
    target_components = _compiler_guidance_target_components(
        compiler_guidance,
        evidence_rows=evidence_rows,
    )
    if not (
        "repair_multiview_legal_ir_loss" in routes
        or "repair_multiview_legal_ir_graph_projection" in routes
        or "bridge.contracts" in target_components
        or any(_evidence_row_targets_bridge_contracts(row) for row in evidence_rows)
    ):
        return {}

    lane_scores: Dict[str, float] = {}
    component_gaps: Dict[str, float] = {}

    def add_lane(value: Any, score: float = 1.0) -> None:
        lane = _bridge_contract_lane_component(
            _canonical_bridge_component_name(str(value or "")),
        )
        if lane:
            lane_scores[lane] = lane_scores.get(lane, 0.0) + max(0.0, float(score))

    def collect(mapping: Mapping[str, Any]) -> None:
        for key in ("target_view", "predicted_view", "target_component"):
            add_lane(mapping.get(key))
        for key in (
            "legal_ir_underrepresented_components",
            "underrepresented_components",
        ):
            for value in _guidance_sequence(mapping.get(key)):
                add_lane(value)
        for key in (
            "legal_ir_target_view_distribution",
            "compiler_guidance_legal_ir_view_gap_distribution",
        ):
            for lane, score in _guidance_distribution_items(mapping.get(key)):
                add_lane(lane, score)
        for lane, score in _guidance_distribution_items(
            mapping.get("legal_ir_component_gaps")
        ):
            canonical_lane = _bridge_contract_lane_component(
                _canonical_bridge_component_name(lane)
            )
            if canonical_lane:
                component_gaps[canonical_lane] = float(score)
                if score > 0.0:
                    add_lane(lane, score)

    collect(compiler_guidance)
    for mapping in _compiler_guidance_nested_mappings(compiler_guidance):
        collect(mapping)
    for evidence in evidence_rows:
        collect(evidence)

    target_distribution = _normalize_positive_mapping(lane_scores)
    if not target_distribution:
        return {}
    return {
        "compiler_guidance_bridge_contract_evidence_count": len(evidence_rows),
        "compiler_guidance_bridge_contract_projection_strength": (
            _BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH
        ),
        "compiler_guidance_bridge_contract_target_distribution": target_distribution,
        "compiler_guidance_bridge_contract_target_lanes": sorted(target_distribution),
        "compiler_guidance_component_gaps": dict(sorted(component_gaps.items())),
    }


def _compiler_guidance_routes(
    compiler_guidance: Mapping[str, Any],
    *,
    evidence_rows: Sequence[Mapping[str, Any]],
) -> set[str]:
    routes: set[str] = set()
    keys = (
        "action",
        "route",
        "compiler_guidance_route",
        "loss_name",
        "bridge_failure_name",
    )
    for mapping in (
        compiler_guidance,
        *_compiler_guidance_nested_mappings(compiler_guidance),
        *evidence_rows,
    ):
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                routes.add(value.strip())
        for key in ("compiler_guidance_todo_routes", "todo_routes", "routes"):
            raw_routes = mapping.get(key)
            if isinstance(raw_routes, Mapping):
                routes.update(str(route) for route in raw_routes if str(route).strip())
            else:
                routes.update(str(route) for route in _guidance_sequence(raw_routes))
    return routes


def _compiler_guidance_target_components(
    compiler_guidance: Mapping[str, Any],
    *,
    evidence_rows: Sequence[Mapping[str, Any]],
) -> set[str]:
    components: set[str] = set()
    keys = ("target", "target_component", "target_view", "predicted_view")
    for mapping in (
        compiler_guidance,
        *_compiler_guidance_nested_mappings(compiler_guidance),
        *evidence_rows,
    ):
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                components.add(value.strip())
    return components


def _compiler_guidance_nested_mappings(
    compiler_guidance: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    mappings: list[Mapping[str, Any]] = []
    for key in (
        "bundle",
        "compiler_guidance_bundle",
        "semantic_bundle",
        "compiler_guidance_attribution",
    ):
        value = compiler_guidance.get(key)
        if isinstance(value, Mapping):
            mappings.append(value)
    return tuple(mappings)


def _compiler_guidance_evidence_rows(
    compiler_guidance: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for key in (
        "evidence",
        "hint_evidence",
        "compiler_guidance_evidence",
        "metric_sample_payloads",
    ):
        value = compiler_guidance.get(key)
        if isinstance(value, Mapping):
            rows.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            rows.extend(item for item in value if isinstance(item, Mapping))
    return tuple(rows)


def _evidence_row_targets_bridge_contracts(row: Mapping[str, Any]) -> bool:
    target = str(row.get("target_component") or row.get("target") or "").strip()
    failure = str(row.get("bridge_failure_name") or row.get("loss_name") or "").strip()
    return target == "bridge.contracts" or failure.startswith("legal_ir_")


def _guidance_sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or value is None:
        return () if value is None else (value,)
    if isinstance(value, Mapping):
        return tuple(value)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _guidance_distribution_items(value: Any) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, Mapping):
        return ()
    items: list[tuple[str, float]] = []
    for raw_lane, raw_score in value.items():
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if score == 0.0:
            continue
        items.append((str(raw_lane), score))
    return tuple(items)


def _normalize_positive_mapping(values: Mapping[str, float]) -> Dict[str, float]:
    positive = {
        str(name): max(0.0, float(value))
        for name, value in dict(values or {}).items()
        if float(value) > 0.0
    }
    total = sum(positive.values())
    if total <= 0.0:
        return {}
    return {name: value / total for name, value in sorted(positive.items())}


def _evaluate_adapter(
    adapter: Any,
    text: str,
    *,
    citation: Optional[str],
    document_id: Optional[str],
    evaluate_provers: Optional[bool],
    compiler_guidance: Optional[Mapping[str, Any]],
    source: str,
    source_embedding: Optional[Sequence[float]],
) -> BridgeEvaluationReport:
    kwargs: Dict[str, Any] = {
        "citation": citation,
        "document_id": document_id,
        "source": source,
        "source_embedding": source_embedding,
    }
    if evaluate_provers is not None:
        try:
            parameters = inspect.signature(adapter.evaluate).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "evaluate_provers" in parameters:
            kwargs["evaluate_provers"] = bool(evaluate_provers)
    if compiler_guidance:
        try:
            parameters = inspect.signature(adapter.evaluate).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if "compiler_guidance" in parameters or accepts_kwargs:
            kwargs["compiler_guidance"] = dict(compiler_guidance)
    return adapter.evaluate(text, **kwargs)


def _bridge_names(bridge_names: Optional[Sequence[str]]) -> tuple[str, ...]:
    if bridge_names is None:
        return tuple(spec.name for spec in logic_bridge_specs(implemented_only=True))
    return tuple(
        dict.fromkeys(
            str(name).strip()
            for name in bridge_names
            if str(name).strip()
            and str(name).strip().lower() not in {"none", "off", "false"}
        )
    )


def _merge_reports_to_document(
    text: str,
    *,
    bridge_names: Sequence[str],
    citation: Optional[str],
    document_id: Optional[str],
    compiler_guidance: Optional[Mapping[str, Any]],
    failures: Mapping[str, str],
    reports: Mapping[str, BridgeEvaluationReport],
    source: str,
) -> LegalIRDocument:
    resolved_document_id = document_id or _document_id(text)
    normalized_text = " ".join(str(text or "").split())
    views: Dict[str, LogicIRView] = {}
    triples: list[Mapping[str, str]] = []
    seen_triples: set[tuple[str, str, str]] = set()

    for adapter_name, report in sorted(reports.items()):
        if report.ir_document.normalized_text:
            normalized_text = report.ir_document.normalized_text
        for view_name, view in sorted(report.ir_document.views.items()):
            key = f"{adapter_name}.{view_name}"
            views[key] = LogicIRView(
                name=key,
                format=view.format,
                source_component=view.source_component,
                payload=view.payload,
                metadata={
                    **dict(view.metadata),
                    "adapter_name": adapter_name,
                    "original_view_name": view_name,
                },
            )
        for triple in report.ir_document.frame_logic_triples:
            subject = str(triple.get("subject") or "")
            predicate = str(triple.get("predicate") or "")
            obj = str(triple.get("object") or "")
            triple_key = (subject, predicate, obj)
            if not all(triple_key) or triple_key in seen_triples:
                continue
            seen_triples.add(triple_key)
            triples.append({"subject": subject, "predicate": predicate, "object": obj})

    metadata = {
        "accepted_bridge_count": sum(1 for report in reports.values() if report.accepted),
        "attempted_bridge_count": len(bridge_names),
        "bridge_names": list(bridge_names),
        "failed_bridge_count": len(failures),
        "implemented_bridge_count": len(reports),
        "multiview_version": "legal-ir-multiview-v1",
        "view_count": len(views),
    }
    metadata.update(_compiler_guidance_bridge_contract_metadata(compiler_guidance))
    return LegalIRDocument(
        document_id=resolved_document_id,
        source_text=text,
        normalized_text=normalized_text,
        source=source,
        citation=citation or _first_citation(reports),
        views=views,
        frame_logic_triples=tuple(triples),
        metadata=metadata,
        version="legal-ir-multiview-v1",
    )


def _first_citation(reports: Mapping[str, BridgeEvaluationReport]) -> Optional[str]:
    for report in reports.values():
        if report.ir_document.citation:
            return report.ir_document.citation
    return None


def _mean_with_failures(
    values: Sequence[float],
    *,
    expected_count: int,
    failure_count: int,
) -> float:
    if expected_count <= 0:
        return 0.0
    total = sum(float(value) for value in values) + float(failure_count)
    return total / expected_count


def _document_id(text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"legal-ir-multiview:{digest}"


def _loss_prefix(adapter_name: str) -> str:
    return str(adapter_name or "bridge").replace("-", "_")


def _canonical_bridge_component_name(component: str) -> str:
    name = str(component or "").strip()
    if not name:
        return ""
    canonical_prefixes = (
        ("knowledge_graphs.", "knowledge_graphs.neo4j_compat"),
        ("deontic.", "deontic.ir"),
        ("TDFOL.", "TDFOL.prover"),
        ("fol.", "TDFOL.prover"),
        ("CEC.", "CEC.native"),
        ("external_provers.", "external_provers.router"),
        ("zkp.", "zkp.circuits"),
        ("modal.", "modal.frame_logic"),
    )
    for prefix, canonical in canonical_prefixes:
        if name.startswith(prefix):
            return canonical
    return name


def _bridge_contract_lane_component(component: str) -> str:
    """Map canonical component names to bridge-contract optimizer lanes."""

    name = str(component or "").strip()
    if not name:
        return ""
    lane_prefixes = (
        ("deontic.", "deontic.ir"),
        ("modal.", "modal.frame_logic"),
        ("TDFOL.", "TDFOL.prover"),
        ("fol.", "TDFOL.prover"),
        ("CEC.", "CEC.native"),
        ("external_provers.", "external_provers.router"),
        ("knowledge_graphs.", "knowledge_graphs.neo4j_compat"),
        ("zkp.", "zkp.circuits"),
    )
    for prefix, lane in lane_prefixes:
        if name.startswith(prefix):
            return lane
    return ""


def _adapter_name_for_view(view_name: str, view: LogicIRView) -> str:
    adapter_name = str(view.metadata.get("adapter_name") or "").strip()
    if adapter_name:
        return adapter_name
    if "." in str(view_name):
        prefix, _separator, _suffix = str(view_name).partition(".")
        if prefix:
            return prefix
    return "_unscoped"


def _adapter_view_distribution_mass(report: Optional[BridgeEvaluationReport]) -> float:
    """Return deterministic adapter mass for canonical view balancing."""

    if report is None:
        return 1.0
    proof_quality = max(0.0, 1.0 - float(report.proof_gate.failure_ratio))
    graph_quality = max(
        0.0,
        1.0 - float(report.graph_projection.graph_failure_penalty),
    )
    # Keep non-accepted adapters visible but down-weighted.
    if not report.accepted:
        return 0.65 + (0.2 * proof_quality) + (0.15 * graph_quality)
    return 1.0


def _view_signal_weight(view: LogicIRView) -> float:
    """Return deterministic evidence weight for one canonical view."""

    signal_values: list[float] = []
    signal_values.extend(_metadata_signal_values(view.metadata))
    signal_values.extend(_payload_signal_values(view.payload))
    if not signal_values:
        return 1.0
    strongest = max(0.0, max(signal_values))
    return 1.0 + min(_BRIDGE_VIEW_SIGNAL_WEIGHT_CAP, math.log1p(strongest))


def _rebalance_dense_contract_distribution(
    distribution: Mapping[str, float],
    *,
    text: str,
) -> Dict[str, float]:
    """Reduce dense-lane entropy for bridge.contracts targets.

    Multi-adapter samples can yield nearly-uniform lane mass across
    ``deontic.ir``, ``TDFOL.prover``, ``CEC.native``, and
    ``knowledge_graphs.neo4j_compat``.  The autoencoder receives stronger and
    more stable guidance when auxiliary lanes are softly capped and excess mass
    is redistributed to semantic lanes based on deterministic statutory cues.
    """

    lanes = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    if len(lanes) < _BRIDGE_CONTRACT_DENSE_LANE_MIN_COUNT:
        return lanes

    normalized_text = " ".join(str(text or "").split()).lower()
    conditional_cue_count = _cue_count(
        _BRIDGE_CONTRACT_CONDITIONAL_CUE_RE,
        normalized_text,
    )
    for_purposes_cue_count = _cue_count(
        _BRIDGE_CONTRACT_FOR_PURPOSES_CUE_RE,
        normalized_text,
    )
    provided_for_cue_count = _cue_count(
        _BRIDGE_CONTRACT_PROVIDED_FOR_CUE_RE,
        normalized_text,
    )
    conditional_cue_count += for_purposes_cue_count
    conditional_cue_count += provided_for_cue_count
    deontic_cue_count = _contextual_modal_cue_count(
        _BRIDGE_CONTRACT_DEONTIC_CUE_RE,
        normalized_text,
    )
    permission_deontic_cue_count = _contextual_modal_cue_count(
        _BRIDGE_CONTRACT_PERMISSION_DEONTIC_CUE_RE,
        normalized_text,
    )
    obligation_deontic_cue_count = _cue_count(
        _BRIDGE_CONTRACT_OBLIGATION_DEONTIC_CUE_RE,
        normalized_text,
    )
    temporal_cue_count = _cue_count(_BRIDGE_CONTRACT_TEMPORAL_CUE_RE, normalized_text)
    strong_temporal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STRONG_TEMPORAL_CUE_RE,
        normalized_text,
    )
    month_temporal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_MONTH_TEMPORAL_CUE_RE,
        normalized_text,
    )
    prior_to_temporal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_PRIOR_TO_TEMPORAL_CUE_RE,
        normalized_text,
    )
    by_date_temporal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_BY_DATE_TEMPORAL_CUE_RE,
        normalized_text,
    )
    repeal_temporal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE,
        normalized_text,
    )
    temporal_cue_count += strong_temporal_cue_count
    temporal_cue_count += month_temporal_cue_count
    temporal_cue_count += prior_to_temporal_cue_count
    temporal_cue_count += by_date_temporal_cue_count
    temporal_cue_count += repeal_temporal_cue_count
    strong_temporal_cue_count += by_date_temporal_cue_count
    strong_temporal_cue_count += repeal_temporal_cue_count
    strong_temporal_cue_count += prior_to_temporal_cue_count
    statute_structure_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STATUTE_STRUCTURE_CUE_RE,
        normalized_text,
    )
    structural_frame_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STRUCTURAL_FRAME_CUE_RE,
        normalized_text,
    ) + statute_structure_cue_count
    statute_scaffold_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STATUTE_SCAFFOLD_CUE_RE,
        normalized_text,
    )
    has_conditional_cue = conditional_cue_count > 0
    has_deontic_cue = deontic_cue_count > 0
    has_temporal_cue = temporal_cue_count > 0
    has_explicit_temporal_deadline_cue = (
        by_date_temporal_cue_count > 0
        or repeal_temporal_cue_count > 0
    )
    has_frame_definition_cue = bool(
        _BRIDGE_CONTRACT_FRAME_DEFINITION_CUE_RE.search(normalized_text)
    )
    has_authority_frame_cue = bool(
        _BRIDGE_CONTRACT_FRAME_AUTHORITY_CUE_RE.search(normalized_text)
    )
    has_title_transfer_authority = bool(
        _BRIDGE_CONTRACT_TITLE_TRANSFER_AUTHORITY_RE.search(normalized_text)
    )
    has_effect_on_existing_law_frame_cue = bool(
        _BRIDGE_CONTRACT_EFFECT_ON_EXISTING_LAW_CUE_RE.search(normalized_text)
    )
    has_enforcement_frame_cue = bool(
        _BRIDGE_CONTRACT_FRAME_ENFORCEMENT_CUE_RE.search(normalized_text)
    )
    has_admin_notice_hearing_frame_cue = bool(
        _BRIDGE_CONTRACT_ADMIN_NOTICE_HEARING_CUE_RE.search(normalized_text)
    )
    if (
        for_purposes_cue_count > 0
        and not has_frame_definition_cue
        and not has_deontic_cue
        and not has_temporal_cue
    ):
        has_frame_definition_cue = True
    has_structural_frame_cue = structural_frame_cue_count > 0
    has_frame_cue = (
        has_frame_definition_cue
        or has_structural_frame_cue
        or has_authority_frame_cue
        or has_effect_on_existing_law_frame_cue
        or has_enforcement_frame_cue
        or has_admin_notice_hearing_frame_cue
    )
    has_structural_only_frame_cue = (
        has_structural_frame_cue
        and not has_frame_definition_cue
        and not has_authority_frame_cue
        and not has_effect_on_existing_law_frame_cue
        and not has_enforcement_frame_cue
        and not has_admin_notice_hearing_frame_cue
    )
    has_epistemic_cue = bool(_BRIDGE_CONTRACT_EPISTEMIC_CUE_RE.search(normalized_text))
    has_dense_statute_scaffold = (
        statute_scaffold_cue_count > 0 and structural_frame_cue_count >= 2
    )
    has_governance_cross_reference_cue = bool(
        _BRIDGE_CONTRACT_GOVERNANCE_CROSS_REFERENCE_CUE_RE.search(normalized_text)
    )
    has_frame_to_frame_cec_cue = bool(
        _BRIDGE_CONTRACT_FRAME_TO_FRAME_CEC_CUE_RE.search(normalized_text)
    )
    if (
        has_governance_cross_reference_cue
        and has_structural_only_frame_cue
        and has_deontic_cue
        and has_conditional_cue
        and not has_temporal_cue
        and not has_dense_statute_scaffold
    ):
        # Treat governance cross-references as normative conditionals rather than
        # standalone structural/frame evidence.
        has_structural_frame_cue = False
        has_structural_only_frame_cue = False
        has_frame_cue = (
            has_frame_definition_cue or has_authority_frame_cue or has_enforcement_frame_cue
        )
    has_temporal_priority_without_normative_cue = (
        has_temporal_cue
        and not has_deontic_cue
        and (
            strong_temporal_cue_count > 0
            or has_explicit_temporal_deadline_cue
        )
    )
    has_sparse_statutory_reference = _has_sparse_statutory_reference(normalized_text)
    legislative_history_cue_count = _cue_count(
        _BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE,
        normalized_text,
    )
    has_repealed_history_frame_cue = (
        repeal_temporal_cue_count > 0
        and legislative_history_cue_count >= 2
        and has_structural_only_frame_cue
        and not has_deontic_cue
    )
    has_repealed_legislative_history_signal = (
        repeal_temporal_cue_count > 0
        and legislative_history_cue_count > 0
        and has_structural_frame_cue
        and not has_deontic_cue
    )
    if has_repealed_history_frame_cue:
        has_temporal_priority_without_normative_cue = False
    has_permission_only_deontic_signal = (
        has_deontic_cue
        and permission_deontic_cue_count > 0
        and obligation_deontic_cue_count == 0
    )
    has_appropriation_norm_cue = bool(
        _BRIDGE_CONTRACT_APPROPRIATION_NORM_CUE_RE.search(normalized_text)
    )
    has_direct_appropriation_authorization = bool(
        _BRIDGE_CONTRACT_DIRECT_APPROPRIATION_AUTHORIZATION_RE.search(normalized_text)
    )
    has_regulatory_cost_estimate = bool(
        _BRIDGE_CONTRACT_REGULATORY_COST_ESTIMATE_RE.search(normalized_text)
    )
    has_construction_exemption = bool(
        _BRIDGE_CONTRACT_CONSTRUCTION_EXEMPTION_RE.search(normalized_text)
    )
    has_compliance_enforcement_norm = bool(
        _BRIDGE_CONTRACT_COMPLIANCE_ENFORCEMENT_NORM_RE.search(normalized_text)
    )
    has_fiscal_availability_norm = bool(
        _BRIDGE_CONTRACT_FISCAL_AVAILABILITY_NORM_RE.search(normalized_text)
    )
    has_statutory_definition_section = bool(
        _BRIDGE_CONTRACT_STATUTORY_DEFINITION_SECTION_RE.search(normalized_text)
    )
    has_epistemic_heading_cue = bool(
        _BRIDGE_CONTRACT_EPISTEMIC_HEADING_CUE_RE.search(normalized_text)
    )
    has_repeated_normative_deontic_signal = (
        permission_deontic_cue_count + obligation_deontic_cue_count
    ) >= 3
    status_operation_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STATUS_OPERATION_CUE_RE,
        normalized_text,
    )
    has_status_operation_cue = status_operation_cue_count > 0
    has_omitted_codification_cue = bool(
        _BRIDGE_CONTRACT_OMITTED_CODIFICATION_CUE_RE.search(normalized_text)
    )
    has_scaffolded_normative_operations = (
        has_dense_statute_scaffold
        and has_repeated_normative_deontic_signal
        and has_deontic_cue
        and not has_epistemic_heading_cue
        and not has_frame_definition_cue
        and not has_authority_frame_cue
        and not has_enforcement_frame_cue
    )
    has_structural_status_operation_signal = (
        has_dense_statute_scaffold
        and has_status_operation_cue
        and has_structural_only_frame_cue
        and not has_authority_frame_cue
        and not has_enforcement_frame_cue
    )
    has_scaffolded_scope_norm_hint = (
        has_dense_statute_scaffold
        and has_structural_only_frame_cue
        and bool(_BRIDGE_CONTRACT_NORMATIVE_SCOPE_CUE_RE.search(normalized_text))
        and not has_deontic_cue
        and not has_temporal_cue
        and not has_epistemic_heading_cue
        and not has_authority_frame_cue
        and not has_enforcement_frame_cue
        and not has_status_operation_cue
        and not has_repealed_history_frame_cue
    )
    has_conditional_structural_normative_signal = (
        has_structural_status_operation_signal
        and has_conditional_cue
        and has_deontic_cue
        and not has_temporal_cue
        and (permission_deontic_cue_count + obligation_deontic_cue_count) >= 2
    )

    caps = dict(_BRIDGE_CONTRACT_DENSE_LANE_CAPS)
    if has_repealed_history_frame_cue:
        caps["CEC.native"] = max(caps.get("CEC.native", 0.0), 0.24)
        caps["knowledge_graphs.neo4j_compat"] = max(
            caps.get("knowledge_graphs.neo4j_compat", 0.0),
            0.21,
        )
        caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.20)
    elif has_repealed_legislative_history_signal:
        caps["CEC.native"] = max(caps.get("CEC.native", 0.0), 0.24)
        caps["knowledge_graphs.neo4j_compat"] = max(
            caps.get("knowledge_graphs.neo4j_compat", 0.0),
            0.21,
        )
        caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.20)
    if has_conditional_cue and not has_frame_cue:
        caps["knowledge_graphs.neo4j_compat"] = min(
            caps["knowledge_graphs.neo4j_compat"],
            0.12,
        )
    if has_frame_cue:
        caps["knowledge_graphs.neo4j_compat"] = max(
            caps["knowledge_graphs.neo4j_compat"],
            0.19,
        )
        caps["CEC.native"] = max(caps["CEC.native"], 0.22)
        caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.68)
        if has_admin_notice_hearing_frame_cue:
            caps["knowledge_graphs.neo4j_compat"] = max(
                caps["knowledge_graphs.neo4j_compat"],
                0.21,
            )
            caps["CEC.native"] = max(caps["CEC.native"], 0.24)
            caps["deontic.ir"] = min(caps["deontic.ir"], 0.58)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.17)
        if has_authority_frame_cue and has_deontic_cue and not has_conditional_cue:
            caps["knowledge_graphs.neo4j_compat"] = max(
                caps["knowledge_graphs.neo4j_compat"],
                0.20,
            )
            caps["CEC.native"] = max(caps["CEC.native"], 0.23)
            caps["deontic.ir"] = min(caps["deontic.ir"], 0.62)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.18)
        if has_effect_on_existing_law_frame_cue:
            caps["knowledge_graphs.neo4j_compat"] = max(
                caps["knowledge_graphs.neo4j_compat"],
                0.22,
            )
            caps["CEC.native"] = max(caps["CEC.native"], 0.25)
            caps["deontic.ir"] = min(caps["deontic.ir"], 0.26)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.17)
        if (
            has_authority_frame_cue
            and has_permission_only_deontic_signal
            and not has_temporal_cue
        ):
            caps["knowledge_graphs.neo4j_compat"] = max(
                caps["knowledge_graphs.neo4j_compat"],
                0.23,
            )
            caps["CEC.native"] = max(caps["CEC.native"], 0.25)
            caps["deontic.ir"] = min(caps["deontic.ir"], 0.24)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.17)
        if (
            has_permission_only_deontic_signal
            and has_authority_frame_cue
            and not has_temporal_cue
        ):
            # Preserve deontic->frame supervision signal for delegated authority
            # passages where permissive norm text co-occurs with frame semantics.
            caps["deontic.ir"] = max(caps.get("deontic.ir", 0.0), 0.12)
        if has_title_transfer_authority:
            caps["knowledge_graphs.neo4j_compat"] = max(
                caps["knowledge_graphs.neo4j_compat"],
                0.24,
            )
            caps["CEC.native"] = max(caps["CEC.native"], 0.24)
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.30)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.16)
    elif has_epistemic_cue and not has_temporal_cue:
        caps["knowledge_graphs.neo4j_compat"] = max(
            caps["knowledge_graphs.neo4j_compat"],
            0.18,
        )
        caps["CEC.native"] = max(caps["CEC.native"], 0.22)
    if has_deontic_cue:
        if not has_frame_cue:
            caps["CEC.native"] = min(caps["CEC.native"], 0.17)
            if not has_temporal_cue:
                caps["knowledge_graphs.neo4j_compat"] = min(
                    caps["knowledge_graphs.neo4j_compat"],
                    0.12,
                )
        if (
            for_purposes_cue_count > 0
            and not has_temporal_cue
            and not has_frame_definition_cue
        ):
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.11,
            )
            caps["CEC.native"] = min(caps["CEC.native"], 0.16)
    if has_deontic_cue and has_temporal_cue:
        caps["TDFOL.prover"] = min(caps["TDFOL.prover"], 0.18)
        caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.76)
        if has_direct_appropriation_authorization:
            caps["CEC.native"] = max(caps.get("CEC.native", 0.0), 0.22)
        if (
            strong_temporal_cue_count > 0
            or temporal_cue_count > deontic_cue_count
        ):
            caps["deontic.ir"] = min(caps["deontic.ir"], 0.72)
            caps["TDFOL.prover"] = max(caps["TDFOL.prover"], 0.20)
            if has_permission_only_deontic_signal:
                caps["deontic.ir"] = min(caps["deontic.ir"], 0.68)
                caps["TDFOL.prover"] = max(caps["TDFOL.prover"], 0.22)
            if has_conditional_cue and has_explicit_temporal_deadline_cue:
                caps["deontic.ir"] = min(caps["deontic.ir"], 0.68)
                caps["TDFOL.prover"] = max(caps["TDFOL.prover"], 0.24)
    if has_regulatory_cost_estimate and has_deontic_cue:
        caps["TDFOL.prover"] = max(caps.get("TDFOL.prover", 0.0), 0.24)
        caps["CEC.native"] = min(caps.get("CEC.native", 1.0), 0.20)
        caps["knowledge_graphs.neo4j_compat"] = min(
            caps.get("knowledge_graphs.neo4j_compat", 1.0),
            0.16,
        )
    if has_construction_exemption and has_deontic_cue:
        caps["deontic.ir"] = max(caps.get("deontic.ir", 0.0), 0.42)
        caps["TDFOL.prover"] = max(caps.get("TDFOL.prover", 0.0), 0.20)
        caps["CEC.native"] = min(caps.get("CEC.native", 1.0), 0.18)
    if has_conditional_cue and has_deontic_cue and not has_frame_cue:
        # Keep conditional_normative->deontic targets stable in non-frame text.
        caps["deontic.ir"] = max(caps.get("deontic.ir", 0.0), 0.60)
    if has_temporal_cue and strong_temporal_cue_count > 0:
        # Preserve temporal->temporal routing when strong deadline/repeal cues fire.
        caps["TDFOL.prover"] = max(caps.get("TDFOL.prover", 0.0), 0.22)
    if (
        has_conditional_cue
        and has_deontic_cue
        and not has_temporal_cue
        and not has_dense_statute_scaffold
        and not has_authority_frame_cue
        and not has_enforcement_frame_cue
    ):
        if has_direct_appropriation_authorization:
            caps["CEC.native"] = max(caps["CEC.native"], 0.22)
        else:
            caps["CEC.native"] = min(caps["CEC.native"], 0.17)
        caps["knowledge_graphs.neo4j_compat"] = min(
            caps["knowledge_graphs.neo4j_compat"],
            0.12,
        )
        caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.16)
        caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.13)
    if has_conditional_cue or has_deontic_cue or has_temporal_cue:
        caps["zkp.circuits"] = min(caps["zkp.circuits"], 0.15)
    if has_dense_statute_scaffold:
        caps["CEC.native"] = max(caps["CEC.native"], 0.24)
        caps["knowledge_graphs.neo4j_compat"] = max(
            caps["knowledge_graphs.neo4j_compat"],
            0.22,
        )
        caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.17)
        caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.64)
        caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.12)
        if has_scaffolded_scope_norm_hint:
            caps["CEC.native"] = min(caps["CEC.native"], 0.23)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.20,
            )
            caps["deontic.ir"] = max(caps.get("deontic.ir", 1.0), 0.68)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.16)
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.11)
        if has_epistemic_heading_cue and not has_explicit_temporal_deadline_cue:
            caps["CEC.native"] = max(caps["CEC.native"], 0.26)
            caps["knowledge_graphs.neo4j_compat"] = max(
                caps["knowledge_graphs.neo4j_compat"],
                0.24,
            )
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.56)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.16)
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.11)
        if has_scaffolded_normative_operations:
            caps["CEC.native"] = min(caps["CEC.native"], 0.18)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.14,
            )
            caps["TDFOL.prover"] = max(
                caps.get("TDFOL.prover", 0.0),
                0.20 if has_temporal_cue else 0.15,
            )
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.10)
        if has_structural_status_operation_signal and not has_repealed_history_frame_cue:
            if has_omitted_codification_cue and not has_deontic_cue:
                caps["CEC.native"] = max(caps["CEC.native"], 0.28)
                caps["knowledge_graphs.neo4j_compat"] = max(
                    caps["knowledge_graphs.neo4j_compat"],
                    0.24,
                )
                caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.24)
                caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.18)
            else:
                caps["CEC.native"] = min(caps["CEC.native"], 0.22)
                caps["knowledge_graphs.neo4j_compat"] = min(
                    caps["knowledge_graphs.neo4j_compat"],
                    0.20,
                )
                caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.16)
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.10)
        if has_conditional_structural_normative_signal:
            caps["CEC.native"] = min(caps["CEC.native"], 0.19)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.15,
            )
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.62)
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.14)
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.10)
        if (
            has_conditional_cue
            and has_deontic_cue
            and has_temporal_cue
            and (
                strong_temporal_cue_count > 0
                or has_explicit_temporal_deadline_cue
            )
        ):
            # Keep scaffold-heavy temporal norms from collapsing into a static
            # frame-dominant lane mix.
            caps["CEC.native"] = min(caps["CEC.native"], 0.20)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.16,
            )
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.58)
            caps["TDFOL.prover"] = max(caps.get("TDFOL.prover", 0.0), 0.24)
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.10)
        if (
            has_appropriation_norm_cue
            and has_temporal_cue
            and has_deontic_cue
            and not has_authority_frame_cue
            and not has_enforcement_frame_cue
        ):
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.66)
            caps["TDFOL.prover"] = max(caps.get("TDFOL.prover", 0.0), 0.22)
            if has_direct_appropriation_authorization:
                caps["CEC.native"] = max(caps.get("CEC.native", 0.0), 0.22)
            else:
                caps["CEC.native"] = min(caps.get("CEC.native", 1.0), 0.20)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps.get("knowledge_graphs.neo4j_compat", 1.0),
                0.15,
            )
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.10)
        if has_deontic_cue and deontic_cue_count > temporal_cue_count:
            # Preserve deontic signal for clearly normative statutory passages.
            caps["deontic.ir"] = min(caps["deontic.ir"], 0.68)
            caps["TDFOL.prover"] = min(caps["TDFOL.prover"], 0.18)
        if (
            has_conditional_cue
            and has_deontic_cue
            and not has_temporal_cue
            and not has_authority_frame_cue
            and not has_enforcement_frame_cue
        ):
            caps["CEC.native"] = min(caps["CEC.native"], 0.18)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.13,
            )
            caps["TDFOL.prover"] = min(caps.get("TDFOL.prover", 1.0), 0.14)
            caps["zkp.circuits"] = min(caps.get("zkp.circuits", 1.0), 0.10)
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.74)
        if (
            has_temporal_priority_without_normative_cue
            and has_structural_only_frame_cue
        ):
            caps["CEC.native"] = min(caps["CEC.native"], 0.19)
            caps["knowledge_graphs.neo4j_compat"] = min(
                caps["knowledge_graphs.neo4j_compat"],
                0.15,
            )
            caps["deontic.ir"] = min(caps.get("deontic.ir", 1.0), 0.14)
            caps["TDFOL.prover"] = max(caps.get("TDFOL.prover", 0.0), 0.24)

    adjusted = dict(lanes)
    excess_mass = 0.0
    for lane, cap in caps.items():
        if lane not in adjusted:
            continue
        value = adjusted[lane]
        if value <= cap:
            continue
        excess_mass += value - cap
        adjusted[lane] = cap
    if excess_mass <= 0.0:
        if has_dense_statute_scaffold and has_structural_status_operation_signal:
            return _enforce_contract_lane_floors(
                adjusted,
                floors={
                    "CEC.native": 0.22,
                    "deontic.ir": 0.20,
                    "TDFOL.prover": 0.10,
                },
                donor_priority=(
                    "zkp.circuits",
                    "external_provers.router",
                    "modal.frame_logic",
                    "knowledge_graphs.neo4j_compat",
                ),
            )
        return adjusted

    if (
        has_temporal_priority_without_normative_cue
        and (not has_frame_cue or has_structural_only_frame_cue)
    ):
        target_mix = (
            ("TDFOL.prover", 0.74),
            ("CEC.native", 0.16),
            ("knowledge_graphs.neo4j_compat", 0.07),
            ("deontic.ir", 0.03),
        )
    elif (
        has_sparse_statutory_reference
        and not has_deontic_cue
        and not has_temporal_cue
    ):
        # Short citation-heavy references are usually structural/contextual.
        # Keep CEC + graph lanes prominent so bridge.contracts targets do not
        # collapse into a deontic-default mix.
        target_mix = (
            ("CEC.native", 0.52),
            ("knowledge_graphs.neo4j_compat", 0.34),
            ("TDFOL.prover", 0.10),
            ("deontic.ir", 0.04),
        )
    elif (
        has_authority_frame_cue
        and has_permission_only_deontic_signal
        and not has_temporal_cue
    ):
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.40),
            ("CEC.native", 0.42),
            ("deontic.ir", 0.10),
            ("TDFOL.prover", 0.08),
        )
    elif has_title_transfer_authority:
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.36),
            ("CEC.native", 0.32),
            ("deontic.ir", 0.22),
            ("TDFOL.prover", 0.10),
        )
    elif has_frame_cue:
        if has_dense_statute_scaffold:
            if has_admin_notice_hearing_frame_cue:
                target_mix = (
                    ("CEC.native", 0.42),
                    ("knowledge_graphs.neo4j_compat", 0.32),
                    ("deontic.ir", 0.18),
                    ("TDFOL.prover", 0.08),
                )
            elif has_epistemic_heading_cue and not has_explicit_temporal_deadline_cue:
                target_mix = (
                    ("CEC.native", 0.44),
                    ("knowledge_graphs.neo4j_compat", 0.34),
                    ("deontic.ir", 0.16),
                    ("TDFOL.prover", 0.06),
                )
            elif (
                has_structural_only_frame_cue
                and not has_deontic_cue
                and not has_temporal_cue
                and not has_status_operation_cue
                and not has_authority_frame_cue
                and not has_enforcement_frame_cue
            ):
                target_mix = (
                    ("CEC.native", 0.38),
                    ("deontic.ir", 0.33),
                    ("knowledge_graphs.neo4j_compat", 0.21),
                    ("TDFOL.prover", 0.08),
                )
            elif has_scaffolded_normative_operations:
                if has_temporal_cue:
                    target_mix = (
                        ("deontic.ir", 0.60),
                        ("TDFOL.prover", 0.24),
                        ("CEC.native", 0.11),
                        ("knowledge_graphs.neo4j_compat", 0.05),
                    )
                else:
                    target_mix = (
                        ("deontic.ir", 0.66),
                        ("CEC.native", 0.18),
                        ("TDFOL.prover", 0.10),
                        ("knowledge_graphs.neo4j_compat", 0.06),
                    )
            elif has_scaffolded_scope_norm_hint:
                target_mix = (
                    ("deontic.ir", 0.46),
                    ("CEC.native", 0.27),
                    ("knowledge_graphs.neo4j_compat", 0.19),
                    ("TDFOL.prover", 0.08),
                )
            elif (
                has_omitted_codification_cue
                and has_structural_status_operation_signal
                and not has_deontic_cue
            ):
                target_mix = (
                    ("CEC.native", 0.48),
                    ("knowledge_graphs.neo4j_compat", 0.32),
                    ("TDFOL.prover", 0.12),
                    ("deontic.ir", 0.08),
                )
            elif has_structural_status_operation_signal and not has_repealed_history_frame_cue:
                target_mix = (
                    ("deontic.ir", 0.44),
                    ("CEC.native", 0.30),
                    ("knowledge_graphs.neo4j_compat", 0.18),
                    ("TDFOL.prover", 0.08),
                )
            elif has_repealed_history_frame_cue:
                # Repealed sections with dense legislative-history scaffolding are
                # still frame-heavy, but keep a small deontic lane so multiview
                # targets do not collapse into purely archival structure.
                target_mix = (
                    ("CEC.native", 0.41),
                    ("knowledge_graphs.neo4j_compat", 0.31),
                    ("deontic.ir", 0.18),
                    ("TDFOL.prover", 0.10),
                )
            elif has_effect_on_existing_law_frame_cue:
                target_mix = (
                    ("CEC.native", 0.42),
                    ("knowledge_graphs.neo4j_compat", 0.32),
                    ("deontic.ir", 0.16),
                    ("TDFOL.prover", 0.10),
                )
            elif has_conditional_structural_normative_signal:
                target_mix = (
                    ("deontic.ir", 0.58),
                    ("CEC.native", 0.20),
                    ("knowledge_graphs.neo4j_compat", 0.14),
                    ("TDFOL.prover", 0.08),
                )
            elif (
                has_conditional_cue
                and has_deontic_cue
                and has_temporal_cue
                and (
                    strong_temporal_cue_count > 0
                    or has_explicit_temporal_deadline_cue
                )
            ):
                target_mix = (
                    ("deontic.ir", 0.48),
                    ("TDFOL.prover", 0.30),
                    ("CEC.native", 0.16),
                    ("knowledge_graphs.neo4j_compat", 0.06),
                )
            elif (
                has_appropriation_norm_cue
                and has_temporal_cue
                and has_deontic_cue
                and not has_authority_frame_cue
                and not has_enforcement_frame_cue
            ):
                if has_direct_appropriation_authorization:
                    target_mix = (
                        ("deontic.ir", 0.44),
                        ("CEC.native", 0.30),
                        ("TDFOL.prover", 0.18),
                        ("knowledge_graphs.neo4j_compat", 0.08),
                    )
                else:
                    target_mix = (
                        ("deontic.ir", 0.56),
                        ("TDFOL.prover", 0.26),
                        ("CEC.native", 0.12),
                        ("knowledge_graphs.neo4j_compat", 0.06),
                    )
            elif has_regulatory_cost_estimate and has_deontic_cue:
                target_mix = (
                    ("TDFOL.prover", 0.38),
                    ("deontic.ir", 0.30),
                    ("CEC.native", 0.20),
                    ("knowledge_graphs.neo4j_compat", 0.12),
                )
            elif has_construction_exemption and has_deontic_cue:
                target_mix = (
                    ("deontic.ir", 0.50),
                    ("TDFOL.prover", 0.24),
                    ("knowledge_graphs.neo4j_compat", 0.16),
                    ("CEC.native", 0.10),
                )
            elif (
                has_conditional_cue
                and has_deontic_cue
                and not has_temporal_cue
                and not has_authority_frame_cue
                and not has_enforcement_frame_cue
            ):
                target_mix = (
                    ("deontic.ir", 0.64),
                    ("CEC.native", 0.18),
                    ("knowledge_graphs.neo4j_compat", 0.12),
                    ("TDFOL.prover", 0.06),
                )
            elif has_compliance_enforcement_norm:
                target_mix = (
                    ("deontic.ir", 0.48),
                    ("TDFOL.prover", 0.26),
                    ("knowledge_graphs.neo4j_compat", 0.18),
                    ("CEC.native", 0.08),
                )
            elif has_deontic_cue and deontic_cue_count > temporal_cue_count:
                target_mix = (
                    ("CEC.native", 0.38),
                    ("knowledge_graphs.neo4j_compat", 0.34),
                    ("deontic.ir", 0.20),
                    ("TDFOL.prover", 0.08),
                )
            elif (
                has_frame_to_frame_cec_cue
                and not has_deontic_cue
                and not has_temporal_cue
                and has_structural_only_frame_cue
                and not has_repealed_history_frame_cue
            ):
                target_mix = (
                    ("CEC.native", 0.48),
                    ("knowledge_graphs.neo4j_compat", 0.34),
                    ("TDFOL.prover", 0.10),
                    ("deontic.ir", 0.08),
                )
            else:
                target_mix = (
                    ("knowledge_graphs.neo4j_compat", 0.48),
                    ("CEC.native", 0.36),
                    ("TDFOL.prover", 0.10),
                    ("deontic.ir", 0.06),
                )
        else:
            if (
                has_conditional_cue
                and has_deontic_cue
                and not has_temporal_cue
                and not has_authority_frame_cue
                and not has_enforcement_frame_cue
            ):
                target_mix = (
                    ("deontic.ir", 0.60),
                    ("CEC.native", 0.22),
                    ("knowledge_graphs.neo4j_compat", 0.12),
                    ("TDFOL.prover", 0.06),
                )
            elif (
                has_statutory_definition_section
                and has_frame_definition_cue
                and not has_deontic_cue
                and not has_temporal_cue
            ):
                target_mix = (
                    ("CEC.native", 0.42),
                    ("knowledge_graphs.neo4j_compat", 0.32),
                    ("deontic.ir", 0.18),
                    ("TDFOL.prover", 0.08),
                )
            elif has_effect_on_existing_law_frame_cue:
                target_mix = (
                    ("CEC.native", 0.44),
                    ("knowledge_graphs.neo4j_compat", 0.30),
                    ("deontic.ir", 0.16),
                    ("TDFOL.prover", 0.10),
                )
            elif has_compliance_enforcement_norm:
                target_mix = (
                    ("deontic.ir", 0.48),
                    ("TDFOL.prover", 0.26),
                    ("knowledge_graphs.neo4j_compat", 0.18),
                    ("CEC.native", 0.08),
                )
            elif has_status_operation_cue and has_deontic_cue:
                target_mix = (
                    ("deontic.ir", 0.36),
                    ("CEC.native", 0.26),
                    ("TDFOL.prover", 0.20),
                    ("knowledge_graphs.neo4j_compat", 0.18),
                )
            elif has_status_operation_cue and not has_omitted_codification_cue:
                target_mix = (
                    ("deontic.ir", 0.34),
                    ("CEC.native", 0.30),
                    ("knowledge_graphs.neo4j_compat", 0.24),
                    ("TDFOL.prover", 0.12),
                )
            else:
                target_mix = (
                    ("knowledge_graphs.neo4j_compat", 0.45),
                    ("CEC.native", 0.30),
                    ("deontic.ir", 0.15),
                    ("TDFOL.prover", 0.10),
                )
    elif has_epistemic_cue and not has_temporal_cue:
        target_mix = (
            ("CEC.native", 0.45),
            ("knowledge_graphs.neo4j_compat", 0.25),
            ("deontic.ir", 0.20),
            ("TDFOL.prover", 0.10),
        )
    elif has_temporal_cue and not has_deontic_cue:
        target_mix = (
            ("TDFOL.prover", 0.65),
            ("CEC.native", 0.22),
            ("deontic.ir", 0.13),
        )
    elif has_direct_appropriation_authorization and has_deontic_cue:
        target_mix = (
            ("deontic.ir", 0.44),
            ("CEC.native", 0.30),
            ("TDFOL.prover", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
    elif has_regulatory_cost_estimate and has_deontic_cue:
        target_mix = (
            ("TDFOL.prover", 0.40),
            ("deontic.ir", 0.30),
            ("CEC.native", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.12),
        )
    elif has_construction_exemption and has_deontic_cue:
        target_mix = (
            ("deontic.ir", 0.52),
            ("TDFOL.prover", 0.24),
            ("knowledge_graphs.neo4j_compat", 0.16),
            ("CEC.native", 0.08),
        )
    elif has_deontic_cue and not has_temporal_cue:
        target_mix = (
            ("deontic.ir", 0.82),
            ("CEC.native", 0.08),
            ("TDFOL.prover", 0.08),
        )
    elif has_deontic_cue and has_temporal_cue:
        if (
            strong_temporal_cue_count > 0
            or temporal_cue_count > deontic_cue_count
        ):
            if has_direct_appropriation_authorization:
                target_mix = (
                    ("deontic.ir", 0.44),
                    ("CEC.native", 0.30),
                    ("TDFOL.prover", 0.18),
                    ("knowledge_graphs.neo4j_compat", 0.08),
                )
            elif has_conditional_cue and has_explicit_temporal_deadline_cue:
                target_mix = (
                    ("deontic.ir", 0.54),
                    ("TDFOL.prover", 0.34),
                    ("CEC.native", 0.12),
                )
            elif has_permission_only_deontic_signal:
                target_mix = (
                    ("deontic.ir", 0.54),
                    ("TDFOL.prover", 0.28),
                    ("CEC.native", 0.10),
                    ("knowledge_graphs.neo4j_compat", 0.08),
                )
            else:
                target_mix = (
                    ("deontic.ir", 0.62),
                    ("TDFOL.prover", 0.24),
                    ("CEC.native", 0.10),
                    ("knowledge_graphs.neo4j_compat", 0.04),
                )
        elif has_conditional_cue or has_epistemic_cue:
            target_mix = (
                ("deontic.ir", 0.70),
                ("TDFOL.prover", 0.20),
                ("CEC.native", 0.10),
            )
        else:
            target_mix = (
                ("deontic.ir", 0.74),
                ("TDFOL.prover", 0.18),
                ("CEC.native", 0.08),
            )
    else:
        target_mix = (
            ("deontic.ir", 0.66),
            ("TDFOL.prover", 0.22),
            ("CEC.native", 0.12),
        )

    target_mix = _contract_target_mix_with_auxiliary_lanes(
        target_mix,
        adjusted,
        frame_weight=0.16 if has_frame_cue else 0.08,
        prover_weight=0.06 if has_conditional_cue or has_temporal_cue else 0.04,
    )

    present_targets = [
        (lane, weight)
        for lane, weight in target_mix
        if lane in adjusted
    ]
    if not present_targets:
        top_lane = max(adjusted.items(), key=lambda item: (item[1], item[0]))[0]
        adjusted[top_lane] += excess_mass
        return adjusted

    weight_total = sum(weight for _lane, weight in present_targets)
    if weight_total <= 0.0:
        top_lane = max(adjusted.items(), key=lambda item: (item[1], item[0]))[0]
        adjusted[top_lane] += excess_mass
        return adjusted

    for lane, weight in present_targets:
        adjusted[lane] += excess_mass * (weight / weight_total)

    if _should_project_flat_dense_contract_distribution(
        lanes,
        has_conditional_structural_normative_signal=has_conditional_structural_normative_signal,
        has_construction_exemption=has_construction_exemption,
        has_dense_statute_scaffold=has_dense_statute_scaffold,
        has_direct_appropriation_authorization=has_direct_appropriation_authorization,
        has_effect_on_existing_law_frame_cue=has_effect_on_existing_law_frame_cue,
        has_regulatory_cost_estimate=has_regulatory_cost_estimate,
        has_scaffolded_normative_operations=has_scaffolded_normative_operations,
        has_scaffolded_scope_norm_hint=has_scaffolded_scope_norm_hint,
        has_statutory_deontic_projection_signal=(
            has_compliance_enforcement_norm
            or has_fiscal_availability_norm
            or (
                has_status_operation_cue
                and (has_deontic_cue or not has_omitted_codification_cue)
            )
        ),
        has_structural_status_operation_signal=has_structural_status_operation_signal,
    ):
        adjusted = _project_contract_distribution_toward_target(
            adjusted,
            target_mix,
            strength=0.38,
        )

    if has_title_transfer_authority:
        adjusted = _project_contract_distribution_toward_target(
            adjusted,
            (
                ("knowledge_graphs.neo4j_compat", 0.36),
                ("CEC.native", 0.32),
                ("deontic.ir", 0.22),
                ("TDFOL.prover", 0.10),
            ),
            strength=0.35,
        )

    if has_repealed_legislative_history_signal:
        kg_lane = "knowledge_graphs.neo4j_compat"
        kg_floor = 0.21
        if adjusted.get(kg_lane, 0.0) < kg_floor:
            deficit = kg_floor - adjusted.get(kg_lane, 0.0)
            for donor_lane in ("TDFOL.prover", "deontic.ir", "zkp.circuits", "CEC.native"):
                donor_value = adjusted.get(donor_lane, 0.0)
                if donor_value <= 0.0 or deficit <= 0.0:
                    continue
                shift = min(deficit, max(0.0, donor_value - 0.08))
                if shift <= 0.0:
                    continue
                adjusted[donor_lane] = donor_value - shift
                adjusted[kg_lane] = adjusted.get(kg_lane, 0.0) + shift
                deficit -= shift
        tdfol_lane = "TDFOL.prover"
        tdfol_cap = 0.20
        if adjusted.get(tdfol_lane, 0.0) > tdfol_cap:
            excess = adjusted[tdfol_lane] - tdfol_cap
            adjusted[tdfol_lane] = tdfol_cap
            adjusted["CEC.native"] = adjusted.get("CEC.native", 0.0) + (0.6 * excess)
            adjusted[kg_lane] = adjusted.get(kg_lane, 0.0) + (0.4 * excess)

    if (
        has_frame_cue
        and not has_conditional_cue
        and not has_deontic_cue
        and not has_temporal_cue
        and statute_scaffold_cue_count > 0
        and statute_structure_cue_count >= _BRIDGE_CONTRACT_CITATION_FRAME_STRUCTURE_MIN_COUNT
    ):
        deontic_floor = _BRIDGE_CONTRACT_CITATION_FRAME_DEONTIC_FLOOR
        deontic_value = adjusted.get("deontic.ir", 0.0)
        if deontic_value < deontic_floor:
            deficit = deontic_floor - deontic_value
            donor_lanes = [
                "knowledge_graphs.neo4j_compat",
                "CEC.native",
                "modal.frame_logic",
                "external_provers.router",
                "zkp.circuits",
                "TDFOL.prover",
            ]
            for donor_lane in donor_lanes:
                donor_value = adjusted.get(donor_lane, 0.0)
                if donor_value <= 0.0:
                    continue
                shift = min(deficit, donor_value)
                if shift <= 0.0:
                    continue
                adjusted[donor_lane] = donor_value - shift
                deontic_value += shift
                deficit -= shift
                if deficit <= 1e-12:
                    break
            adjusted["deontic.ir"] = deontic_value
    adjusted = _enforce_dense_normative_deontic_floor(
        adjusted,
        has_deontic_cue=has_deontic_cue,
        has_conditional_cue=has_conditional_cue,
        has_temporal_cue=has_temporal_cue,
        has_dense_statute_scaffold=has_dense_statute_scaffold,
        has_repealed_history_frame_cue=has_repealed_history_frame_cue,
    )
    if (
        has_conditional_cue
        and has_deontic_cue
        and not has_dense_statute_scaffold
        and not has_authority_frame_cue
        and not has_enforcement_frame_cue
    ):
        kg_lane = "knowledge_graphs.neo4j_compat"
        kg_cap = 0.14
        kg_value = adjusted.get(kg_lane, 0.0)
        if kg_value > kg_cap:
            adjusted[kg_lane] = kg_cap
            adjusted["deontic.ir"] = adjusted.get("deontic.ir", 0.0) + (
                kg_value - kg_cap
            )
    if (
        has_status_operation_cue
        and not has_repealed_history_frame_cue
        and not has_temporal_priority_without_normative_cue
        and (has_deontic_cue or not has_omitted_codification_cue)
    ):
        adjusted = _enforce_contract_lane_floors(
            adjusted,
            floors={"deontic.ir": 0.30},
            donor_priority=(
                "external_provers.router",
                "zkp.circuits",
                "modal.frame_logic",
                "knowledge_graphs.neo4j_compat",
                "CEC.native",
                "TDFOL.prover",
            ),
        )
    return adjusted


def _contract_target_mix_with_auxiliary_lanes(
    target_mix: Sequence[tuple[str, float]],
    lanes: Mapping[str, float],
    *,
    frame_weight: float,
    prover_weight: float,
) -> tuple[tuple[str, float], ...]:
    """Keep deterministic frame/prover lanes eligible for excess redistribution."""

    augmented = list(target_mix)
    present = {lane for lane, _weight in augmented}
    if "modal.frame_logic" in lanes and "modal.frame_logic" not in present:
        augmented.append(("modal.frame_logic", max(0.0, float(frame_weight))))
    if (
        "external_provers.router" in lanes
        and "external_provers.router" not in present
    ):
        augmented.append(("external_provers.router", max(0.0, float(prover_weight))))
    return tuple(augmented)


def _should_project_flat_dense_contract_distribution(
    lanes: Mapping[str, float],
    *,
    has_conditional_structural_normative_signal: bool,
    has_construction_exemption: bool,
    has_dense_statute_scaffold: bool,
    has_direct_appropriation_authorization: bool,
    has_effect_on_existing_law_frame_cue: bool,
    has_regulatory_cost_estimate: bool,
    has_scaffolded_normative_operations: bool,
    has_scaffolded_scope_norm_hint: bool,
    has_statutory_deontic_projection_signal: bool,
    has_structural_status_operation_signal: bool,
) -> bool:
    """Return whether a flat dense mix should be pulled toward semantic cues."""

    values = [max(0.0, float(value)) for value in dict(lanes or {}).values()]
    if len(values) < 6:
        return False
    if not values:
        return False
    if max(values) - min(values) > 0.09:
        return False
    return (
        has_dense_statute_scaffold
        or has_effect_on_existing_law_frame_cue
        or has_direct_appropriation_authorization
        or has_regulatory_cost_estimate
        or has_construction_exemption
        or has_scaffolded_normative_operations
        or has_scaffolded_scope_norm_hint
        or has_statutory_deontic_projection_signal
        or has_structural_status_operation_signal
        or has_conditional_structural_normative_signal
    )


def _project_contract_distribution_toward_target(
    distribution: Mapping[str, float],
    target_mix: Sequence[tuple[str, float]],
    *,
    strength: float,
) -> Dict[str, float]:
    """Blend a flat bridge-contract distribution toward deterministic cues."""

    adjusted = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    if not adjusted:
        return adjusted

    present_target_weights = {
        str(lane): max(0.0, float(weight))
        for lane, weight in target_mix
        if str(lane) in adjusted and float(weight) > 0.0
    }
    target_total = sum(present_target_weights.values())
    if target_total <= 0.0:
        return adjusted

    target_distribution = {
        lane: weight / target_total
        for lane, weight in present_target_weights.items()
    }
    total = sum(adjusted.values())
    if total <= 0.0:
        return adjusted

    normalized = {lane: value / total for lane, value in adjusted.items()}
    blend = max(0.0, min(1.0, float(strength)))
    projected: Dict[str, float] = {}
    for lane, value in normalized.items():
        target_value = target_distribution.get(lane, value)
        projected[lane] = ((1.0 - blend) * value) + (blend * target_value)

    projected_total = sum(projected.values())
    if projected_total <= 0.0:
        return adjusted
    return {
        lane: value / projected_total
        for lane, value in projected.items()
    }


def _project_guided_contract_distribution(
    distribution: Mapping[str, float],
    *,
    metadata: Mapping[str, Any],
) -> Dict[str, float]:
    """Blend contract lanes toward distilled compiler-guidance evidence."""

    adjusted = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    if not adjusted:
        return adjusted

    raw_target_value = (metadata or {}).get(
        "compiler_guidance_bridge_contract_target_distribution"
    )
    if not isinstance(raw_target_value, Mapping):
        return adjusted
    raw_target = dict(raw_target_value)
    target_distribution = {
        _bridge_contract_lane_component(_canonical_bridge_component_name(str(lane))): (
            max(0.0, _float_or_zero(weight))
        )
        for lane, weight in raw_target.items()
    }
    target_distribution = {
        lane: weight
        for lane, weight in target_distribution.items()
        if lane and weight > 0.0
    }
    if not target_distribution:
        return adjusted

    for lane in target_distribution:
        if lane not in adjusted and lane in _BRIDGE_CONTRACT_CORE_COMPONENTS:
            adjusted[lane] = 0.0

    guidance_mix = tuple(sorted(target_distribution.items()))
    projected = _project_contract_distribution_toward_target(
        adjusted,
        guidance_mix,
        strength=_float_or_zero(
            (metadata or {}).get(
                "compiler_guidance_bridge_contract_projection_strength",
                _BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH,
            )
        ),
    )
    floors = {
        lane: _BRIDGE_CONTRACT_GUIDANCE_LANE_FLOOR * weight
        for lane, weight in target_distribution.items()
        if lane in projected
    }
    return _enforce_contract_lane_floors(
        projected,
        floors=floors,
        donor_priority=(
            "zkp.circuits",
            "external_provers.router",
            "modal.frame_logic",
            "CEC.native",
            "deontic.ir",
            "TDFOL.prover",
            "knowledge_graphs.neo4j_compat",
        ),
    )


def _enforce_contract_lane_floors(
    distribution: Mapping[str, float],
    *,
    floors: Mapping[str, float],
    donor_priority: Sequence[str],
) -> Dict[str, float]:
    """Apply deterministic lane floors by shifting mass from donor lanes."""

    adjusted = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
    }
    if not adjusted:
        return adjusted

    present_floors = {
        lane: max(0.0, float(floor))
        for lane, floor in dict(floors or {}).items()
        if lane in adjusted and float(floor) > 0.0
    }
    if not present_floors:
        return adjusted

    # First pass: bring lanes up to floor values from prioritized donors.
    for lane, floor in present_floors.items():
        deficit = floor - adjusted.get(lane, 0.0)
        if deficit <= 0.0:
            continue
        for donor in donor_priority:
            if donor == lane or donor not in adjusted:
                continue
            available = adjusted[donor]
            if available <= 0.0:
                continue
            shift = min(deficit, available)
            adjusted[donor] -= shift
            adjusted[lane] += shift
            deficit -= shift
            if deficit <= 0.0:
                break

    total = sum(adjusted.values())
    if total <= 0.0:
        return adjusted
    return {lane: value / total for lane, value in adjusted.items()}


def _enforce_dense_normative_deontic_floor(
    lanes: Mapping[str, float],
    *,
    has_deontic_cue: bool,
    has_conditional_cue: bool,
    has_temporal_cue: bool,
    has_dense_statute_scaffold: bool,
    has_repealed_history_frame_cue: bool,
) -> Dict[str, float]:
    """Keep deontic mass visible for scaffolded normative conditionals."""

    adjusted = {
        str(name): max(0.0, float(value))
        for name, value in dict(lanes or {}).items()
        if float(value) > 0.0
    }
    if "deontic.ir" not in adjusted:
        return adjusted
    if has_repealed_history_frame_cue:
        return adjusted
    if not has_deontic_cue:
        return adjusted
    if not (has_conditional_cue and has_temporal_cue):
        return adjusted
    if not has_dense_statute_scaffold:
        return adjusted

    deontic_value = adjusted.get("deontic.ir", 0.0)
    if deontic_value >= _BRIDGE_CONTRACT_NORMATIVE_DEONTIC_FLOOR:
        return adjusted

    deficit = _BRIDGE_CONTRACT_NORMATIVE_DEONTIC_FLOOR - deontic_value
    donors = (
        "CEC.native",
        "knowledge_graphs.neo4j_compat",
        "TDFOL.prover",
        "zkp.circuits",
        "modal.frame_logic",
        "external_provers.router",
    )
    moved = 0.0
    for lane in donors:
        available = adjusted.get(lane, 0.0)
        if available <= 0.0:
            continue
        shift = min(deficit - moved, available)
        if shift <= 0.0:
            continue
        adjusted[lane] = available - shift
        moved += shift
        if moved >= deficit:
            break
    if moved > 0.0:
        adjusted["deontic.ir"] = deontic_value + moved
    return adjusted


def _rebalance_sparse_contract_distribution(
    distribution: Mapping[str, float],
    *,
    text: str,
) -> Dict[str, float]:
    """Rebalance three-lane contract mixes for scaffold-heavy statutory text.

    The two-bridge ``deontic_norms`` + ``fol_tdfol`` path yields
    ``deontic.ir``/``TDFOL.prover``/``knowledge_graphs.neo4j_compat`` lanes
    only.  On long scaffold-heavy U.S.C. excerpts (editorial notes, codification,
    amendments), the raw adapter view counts can overstate deontic mass relative
    to graph/context evidence.  Apply a narrow deterministic cap in that case.
    """

    lanes = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    if not lanes:
        return lanes
    if any(name not in _BRIDGE_CONTRACT_SPARSE_CORE_LANES for name in lanes):
        return lanes
    if "deontic.ir" not in lanes or "knowledge_graphs.neo4j_compat" not in lanes:
        return lanes

    normalized_text = " ".join(str(text or "").split()).lower()
    scaffold_count = _cue_count(_BRIDGE_CONTRACT_STATUTE_SCAFFOLD_CUE_RE, normalized_text)
    structural_count = _cue_count(
        _BRIDGE_CONTRACT_STRUCTURAL_FRAME_CUE_RE,
        normalized_text,
    ) + _cue_count(_BRIDGE_CONTRACT_STATUTE_STRUCTURE_CUE_RE, normalized_text)
    deontic_cue_count = _contextual_modal_cue_count(
        _BRIDGE_CONTRACT_DEONTIC_CUE_RE,
        normalized_text,
    )
    repeal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE,
        normalized_text,
    )
    has_short_official_status_signal = (
        len(normalized_text) >= _BRIDGE_CONTRACT_STATUS_OFFICIAL_USC_MIN_CHARS
        and _BRIDGE_CONTRACT_USC_SECTION_MARKER_RE.search(normalized_text) is not None
        and repeal_cue_count > 0
        and (
            _BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_STATUTES_AT_LARGE_CUE_RE.search(normalized_text)
            is not None
        )
        and structural_count > 0
    )
    if (
        not has_short_official_status_signal
        and (
            scaffold_count < _BRIDGE_CONTRACT_SPARSE_SCAFFOLD_MIN_COUNT
            or structural_count < _BRIDGE_CONTRACT_SPARSE_STRUCTURAL_MIN_COUNT
        )
    ):
        return lanes

    has_repeal_scaffold_signal = (
        repeal_cue_count > 0
        and (
            scaffold_count >= (_BRIDGE_CONTRACT_SPARSE_SCAFFOLD_MIN_COUNT + 1)
            or has_short_official_status_signal
        )
    )
    has_epistemic_heading_signal = bool(
        _BRIDGE_CONTRACT_EPISTEMIC_HEADING_CUE_RE.search(normalized_text)
    )
    has_substantive_operational_norm = (
        deontic_cue_count > 0
        and _BRIDGE_CONTRACT_SUBSTANTIVE_OPERATIONAL_NORM_RE.search(normalized_text)
        is not None
    )
    if deontic_cue_count <= 0 and not has_repeal_scaffold_signal:
        return lanes

    adjusted = dict(lanes)
    deontic_lane = "deontic.ir"
    kg_lane = "knowledge_graphs.neo4j_compat"
    deontic_cap = _BRIDGE_CONTRACT_SPARSE_DEONTIC_CAP
    kg_floor = (
        _BRIDGE_CONTRACT_SPARSE_KG_TARGET
        if scaffold_count >= (_BRIDGE_CONTRACT_SPARSE_SCAFFOLD_MIN_COUNT + 2)
        else _BRIDGE_CONTRACT_SPARSE_KG_MIN
    )
    if has_repeal_scaffold_signal:
        deontic_cap = min(
            deontic_cap,
            _BRIDGE_CONTRACT_SPARSE_REPEAL_DEONTIC_CAP,
        )
        kg_floor = max(kg_floor, _BRIDGE_CONTRACT_SPARSE_REPEAL_KG_MIN)
    if has_substantive_operational_norm:
        deontic_cap = max(
            deontic_cap,
            _BRIDGE_CONTRACT_SPARSE_OPERATIONAL_DEONTIC_CAP,
        )
        kg_floor = min(kg_floor, _BRIDGE_CONTRACT_SPARSE_OPERATIONAL_KG_FLOOR)

    if adjusted.get(deontic_lane, 0.0) > deontic_cap:
        excess = adjusted[deontic_lane] - deontic_cap
        adjusted[deontic_lane] = deontic_cap
        adjusted[kg_lane] = adjusted.get(kg_lane, 0.0) + excess

    if adjusted.get(kg_lane, 0.0) < kg_floor:
        deficit = kg_floor - adjusted[kg_lane]
        shiftable = max(
            0.0,
            adjusted.get(deontic_lane, 0.0) - _BRIDGE_CONTRACT_SPARSE_DEONTIC_FLOOR,
        )
        shift = min(deficit, shiftable)
        if shift > 0.0:
            adjusted[deontic_lane] -= shift
            adjusted[kg_lane] += shift

    if has_epistemic_heading_signal:
        adjusted = _rebalance_sparse_epistemic_heading_distribution(adjusted)

    return adjusted


def _rebalance_sparse_epistemic_heading_distribution(
    distribution: Mapping[str, float],
) -> Dict[str, float]:
    """Expose TDFOL/deontic lanes for sparse statutory findings sections."""

    adjusted = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    required_lanes = {
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    if not required_lanes <= set(adjusted):
        return adjusted

    kg_lane = "knowledge_graphs.neo4j_compat"
    kg_value = adjusted.get(kg_lane, 0.0)
    available = kg_value - _BRIDGE_CONTRACT_SPARSE_EPISTEMIC_KG_FLOOR
    if available <= 0.0:
        return adjusted

    shift = min(_BRIDGE_CONTRACT_SPARSE_EPISTEMIC_SHIFT, available)
    if shift <= 0.0:
        return adjusted

    adjusted[kg_lane] = kg_value - shift
    adjusted["TDFOL.prover"] = adjusted.get("TDFOL.prover", 0.0) + (0.8 * shift)
    adjusted["deontic.ir"] = adjusted.get("deontic.ir", 0.0) + (0.2 * shift)
    return adjusted


def _compact_official_usc_contract_distribution(
    distribution: Mapping[str, float],
    *,
    text: str,
) -> Dict[str, float]:
    """Prune auxiliary lanes from long official U.S.C. training targets.

    Raw multiview diagnostics still expose modal/prover/ZKP views.  For
    autoencoder-facing ``bridge.contracts`` targets, long GPO-style statute
    excerpts are better represented by the primary semantic lanes; otherwise
    every sample becomes a broad seven-way target and the view CE floor is
    dominated by adapter plumbing rather than legal content.
    """

    lanes = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    if not lanes:
        return lanes
    normalized_text = " ".join(str(text or "").split())
    is_long_official_excerpt = (
        len(normalized_text) >= _BRIDGE_CONTRACT_OFFICIAL_USC_MIN_CHARS
        and _BRIDGE_CONTRACT_OFFICIAL_USC_EXCERPT_RE.search(normalized_text) is not None
    )
    is_short_official_section = (
        len(normalized_text) >= _BRIDGE_CONTRACT_SHORT_OFFICIAL_USC_MIN_CHARS
        and _BRIDGE_CONTRACT_USC_SECTION_MARKER_RE.search(normalized_text) is not None
        and (
            _BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_STATUTES_AT_LARGE_CUE_RE.search(normalized_text)
            is not None
        )
    )
    is_short_editorial_status_section = (
        len(normalized_text) >= _BRIDGE_CONTRACT_STATUS_OFFICIAL_USC_MIN_CHARS
        and _BRIDGE_CONTRACT_USC_SECTION_MARKER_RE.search(normalized_text) is not None
        and (
            _BRIDGE_CONTRACT_STATUS_OPERATION_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE.search(normalized_text)
            is not None
        )
        and (
            _BRIDGE_CONTRACT_STRUCTURAL_FRAME_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE.search(normalized_text)
            is not None
        )
    )
    is_official_header_editorial_status_section = (
        len(normalized_text) >= _BRIDGE_CONTRACT_STATUS_OFFICIAL_USC_MIN_CHARS
        and _BRIDGE_CONTRACT_OFFICIAL_USC_EXCERPT_RE.search(normalized_text)
        is not None
        and (
            _BRIDGE_CONTRACT_STATUS_OPERATION_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_OMITTED_CODIFICATION_CUE_RE.search(normalized_text)
            is not None
        )
        and (
            _BRIDGE_CONTRACT_STRUCTURAL_FRAME_CUE_RE.search(normalized_text)
            is not None
            or _BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE.search(normalized_text)
            is not None
        )
    )
    if not (
        is_long_official_excerpt
        or is_short_official_section
        or is_short_editorial_status_section
        or is_official_header_editorial_status_section
    ):
        return lanes
    primary = {
        lane: lanes[lane]
        for lane in _BRIDGE_CONTRACT_PRIMARY_AUTOENCODER_LANES
        if lane in lanes and lanes[lane] > 0.0
    }
    if len(primary) < 3:
        return lanes
    if not any(lane in lanes for lane in _BRIDGE_CONTRACT_AUXILIARY_AUTOENCODER_LANES):
        return lanes
    total = sum(primary.values())
    if total <= 0.0:
        return lanes
    compacted = {
        lane: value / total
        for lane, value in sorted(primary.items())
    }
    return _project_official_usc_primary_contract_distribution(
        compacted,
        text=normalized_text,
    )


def _project_official_usc_primary_contract_distribution(
    distribution: Mapping[str, float],
    *,
    text: str,
) -> Dict[str, float]:
    """Tighten primary-lane targets for long official U.S.C. excerpts."""

    lanes = {
        str(name): max(0.0, float(value))
        for name, value in dict(distribution or {}).items()
        if float(value) > 0.0
    }
    if len(lanes) < 3:
        return lanes

    normalized_text = " ".join(str(text or "").split()).lower()
    deontic_cue_count = _contextual_modal_cue_count(
        _BRIDGE_CONTRACT_DEONTIC_CUE_RE,
        normalized_text,
    )
    temporal_cue_count = _cue_count(
        _BRIDGE_CONTRACT_TEMPORAL_CUE_RE,
        normalized_text,
    ) + _cue_count(
        _BRIDGE_CONTRACT_STRONG_TEMPORAL_CUE_RE,
        normalized_text,
    ) + _cue_count(
        _BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE,
        normalized_text,
    )
    legislative_history_cue_count = _cue_count(
        _BRIDGE_CONTRACT_LEGISLATIVE_HISTORY_CUE_RE,
        normalized_text,
    )
    structural_frame_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STRUCTURAL_FRAME_CUE_RE,
        normalized_text,
    ) + _cue_count(
        _BRIDGE_CONTRACT_STATUTE_STRUCTURE_CUE_RE,
        normalized_text,
    )
    has_judicial_review_procedure = bool(
        _BRIDGE_CONTRACT_JUDICIAL_REVIEW_PROCEDURE_RE.search(normalized_text)
    )
    has_repealed_history_scaffold = (
        _cue_count(_BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE, normalized_text) > 0
        and legislative_history_cue_count >= 2
        and structural_frame_cue_count >= 2
        and not has_judicial_review_procedure
    )
    has_admin_rulemaking_schedule = bool(
        _BRIDGE_CONTRACT_ADMIN_RULEMAKING_SCHEDULE_RE.search(normalized_text)
    )
    has_enforcement_penalty_provision = bool(
        _BRIDGE_CONTRACT_ENFORCEMENT_PENALTY_PROVISION_RE.search(normalized_text)
    )
    has_compliance_enforcement_norm = bool(
        _BRIDGE_CONTRACT_COMPLIANCE_ENFORCEMENT_NORM_RE.search(normalized_text)
    )
    has_fiscal_availability_norm = bool(
        _BRIDGE_CONTRACT_FISCAL_AVAILABILITY_NORM_RE.search(normalized_text)
    )
    has_liability_provision = bool(
        _BRIDGE_CONTRACT_LIABILITY_PROVISION_RE.search(normalized_text)
    )
    has_reporting_duty = bool(
        _BRIDGE_CONTRACT_REPORTING_DUTY_RE.search(normalized_text)
    )
    has_determination_condition = bool(
        _BRIDGE_CONTRACT_DETERMINATION_CONDITION_RE.search(normalized_text)
    )
    has_preemption_contract_norm = bool(
        _BRIDGE_CONTRACT_PREEMPTION_CONTRACT_NORM_RE.search(normalized_text)
    )
    has_regulatory_cost_estimate = bool(
        _BRIDGE_CONTRACT_REGULATORY_COST_ESTIMATE_RE.search(normalized_text)
    )
    has_construction_exemption = bool(
        _BRIDGE_CONTRACT_CONSTRUCTION_EXEMPTION_RE.search(normalized_text)
    )
    has_references_repeal_crossref = bool(
        _BRIDGE_CONTRACT_REFERENCES_REPEAL_CROSSREF_RE.search(normalized_text)
    )
    has_repealed_public_law_status = bool(
        _BRIDGE_CONTRACT_REPEALED_PUBLIC_LAW_STATUS_RE.search(normalized_text)
    )
    has_renaming_designation = bool(
        _BRIDGE_CONTRACT_RENAMING_DESIGNATION_RE.search(normalized_text)
    )
    has_purpose_policy_statement = bool(
        _BRIDGE_CONTRACT_PURPOSE_POLICY_STATEMENT_RE.search(normalized_text)
    )
    has_definition_provision = bool(
        _BRIDGE_CONTRACT_DEFINITION_PROVISION_RE.search(normalized_text)
        or _BRIDGE_CONTRACT_STATUTORY_DEFINITION_SECTION_RE.search(normalized_text)
    )
    has_asset_transfer_rule = bool(
        _BRIDGE_CONTRACT_ASSET_TRANSFER_RULE_RE.search(normalized_text)
    )
    has_title_transfer_authority = bool(
        _BRIDGE_CONTRACT_TITLE_TRANSFER_AUTHORITY_RE.search(normalized_text)
    )
    has_safety_regulatory_procedure = bool(
        _BRIDGE_CONTRACT_SAFETY_REGULATORY_PROCEDURE_RE.search(normalized_text)
    )
    has_savings_existing_law = bool(
        _BRIDGE_CONTRACT_SAVINGS_EXISTING_LAW_RE.search(normalized_text)
    )
    has_deceptive_advertising_norm = bool(
        _BRIDGE_CONTRACT_DECEPTIVE_ADVERTISING_NORM_RE.search(normalized_text)
    )
    has_performance_plan_assessment = bool(
        _BRIDGE_CONTRACT_PERFORMANCE_PLAN_ASSESSMENT_RE.search(normalized_text)
    )
    has_recurring_report_deadline = bool(
        _BRIDGE_CONTRACT_RECURRING_REPORT_DEADLINE_RE.search(normalized_text)
    )
    has_retirement_election_rule = bool(
        _BRIDGE_CONTRACT_RETIREMENT_ELECTION_RULE_RE.search(normalized_text)
    )
    has_penalty_noncompliance_period = bool(
        _BRIDGE_CONTRACT_PENALTY_NONCOMPLIANCE_PERIOD_RE.search(normalized_text)
    )
    has_official_notice_duty = bool(
        _BRIDGE_CONTRACT_OFFICIAL_NOTICE_DUTY_RE.search(normalized_text)
    )
    has_admin_review_deadline = bool(
        _BRIDGE_CONTRACT_ADMIN_REVIEW_DEADLINE_RE.search(normalized_text)
    )
    status_operation_cue_count = _cue_count(
        _BRIDGE_CONTRACT_STATUS_OPERATION_CUE_RE,
        normalized_text,
    )
    has_editorial_status_operation = (
        status_operation_cue_count > 0
        or _cue_count(_BRIDGE_CONTRACT_REPEAL_TEMPORAL_CUE_RE, normalized_text) > 0
    ) and (
        structural_frame_cue_count > 0
        or legislative_history_cue_count > 0
    ) and (
        not has_judicial_review_procedure
    )

    target_mix: Sequence[tuple[str, float]]
    strength = 0.0
    if has_repealed_history_scaffold:
        target_mix = (
            ("CEC.native", 0.42),
            ("knowledge_graphs.neo4j_compat", 0.32),
            ("TDFOL.prover", 0.16),
            ("deontic.ir", 0.10),
        )
        strength = 0.42
    elif has_repealed_public_law_status and deontic_cue_count <= 0:
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.38),
            ("CEC.native", 0.34),
            ("TDFOL.prover", 0.18),
            ("deontic.ir", 0.10),
        )
        strength = 0.48
    elif has_editorial_status_operation and deontic_cue_count <= 0:
        target_mix = (
            ("CEC.native", 0.44),
            ("knowledge_graphs.neo4j_compat", 0.34),
            ("TDFOL.prover", 0.14),
            ("deontic.ir", 0.08),
        )
        strength = 0.46
    elif has_definition_provision and deontic_cue_count <= 1:
        target_mix = (
            ("CEC.native", 0.38),
            ("knowledge_graphs.neo4j_compat", 0.28),
            ("deontic.ir", 0.22),
            ("TDFOL.prover", 0.12),
        )
        strength = 0.40
    elif has_purpose_policy_statement and deontic_cue_count <= 1:
        target_mix = (
            ("CEC.native", 0.34),
            ("knowledge_graphs.neo4j_compat", 0.28),
            ("deontic.ir", 0.26),
            ("TDFOL.prover", 0.12),
        )
        strength = 0.36
    elif has_title_transfer_authority and deontic_cue_count > 0:
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.34),
            ("CEC.native", 0.30),
            ("deontic.ir", 0.24),
            ("TDFOL.prover", 0.12),
        )
        strength = 0.44
    elif has_asset_transfer_rule and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.44),
            ("TDFOL.prover", 0.24),
            ("CEC.native", 0.20),
            ("knowledge_graphs.neo4j_compat", 0.12),
        )
        strength = 0.38
    elif has_safety_regulatory_procedure and deontic_cue_count > 0:
        target_mix = (
            ("TDFOL.prover", 0.46),
            ("deontic.ir", 0.28),
            ("CEC.native", 0.16),
            ("knowledge_graphs.neo4j_compat", 0.10),
        )
        strength = 0.40
    elif has_savings_existing_law:
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.34),
            ("CEC.native", 0.28),
            ("deontic.ir", 0.22),
            ("TDFOL.prover", 0.16),
        )
        strength = 0.36
    elif has_deceptive_advertising_norm and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.46),
            ("knowledge_graphs.neo4j_compat", 0.28),
            ("TDFOL.prover", 0.18),
            ("CEC.native", 0.08),
        )
        strength = 0.36
    elif has_performance_plan_assessment and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.46),
            ("TDFOL.prover", 0.28),
            ("CEC.native", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
        strength = 0.34
    elif has_recurring_report_deadline and deontic_cue_count > 0:
        target_mix = (
            ("TDFOL.prover", 0.38),
            ("deontic.ir", 0.34),
            ("CEC.native", 0.20),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
        strength = 0.42
    elif has_retirement_election_rule and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.46),
            ("TDFOL.prover", 0.28),
            ("CEC.native", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
        strength = 0.42
    elif has_penalty_noncompliance_period and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.42),
            ("TDFOL.prover", 0.30),
            ("CEC.native", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.10),
        )
        strength = 0.42
    elif has_official_notice_duty and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.42),
            ("CEC.native", 0.30),
            ("TDFOL.prover", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.10),
        )
        strength = 0.38
    elif has_admin_review_deadline and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.42),
            ("TDFOL.prover", 0.30),
            ("CEC.native", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.10),
        )
        strength = 0.42
    elif has_judicial_review_procedure and deontic_cue_count > 0:
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.30),
            ("deontic.ir", 0.30),
            ("CEC.native", 0.24),
            ("TDFOL.prover", 0.16),
        )
        strength = 0.40
    elif has_liability_provision:
        target_mix = (
            ("deontic.ir", 0.42),
            ("CEC.native", 0.30),
            ("knowledge_graphs.neo4j_compat", 0.20),
            ("TDFOL.prover", 0.08),
        )
        strength = 0.36
    elif has_determination_condition:
        target_mix = (
            ("TDFOL.prover", 0.34),
            ("CEC.native", 0.30),
            ("deontic.ir", 0.24),
            ("knowledge_graphs.neo4j_compat", 0.12),
        )
        strength = 0.38
    elif has_preemption_contract_norm and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.58),
            ("TDFOL.prover", 0.16),
            ("CEC.native", 0.15),
            ("knowledge_graphs.neo4j_compat", 0.11),
        )
        strength = 0.30
    elif has_regulatory_cost_estimate and deontic_cue_count > 0:
        target_mix = (
            ("TDFOL.prover", 0.40),
            ("deontic.ir", 0.28),
            ("CEC.native", 0.20),
            ("knowledge_graphs.neo4j_compat", 0.12),
        )
        strength = 0.42
    elif has_construction_exemption and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.52),
            ("TDFOL.prover", 0.24),
            ("knowledge_graphs.neo4j_compat", 0.16),
            ("CEC.native", 0.08),
        )
        strength = 0.40
    elif has_reporting_duty and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.44),
            ("TDFOL.prover", 0.30),
            ("CEC.native", 0.18),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
        strength = 0.36
    elif has_renaming_designation:
        target_mix = (
            ("knowledge_graphs.neo4j_compat", 0.34),
            ("CEC.native", 0.30),
            ("deontic.ir", 0.24),
            ("TDFOL.prover", 0.12),
        )
        strength = 0.34
    elif has_references_repeal_crossref and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.38),
            ("TDFOL.prover", 0.27),
            ("CEC.native", 0.20),
            ("knowledge_graphs.neo4j_compat", 0.15),
        )
        strength = 0.30
    elif (
        has_enforcement_penalty_provision or has_compliance_enforcement_norm
    ) and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.46),
            ("knowledge_graphs.neo4j_compat", 0.30),
            ("TDFOL.prover", 0.18),
            ("CEC.native", 0.06),
        )
        strength = 0.34
    elif has_fiscal_availability_norm and deontic_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.50),
            ("TDFOL.prover", 0.26),
            ("CEC.native", 0.16),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
        strength = 0.34
    elif has_admin_rulemaking_schedule and deontic_cue_count > 0:
        target_mix = (
            ("CEC.native", 0.34),
            ("TDFOL.prover", 0.30),
            ("deontic.ir", 0.28),
            ("knowledge_graphs.neo4j_compat", 0.08),
        )
        strength = 0.42
    elif deontic_cue_count >= 2 and temporal_cue_count > 0:
        target_mix = (
            ("deontic.ir", 0.50),
            ("TDFOL.prover", 0.28),
            ("CEC.native", 0.16),
            ("knowledge_graphs.neo4j_compat", 0.06),
        )
        strength = 0.28
    elif deontic_cue_count >= 2:
        target_mix = (
            ("deontic.ir", 0.52),
            ("TDFOL.prover", 0.26),
            ("CEC.native", 0.16),
            ("knowledge_graphs.neo4j_compat", 0.06),
        )
        strength = 0.24
    else:
        return lanes

    return _project_contract_distribution_toward_target(
        lanes,
        target_mix,
        strength=strength,
    )


def _metadata_signal_values(metadata: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for key, raw_value in dict(metadata or {}).items():
        key_name = str(key).strip().lower()
        if not key_name.endswith("_count"):
            continue
        if key_name in {"node_count", "relationship_count"}:
            continue
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if numeric_value > 0.0:
            values.append(numeric_value)
    return values


def _payload_signal_values(payload: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    data = payload if isinstance(payload, Mapping) else {}
    for key in ("events", "norms", "obligations", "records", "triples"):
        value = data.get(key)
        if isinstance(value, (str, bytes)):
            continue
        if isinstance(value, Sequence):
            values.append(float(len(value)))
    return values


def _cue_count(pattern: re.Pattern[str], text: str) -> int:
    return sum(1 for _ in pattern.finditer(text))


def _contextual_modal_cue_count(pattern: re.Pattern[str], text: str) -> int:
    """Count modal lexical cues while filtering date-month uses of ``may``."""

    count = 0
    for match in pattern.finditer(text):
        token = match.group(0).strip().lower()
        if token != "may":
            count += 1
            continue
        if _BRIDGE_CONTRACT_MAY_DATE_SUFFIX_RE.match(text[match.end() :]):
            continue
        count += 1
    return count


def _has_sparse_statutory_reference(text: str) -> bool:
    lowered = str(text or "").lower()
    words = re.findall(r"[a-z0-9\-]+", lowered)
    if not words or len(words) > 18:
        return False
    if _BRIDGE_CONTRACT_CITATION_PREFIX_RE.search(text) is None:
        return False
    numeric_tokens = _BRIDGE_CONTRACT_CITATION_TOKEN_RE.findall(text)
    if len(numeric_tokens) < 2:
        return False
    residue = re.sub(r"\b\d+[a-z0-9\-\.]*\b", " ", lowered)
    residue_tokens = [
        token
        for token in re.findall(r"[a-z]+", residue)
        if token not in {"u", "s", "c", "usc", "sec", "section"}
    ]
    return len(residue_tokens) <= 2


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "LegalIRTrainingTarget",
    "MultiViewLegalIRReport",
    "evaluate_legal_ir_multiview",
]
