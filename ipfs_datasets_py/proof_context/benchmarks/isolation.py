"""Fail-closed benchmark and provider-disclosure isolation for PCCE-074.

This module is an independently testable candidate boundary.  It does not run
providers or benchmarks and it is not wired into an authoritative execution
path at this revision.  Agent-visible artifacts and evaluator-only artifacts
have different immutable access graphs and different descriptor roots.  The
evaluator root is metadata-anchored at session creation, but evaluator artifact
descriptors and bodies are opened only after an exact terminal proposal closes.
Normalized and raw hidden-body fragments are screened out of the immutable
objective before the evaluator graph discards those bodies, and each session
anchors both graph CIDs against later object drift.

Provider records are manifests, not source-body transports.  They contain only
bounded, redacted objective text and identities for already-admitted visible
artifacts; paths, filenames, evaluator identities, answers, and body bytes are
absent.  A trusted evaluator callback may read exact evaluator grants during
the post-proposal scoring window, but this module does not claim to sandbox a
malicious callback or to qualify a provider/runtime integration that does not
yet exist.
"""

from __future__ import annotations

import errno
import fnmatch
import os
import re
import shlex
import stat
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import InitVar, dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Self

from ipfs_datasets_py.logic.software_contracts.content import (
    SOURCE_CODEC,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_obj,
    validate_cid,
)
from ipfs_datasets_py.proof_context.benchmarks.specification import (
    BenchmarkSpecificationError,
    strict_json_loads,
)

INTERFACE: Final[str] = "BenchmarkIsolation@0.1"
RUNTIME_INTEGRATION_STATUS: Final[str] = "not_integrated"
ENFORCEMENT_DISPOSITION: Final[str] = "observed_tested_limited"
QUALIFICATION_CREDIT: Final[bool] = False
_EVALUATOR_GRAPH_FACTORY_TOKEN: Final[object] = object()

ISOLATION_DESCRIPTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-context.benchmark-isolation-descriptor@1"
)
AGENT_ACCESS_GRAPH_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-agent-access-graph@1"
EVALUATOR_ACCESS_GRAPH_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-context.benchmark-evaluator-access-graph@1"
)
PROVIDER_PAYLOAD_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-context.benchmark-provider-payload-manifest@1"
)
TERMINAL_PROPOSAL_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-terminal-proposal@1"
EVALUATION_SCORE_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-evaluation-score@1"
ISOLATION_DENIAL_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-isolation-denial@1"

MAX_IDENTIFIER_BYTES: Final[int] = 128
MAX_PATH_BYTES: Final[int] = 4096
MAX_OBJECTIVE_BYTES: Final[int] = 16_384
MAX_PROVIDER_OBJECTIVE_BYTES: Final[int] = 8192
MAX_PROVIDER_PAYLOAD_BYTES: Final[int] = 65_536
MAX_WIRE_RECORD_BYTES: Final[int] = 65_536
MAX_ARTIFACT_BYTES: Final[int] = 2_500_000
MAX_AGGREGATE_ARTIFACT_BYTES: Final[int] = 16_000_000
MAX_AGENT_ARTIFACTS: Final[int] = 256
MAX_EVALUATOR_ARTIFACTS: Final[int] = 256
MAX_OWNED_PATHS: Final[int] = 128
MAX_EVALUATION_CHECKS: Final[int] = 4096
MAX_DENIAL_EVENTS: Final[int] = 256
MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS: Final[int] = 16
MIN_SHORT_CONFIDENTIAL_LITERAL_CHARACTERS: Final[int] = 1
MIN_RAW_CONFIDENTIAL_FRAGMENT_BYTES: Final[int] = 4

AGENT_ARTIFACT_KINDS: Final[tuple[str, ...]] = ("baseline", "public_test")
EVALUATOR_ARTIFACT_KINDS: Final[tuple[str, ...]] = (
    "hidden_test",
    "historical_answer",
    "negative_review",
    "assurance_data",
)
PROPOSAL_STATUSES: Final[tuple[str, ...]] = (
    "proposed",
    "abstained",
    "failed",
    "unavailable",
    "timeout",
    "cancelled",
)
SCORE_STATUSES: Final[tuple[str, ...]] = ("scored_pass", "scored_failures")
DENIAL_REASONS: Final[tuple[str, ...]] = (
    "invalid_record",
    "invalid_path",
    "path_traversal",
    "path_symlink",
    "path_hardlink",
    "path_cross_device",
    "path_alias",
    "path_identity_drift",
    "graph_identity_drift",
    "root_overlap",
    "root_identity_drift",
    "unknown_grant",
    "grant_identity_mismatch",
    "content_alias",
    "future_ref",
    "evaluator_sealed",
    "proposal_mismatch",
    "proposal_already_closed",
    "evaluation_already_terminal",
    "incomplete_evaluation",
    "scoring_failed",
    "payload_overflow",
    "provider_disclosure",
    "serialization_forbidden",
    "closed",
    "audit_overflow",
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_ARTIFACT_ID = re.compile(r"^artifact-[0-9]{4}$")
_GIT_OID = re.compile(r"^[0-9a-f]{40}$")
_GIT_OID_TEXT = re.compile(
    r"(?<![A-Za-z0-9])[0-9a-f]{40}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_ABBREVIATED_GIT_OID_TEXT = re.compile(
    r"(?<![A-Za-z0-9#-])(?=[0-9a-f]{7,39}(?![A-Za-z0-9-]))"
    r"(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,39}(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_EXPLICIT_SHORT_GIT_OID_TEXT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:revision|ref|branch|tag)[ \t]+(?:commit[ \t]+)?"
    r"[0-9a-f]{4,39}(?![A-Za-z0-9])"
)
_CONTEXTUAL_COMMIT_OID_TEXT = re.compile(
    r"(?ix)(?:"
    r"(?<![A-Za-z0-9])(?:use|read|inspect|checkout|resolve|select|from|at)"
    r"[ \t]+commit[ \t]+[0-9a-f]{4,39}(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])commit[ \t]+[0-9a-f]{4,39}"
    r"[ \t]+(?:as|revision|ref|branch|tag|answer)(?![A-Za-z0-9])|"
    r"^[ \t]*commit[ \t]+[0-9a-f]{4,39}[.!?]?[ \t]*$"
    r")"
)
_QUALIFIED_WHITESPACE_REF_TEXT = re.compile(
    r"(?ix)(?<![A-Za-z0-9])(?:branch|tag|ref|revision)[ \t]+(?:"
    r"v?\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.-]+)?|"
    r"(?:main|master|develop|development|trunk|stable|release|next|latest)|"
    r"[A-Za-z0-9]+(?:[-_./:@{}~^][A-Za-z0-9._/!@{}~^:+-]+)+|"
    r":/!?[^\s,;]{1,128}"
    r")(?![A-Za-z0-9])"
)
_CID_CANDIDATE_TEXT = re.compile(
    rf"(?<![A-Za-z0-9_+/\-])[A-Za-z0-9_+/\-]{{4,{MAX_OBJECTIVE_BYTES}}}={{0,8}}"
    r"(?![A-Za-z0-9_+/=\-])"
)
_KNOWN_GIT_REF = (
    r"(?:HEAD|main|master|develop|development|trunk|stable|release|next|latest|"
    r"refs/[A-Za-z0-9._/@{}~^+-]+(?:/[A-Za-z0-9._/@{}~^+-]+)*|"
    r"(?:origin|upstream)/[A-Za-z0-9._/-]+)"
)
_REVISION_EXPRESSION_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?:"
    rf"{_KNOWN_GIT_REF}(?:[~^][0-9]*|@\{{(?:[0-9]+|upstream|u|push|"
    r"yesterday|today|now|[0-9]{4}-[0-9]{2}-[0-9]{2}|"
    r"[0-9]+[ \t]+(?:seconds?|minutes?|hours?|days?|weeks?)[ \t]+ago)\})|"
    r"[A-Za-z][A-Za-z0-9._/-]*[-_./][A-Za-z0-9._/-]*(?:[~^][0-9]*)|"
    r"@\{(?:-?[0-9]+|upstream|u|push|yesterday|today|now)\}"
    r")(?![A-Za-z0-9])"
)
_GIT_RANGE_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?:"
    rf"{_KNOWN_GIT_REF}\.\.\.?(?:HEAD|@|[A-Za-z0-9][A-Za-z0-9_./-]*)|"
    rf"(?:HEAD|@|[A-Za-z0-9][A-Za-z0-9_./-]*)\.\.\.?{_KNOWN_GIT_REF}"
    r")(?![A-Za-z0-9])"
)
_GENERIC_REF_ATOM = r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}"
_GENERIC_REFLOG_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9]){_GENERIC_REF_ATOM}"
    r"@\{(?:[0-9]+|upstream|u|push|yesterday|today|now|"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}|"
    r"[0-9]+(?:[. \t]+)(?:seconds?|minutes?|hours?|days?|weeks?)"
    r"(?:[. \t]+)ago)\}"
    r"(?![A-Za-z0-9])"
)
_FULL_REFLOG_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9]){_GENERIC_REF_ATOM}@\{{(?:"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?"
    r"(?:[ \t]+[+-][0-9]{4})?)?|"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[ \t]+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[ \t]+"
    r"[0-9]{1,2}[ \t]+[0-9]{2}:[0-9]{2}:[0-9]{2}[ \t]+[0-9]{4}"
    r"(?:[ \t]+[+-][0-9]{4})?"
    r")\}(?![A-Za-z0-9])"
)
_GENERIC_TILDE_TEXT = re.compile(rf"(?ix)(?<![A-Za-z0-9]){_GENERIC_REF_ATOM}~[0-9]+(?![A-Za-z0-9])")
_GENERIC_BARE_TILDE_TEXT = re.compile(rf"(?ix)(?<![A-Za-z0-9]){_GENERIC_REF_ATOM}~(?![0-9A-Za-z])")
_GENERIC_BARE_CARET_TEXT = re.compile(rf"(?ix)(?<![A-Za-z0-9]){_GENERIC_REF_ATOM}\^(?![0-9A-Za-z])")
_GENERIC_NUMBERED_CARET_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?P<ref>{_GENERIC_REF_ATOM})\^[0-9]+(?![A-Za-z0-9])"
)
_MATHEMATICAL_CARET_SUFFIX_TEXT = re.compile(
    r"(?ix)^[ \t]+(?:in|for)[ \t]+(?:the[ \t]+)?(?:visible[ \t]+)?"
    r"(?:scoring[ \t]+)?(?:formula|equation|expression)(?![A-Za-z0-9])"
)
_GENERIC_REVISION_PATH_CAPTURE = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?P<ref>{_GENERIC_REF_ATOM}):"
    r"(?P<path>[A-Za-z0-9._/@{}~^+!-]{1,128})"
    r"(?![A-Za-z0-9._/@{}~^+:=!-])"
)
_GENERIC_GIT_RANGE_CAPTURE = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?P<left>{_GENERIC_REF_ATOM})"
    rf"\.{{2,3}}(?P<right>{_GENERIC_REF_ATOM})(?![A-Za-z0-9])"
)
_GENERIC_OMITTED_GIT_RANGE_CAPTURE = re.compile(
    rf"(?ix)(?:"
    rf"(?<![A-Za-z0-9.])(?P<left>{_GENERIC_REF_ATOM})\.{{2,3}}(?![.A-Za-z0-9])|"
    rf"(?<![A-Za-z0-9.])\.{{2,3}}(?P<right>{_GENERIC_REF_ATOM})(?![A-Za-z0-9])"
    r")"
)
_HEX_GIT_RANGE_TEXT = re.compile(
    r"(?ix)(?<![A-Za-z0-9])[0-9a-f]{4,39}\.{2,3}[0-9a-f]{4,39}"
    r"(?![A-Za-z0-9])"
)
_QUALIFIED_SIMPLE_REF_CAPTURE = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?P<qualifier>branch|tag|ref|revision|commit)"
    rf"[ \t]+(?P<ref>{_GENERIC_REF_ATOM})(?![A-Za-z0-9._/-])"
)
_QUALIFIED_UNICODE_REF_CAPTURE = re.compile(
    r"(?iu)(?<!\w)(?P<qualifier>branch|tag|ref|revision|commit)[ \t]+"
    r"(?P<ref>[^\W_][\w./@{}+-]{0,127})(?=$|[\s,;.!?])"
)
_REFERENCE_PREFIX_CONTEXT_TEXT = re.compile(
    r"(?ix)(?:(?:revision|ref|branch|tag|commit)[ \t]+|"
    r"(?:answer|patch|target)[ \t]+(?:is|=)[ \t]+)$"
)
_ANSWER_PREFIX_CONTEXT_TEXT = re.compile(r"(?ix)(?:answer|patch|target)[ \t]+(?:is|=)[ \t]+$")
_REFERENCE_ACTION_PREFIX_TEXT = re.compile(
    r"(?ix)(?:use|read|inspect|checkout|resolve|select|compare|comparison|diff|"
    r"between|from|at)[ \t]+$"
)
_REFERENCE_SUFFIX_CONTEXT_TEXT = re.compile(
    r"(?ix)^[ \t]*(?:"
    r"as[ \t]+(?:the[ \t]+)?(?:answer|revision|ref|branch|tag|commit|patch)|"
    r"for[ \t]+(?:the[ \t]+)?(?:answer|revision|ref|branch|tag|commit|patch)|"
    r"from[ \t]+(?:the[ \t]+)?(?:revision|ref|branch|tag|commit)"
    r")(?![A-Za-z0-9])"
)
_CONTEXTUAL_REF_ATOM_CAPTURE = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?P<ref>{_GENERIC_REF_ATOM})(?![A-Za-z0-9._/-])"
)
_ANY_REFLOG_CAPTURE = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?P<ref>{_GENERIC_REF_ATOM})"
    r"@\{(?P<selector>[^{}\r\n]{1,128})\}(?![A-Za-z0-9])"
)
_GIT_COMMAND_REF_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?:"
    rf"(?:run[ \t]+)?git[ \t]+(?:show|checkout|switch|merge|rebase|"
    rf"cherry-pick|reset|revert|diff)[ \t]+{_GENERIC_REF_ATOM}|"
    rf"(?:checkout|switch|merge|rebase|cherry-pick|reset|revert)[ \t]+"
    rf"(?:(?:branch|tag|ref|revision)[ \t]+)?{_GENERIC_REF_ATOM}"
    rf"[ \t]+(?:before|after)[ \t]+"
    r"(?:coding|implementation|evaluation|review)"
    r")(?![A-Za-z0-9])"
)
_GIT_REVISION_COMMAND_TEXT = re.compile(
    r"(?ix)(?<![A-Za-z0-9])(?:run|exec|command|invoke)?[ \t]*git[ \t]+"
    r"(?:(?:--no-pager|--bare)[ \t]+|"
    r"(?:-C|-c|--git-dir|--work-tree|--namespace)(?:[ \t]+|=)"
    r"[^ \t\r\n]{1,128}[ \t]+){0,4}(?:"
    r"archive|bisect|blame|branch|bundle|cat-file|checkout|cherry|cherry-pick|"
    r"clone|describe|diff|difftool|fetch|for-each-ref|format-patch|grep|log|"
    r"ls-remote|ls-tree|merge|merge-base|name-rev|notes|pack-refs|pull|range-diff|"
    r"rebase|reflog|replace|reset|restore|rev-list|rev-parse|revert|shortlog|show|"
    r"show-branch|show-ref|submodule|switch|symbolic-ref|tag|update-ref|"
    r"verify-commit|verify-tag|whatchanged|worktree"
    r")(?![A-Za-z0-9-])"
)
_GIT_EXECUTABLE_TEXT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_./-])(?:git|(?:/[A-Za-z0-9._+-]+)+/git)"
    r"(?![A-Za-z0-9_.-])"
)
# This is deliberately an allowlist, not an inevitably incomplete list of Git
# revision readers.  Every other command name (including aliases and newly
# added Git commands) is unsafe at this boundary.  These two commands do not
# accept a caller-selected revision operand; revision-valued options are
# screened independently below.
_GIT_NON_REVISION_COMMANDS: Final[frozenset[str]] = frozenset({"add", "status"})
_GIT_REVISION_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "--attr-source",
        "--contains",
        "--merged",
        "--negotiation-tip",
        "--no-contains",
        "--no-merged",
        "--onto",
        "--points-at",
        "--revision",
        "--source",
        "--starting-point",
        "--upstream",
    }
)
_GIT_GLOBAL_OPTIONS_WITH_VALUES: Final[frozenset[str]] = frozenset(
    {
        "-C",
        "-c",
        "--config-env",
        "--exec-path",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
)
_GIT_GLOBAL_OPTIONS_WITHOUT_VALUES: Final[frozenset[str]] = frozenset(
    {
        "-P",
        "-p",
        "--bare",
        "--glob-pathspecs",
        "--help",
        "--html-path",
        "--icase-pathspecs",
        "--info-path",
        "--literal-pathspecs",
        "--man-path",
        "--no-advice",
        "--no-lazy-fetch",
        "--no-optional-locks",
        "--no-pager",
        "--no-replace-objects",
        "--noglob-pathspecs",
        "--paginate",
        "--version",
    }
)
_SHELL_COMMAND_SEPARATORS: Final[frozenset[str]] = frozenset({";", "&", "&&", "|", "||", "(", ")"})
_BARE_GIT_COMMAND_REF_TEXT = re.compile(
    rf"(?ix)^[ \t]*(?:checkout(?:[ \t]+to)?|switch(?:[ \t]+to)?|merge|"
    rf"cherry-pick|rebase|reset|revert)[ \t]+"
    rf"(?:(?:branch|tag|ref|revision)[ \t]+)?{_GENERIC_REF_ATOM}"
    r"[.!?]?[ \t]*$"
)
_CONTEXTUAL_REVISION_ACTION_TEXT = re.compile(
    rf"(?ix)(?<![A-Za-z0-9])(?:use|read|inspect|open|load|retrieve|view|checkout|"
    rf"resolve|select|compare|diff|merge|rebase|reset|switch|apply|evaluate|review|from|at)"
    rf"[ \t]+(?:(?:--[A-Za-z0-9][A-Za-z0-9-]*|-[A-Za-z])[ \t]+)*"
    rf"(?:(?:branch|tag|ref|revision|commit)[ \t]+)?{_GENERIC_REF_ATOM}"
    r"(?:[ \t]+(?:before|after)[ \t]+(?:coding|implementation|evaluation|review)|"
    r"[ \t]+as[ \t]+(?:the[ \t]+)?(?:answer|revision|ref|branch|tag|commit|patch))"
)
_CONTEXTUAL_UNICODE_REVISION_ACTION_CAPTURE = re.compile(
    r"(?iu)(?<!\w)(?:use|read|inspect|open|load|retrieve|view|checkout|resolve|"
    r"select|compare|diff|merge|rebase|reset|switch|apply|evaluate|review|from|at)"
    r"[ \t]+(?:(?:--[A-Za-z0-9][A-Za-z0-9-]*|-[A-Za-z])[ \t]+)*"
    r"(?:(?:branch|tag|ref|revision|commit)[ \t]+)?"
    r"(?P<ref>[^\W_][\w./@{}+-]{0,127})"
    r"(?:[ \t]+(?:before|after)[ \t]+(?:coding|implementation|evaluation|review)|"
    r"[ \t]+as[ \t]+(?:the[ \t]+)?(?:answer|revision|ref|branch|tag|commit|patch))"
)
_BENIGN_CARET_SUFFIX_TEXT = re.compile(
    r"(?ix)^[ \t]+(?:as|in|for)[ \t]+(?:the[ \t]+)?(?:visible[ \t]+)?"
    r"(?:scoring[ \t]+)?(?:exponent|polynomial|formula|equation|expression|power)"
    r"(?![A-Za-z0-9])"
)
_BENIGN_RANGE_SUFFIX_TEXT = re.compile(
    r"(?ix)^[ \t]+(?:as|in|for)[ \t]+(?:the[ \t]+)?(?:visible[ \t]+)?"
    r"(?:range|interval)(?:[ \t]+(?:expression|syntax|notation))?"
    r"(?![A-Za-z0-9])"
)
_BENIGN_COLON_SUFFIX_TEXT = re.compile(
    r"(?ix)^[ \t]+(?:as|in|for)[ \t]+(?:the[ \t]+)?(?:visible[ \t]+)?"
    r"(?:mapping|ratio|syntax|template|documentation)(?![A-Za-z0-9])"
)
_REF_WORDS: Final[frozenset[str]] = frozenset(
    {
        "candidate",
        "develop",
        "development",
        "feature",
        "future",
        "head",
        "latest",
        "main",
        "master",
        "next",
        "release",
        "stable",
        "trunk",
    }
)
_GIT_PATHSPEC_TEXT = re.compile(r"(?<![A-Za-z0-9]):/!?[^\s,;]{1,128}")
_GIT_REVISION_PATH_TEXT = re.compile(rf"(?ix)(?<![A-Za-z0-9]){_KNOWN_GIT_REF}:[^\s,;]{{1,128}}")
_BARE_AT_REF_TEXT = re.compile(r"(?<![A-Za-z0-9_./+@-])@(?![A-Za-z0-9_./+@{-])")
_HTTP_HEAD_TEXT = re.compile(r"(?i)(?<![A-Za-z0-9])HTTP[ \t]+HEAD(?![A-Za-z0-9])")
_REF_LIKE_TEXT = re.compile(
    r"(?x)(?<![A-Za-z0-9])(?:"
    r"(?i:refs[/_-][A-Za-z0-9._/@{}~^+-]+(?:[/_-][A-Za-z0-9._/@{}~^+-]+)*)|"
    r"(?i:(?:origin|upstream)[/_-][A-Za-z0-9._/-]+)|"
    r"(?i:(?:git[ _-]?)?(?:ref|revision|commit|branch|tag)[ \t]*[:=][ \t]*"
    r"[A-Za-z0-9._/-]+)|"
    r"HEAD(?:[~^/_-][A-Za-z0-9._/-]*)?|"
    r"(?i:future[ _-](?:ref|revision|commit|patch|answer|release))"
    r")(?![A-Za-z0-9])"
)
_SECRET_TEXT = re.compile(
    r"(?i)(?:api[\s._:/\\-]*key|access[\s._:/\\-]*token|"
    r"refresh[\s._:/\\-]*token|token|secret|password|passwd|authorization|"
    r"bearer|credential|cookie|private[\s._:/\\-]*key)"
    r"s?\s*[:=]\s*[^\s,;]{3,}"
)
_SENSITIVE_KEYWORD_TEXT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:api[\s._:/\\-]*key|access[\s._:/\\-]*token|"
    r"refresh[\s._:/\\-]*token|client[\s._:/\\-]*secret|"
    r"session[\s._:/\\-]*key|signing[\s._:/\\-]*key|token|secret|password|"
    r"passwd|authorization|bearer|credential|cookie|private[\s._:/\\-]*key)"
    r"(?![A-Za-z0-9])"
)
_BEARER_TEXT = re.compile(
    r"(?i)\b(?:bearer\s+|sk-|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_./+=-]{8,}"
)
_AUTH_SCHEME_TEXT = re.compile(
    r"(?i)\b(?:basic|digest)\s+[A-Za-z0-9+/=_-]{8,}|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]{8,})?\b|"
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----"
)
_PATH_TEXT = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|~?[\\/]|\.{1,2}[\\/])"
    r"[^\s,;\]\[{}\"']+"
    r"|(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+"
    r"|(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+\."
    r"(?:py|pyi|json|toml|yaml|yml|txt|md|patch|diff|cfg|ini)\b",
    re.IGNORECASE,
)
_ANSWER_ASSIGNMENT = re.compile(
    r"(?i)(?:expected[_ -]?patch|future[_ -]?patch|historical[_ -]?answer|"
    r"gold[_ -]?label|hidden[_ -]?test[_ -]?bytes)\s*[:=]"
)
_CONFUSABLE_SLASHES: Final[frozenset[str]] = frozenset(
    {"\N{FRACTION SLASH}", "\N{DIVISION SLASH}", "\N{BIG SOLIDUS}"}
)
_CONFUSABLE_DOTS: Final[frozenset[str]] = frozenset(
    {
        "\N{MIDDLE DOT}",
        "\N{ONE DOT LEADER}",
        "\N{BULLET}",
        "\N{HYPHENATION POINT}",
        "\N{BULLET OPERATOR}",
    }
)
_CONFUSABLE_ASCII: Final[Mapping[str, str]] = MappingProxyType(
    {
        # Bounded UTS-39-style skeleton for common Greek/Cyrillic label and
        # filename homoglyphs.  This is deliberately conservative: provider
        # disclosure prefers redaction over emitting a suspicious alias.
        "\N{CYRILLIC SMALL LETTER A}": "a",
        "\N{GREEK SMALL LETTER ALPHA}": "a",
        "\N{GREEK SMALL LETTER BETA}": "b",
        "\N{CYRILLIC SMALL LETTER VE}": "b",
        "\N{CYRILLIC SMALL LETTER ES}": "c",
        "\N{GREEK LUNATE SIGMA SYMBOL}": "c",
        "\N{CYRILLIC SMALL LETTER KOMI DE}": "d",
        "\N{GREEK SMALL LETTER EPSILON}": "e",
        "\N{CYRILLIC SMALL LETTER IE}": "e",
        "\N{CYRILLIC SMALL LETTER GHE}": "r",
        "\N{GREEK SMALL LETTER ETA}": "h",
        "\N{CYRILLIC SMALL LETTER EN}": "h",
        "\N{CYRILLIC SMALL LETTER SHHA}": "h",
        "\N{GREEK SMALL LETTER IOTA}": "i",
        "\N{CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I}": "i",
        "\N{CYRILLIC SMALL LETTER PALOCHKA}": "i",
        "\N{LATIN SMALL LETTER DOTLESS I}": "i",
        "\N{CYRILLIC SMALL LETTER JE}": "j",
        "\N{GREEK LETTER YOT}": "j",
        "\N{GREEK SMALL LETTER KAPPA}": "k",
        "\N{CYRILLIC SMALL LETTER KA}": "k",
        "\N{GREEK SMALL LETTER MU}": "m",
        "\N{CYRILLIC SMALL LETTER EM}": "m",
        "\N{GREEK SMALL LETTER NU}": "n",
        "\N{GREEK SMALL LETTER OMICRON}": "o",
        "\N{CYRILLIC SMALL LETTER O}": "o",
        "\N{ARMENIAN SMALL LETTER OH}": "o",
        "\N{GREEK SMALL LETTER RHO}": "p",
        "\N{CYRILLIC SMALL LETTER ER}": "p",
        "\N{CYRILLIC SMALL LETTER QA}": "q",
        "\N{CYRILLIC SMALL LETTER DZE}": "s",
        "\N{GREEK SMALL LETTER TAU}": "t",
        "\N{CYRILLIC SMALL LETTER TE}": "t",
        "\N{GREEK SMALL LETTER UPSILON}": "y",
        "\N{CYRILLIC SMALL LETTER U}": "y",
        "\N{CYRILLIC SMALL LETTER IZHITSA}": "v",
        "\N{CYRILLIC SMALL LETTER WE}": "w",
        "\N{GREEK SMALL LETTER CHI}": "x",
        "\N{CYRILLIC SMALL LETTER HA}": "x",
        "\N{GREEK SMALL LETTER ZETA}": "z",
    }
)
_CONFUSABLE_ASCII_ALTERNATIVES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        # Some glyphs have more than one plausible ASCII skeleton depending
        # on the font.  Provider disclosure must treat either reading as an
        # alias instead of selecting the least restrictive interpretation.
        "\N{GREEK SMALL LETTER NU}": frozenset(("n", "v")),
        "\N{GREEK SMALL LETTER IOTA}": frozenset(("i", "l")),
        "\N{CYRILLIC SMALL LETTER PALOCHKA}": frozenset(("i", "l")),
        "\N{LATIN SMALL LETTER DOTLESS I}": frozenset(("i", "l")),
        "\N{GREEK LUNATE SIGMA SYMBOL}": frozenset(("c",)),
        "\N{CYRILLIC SMALL LETTER GHE}": frozenset(("r",)),
        "\N{CYRILLIC SMALL LETTER KOMI DE}": frozenset(("d",)),
        "\N{CYRILLIC SMALL LETTER QA}": frozenset(("q",)),
        "\N{GREEK SMALL LETTER UPSILON}": frozenset(("u", "y")),
        "\N{CYRILLIC SMALL LETTER IZHITSA}": frozenset(("v", "y")),
        "\N{GREEK SMALL LETTER SIGMA}": frozenset(("c", "s")),
        "\N{GREEK SMALL LETTER FINAL SIGMA}": frozenset(("c", "s")),
    }
)
_COMPACT_SENSITIVE_KEYWORDS: Final[tuple[str, ...]] = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "sessionkey",
    "signingkey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "bearer",
    "credential",
    "cookie",
    "privatekey",
)
_ROOT_DIRECTORY_FLAGS: Final[int] = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_FILE_FLAGS: Final[int] = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK

_STATIC_MESSAGES: Final[dict[str, str]] = {
    "invalid_record": "isolation record was rejected",
    "invalid_path": "artifact path was rejected",
    "path_traversal": "artifact traversal was rejected",
    "path_symlink": "symbolic-link access was rejected",
    "path_hardlink": "hard-linked artifact access was rejected",
    "path_cross_device": "cross-device artifact access was rejected",
    "path_alias": "artifact alias was rejected",
    "path_identity_drift": "artifact identity changed",
    "graph_identity_drift": "access graph identity changed",
    "root_overlap": "agent and evaluator roots overlap",
    "root_identity_drift": "projection root identity changed",
    "unknown_grant": "no exact artifact grant matched",
    "grant_identity_mismatch": "artifact grant identity did not match",
    "content_alias": "visible and evaluator content overlap",
    "future_ref": "future or unscoped revision was rejected",
    "evaluator_sealed": "evaluator access is sealed until proposal closure",
    "proposal_mismatch": "terminal proposal binding did not match",
    "proposal_already_closed": "a terminal proposal was already closed",
    "evaluation_already_terminal": "evaluation is already terminal",
    "incomplete_evaluation": "evaluator did not consume every granted artifact",
    "scoring_failed": "evaluator scoring failed",
    "payload_overflow": "provider payload exceeded its bound",
    "provider_disclosure": "provider payload disclosure policy was violated",
    "serialization_forbidden": "private evaluator graph serialization is forbidden",
    "closed": "isolation session is closed",
    "audit_overflow": "isolation denial audit reached its bound",
}


class IsolationError(RuntimeError):
    """Fail-closed isolation error with a closed, non-sensitive reason."""

    def __init__(self, reason: str, *, denial: Any | None = None) -> None:
        if reason not in DENIAL_REASONS:
            reason = "invalid_record"
        self.reason = reason
        self.denial = denial
        super().__init__(_STATIC_MESSAGES[reason])


def _utf8_length(value: str, *, reason: str = "invalid_record") -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise IsolationError(reason) from None


def _require_exact_fields(
    value: Mapping[str, Any], *, required: Sequence[str], field_name: str
) -> None:
    required_set = set(required)
    if set(value) != required_set:
        raise IsolationError("invalid_record")


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    del field_name
    if type(value) is not dict:
        raise IsolationError("invalid_record")
    return value


def _identifier(value: Any) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise IsolationError("invalid_record")
    if _utf8_length(value) > MAX_IDENTIFIER_BYTES:
        raise IsolationError("invalid_record")
    return value


def _cid(value: Any, *, structured: bool | None = None) -> str:
    if type(value) is not str:
        raise IsolationError("invalid_record")
    codecs: tuple[str, ...]
    if structured is True:
        codecs = (STRUCTURED_CODEC,)
    elif structured is False:
        codecs = (SOURCE_CODEC,)
    else:
        codecs = (SOURCE_CODEC, STRUCTURED_CODEC)
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise IsolationError("invalid_record") from exc


def _bounded_int(value: Any, *, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise IsolationError("invalid_record")
    return value


def _text(value: Any, *, maximum: int, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value.strip()):
        raise IsolationError("invalid_record")
    if _utf8_length(value) > maximum or "\x00" in value:
        raise IsolationError("invalid_record")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise IsolationError("invalid_record")
    return value


def _safe_relative_path(value: Any) -> str:
    if (
        type(value) is not str
        or not value
        or _utf8_length(value, reason="invalid_path") > MAX_PATH_BYTES
    ):
        raise IsolationError("invalid_path")
    if unicodedata.normalize("NFC", value) != value or "\x00" in value or "\\" in value:
        raise IsolationError("invalid_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise IsolationError("path_traversal")
    if str(path) != value or any(part.casefold() == ".git" for part in path.parts):
        raise IsolationError("path_traversal")
    for part in path.parts:
        if part.endswith((" ", ".")) or ":" in part:
            raise IsolationError("invalid_path")
        if any(ord(character) < 32 for character in part):
            raise IsolationError("invalid_path")
    return value


def _path_alias_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _is_ignorable_security_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.category(character) == "Cf"
        or character == "\N{COMBINING GRAPHEME JOINER}"
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xE0100 <= codepoint <= 0xE01EF
    )


def _canonical_separator(character: str) -> str:
    # Strip combining marks after compatibility decomposition so precomposed
    # and decomposed accents cannot split security keywords or hidden tokens.
    decomposed = "".join(
        part
        for part in unicodedata.normalize("NFKD", character)
        if unicodedata.category(part) not in {"Mn", "Me"}
    )
    result: list[str] = []
    for part in decomposed:
        confusable = _CONFUSABLE_ASCII.get(part.casefold())
        if confusable is not None:
            result.append(confusable)
        elif part in _CONFUSABLE_SLASHES:
            result.append("/")
        elif part in _CONFUSABLE_DOTS:
            result.append(".")
        elif unicodedata.category(part) == "Pd":
            result.append("-")
        else:
            result.append(part)
    return "".join(result)


def _normalized_policy_text(value: str) -> str:
    """Canonicalize compatibility forms and separator-like format controls."""

    normalized = unicodedata.normalize("NFKC", value)
    result: list[str] = []
    for character in normalized:
        if _is_ignorable_security_character(character):
            continue
        if character.isspace():
            result.append(" ")
            continue
        canonical = _canonical_separator(character)
        if (
            canonical == character
            and not character.isascii()
            and unicodedata.category(character)[0] in {"P", "S"}
        ):
            result.append(" ")
        else:
            result.append(canonical)
    return "".join(result)


def _confusable_character_options(value: str) -> tuple[frozenset[str], ...]:
    """Return bounded per-character skeleton choices for disclosure matching."""

    result: list[frozenset[str]] = []
    for character in unicodedata.normalize("NFKC", value).casefold():
        if _is_ignorable_security_character(character):
            continue
        if character.isspace():
            options = frozenset((" ",))
        else:
            decomposed = tuple(
                part
                for part in unicodedata.normalize("NFKD", character)
                if unicodedata.category(part) not in {"Mn", "Me"}
            )
            for part in decomposed:
                alternatives = _CONFUSABLE_ASCII_ALTERNATIVES.get(part.casefold())
                canonical = _canonical_separator(part)
                if alternatives is not None:
                    for canonical_part in canonical:
                        result.append(frozenset((*alternatives, canonical_part)))
                elif not part.isascii() and part.isalpha():
                    # The Unicode confusables table is intentionally open-ended.
                    # Treat an unmapped non-ASCII letter as any ASCII letter at
                    # this disclosure boundary.  This is conservative, bounded,
                    # and prevents a newly added homoglyph from becoming a
                    # one-character hidden-data bypass.
                    for canonical_part in canonical:
                        result.append(frozenset((*"abcdefghijklmnopqrstuvwxyz", canonical_part)))
                else:
                    result.extend(frozenset((canonical_part,)) for canonical_part in canonical)
            continue
        if result and options == frozenset((" ",)) and result[-1] == options:
            continue
        result.append(options)
    return tuple(result)


def _confusable_option_is_continuation(options: frozenset[str]) -> bool:
    return any(_literal_continuation(character) for character in options)


def _contains_confusable_literal(value: str, literal: str) -> bool:
    """Match a private literal through conservative Unicode skeleton choices."""

    if not literal or (value.isascii() and literal.isascii()):
        return False
    value_options = _confusable_character_options(value)
    literal_options = _confusable_character_options(literal)
    if not literal_options or len(literal_options) > len(value_options):
        return False
    width = len(literal_options)
    for index in range(len(value_options) - width + 1):
        end = index + width
        if not all(
            value_options[index + offset] & literal_options[offset] for offset in range(width)
        ):
            continue
        left_ok = index == 0 or not _confusable_option_is_continuation(value_options[index - 1])
        right_ok = end == len(value_options) or not _confusable_option_is_continuation(
            value_options[end]
        )
        if not right_ok and value_options[end] == frozenset((".",)):
            after_dot = end + 1
            right_ok = after_dot == len(value_options) or not any(
                character.isalnum() for character in value_options[after_dot]
            )
        if left_ok and right_ok:
            return True
    return False


def _has_suspicious_mixed_script(value: str) -> bool:
    """Fail closed on mixed Latin/Greek/Cyrillic text in provider-visible fields."""

    scripts: set[str] = set()
    for character in unicodedata.normalize("NFKC", value):
        if not character.isalpha():
            continue
        name = unicodedata.name(character, "")
        script = next(
            (candidate for candidate in ("LATIN", "GREEK", "CYRILLIC") if candidate in name),
            None,
        )
        if script is not None:
            scripts.add(script)
    return len(scripts) > 1


def _has_local_revision_context(value: str, start: int, end: int) -> bool:
    """Recognize syntax as a revision without treating distant prose as context."""

    prefix = value[max(0, start - 96) : start]
    suffix = value[end : min(len(value), end + 96)]
    return bool(
        _REFERENCE_PREFIX_CONTEXT_TEXT.search(prefix)
        or _REFERENCE_ACTION_PREFIX_TEXT.search(prefix)
        or _REFERENCE_SUFFIX_CONTEXT_TEXT.search(suffix)
    )


def _is_standalone_revision_syntax(value: str, start: int, end: int) -> bool:
    prefix = value[:start].strip()
    suffix = value[end:].strip()
    return not prefix and (not suffix or suffix in {".", "!", "?"})


def _fold_shell_line_continuations(value: str) -> str:
    """Fold only POSIX backslash-newline pairs outside single quotes."""

    result: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote == "'":
            result.append(character)
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\":
            newline_width = 0
            if value[index + 1 : index + 2] == "\n":
                newline_width = 1
            elif value[index + 1 : index + 3] == "\r\n":
                newline_width = 2
            if newline_width:
                index += newline_width + 1
                continue
            result.append(character)
            if quote is None and index + 1 < len(value):
                # Outside quotes, the backslash quotes the next character.  Do
                # not let a quoted backslash independently quote a later newline.
                result.append(value[index + 1])
                index += 2
                continue
            if quote == '"' and value[index + 1 : index + 2] in {'"', "$", "`", "\\"}:
                result.append(value[index + 1])
                index += 2
                continue
            index += 1
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
        result.append(character)
        index += 1
    return "".join(result)


def _contains_unresolved_shell_expansion(value: str) -> bool:
    """Return whether shell expansion could change an executable or argument."""

    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\":
            following = value[index + 1 : index + 2]
            if quote is None or following in {'"', "$", "`", "\\"}:
                index += 2
            else:
                index += 1
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            index += 1
            continue
        if character == "'" and quote is None:
            quote = "'"
            index += 1
            continue
        if character == "`":
            return True
        if (
            character == "$"
            and value[index + 1 : index + 2]
            and (value[index + 1].isalnum() or value[index + 1] in "_{('*@#?$!-\"")
        ):
            # Do not simulate parameter, command, arithmetic, ANSI-C, or
            # locale expansion.  Any unresolved expansion is unsafe because it
            # can supply ``git`` or a revision-consuming subcommand at runtime.
            return True
        index += 1
    return False


def _shell_words(value: str) -> tuple[str, ...] | None:
    """Lex shell-shaped prose without expanding or executing any of it."""

    continued = _fold_shell_line_continuations(value)
    lexer = shlex.shlex(continued, posix=True, punctuation_chars=";&|()")
    lexer.commenters = ""
    lexer.whitespace_split = True
    try:
        return tuple(lexer)
    except ValueError:
        # An unmatched quote is not executable shell syntax.  The legacy raw
        # scan below still handles ordinary prose such as ``git's parser``.
        return None


def _shell_brace_expansions(value: str) -> tuple[str, ...] | None:
    """Return bounded simple shell brace expansions, or ``None`` on overflow."""

    pending = [value]
    expanded: list[str] = []
    while pending:
        candidate = pending.pop()
        start = candidate.find("{")
        end = candidate.find("}", start + 1) if start >= 0 else -1
        if start < 0 or end < 0 or "," not in candidate[start + 1 : end]:
            expanded.append(candidate)
            continue
        alternatives = candidate[start + 1 : end].split(",")
        if len(pending) + len(expanded) + len(alternatives) > 32:
            return None
        pending.extend(
            candidate[:start] + alternative + candidate[end + 1 :] for alternative in alternatives
        )
    return tuple(expanded)


def _shell_word_can_name(value: str, target: str) -> bool:
    expansions = _shell_brace_expansions(value)
    if expansions is None:
        return True
    return any(
        candidate == target
        or (
            any(character in candidate for character in "*?[")
            and fnmatch.fnmatchcase(target, candidate)
        )
        for candidate in expansions
    )


def _git_executable_subcommand(value: str) -> str | None:
    """Return a direct ``git-*`` subcommand, or ``""`` for Git itself.

    Shell pathname expansion can turn spellings such as ``g?t`` into ``git``.
    Treat only patterns that can name Git as Git-shaped; other ordinary glob
    prose remains outside this detector.  Installed ``git-<command>`` helpers
    are executable entry points too and must not bypass the command allowlist.
    """

    candidate = value.strip("'\"`()").rstrip(".,;:")
    basename = PurePosixPath(candidate).name.casefold()
    if _shell_word_can_name(basename, "git"):
        return ""
    expansions = _shell_brace_expansions(basename)
    if expansions is None:
        return "dynamic"
    subcommands = {
        expanded[len("git-") :]
        for expanded in expansions
        if expanded.startswith("git-") and len(expanded) > len("git-")
    }
    if any(any(character in expanded for character in "*?[") for expanded in expansions):
        if any(expanded.startswith("git-") for expanded in expansions):
            return "dynamic"
    if len(subcommands) == 1:
        return subcommands.pop()
    if subcommands:
        return "dynamic"
    return None


def _shell_words_invoke_revision_command(words: tuple[str, ...], *, depth: int) -> bool:
    """Inspect bounded shell and ``eval`` payloads after quote concatenation."""

    shells = frozenset({"bash", "dash", "ksh", "sh", "zsh"})
    for executable_index, executable in enumerate(words):
        candidate = executable.strip("'\"`()").rstrip(".,;:")
        basename = PurePosixPath(candidate).name.casefold()
        if basename == "eval":
            payload: list[str] = []
            index = executable_index + 1
            while index < len(words) and words[index] not in _SHELL_COMMAND_SEPARATORS:
                payload.append(words[index])
                index += 1
            if not payload or depth >= 8:
                return True
            if _contains_git_revision_command(" ".join(payload), _depth=depth + 1):
                return True
            continue
        if not any(_shell_word_can_name(basename, shell) for shell in shells):
            continue
        index = executable_index + 1
        while index < len(words) and words[index] not in _SHELL_COMMAND_SEPARATORS:
            option = words[index].strip("'\"`()[]{}.,;:")
            if option.startswith("-") and "c" in option[1:]:
                if index + 1 >= len(words) or words[index + 1] in _SHELL_COMMAND_SEPARATORS:
                    return True
                if depth >= 8:
                    return True
                if _contains_git_revision_command(words[index + 1], _depth=depth + 1):
                    return True
                break
            if not option.startswith("-"):
                break
            index += 1
    return False


def _git_words_invoke_revision_command(
    words: tuple[str, ...],
) -> bool:
    for executable_index, executable in enumerate(words):
        direct_subcommand = _git_executable_subcommand(executable)
        if direct_subcommand is None:
            continue
        index = executable_index + 1
        if direct_subcommand:
            if direct_subcommand not in _GIT_NON_REVISION_COMMANDS:
                return True
            while index < len(words) and words[index] not in _SHELL_COMMAND_SEPARATORS:
                command_token = words[index].strip("'\"`()[]{}.,;:")
                if command_token.partition("=")[0] in _GIT_REVISION_VALUE_OPTIONS:
                    return True
                index += 1
            continue
        while index < len(words):
            raw_token = words[index]
            if raw_token in _SHELL_COMMAND_SEPARATORS:
                break
            token = raw_token.strip("'\"`()[]{}.,;:")
            if not token:
                index += 1
                continue
            option, separator, _ = token.partition("=")
            if option in _GIT_REVISION_VALUE_OPTIONS:
                return True
            if option in _GIT_GLOBAL_OPTIONS_WITH_VALUES:
                if not separator:
                    if index + 1 >= len(words) or words[index + 1] in _SHELL_COMMAND_SEPARATORS:
                        return True
                    index += 1
                index += 1
                continue
            attached_value_option = next(
                (
                    candidate
                    for candidate in ("-C", "-c")
                    if token.startswith(candidate) and token != candidate
                ),
                None,
            )
            if attached_value_option is not None:
                index += 1
                continue
            if token in _GIT_GLOBAL_OPTIONS_WITHOUT_VALUES:
                index += 1
                continue
            if token == "--" or token.startswith("-"):
                # Unknown global options may consume the next token and change
                # how Git dispatches.  Refuse them instead of guessing arity.
                return True
            if token.casefold() not in _GIT_NON_REVISION_COMMANDS:
                return True
            index += 1
            while index < len(words) and words[index] not in _SHELL_COMMAND_SEPARATORS:
                command_token = words[index].strip("'\"`()[]{}.,;:")
                command_option = command_token.partition("=")[0]
                if command_option in _GIT_REVISION_VALUE_OPTIONS:
                    return True
                index += 1
            break
    return False


def _contains_git_revision_command(value: str, *, _depth: int = 0) -> bool:
    """Fail closed on dynamic or non-allowlisted Git-shaped shell text."""

    continued = _fold_shell_line_continuations(value)
    if _contains_unresolved_shell_expansion(continued):
        return True
    words = _shell_words(continued)
    if words is not None and _git_words_invoke_revision_command(words):
        return True
    if words is not None and _shell_words_invoke_revision_command(words, depth=_depth):
        return True

    # Retain a bounded tolerant scan for natural prose with unmatched quotes.
    if words is not None:
        return False
    for executable in _GIT_EXECUTABLE_TEXT.finditer(value):
        tail = value[executable.end() :]
        if tail.casefold().startswith("'s"):
            continue
        line = tail.splitlines()[0] if tail else ""
        tokens = re.findall(r"[^ \t\r\n]+", line)
        if _git_words_invoke_revision_command(("git", *tokens)):
            return True
    return False


def _contains_future_reference(value: str) -> bool:
    """Conservatively identify Git/CID/future-answer reference syntax."""

    # Shell line continuation is meaningful before policy whitespace
    # normalization, so inspect the bounded original spelling first.
    if _contains_git_revision_command(value):
        return True
    value = _normalized_policy_text(value)
    value = _HTTP_HEAD_TEXT.sub("HTTP_METHOD", value)
    if (
        _GIT_OID_TEXT.search(value)
        or _ABBREVIATED_GIT_OID_TEXT.search(value)
        or _EXPLICIT_SHORT_GIT_OID_TEXT.search(value)
        or _CONTEXTUAL_COMMIT_OID_TEXT.search(value)
        or _QUALIFIED_WHITESPACE_REF_TEXT.search(value)
        or _REVISION_EXPRESSION_TEXT.search(value)
        or _GENERIC_REFLOG_TEXT.search(value)
        or _FULL_REFLOG_TEXT.search(value)
        or _GENERIC_TILDE_TEXT.search(value)
        or _GENERIC_BARE_TILDE_TEXT.search(value)
        or _GENERIC_BARE_CARET_TEXT.search(value)
        or _GIT_RANGE_TEXT.search(value)
        or _HEX_GIT_RANGE_TEXT.search(value)
        or _GIT_PATHSPEC_TEXT.search(value)
        or _GIT_REVISION_PATH_TEXT.search(value)
        or _BARE_AT_REF_TEXT.search(value)
        or _REF_LIKE_TEXT.search(value)
        or _GIT_COMMAND_REF_TEXT.search(value)
        or _GIT_REVISION_COMMAND_TEXT.search(value)
        or _contains_git_revision_command(value)
        or _BARE_GIT_COMMAND_REF_TEXT.search(value)
        or _CONTEXTUAL_REVISION_ACTION_TEXT.search(value)
    ):
        return True
    for match in _ANY_REFLOG_CAPTURE.finditer(value):
        reference = match.group("ref")
        selector = match.group("selector")
        suffix = value[match.end() : min(len(value), match.end() + 96)]
        benign_template = (
            reference.casefold() == "user"
            and selector.casefold() == "host"
            and re.search(r"(?i)^\s+literally\s+in\s+the\s+template", suffix)
        )
        if not benign_template:
            return True
    for match in _CONTEXTUAL_UNICODE_REVISION_ACTION_CAPTURE.finditer(value):
        if not match.group("ref").isascii():
            return True
    for match in _CONTEXTUAL_REF_ATOM_CAPTURE.finditer(value):
        prefix = value[max(0, match.start() - 96) : match.start()]
        suffix = value[match.end() : min(len(value), match.end() + 96)]
        if _ANSWER_PREFIX_CONTEXT_TEXT.search(prefix) or _REFERENCE_SUFFIX_CONTEXT_TEXT.search(
            suffix
        ):
            return True
    for match in _QUALIFIED_SIMPLE_REF_CAPTURE.finditer(value):
        reference = match.group("ref")
        if (
            reference.casefold() in _REF_WORDS
            or _has_local_revision_context(value, match.start(), match.end())
            or _is_standalone_revision_syntax(value, match.start(), match.end())
        ):
            return True
    for match in _QUALIFIED_UNICODE_REF_CAPTURE.finditer(value):
        reference = match.group("ref")
        if not reference.isascii() and (
            _has_local_revision_context(value, match.start(), match.end())
            or _is_standalone_revision_syntax(value, match.start(), match.end())
        ):
            return True
    for match in _GENERIC_NUMBERED_CARET_TEXT.finditer(value):
        reference = match.group("ref")
        local_context = _has_local_revision_context(value, match.start(), match.end())
        if _MATHEMATICAL_CARET_SUFFIX_TEXT.search(
            value[match.end() :]
        ) or _BENIGN_CARET_SUFFIX_TEXT.search(value[match.end() :]):
            local_context = False
        if (
            reference.casefold() in _REF_WORDS
            or "/" in reference
            or "." in reference
            or local_context
            or _is_standalone_revision_syntax(value, match.start(), match.end())
        ):
            return True
    for match in _GENERIC_REVISION_PATH_CAPTURE.finditer(value):
        path = match.group("path")
        reference = match.group("ref")
        if _BENIGN_COLON_SUFFIX_TEXT.search(value[match.end() :]):
            continue
        if (
            reference.casefold() in _REF_WORDS
            or path.casefold() == "path"
            or "/" in path
            or "." in path
            or _has_local_revision_context(value, match.start(), match.end())
        ):
            return True
    for match in _GENERIC_GIT_RANGE_CAPTURE.finditer(value):
        left = match.group("left")
        right = match.group("right")
        if _BENIGN_RANGE_SUFFIX_TEXT.search(value[match.end() :]):
            continue
        alphabet_interval = len(left) == len(right) == 1 and left.isupper() and right.isupper()
        if not alphabet_interval and (
            "/" in left
            or "/" in right
            or left.casefold() in _REF_WORDS
            or right.casefold() in _REF_WORDS
            or _has_local_revision_context(value, match.start(), match.end())
            or _is_standalone_revision_syntax(value, match.start(), match.end())
        ):
            return True
    for match in _GENERIC_OMITTED_GIT_RANGE_CAPTURE.finditer(value):
        endpoint = match.group("left") or match.group("right")
        if (
            "/" in endpoint
            or endpoint.casefold() in _REF_WORDS
            or _has_local_revision_context(value, match.start(), match.end())
            or _is_standalone_revision_syntax(value, match.start(), match.end())
        ):
            return True
    for candidate in _CID_CANDIDATE_TEXT.findall(value):
        try:
            from multiformats import CID

            parsed = CID.decode(candidate)
        except (KeyError, TypeError, ValueError):
            continue
        if parsed.version in {0, 1} and str(parsed) == candidate:
            return True
    return False


def _literal_continuation(character: str) -> bool:
    return character.isalnum() or character in "_./:-\\"


def _contains_sensitive_literal(value: str, literal: str) -> bool:
    """Match an exact private token/path without one-character substring aliases."""

    if not literal:
        return False
    if _contains_confusable_literal(value, literal):
        return True
    folded_value = _normalized_confidential_literal(value)
    folded_literal = _normalized_confidential_literal(literal)
    start = 0
    while True:
        index = folded_value.find(folded_literal, start)
        if index < 0:
            return False
        end = index + len(folded_literal)
        left_ok = index == 0 or not _literal_continuation(folded_value[index - 1])
        right_ok = end == len(folded_value) or not _literal_continuation(folded_value[end])
        if not right_ok and folded_value[end] == ".":
            # A terminal sentence full stop is a delimiter; a dot followed by
            # another path/token character remains a continuation (``x.py``).
            after_dot = end + 1
            right_ok = after_dot == len(folded_value) or not folded_value[after_dot].isalnum()
        if left_ok and right_ok:
            return True
        start = index + 1


def _normalized_confidential_text(value: str) -> str:
    normalized = _normalized_confidential_literal(value)
    return " ".join(re.sub(r"[\W_]+", " ", normalized).split())


def _normalized_confidential_literal(value: str) -> str:
    """Normalize case and spacing while retaining exact symbols and punctuation."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    result: list[str] = []
    for character in normalized:
        if _is_ignorable_security_character(character):
            continue
        result.append(_canonical_separator(character))
    return " ".join("".join(result).split())


def _compact_confidential_text(value: str) -> tuple[str, frozenset[int]]:
    """Remove in-token punctuation while retaining exact outer token boundaries."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters: list[str] = []
    boundaries: set[int] = {0}
    separator_seen = False
    for character in normalized:
        if _is_ignorable_security_character(character):
            continue
        if character.isalnum():
            if separator_seen:
                boundaries.add(len(characters))
            characters.append(character)
            separator_seen = False
        else:
            separator_seen = True
    boundaries.add(len(characters))
    return "".join(characters), frozenset(boundaries)


def _contains_compact_token(value: str, token: str) -> bool:
    compact, boundaries = _compact_confidential_text(value)
    start = 0
    while True:
        index = compact.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        if index in boundaries and end in boundaries:
            return True
        start = index + 1


def _contains_compact_confidential_fragment(objective: str, hidden: str) -> bool:
    objective_compact, objective_boundaries = _compact_confidential_text(objective)
    hidden_compact, _hidden_boundaries = _compact_confidential_text(hidden)
    if not hidden_compact:
        return False
    if len(hidden_compact) < MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS:
        start = 0
        while True:
            index = objective_compact.find(hidden_compact, start)
            if index < 0:
                return False
            end = index + len(hidden_compact)
            if index in objective_boundaries and end in objective_boundaries:
                return True
            start = index + 1
    objective_fragments = {
        objective_compact[index : index + MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS]
        for index in range(
            max(0, len(objective_compact) - MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS + 1)
        )
    }
    return any(
        hidden_compact[index : index + MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS] in objective_fragments
        for index in range(len(hidden_compact) - MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS + 1)
    )


def _contains_confidential_fragment(objective: str, payload: bytes) -> bool:
    """Detect exact normalized hidden fragments with bounded linear scanning."""

    try:
        decoded_payload = payload.decode("utf-8")
    except UnicodeDecodeError:
        decoded_payload = ""
        hidden_text = ""
        hidden_literal = ""
    else:
        hidden_text = _normalized_confidential_text(decoded_payload)
        hidden_literal = _normalized_confidential_literal(decoded_payload)
        if _contains_confusable_literal(objective, decoded_payload):
            return True
    objective_text = _normalized_confidential_text(objective)
    objective_literal = _normalized_confidential_literal(objective)
    if hidden_literal and len(hidden_literal) < MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS:
        if any(character.isalnum() for character in hidden_literal):
            if _contains_sensitive_literal(objective_literal, hidden_literal):
                return True
        elif hidden_literal in objective_literal:
            return True
    if hidden_text:
        if len(hidden_text) < MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS:
            if len(
                hidden_text
            ) >= MIN_SHORT_CONFIDENTIAL_LITERAL_CHARACTERS and _contains_sensitive_literal(
                objective_text, hidden_text
            ):
                return True
        else:
            objective_fragments = {
                objective_text[index : index + MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS]
                for index in range(
                    max(0, len(objective_text) - MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS + 1)
                )
            }
            if any(
                hidden_text[index : index + MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS]
                in objective_fragments
                for index in range(len(hidden_text) - MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS + 1)
            ):
                return True
    if decoded_payload and _contains_compact_confidential_fragment(objective, decoded_payload):
        return True

    objective_bytes = objective.encode("utf-8")
    if len(payload) < MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS:
        return len(payload) >= MIN_RAW_CONFIDENTIAL_FRAGMENT_BYTES and payload in objective_bytes
    objective_byte_fragments = {
        objective_bytes[index : index + MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS]
        for index in range(max(0, len(objective_bytes) - MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS + 1))
    }
    return any(
        payload[index : index + MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS] in objective_byte_fragments
        for index in range(len(payload) - MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS + 1)
    )


def _contains_secret_indicator(value: str) -> bool:
    normalized = _normalized_policy_text(value)
    return bool(
        _SECRET_TEXT.search(normalized)
        or _SENSITIVE_KEYWORD_TEXT.search(normalized)
        or any(_contains_compact_token(value, keyword) for keyword in _COMPACT_SENSITIVE_KEYWORDS)
        or _BEARER_TEXT.search(normalized)
        or _AUTH_SCHEME_TEXT.search(normalized)
    )


def _canonical_json(mapping: Mapping[str, Any]) -> str:
    try:
        return canonical_dag_json_bytes(dict(mapping)).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IsolationError("invalid_record") from exc


def _strict_mapping(payload: str | bytes) -> Mapping[str, Any]:
    if type(payload) is bytes:
        size = len(payload)
    elif type(payload) is str:
        size = _utf8_length(payload)
    else:
        raise IsolationError("invalid_record")
    if size > MAX_WIRE_RECORD_BYTES:
        raise IsolationError("payload_overflow")
    try:
        value = strict_json_loads(payload)
    except BenchmarkSpecificationError as exc:
        raise IsolationError("invalid_record") from exc
    return _mapping(value, "payload")


@dataclass(frozen=True, slots=True, repr=False)
class ArtifactGrant:
    """Exact internal grant; paths never enter provider or score records."""

    artifact_id: str
    kind: str
    relative_path: str
    content_cid: str
    byte_count: int

    def __post_init__(self) -> None:
        if type(self.artifact_id) is not str or not _ARTIFACT_ID.fullmatch(self.artifact_id):
            raise IsolationError("invalid_record")
        if (
            type(self.kind) is not str
            or self.kind not in AGENT_ARTIFACT_KINDS + EVALUATOR_ARTIFACT_KINDS
        ):
            raise IsolationError("invalid_record")
        object.__setattr__(self, "relative_path", _safe_relative_path(self.relative_path))
        object.__setattr__(self, "content_cid", _cid(self.content_cid, structured=False))
        object.__setattr__(
            self,
            "byte_count",
            _bounded_int(self.byte_count, maximum=MAX_ARTIFACT_BYTES),
        )

    def _identity_mapping(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "content_cid": self.content_cid,
            "byte_count": self.byte_count,
        }

    def __repr__(self) -> str:
        return f"ArtifactGrant(artifact_id={self.artifact_id!r}, kind={self.kind!r})"


def _validate_grants(
    grants: tuple[ArtifactGrant, ...], *, kinds: tuple[str, ...], maximum: int
) -> None:
    if type(grants) is not tuple or len(grants) > maximum:
        raise IsolationError("invalid_record")
    expected_ids = tuple(f"artifact-{index:04d}" for index in range(len(grants)))
    if tuple(grant.artifact_id for grant in grants) != expected_ids:
        raise IsolationError("invalid_record")
    if any(type(grant) is not ArtifactGrant or grant.kind not in kinds for grant in grants):
        raise IsolationError("invalid_record")
    kind_order = {kind: index for index, kind in enumerate(kinds)}
    order_keys = tuple(
        (kind_order[grant.kind], _path_alias_key(grant.relative_path)) for grant in grants
    )
    if order_keys != tuple(sorted(order_keys)):
        raise IsolationError("invalid_record")
    paths = [grant.relative_path for grant in grants]
    aliases = [_path_alias_key(path) for path in paths]
    if len(paths) != len(set(paths)) or len(aliases) != len(set(aliases)):
        raise IsolationError("path_alias")
    if sum(grant.byte_count for grant in grants) > MAX_AGGREGATE_ARTIFACT_BYTES:
        raise IsolationError("invalid_record")


@dataclass(frozen=True, slots=True, repr=False)
class AgentAccessGraph:
    """The complete local agent projection: no history or evaluator grants."""

    task_id: str
    baseline_commit: str
    baseline_tree: str
    objective: str
    owned_paths: tuple[str, ...]
    grants: tuple[ArtifactGrant, ...]
    schema: str = field(init=False, default=AGENT_ACCESS_GRAPH_SCHEMA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _identifier(self.task_id))
        if (
            type(self.baseline_commit) is not str
            or type(self.baseline_tree) is not str
            or not _GIT_OID.fullmatch(self.baseline_commit)
            or not _GIT_OID.fullmatch(self.baseline_tree)
        ):
            raise IsolationError("invalid_record")
        object.__setattr__(
            self,
            "objective",
            _text(self.objective, maximum=MAX_OBJECTIVE_BYTES),
        )
        if unicodedata.normalize("NFC", self.objective) != self.objective:
            raise IsolationError("invalid_record")
        if _contains_future_reference(self.objective):
            raise IsolationError("future_ref")
        if (
            type(self.owned_paths) is not tuple
            or not self.owned_paths
            or len(self.owned_paths) > MAX_OWNED_PATHS
        ):
            raise IsolationError("invalid_record")
        owned = tuple(_safe_relative_path(path) for path in self.owned_paths)
        if owned != tuple(sorted(owned, key=_path_alias_key)):
            raise IsolationError("path_alias")
        if len({_path_alias_key(path) for path in owned}) != len(owned):
            raise IsolationError("path_alias")
        object.__setattr__(self, "owned_paths", owned)
        _validate_grants(
            self.grants,
            kinds=AGENT_ARTIFACT_KINDS,
            maximum=MAX_AGENT_ARTIFACTS,
        )
        owned_set = set(owned)
        if any(
            grant.kind == "baseline" and grant.relative_path not in owned_set
            for grant in self.grants
        ):
            raise IsolationError("invalid_path")
        baseline_paths = {grant.relative_path for grant in self.grants if grant.kind == "baseline"}
        public_paths = {grant.relative_path for grant in self.grants if grant.kind == "public_test"}
        if baseline_paths & public_paths:
            raise IsolationError("path_alias")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "baseline_commit": self.baseline_commit,
            "baseline_tree": self.baseline_tree,
            "objective": self.objective,
            "owned_paths": list(self.owned_paths),
            "grants": [grant._identity_mapping() for grant in self.grants],
        }

    @property
    def cid(self) -> str:
        return cid_for_obj(self.to_mapping())

    def __repr__(self) -> str:
        return f"AgentAccessGraph(task_id={self.task_id!r}, artifact_count={len(self.grants)})"


@dataclass(frozen=True, slots=True, repr=False)
class EvaluatorAccessGraph:
    """Private evaluator projection, deliberately without a wire serializer."""

    task_id: str
    agent_access_graph_cid: str
    _grants: tuple[ArtifactGrant, ...]
    _factory_token: InitVar[object | None] = None
    schema: str = field(init=False, default=EVALUATOR_ACCESS_GRAPH_SCHEMA)

    def __post_init__(self, _factory_token: object | None) -> None:
        if _factory_token is not _EVALUATOR_GRAPH_FACTORY_TOKEN:
            raise IsolationError("invalid_record")
        object.__setattr__(self, "task_id", _identifier(self.task_id))
        object.__setattr__(
            self,
            "agent_access_graph_cid",
            _cid(self.agent_access_graph_cid, structured=True),
        )
        if not self._grants:
            raise IsolationError("invalid_record")
        _validate_grants(
            self._grants,
            kinds=EVALUATOR_ARTIFACT_KINDS,
            maximum=MAX_EVALUATOR_ARTIFACTS,
        )

    def _identity_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "agent_access_graph_cid": self.agent_access_graph_cid,
            "grants": [grant._identity_mapping() for grant in self._grants],
        }

    @property
    def cid(self) -> str:
        return cid_for_obj(self._identity_mapping())

    def to_mapping(self) -> dict[str, Any]:
        raise IsolationError("serialization_forbidden")

    def __repr__(self) -> str:
        return (
            f"EvaluatorAccessGraph(task_id={self.task_id!r}, "
            f"sealed_artifact_count={len(self._grants)})"
        )


def _material_pairs(value: Any) -> list[tuple[str, bytes]]:
    if type(value) is dict:
        if len(value) > max(MAX_AGENT_ARTIFACTS, MAX_EVALUATOR_ARTIFACTS):
            raise IsolationError("invalid_record")
        pairs = list(value.items())
    elif type(value) in {list, tuple}:
        if len(value) > max(MAX_AGENT_ARTIFACTS, MAX_EVALUATOR_ARTIFACTS):
            raise IsolationError("invalid_record")
        pairs = list(value)
    else:
        raise IsolationError("invalid_record")
    result: list[tuple[str, bytes]] = []
    for pair in pairs:
        if type(pair) not in {list, tuple} or len(pair) != 2:
            raise IsolationError("invalid_record")
        path, payload = pair
        safe_path = _safe_relative_path(path)
        if type(payload) is not bytes or len(payload) > MAX_ARTIFACT_BYTES:
            raise IsolationError("invalid_record")
        result.append((safe_path, payload))
    return result


def _build_grants(groups: Sequence[tuple[str, Any]]) -> tuple[ArtifactGrant, ...]:
    expanded: list[tuple[str, str, bytes]] = []
    for kind, material in groups:
        pairs = _material_pairs(material)
        if len(expanded) + len(pairs) > max(MAX_AGENT_ARTIFACTS, MAX_EVALUATOR_ARTIFACTS):
            raise IsolationError("invalid_record")
        for path, payload in pairs:
            expanded.append((kind, path, payload))
    kind_order = {
        kind: index for index, kind in enumerate(AGENT_ARTIFACT_KINDS + EVALUATOR_ARTIFACT_KINDS)
    }
    expanded.sort(key=lambda item: (kind_order[item[0]], _path_alias_key(item[1])))
    aliases = [_path_alias_key(path) for _kind, path, _payload in expanded]
    if len(aliases) != len(set(aliases)):
        raise IsolationError("path_alias")
    if sum(len(payload) for _kind, _path, payload in expanded) > MAX_AGGREGATE_ARTIFACT_BYTES:
        raise IsolationError("invalid_record")
    return tuple(
        ArtifactGrant(
            artifact_id=f"artifact-{index:04d}",
            kind=kind,
            relative_path=path,
            content_cid=cid_for_bytes(payload),
            byte_count=len(payload),
        )
        for index, (kind, path, payload) in enumerate(expanded)
    )


def _audit_task_id(value: Any, *, fallback: Any = None) -> str:
    for candidate in (value, fallback):
        if type(candidate) is str and _SAFE_ID.fullmatch(candidate):
            try:
                if _utf8_length(candidate) <= MAX_IDENTIFIER_BYTES:
                    return candidate
            except IsolationError:
                pass
    return "invalid-task"


def _agent_admission_attempt_cid(
    *,
    task_id: Any,
    baseline_commit: Any,
    baseline_tree: Any,
    objective: Any,
    owned_paths: Any,
    baseline_files: Any,
    public_tests: Any,
) -> str:
    """Bind rejected inputs by opaque identities without retaining their values."""

    return cid_for_obj(
        {
            "schema": "ipfs-datasets.proof-context.agent-graph-admission-attempt@1",
            "task_id": _audit_task_id(task_id),
            "baseline_commit_identity": _attempt_value_identity(baseline_commit),
            "baseline_tree_identity": _attempt_value_identity(baseline_tree),
            "objective_identity": _attempt_value_identity(objective),
            "owned_paths_cid": _attempt_collection_cid(
                owned_paths,
                schema="ipfs-datasets.proof-context.agent-owned-path-attempt@1",
                limit=MAX_OWNED_PATHS,
            ),
            "baseline_files_cid": _attempt_collection_cid(
                baseline_files,
                schema="ipfs-datasets.proof-context.agent-baseline-material-attempt@1",
                limit=MAX_AGENT_ARTIFACTS,
            ),
            "public_tests_cid": _attempt_collection_cid(
                public_tests,
                schema="ipfs-datasets.proof-context.agent-public-test-material-attempt@1",
                limit=MAX_AGENT_ARTIFACTS,
            ),
        }
    )


def _attempt_value_identity(value: Any) -> dict[str, str]:
    """Return a bounded type tag and digest, never caller-controlled cleartext."""

    exact_type = type(value)
    type_tag = {
        str: "str",
        bytes: "bytes",
        int: "int",
        bool: "bool",
        type(None): "none",
        list: "list",
        tuple: "tuple",
        dict: "dict",
    }.get(exact_type, "other")
    if exact_type is str:
        payload = value.encode("utf-8", errors="surrogatepass")
    elif exact_type is bytes:
        payload = value
    elif exact_type is int:
        payload = str(value).encode("ascii")
    elif exact_type is bool:
        payload = b"true" if value else b"false"
    elif value is None:
        payload = b"null"
    else:
        payload = type_tag.encode("ascii")
    return {"type": type_tag, "bytes_cid": cid_for_bytes(payload)}


def _attempt_collection_cid(value: Any, *, schema: str, limit: int) -> str:
    """Digest a rejected sequence/mapping without invoking arbitrary representations."""

    exact_type = type(value)
    container_tag = {dict: "dict", list: "list", tuple: "tuple"}.get(exact_type, "other")
    item_count = len(value) if exact_type in {dict, list, tuple} else 0
    entries: list[dict[str, Any]] = []
    if exact_type is dict:
        iterator = iter(value.items())
    elif exact_type in {list, tuple}:
        iterator = iter(value)
    else:
        iterator = iter(())
    for index, item in enumerate(iterator):
        if index > limit:
            break
        if type(item) in {list, tuple} and len(item) == 2:
            entries.append(
                {
                    "index": index,
                    "left": _attempt_value_identity(item[0]),
                    "right": _attempt_value_identity(item[1]),
                }
            )
        else:
            entries.append({"index": index, "value": _attempt_value_identity(item)})
    return cid_for_obj(
        {
            "schema": schema,
            "container_type": container_tag,
            "item_count": item_count,
            "entries": entries,
            "truncated": item_count > limit + 1,
        }
    )


def _evaluator_admission_attempt_cid(
    *,
    task_id: Any,
    agent_graph: Any,
    hidden_tests: Any,
    historical_answers: Any,
    negative_reviews: Any,
    assurance_data: Any,
) -> str:
    try:
        agent_graph_cid = (
            agent_graph.cid
            if type(agent_graph) is AgentAccessGraph
            else cid_for_obj(_attempt_value_identity(agent_graph))
        )
    except BaseException:
        agent_graph_cid = cid_for_obj({"type": "invalid-agent-graph"})
    groups = (
        ("hidden_tests", hidden_tests),
        ("historical_answers", historical_answers),
        ("negative_reviews", negative_reviews),
        ("assurance_data", assurance_data),
    )
    return cid_for_obj(
        {
            "schema": "ipfs-datasets.proof-context.evaluator-graph-admission-attempt@1",
            "task_id": _audit_task_id(task_id),
            "agent_graph_cid": agent_graph_cid,
            "material_cids": {
                name: _attempt_collection_cid(
                    material,
                    schema=("ipfs-datasets.proof-context.evaluator-material-attempt@1"),
                    limit=MAX_EVALUATOR_ARTIFACTS,
                )
                for name, material in groups
            },
        }
    )


def _admission_denial(
    *,
    task_id: Any,
    fallback_task_id: Any = None,
    stage: str,
    reason: str,
    graph_or_attempt_cid: str,
) -> IsolationDenial:
    return IsolationDenial(
        task_id=_audit_task_id(task_id, fallback=fallback_task_id),
        sequence=0,
        stage=stage,
        reason=reason,
        agent_access_graph_cid=graph_or_attempt_cid,
    )


def _build_agent_access_graph_candidate(
    *,
    task_id: Any,
    baseline_commit: Any,
    baseline_tree: Any,
    objective: Any,
    owned_paths: Any,
    baseline_files: Any,
    public_tests: Any,
) -> tuple[AgentAccessGraph | None, str | None]:
    """Validate raw agent material in a frame never attached to the denial."""

    candidate: AgentAccessGraph | None = None
    failure_reason: str | None = None
    try:
        if type(owned_paths) not in {list, tuple} or len(owned_paths) > MAX_OWNED_PATHS:
            raise IsolationError("invalid_record")
        normalized_owned = tuple(
            sorted((_safe_relative_path(path) for path in owned_paths), key=_path_alias_key)
        )
        grants = _build_grants(
            (
                ("baseline", baseline_files),
                ("public_test", public_tests),
            )
        )
        candidate = AgentAccessGraph(
            task_id=task_id,
            baseline_commit=baseline_commit,
            baseline_tree=baseline_tree,
            objective=objective,
            owned_paths=normalized_owned,
            grants=grants,
        )
    except IsolationError as error:
        failure_reason = error.reason
    except BaseException:
        failure_reason = "invalid_record"
    return candidate, failure_reason


def build_agent_access_graph(
    *,
    task_id: str,
    baseline_commit: str,
    baseline_tree: str,
    objective: str,
    owned_paths: Sequence[str],
    baseline_files: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    public_tests: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
) -> AgentAccessGraph:
    """Build an exact visible graph from caller-supplied synthetic/materialized bytes."""

    try:
        attempt_cid = _agent_admission_attempt_cid(
            task_id=task_id,
            baseline_commit=baseline_commit,
            baseline_tree=baseline_tree,
            objective=objective,
            owned_paths=owned_paths,
            baseline_files=baseline_files,
            public_tests=public_tests,
        )
    except BaseException:
        attempt_cid = cid_for_obj(
            {
                "schema": "ipfs-datasets.proof-context.agent-graph-admission-attempt@1",
                "task_id": _audit_task_id(task_id),
                "identity_status": "unavailable",
            }
        )
    candidate, failure_reason = _build_agent_access_graph_candidate(
        task_id=task_id,
        baseline_commit=baseline_commit,
        baseline_tree=baseline_tree,
        objective=objective,
        owned_paths=owned_paths,
        baseline_files=baseline_files,
        public_tests=public_tests,
    )
    if candidate is not None and failure_reason is None:
        return candidate
    reason = failure_reason or "invalid_record"
    safe_task_id = _audit_task_id(task_id)
    del (
        task_id,
        baseline_commit,
        baseline_tree,
        objective,
        owned_paths,
        baseline_files,
        public_tests,
        candidate,
        failure_reason,
    )
    denial = _admission_denial(
        task_id=safe_task_id,
        stage="agent_graph_admission",
        reason=reason,
        graph_or_attempt_cid=attempt_cid,
    )
    raise IsolationError(reason, denial=denial) from None


def _build_evaluator_access_graph_candidate(
    *,
    task_id: str,
    agent_graph: AgentAccessGraph,
    hidden_tests: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    historical_answers: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    negative_reviews: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    assurance_data: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
) -> tuple[EvaluatorAccessGraph | None, str | None]:
    """Build inside a non-raising frame so hidden bytes cannot enter a denial traceback."""

    candidate: EvaluatorAccessGraph | None = None
    failure_reason: str | None = None
    try:
        if type(agent_graph) is not AgentAccessGraph or task_id != agent_graph.task_id:
            raise IsolationError("invalid_record")
        groups: tuple[tuple[str, Any], ...] = (
            ("hidden_test", hidden_tests),
            ("historical_answer", historical_answers),
            ("negative_review", negative_reviews),
            ("assurance_data", assurance_data),
        )
        material = [(kind, _material_pairs(items)) for kind, items in groups]
        if (
            sum(len(pairs) for _kind, pairs in material) > MAX_EVALUATOR_ARTIFACTS
            or sum(len(payload) for _kind, pairs in material for _path, payload in pairs)
            > MAX_AGGREGATE_ARTIFACT_BYTES
        ):
            raise IsolationError("invalid_record")
        if any(
            _contains_confidential_fragment(agent_graph.objective, payload)
            for _kind, pairs in material
            for _path, payload in pairs
        ):
            raise IsolationError("content_alias")
        if any(
            _contains_sensitive_literal(agent_graph.objective, private_literal)
            for _kind, pairs in material
            for path, _payload in pairs
            for private_literal in (path, PurePosixPath(path).name)
        ):
            raise IsolationError("content_alias")
        grants = _build_grants(material)
        visible_cids = {grant.content_cid for grant in agent_graph.grants}
        evaluator_cids = [grant.content_cid for grant in grants]
        if visible_cids & set(evaluator_cids) or len(evaluator_cids) != len(set(evaluator_cids)):
            raise IsolationError("content_alias")
        candidate = EvaluatorAccessGraph(
            task_id=task_id,
            agent_access_graph_cid=agent_graph.cid,
            _grants=grants,
            _factory_token=_EVALUATOR_GRAPH_FACTORY_TOKEN,
        )
        provider_manifest, provider_failure = _build_provider_payload_candidate(
            agent_graph,
            candidate,
        )
        if provider_failure == "provider_disclosure":
            raise IsolationError("content_alias")
        if provider_manifest is not None:
            provider_json = provider_manifest.to_json()
            if any(
                _provider_json_contains_private_body(provider_json, payload)
                for _kind, pairs in material
                for _path, payload in pairs
            ):
                raise IsolationError("content_alias")
    except IsolationError as error:
        failure_reason = error.reason
    except BaseException:
        failure_reason = "invalid_record"
    return candidate, failure_reason


def build_evaluator_access_graph(
    *,
    task_id: str,
    agent_graph: AgentAccessGraph,
    hidden_tests: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    historical_answers: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    negative_reviews: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
    assurance_data: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
) -> EvaluatorAccessGraph:
    """Build the sealed graph without retaining evaluator bodies in failures or results."""

    fallback_task_id = agent_graph.task_id if type(agent_graph) is AgentAccessGraph else None
    safe_task_id = _audit_task_id(task_id, fallback=fallback_task_id)
    try:
        graph_or_attempt_cid = _evaluator_admission_attempt_cid(
            task_id=task_id,
            agent_graph=agent_graph,
            hidden_tests=hidden_tests,
            historical_answers=historical_answers,
            negative_reviews=negative_reviews,
            assurance_data=assurance_data,
        )
    except BaseException:
        graph_or_attempt_cid = cid_for_obj(
            {
                "schema": "ipfs-datasets.proof-context.evaluator-graph-admission-attempt@1",
                "task_id": safe_task_id,
                "identity_status": "unavailable",
            }
        )
    candidate, failure_reason = _build_evaluator_access_graph_candidate(
        task_id=task_id,
        agent_graph=agent_graph,
        hidden_tests=hidden_tests,
        historical_answers=historical_answers,
        negative_reviews=negative_reviews,
        assurance_data=assurance_data,
    )
    del hidden_tests, historical_answers, negative_reviews, assurance_data
    if failure_reason is not None or candidate is None:
        reason = failure_reason or "invalid_record"
        del task_id, agent_graph, fallback_task_id, failure_reason, candidate
        denial = _admission_denial(
            task_id=safe_task_id,
            stage="evaluator_graph_admission",
            reason=reason,
            graph_or_attempt_cid=graph_or_attempt_cid,
        )
        raise IsolationError(reason, denial=denial) from None
    return candidate


@dataclass(frozen=True, slots=True)
class ProviderArtifact:
    slot: int
    kind: str
    content_cid: str
    byte_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _bounded_int(self.slot, maximum=MAX_AGENT_ARTIFACTS))
        if type(self.kind) is not str or self.kind not in AGENT_ARTIFACT_KINDS:
            raise IsolationError("invalid_record")
        object.__setattr__(self, "content_cid", _cid(self.content_cid, structured=False))
        object.__setattr__(
            self,
            "byte_count",
            _bounded_int(self.byte_count, maximum=MAX_ARTIFACT_BYTES),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "kind": self.kind,
            "content_cid": self.content_cid,
            "byte_count": self.byte_count,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        raw = _mapping(value, "provider_artifact")
        fields = ("slot", "kind", "content_cid", "byte_count")
        _require_exact_fields(raw, required=fields, field_name="provider_artifact")
        return cls(**{field: raw[field] for field in fields})


@dataclass(frozen=True, slots=True)
class ProviderPayloadManifest:
    task_id: str
    policy_cid: str
    agent_access_graph_cid: str
    objective_preview: str
    redaction_applied: bool
    scope_item_count: int
    artifacts: tuple[ProviderArtifact, ...]
    body_bytes_included: bool = False
    filename_metadata_included: bool = False
    evaluator_identity_included: bool = False
    provider_call_authority: bool = False
    live_benchmark_authority: bool = False
    runtime_integration_status: str = RUNTIME_INTEGRATION_STATUS
    schema: str = field(init=False, default=PROVIDER_PAYLOAD_SCHEMA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _identifier(self.task_id))
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, structured=True))
        object.__setattr__(
            self,
            "agent_access_graph_cid",
            _cid(self.agent_access_graph_cid, structured=True),
        )
        object.__setattr__(
            self,
            "objective_preview",
            _text(
                self.objective_preview,
                maximum=MAX_PROVIDER_OBJECTIVE_BYTES,
                nonempty=True,
            ),
        )
        if type(self.redaction_applied) is not bool:
            raise IsolationError("invalid_record")
        object.__setattr__(
            self,
            "scope_item_count",
            _bounded_int(self.scope_item_count, maximum=MAX_OWNED_PATHS),
        )
        if type(self.artifacts) is not tuple or len(self.artifacts) > MAX_AGENT_ARTIFACTS:
            raise IsolationError("invalid_record")
        if tuple(item.slot for item in self.artifacts) != tuple(range(len(self.artifacts))):
            raise IsolationError("invalid_record")
        if any(type(item) is not ProviderArtifact for item in self.artifacts):
            raise IsolationError("invalid_record")
        for value in (
            self.body_bytes_included,
            self.filename_metadata_included,
            self.evaluator_identity_included,
            self.provider_call_authority,
            self.live_benchmark_authority,
        ):
            if value is not False:
                raise IsolationError("provider_disclosure")
        if self.runtime_integration_status != RUNTIME_INTEGRATION_STATUS:
            raise IsolationError("invalid_record")
        if _PATH_TEXT.search(_normalized_policy_text(self.objective_preview)):
            raise IsolationError("provider_disclosure")
        if _contains_future_reference(self.objective_preview):
            raise IsolationError("future_ref")
        if _contains_secret_indicator(self.objective_preview):
            raise IsolationError("provider_disclosure")
        if _utf8_length(self.to_json()) > MAX_PROVIDER_PAYLOAD_BYTES:
            raise IsolationError("payload_overflow")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "policy_cid": self.policy_cid,
            "agent_access_graph_cid": self.agent_access_graph_cid,
            "objective_preview": self.objective_preview,
            "redaction_applied": self.redaction_applied,
            "scope_item_count": self.scope_item_count,
            "artifacts": [item.to_mapping() for item in self.artifacts],
            "body_bytes_included": False,
            "filename_metadata_included": False,
            "evaluator_identity_included": False,
            "provider_call_authority": False,
            "live_benchmark_authority": False,
            "runtime_integration_status": self.runtime_integration_status,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_mapping())

    @property
    def cid(self) -> str:
        return cid_for_obj(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        raw = _mapping(value, "provider_payload")
        fields = (
            "schema",
            "task_id",
            "policy_cid",
            "agent_access_graph_cid",
            "objective_preview",
            "redaction_applied",
            "scope_item_count",
            "artifacts",
            "body_bytes_included",
            "filename_metadata_included",
            "evaluator_identity_included",
            "provider_call_authority",
            "live_benchmark_authority",
            "runtime_integration_status",
        )
        _require_exact_fields(raw, required=fields, field_name="provider_payload")
        if (
            raw["schema"] != PROVIDER_PAYLOAD_SCHEMA
            or type(raw["artifacts"]) is not list
            or len(raw["artifacts"]) > MAX_AGENT_ARTIFACTS
        ):
            raise IsolationError("invalid_record")
        return cls(
            **{field: raw[field] for field in fields if field not in {"schema", "artifacts"}},
            artifacts=tuple(ProviderArtifact.from_mapping(item) for item in raw["artifacts"]),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> Self:
        return cls.from_mapping(_strict_mapping(payload))


@dataclass(frozen=True, slots=True)
class TerminalProposal:
    proposal_id: str
    task_id: str
    agent_access_graph_cid: str
    provider_payload_cid: str
    terminal_status: str
    patch_cid: str | None
    schema: str = field(init=False, default=TERMINAL_PROPOSAL_SCHEMA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _identifier(self.proposal_id))
        object.__setattr__(self, "task_id", _identifier(self.task_id))
        object.__setattr__(
            self,
            "agent_access_graph_cid",
            _cid(self.agent_access_graph_cid, structured=True),
        )
        object.__setattr__(
            self,
            "provider_payload_cid",
            _cid(self.provider_payload_cid, structured=True),
        )
        if type(self.terminal_status) is not str or self.terminal_status not in PROPOSAL_STATUSES:
            raise IsolationError("invalid_record")
        if self.terminal_status == "proposed":
            object.__setattr__(self, "patch_cid", _cid(self.patch_cid, structured=False))
        elif self.patch_cid is not None:
            raise IsolationError("invalid_record")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "agent_access_graph_cid": self.agent_access_graph_cid,
            "provider_payload_cid": self.provider_payload_cid,
            "terminal_status": self.terminal_status,
            "patch_cid": self.patch_cid,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_mapping())

    @property
    def cid(self) -> str:
        return cid_for_obj(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        raw = _mapping(value, "terminal_proposal")
        fields = (
            "schema",
            "proposal_id",
            "task_id",
            "agent_access_graph_cid",
            "provider_payload_cid",
            "terminal_status",
            "patch_cid",
        )
        _require_exact_fields(raw, required=fields, field_name="terminal_proposal")
        if raw["schema"] != TERMINAL_PROPOSAL_SCHEMA:
            raise IsolationError("invalid_record")
        return cls(**{field: raw[field] for field in fields if field != "schema"})

    @classmethod
    def from_json(cls, payload: str | bytes) -> Self:
        return cls.from_mapping(_strict_mapping(payload))


@dataclass(frozen=True, slots=True)
class EvaluationScore:
    task_id: str
    proposal_cid: str
    status: str
    evaluated_artifact_count: int
    passed_check_count: int
    failed_check_count: int
    answer_bytes_included: bool = False
    evaluator_paths_included: bool = False
    repair_feedback_included: bool = False
    qualification_credit: bool = False
    runtime_integration_status: str = RUNTIME_INTEGRATION_STATUS
    schema: str = field(init=False, default=EVALUATION_SCORE_SCHEMA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _identifier(self.task_id))
        object.__setattr__(self, "proposal_cid", _cid(self.proposal_cid, structured=True))
        if type(self.status) is not str or self.status not in SCORE_STATUSES:
            raise IsolationError("invalid_record")
        object.__setattr__(
            self,
            "evaluated_artifact_count",
            _bounded_int(self.evaluated_artifact_count, maximum=MAX_EVALUATOR_ARTIFACTS),
        )
        object.__setattr__(
            self,
            "passed_check_count",
            _bounded_int(self.passed_check_count, maximum=MAX_EVALUATION_CHECKS),
        )
        object.__setattr__(
            self,
            "failed_check_count",
            _bounded_int(self.failed_check_count, maximum=MAX_EVALUATION_CHECKS),
        )
        if not 1 <= self.passed_check_count + self.failed_check_count <= MAX_EVALUATION_CHECKS:
            raise IsolationError("invalid_record")
        if (self.status == "scored_pass") != (self.failed_check_count == 0):
            raise IsolationError("invalid_record")
        for value in (
            self.answer_bytes_included,
            self.evaluator_paths_included,
            self.repair_feedback_included,
            self.qualification_credit,
        ):
            if value is not False:
                raise IsolationError("provider_disclosure")
        if self.runtime_integration_status != RUNTIME_INTEGRATION_STATUS:
            raise IsolationError("invalid_record")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "proposal_cid": self.proposal_cid,
            "status": self.status,
            "evaluated_artifact_count": self.evaluated_artifact_count,
            "passed_check_count": self.passed_check_count,
            "failed_check_count": self.failed_check_count,
            "answer_bytes_included": False,
            "evaluator_paths_included": False,
            "repair_feedback_included": False,
            "qualification_credit": False,
            "runtime_integration_status": self.runtime_integration_status,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_mapping())

    @property
    def cid(self) -> str:
        return cid_for_obj(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        raw = _mapping(value, "evaluation_score")
        fields = (
            "schema",
            "task_id",
            "proposal_cid",
            "status",
            "evaluated_artifact_count",
            "passed_check_count",
            "failed_check_count",
            "answer_bytes_included",
            "evaluator_paths_included",
            "repair_feedback_included",
            "qualification_credit",
            "runtime_integration_status",
        )
        _require_exact_fields(raw, required=fields, field_name="evaluation_score")
        if raw["schema"] != EVALUATION_SCORE_SCHEMA:
            raise IsolationError("invalid_record")
        return cls(**{field: raw[field] for field in fields if field != "schema"})

    @classmethod
    def from_json(cls, payload: str | bytes) -> Self:
        return cls.from_mapping(_strict_mapping(payload))


@dataclass(frozen=True, slots=True)
class IsolationDenial:
    task_id: str
    sequence: int
    stage: str
    reason: str
    agent_access_graph_cid: str
    sensitive_detail_included: bool = False
    schema: str = field(init=False, default=ISOLATION_DENIAL_SCHEMA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _identifier(self.task_id))
        object.__setattr__(self, "sequence", _bounded_int(self.sequence, maximum=1_000_000))
        object.__setattr__(self, "stage", _identifier(self.stage))
        if self.reason not in DENIAL_REASONS or self.sensitive_detail_included is not False:
            raise IsolationError("invalid_record")
        object.__setattr__(
            self,
            "agent_access_graph_cid",
            _cid(self.agent_access_graph_cid, structured=True),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "reason": self.reason,
            "agent_access_graph_cid": self.agent_access_graph_cid,
            "sensitive_detail_included": False,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_mapping())

    @property
    def cid(self) -> str:
        return cid_for_obj(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        raw = _mapping(value, "isolation_denial")
        fields = (
            "schema",
            "task_id",
            "sequence",
            "stage",
            "reason",
            "agent_access_graph_cid",
            "sensitive_detail_included",
        )
        _require_exact_fields(raw, required=fields, field_name="isolation_denial")
        if raw["schema"] != ISOLATION_DENIAL_SCHEMA:
            raise IsolationError("invalid_record")
        return cls(**{field: raw[field] for field in fields if field != "schema"})

    @classmethod
    def from_json(cls, payload: str | bytes) -> Self:
        return cls.from_mapping(_strict_mapping(payload))


@dataclass(frozen=True, slots=True)
class _RootAnchor:
    path: str = field(repr=False)
    device: int
    inode: int
    mode: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    links: int


def _absolute_root_path(value: Any) -> str:
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise IsolationError("invalid_path") from exc
    if type(path) is not str or not os.path.isabs(path) or "\x00" in path:
        raise IsolationError("invalid_path")
    normalized = os.path.normpath(path)
    if normalized != path or path == os.path.sep or path.startswith(os.path.sep * 2):
        raise IsolationError("invalid_path")
    return path


def _open_absolute_root(path: str) -> int:
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")):
        raise IsolationError("invalid_record")
    descriptor = os.open(os.path.sep, _ROOT_DIRECTORY_FLAGS)
    try:
        for component in PurePosixPath(path).parts[1:]:
            try:
                entry = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            except OSError:
                raise IsolationError("invalid_path") from None
            if stat.S_ISLNK(entry.st_mode):
                raise IsolationError("path_symlink")
            try:
                next_descriptor = os.open(component, _ROOT_DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.EMLINK}:
                    raise IsolationError("path_symlink") from None
                raise IsolationError("invalid_path") from None
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _capture_root(value: Any) -> _RootAnchor:
    path = _absolute_root_path(value)
    descriptor = _open_absolute_root(path)
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISDIR(current.st_mode):
            raise IsolationError("invalid_path")
        return _RootAnchor(
            path=path,
            device=current.st_dev,
            inode=current.st_ino,
            mode=current.st_mode,
            ctime_ns=current.st_ctime_ns,
        )
    finally:
        os.close(descriptor)


def _file_identity(value: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        device=value.st_dev,
        inode=value.st_ino,
        mode=value.st_mode,
        size=value.st_size,
        mtime_ns=value.st_mtime_ns,
        ctime_ns=value.st_ctime_ns,
        links=value.st_nlink,
    )


class _DescriptorRoot:
    def __init__(self, anchor: _RootAnchor) -> None:
        descriptor = _open_absolute_root(anchor.path)
        current = os.fstat(descriptor)
        observed = (current.st_dev, current.st_ino, current.st_mode, current.st_ctime_ns)
        expected = (anchor.device, anchor.inode, anchor.mode, anchor.ctime_ns)
        if observed != expected:
            os.close(descriptor)
            raise IsolationError("root_identity_drift")
        self._anchor = anchor
        self._descriptor = descriptor

    @property
    def anchor(self) -> _RootAnchor:
        return self._anchor

    def close(self) -> None:
        descriptor = getattr(self, "_descriptor", -1)
        if descriptor >= 0:
            os.close(descriptor)
            self._descriptor = -1

    def read(self, grant: ArtifactGrant) -> tuple[bytes, _FileIdentity]:
        if self._descriptor < 0:
            raise IsolationError("closed")
        parts = PurePosixPath(grant.relative_path).parts
        parent = os.dup(self._descriptor)
        try:
            for component in parts[:-1]:
                try:
                    entry = os.stat(component, dir_fd=parent, follow_symlinks=False)
                except OSError:
                    raise IsolationError("invalid_path") from None
                if stat.S_ISLNK(entry.st_mode):
                    raise IsolationError("path_symlink")
                try:
                    child = os.open(component, _ROOT_DIRECTORY_FLAGS, dir_fd=parent)
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.EMLINK}:
                        raise IsolationError("path_symlink") from None
                    raise IsolationError("invalid_path") from None
                observed = os.fstat(child)
                if observed.st_dev != self._anchor.device:
                    os.close(child)
                    raise IsolationError("path_cross_device")
                os.close(parent)
                parent = child
            try:
                entry = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            except OSError:
                raise IsolationError("invalid_path") from None
            if stat.S_ISLNK(entry.st_mode):
                raise IsolationError("path_symlink")
            try:
                descriptor = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.EMLINK}:
                    raise IsolationError("path_symlink") from None
                raise IsolationError("invalid_path") from None
            try:
                before_stat = os.fstat(descriptor)
                before = _file_identity(before_stat)
                if not stat.S_ISREG(before.mode):
                    raise IsolationError("invalid_path")
                if before.device != self._anchor.device:
                    raise IsolationError("path_cross_device")
                if before.links != 1:
                    raise IsolationError("path_hardlink")
                if before.size != grant.byte_count or before.size > MAX_ARTIFACT_BYTES:
                    raise IsolationError("grant_identity_mismatch")
                chunks: list[bytes] = []
                remaining = before.size + 1
                while remaining > 0:
                    chunk = os.read(descriptor, min(65_536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                payload = b"".join(chunks)
                after = _file_identity(os.fstat(descriptor))
                if after != before:
                    raise IsolationError("path_identity_drift")
                if len(payload) != grant.byte_count or cid_for_bytes(payload) != grant.content_cid:
                    raise IsolationError("grant_identity_mismatch")
                return payload, before
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)


@dataclass(frozen=True, slots=True, repr=False)
class EvaluatorHandle:
    artifact_id: str
    kind: str
    content_cid: str = field(repr=False)
    byte_count: int

    def __repr__(self) -> str:
        return (
            f"EvaluatorHandle(artifact_id={self.artifact_id!r}, "
            f"kind={self.kind!r}, byte_count={self.byte_count})"
        )


class _EvaluatorMaterial:
    def __init__(
        self,
        *,
        graph: EvaluatorAccessGraph,
        root: _DescriptorRoot,
        agent_file_identities: frozenset[tuple[int, int]],
    ) -> None:
        self._grants = {grant.artifact_id: grant for grant in graph._grants}
        self._root = root
        self._agent_file_identities = agent_file_identities
        self._evaluator_file_identities: set[tuple[int, int]] = set()
        self._read_ids: set[str] = set()
        self._active = True

    def handles(self) -> tuple[EvaluatorHandle, ...]:
        if not self._active:
            raise IsolationError("closed")
        return tuple(
            EvaluatorHandle(
                artifact_id=grant.artifact_id,
                kind=grant.kind,
                content_cid=grant.content_cid,
                byte_count=grant.byte_count,
            )
            for grant in self._grants.values()
        )

    def read(self, artifact_id: str, expected_cid: str) -> bytes:
        if not self._active:
            raise IsolationError("closed")
        grant = self._grants.get(artifact_id)
        if grant is None:
            raise IsolationError("unknown_grant")
        admitted_cid: str | None = None
        try:
            admitted_cid = _cid(expected_cid, structured=False)
        except IsolationError:
            pass
        if admitted_cid is None or admitted_cid != grant.content_cid:
            raise IsolationError("grant_identity_mismatch")
        payload, identity = self._root.read(grant)
        inode_key = (identity.device, identity.inode)
        if inode_key in self._agent_file_identities or inode_key in self._evaluator_file_identities:
            raise IsolationError("path_alias")
        self._evaluator_file_identities.add(inode_key)
        self._read_ids.add(grant.artifact_id)
        return payload

    def complete(self) -> bool:
        return self._read_ids == set(self._grants)

    def invalidate(self) -> None:
        self._active = False


def _sanitize_provider_objective(
    objective: str, *, sensitive_literals: Sequence[str]
) -> tuple[str, bool]:
    if _utf8_length(objective) > MAX_PROVIDER_OBJECTIVE_BYTES:
        raise IsolationError("payload_overflow")
    if _contains_future_reference(objective):
        raise IsolationError("future_ref")
    policy_text = _normalized_policy_text(objective)
    detected = bool(
        _has_suspicious_mixed_script(objective)
        or _contains_secret_indicator(objective)
        or _PATH_TEXT.search(policy_text)
        or _ANSWER_ASSIGNMENT.search(policy_text)
    )
    for literal in sensitive_literals:
        if _contains_sensitive_literal(objective, literal):
            detected = True
            break
    if detected:
        return "[redacted]", True
    return objective, False


def _mapping_string_values(value: Any) -> set[str]:
    result: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if type(current) is str:
            result.add(_normalized_confidential_literal(current))
        elif type(current) is dict:
            result.update(
                _normalized_confidential_literal(key) for key in current if type(key) is str
            )
            pending.extend(current.values())
        elif type(current) in {list, tuple}:
            pending.extend(current)
    return result


def _provider_json_contains_private_body(provider_json: str, payload: bytes) -> bool:
    """Reject an exact hidden body that aliases an inevitable provider field."""

    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        return len(
            payload
        ) >= MIN_RAW_CONFIDENTIAL_FRAGMENT_BYTES and payload in provider_json.encode("utf-8")
    candidates = (decoded, decoded.strip())
    return any(
        candidate and _contains_sensitive_literal(provider_json, candidate)
        for candidate in candidates
    )


def _build_provider_payload_candidate(
    agent_graph: AgentAccessGraph,
    evaluator_graph: EvaluatorAccessGraph,
) -> tuple[ProviderPayloadManifest | None, str | None]:
    """Construct and inspect a payload in a non-raising hidden-data frame."""

    candidate: ProviderPayloadManifest | None = None
    failure_reason: str | None = None
    try:
        if _contains_future_reference(agent_graph.objective):
            raise IsolationError("future_ref")
        agent_paths = [*agent_graph.owned_paths]
        agent_paths.extend(grant.relative_path for grant in agent_graph.grants)
        hidden_private = [evaluator_graph.cid]
        for grant in evaluator_graph._grants:
            hidden_private.extend(
                (
                    grant.relative_path,
                    PurePosixPath(grant.relative_path).name,
                    grant.content_cid,
                )
            )
        sensitive = [*agent_paths]
        sensitive.extend(PurePosixPath(path).name for path in agent_paths)
        sensitive.extend(hidden_private)
        preview, redacted = _sanitize_provider_objective(
            agent_graph.objective,
            sensitive_literals=sensitive,
        )
        manifest = ProviderPayloadManifest(
            task_id=agent_graph.task_id,
            policy_cid=isolation_descriptor_cid(),
            agent_access_graph_cid=agent_graph.cid,
            objective_preview=preview,
            redaction_applied=redacted,
            scope_item_count=len(agent_graph.owned_paths),
            artifacts=tuple(
                ProviderArtifact(
                    slot=index,
                    kind=grant.kind,
                    content_cid=grant.content_cid,
                    byte_count=grant.byte_count,
                )
                for index, grant in enumerate(agent_graph.grants)
            ),
        )
        emitted_strings = _mapping_string_values(manifest.to_mapping())
        private_paths_and_names = [*agent_paths]
        private_paths_and_names.extend(PurePosixPath(path).name for path in agent_paths)
        private_paths_and_names.extend(
            item
            for grant in evaluator_graph._grants
            for item in (grant.relative_path, PurePosixPath(grant.relative_path).name)
        )
        hidden_identities = {_normalized_confidential_literal(evaluator_graph.cid)}
        hidden_identities.update(
            _normalized_confidential_literal(grant.content_cid) for grant in evaluator_graph._grants
        )
        preview_discloses = manifest.objective_preview != "[redacted]" and any(
            _contains_sensitive_literal(manifest.objective_preview, literal)
            for literal in (*private_paths_and_names, *hidden_identities)
        )
        exact_field_alias = any(
            _normalized_confidential_literal(literal) in emitted_strings
            for literal in private_paths_and_names
            if literal
        )
        if preview_discloses or exact_field_alias or hidden_identities & emitted_strings:
            raise IsolationError("provider_disclosure")
        if _utf8_length(manifest.to_json()) > MAX_PROVIDER_PAYLOAD_BYTES:
            raise IsolationError("payload_overflow")
        candidate = manifest
    except IsolationError as error:
        failure_reason = error.reason
    except BaseException:
        failure_reason = "provider_disclosure"
    return candidate, failure_reason


class BenchmarkIsolationSession:
    """One-way agent proposal and post-proposal evaluator gate."""

    def __init__(
        self,
        *,
        agent_graph: AgentAccessGraph,
        evaluator_graph: EvaluatorAccessGraph,
        agent_root: os.PathLike[str] | str,
        evaluator_root: os.PathLike[str] | str,
    ) -> None:
        if (
            type(agent_graph) is not AgentAccessGraph
            or type(evaluator_graph) is not EvaluatorAccessGraph
        ):
            raise IsolationError("invalid_record")
        if (
            evaluator_graph.task_id != agent_graph.task_id
            or evaluator_graph.agent_access_graph_cid != agent_graph.cid
        ):
            raise IsolationError("invalid_record")
        visible_cids = {grant.content_cid for grant in agent_graph.grants}
        hidden_cids = {grant.content_cid for grant in evaluator_graph._grants}
        if visible_cids & hidden_cids:
            raise IsolationError("content_alias")
        agent_anchor = _capture_root(agent_root)
        evaluator_anchor = _capture_root(evaluator_root)
        common = os.path.commonpath((agent_anchor.path, evaluator_anchor.path))
        if common in {agent_anchor.path, evaluator_anchor.path} or (
            agent_anchor.device,
            agent_anchor.inode,
        ) == (evaluator_anchor.device, evaluator_anchor.inode):
            raise IsolationError("root_overlap")
        self._agent_graph = agent_graph
        self._evaluator_graph = evaluator_graph
        self._task_id = agent_graph.task_id
        self._agent_graph_cid = agent_graph.cid
        self._evaluator_graph_cid = evaluator_graph.cid
        self._agent_root = _DescriptorRoot(agent_anchor)
        self._evaluator_anchor = evaluator_anchor
        self._agent_file_identities: dict[str, _FileIdentity] = {}
        admitted_inodes: set[tuple[int, int]] = set()
        try:
            for grant in agent_graph.grants:
                _payload, identity = self._agent_root.read(grant)
                inode_key = (identity.device, identity.inode)
                if inode_key in admitted_inodes:
                    raise IsolationError("path_alias")
                admitted_inodes.add(inode_key)
                self._agent_file_identities[grant.artifact_id] = identity
        except BaseException:
            self._agent_root.close()
            raise
        self._phase = "proposal_open"
        self._payload_cid: str | None = None
        self._proposal_cid: str | None = None
        self._denials: list[IsolationDenial] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    @property
    def phase(self) -> str:
        return self._phase

    def denials(self) -> tuple[IsolationDenial, ...]:
        return tuple(self._denials)

    def _deny(self, reason: str, stage: str) -> None:
        if len(self._denials) >= MAX_DENIAL_EVENTS:
            raise IsolationError("audit_overflow")
        if len(self._denials) == MAX_DENIAL_EVENTS - 1:
            reason = "audit_overflow"
            stage = "audit"
            self._agent_root.close()
            self._phase = "closed"
        denial = IsolationDenial(
            task_id=self._task_id,
            sequence=len(self._denials),
            stage=stage,
            reason=reason,
            agent_access_graph_cid=self._agent_graph_cid,
        )
        self._denials.append(denial)
        raise IsolationError(reason, denial=denial)

    def _require_open_proposal(self, stage: str) -> None:
        if self._phase == "closed":
            self._deny("closed", stage)
        if self._phase != "proposal_open":
            self._deny("evaluator_sealed", stage)

    def _require_graph_identity(self, stage: str) -> None:
        identity_matches = False
        try:
            identity_matches = (
                self._agent_graph.cid == self._agent_graph_cid
                and self._evaluator_graph.cid == self._evaluator_graph_cid
                and self._evaluator_graph.agent_access_graph_cid == self._agent_graph_cid
            )
        except BaseException:
            pass
        if not identity_matches:
            self._deny("graph_identity_drift", stage)

    def _revalidate_agent_projection(self, stage: str) -> None:
        for grant in self._agent_graph.grants:
            failure_reason: str | None = None
            identity: _FileIdentity | None = None
            try:
                _payload, identity = self._agent_root.read(grant)
            except IsolationError as error:
                failure_reason = error.reason
            if failure_reason is not None:
                self._deny(failure_reason, stage)
            if identity is None or identity != self._agent_file_identities[grant.artifact_id]:
                self._deny("path_identity_drift", stage)

    def read_agent_artifact(self, artifact_id: str, expected_cid: str) -> bytes:
        """Read by opaque grant and exact CID; filenames never grant access."""

        self._require_open_proposal("agent_read")
        self._require_graph_identity("agent_read")
        grant = next(
            (item for item in self._agent_graph.grants if item.artifact_id == artifact_id),
            None,
        )
        if grant is None:
            self._deny("unknown_grant", "agent_read")
        admitted_cid: str | None = None
        try:
            admitted_cid = _cid(expected_cid, structured=False)
        except IsolationError:
            pass
        if admitted_cid is None or admitted_cid != grant.content_cid:
            self._deny("grant_identity_mismatch", "agent_read")
        failure_reason: str | None = None
        payload: bytes | None = None
        identity: _FileIdentity | None = None
        try:
            payload, identity = self._agent_root.read(grant)
        except IsolationError as error:
            failure_reason = error.reason
        if failure_reason is not None:
            self._deny(failure_reason, "agent_read")
        if identity is None or identity != self._agent_file_identities[grant.artifact_id]:
            self._deny("path_identity_drift", "agent_read")
        if payload is None:
            self._deny("grant_identity_mismatch", "agent_read")
        return payload

    def build_provider_payload(self) -> ProviderPayloadManifest:
        """Build a visible-only manifest; no provider call is performed."""

        self._require_open_proposal("provider_payload")
        if type(self._agent_graph.objective) is str and _contains_future_reference(
            self._agent_graph.objective
        ):
            self._deny("future_ref", "provider_payload")
        self._require_graph_identity("provider_payload")
        self._revalidate_agent_projection("provider_payload")
        manifest, failure_reason = _build_provider_payload_candidate(
            self._agent_graph,
            self._evaluator_graph,
        )
        if failure_reason is not None or manifest is None:
            self._deny(failure_reason or "provider_disclosure", "provider_payload")
        self._payload_cid = manifest.cid
        return manifest

    def close_proposal(self, proposal: TerminalProposal) -> None:
        if self._phase == "closed":
            self._deny("closed", "proposal_close")
        if self._proposal_cid is not None or self._phase != "proposal_open":
            self._deny("proposal_already_closed", "proposal_close")
        self._require_graph_identity("proposal_close")
        if type(proposal) is not TerminalProposal or self._payload_cid is None:
            self._deny("proposal_mismatch", "proposal_close")
        if (
            proposal.task_id != self._agent_graph.task_id
            or proposal.agent_access_graph_cid != self._agent_graph.cid
            or proposal.provider_payload_cid != self._payload_cid
        ):
            self._deny("proposal_mismatch", "proposal_close")
        self._revalidate_agent_projection("proposal_close")
        self._proposal_cid = proposal.cid
        self._phase = "proposal_closed"

    def score(
        self,
        proposal: TerminalProposal,
        scorer: Callable[[Any], Sequence[bool]],
    ) -> EvaluationScore:
        """Mount private evaluator data after closure and return aggregate scores only."""

        if self._phase == "closed":
            self._deny("closed", "evaluation")
        if self._phase == "proposal_open":
            self._deny("evaluator_sealed", "evaluation")
        if self._phase != "proposal_closed":
            self._deny("evaluation_already_terminal", "evaluation")
        self._require_graph_identity("evaluation")
        if type(proposal) is not TerminalProposal or proposal.cid != self._proposal_cid:
            self._deny("proposal_mismatch", "evaluation")
        if not callable(scorer):
            self._deny("scoring_failed", "evaluation")

        self._phase = "evaluating"
        evaluator_root: _DescriptorRoot | None = None
        material: _EvaluatorMaterial | None = None
        score: EvaluationScore | None = None
        failure_reason: str | None = None
        raw_checks: Any = None
        checks: tuple[Any, ...] = ()
        try:
            evaluator_root = _DescriptorRoot(self._evaluator_anchor)
            material = _EvaluatorMaterial(
                graph=self._evaluator_graph,
                root=evaluator_root,
                agent_file_identities=frozenset(
                    (identity.device, identity.inode)
                    for identity in self._agent_file_identities.values()
                ),
            )
            raw_checks = scorer(material)
            if type(raw_checks) not in {list, tuple}:
                raise IsolationError("scoring_failed")
            checks = tuple(raw_checks)
            if not 1 <= len(checks) <= MAX_EVALUATION_CHECKS or any(
                type(value) is not bool for value in checks
            ):
                raise IsolationError("scoring_failed")
            if not material.complete():
                raise IsolationError("incomplete_evaluation")
            failed = checks.count(False)
            score = EvaluationScore(
                task_id=self._agent_graph.task_id,
                proposal_cid=proposal.cid,
                status="scored_pass" if failed == 0 else "scored_failures",
                evaluated_artifact_count=len(self._evaluator_graph._grants),
                passed_check_count=checks.count(True),
                failed_check_count=failed,
            )
        except IsolationError as exc:
            failure_reason = exc.reason
        except BaseException:
            # Discard the evaluator exception before emitting the public error.
            # Raising inside this handler would retain a secret-bearing
            # ``__context__`` even with ``raise ... from None``.
            failure_reason = "scoring_failed"
        finally:
            if material is not None:
                material.invalidate()
            if evaluator_root is not None:
                evaluator_root.close()
            material = None
            evaluator_root = None
            raw_checks = None
            checks = ()
        if failure_reason is not None:
            self._phase = "evaluation_failed"
            self._deny(failure_reason, "evaluation")
        if score is None:
            self._phase = "evaluation_failed"
            self._deny("scoring_failed", "evaluation")
        self._phase = "evaluated"
        return score

    def close(self) -> None:
        if self._phase != "closed":
            self._agent_root.close()
            self._phase = "closed"


def isolation_descriptor() -> dict[str, Any]:
    return {
        "schema": ISOLATION_DESCRIPTOR_SCHEMA,
        "interface": INTERFACE,
        "schemas": [
            AGENT_ACCESS_GRAPH_SCHEMA,
            EVALUATOR_ACCESS_GRAPH_SCHEMA,
            PROVIDER_PAYLOAD_SCHEMA,
            TERMINAL_PROPOSAL_SCHEMA,
            EVALUATION_SCORE_SCHEMA,
            ISOLATION_DENIAL_SCHEMA,
        ],
        "agent_projection": [
            "history-stripped-baseline",
            "objective",
            "owned-paths",
            "public-tests",
        ],
        "evaluator_projection": [
            "hidden-tests",
            "historical-answers",
            "negative-review-data",
            "assurance-data",
        ],
        "provider_manifest": [
            "redacted-objective-preview",
            "visible-content-cids",
            "visible-byte-counts",
            "opaque-ordinal-slots",
        ],
        "provider_forbidden": [
            "body-bytes",
            "filenames",
            "paths",
            "answers",
            "evaluator-identities",
            "future-refs",
        ],
        "objective_screening": [
            "normalized-hidden-fragment-overlap",
            "raw-hidden-fragment-overlap",
            "conservative-secret-indicators",
            "mixed-script-provider-redaction",
            "git-oid-cid-and-ref-like-identities",
            "explicit-short-oid-and-qualified-whitespace-ref-targets",
            "token-exact-private-paths-and-names",
            "evaluator-admission-private-path-and-name-screening",
            "confusable-skeleton-private-material-screening",
            "conservative-non-ascii-letter-alias-screening",
            "pre-session-provider-field-private-material-screening",
        ],
        "session_identity_controls": [
            "agent-access-graph-cid-anchor",
            "evaluator-access-graph-cid-anchor",
            "factory-only-evaluator-graph-construction",
            "pre-session-agent-admission-denial",
            "pre-session-evaluator-admission-denial",
            "opaque-material-bound-admission-attempt-cids",
            "descriptor-root-and-file-identity-revalidation",
            "closed-denial-reason-without-private-exception-chain",
        ],
        "bounds": {
            "max_identifier_bytes": MAX_IDENTIFIER_BYTES,
            "max_path_bytes": MAX_PATH_BYTES,
            "max_objective_bytes": MAX_OBJECTIVE_BYTES,
            "max_provider_objective_bytes": MAX_PROVIDER_OBJECTIVE_BYTES,
            "max_provider_payload_bytes": MAX_PROVIDER_PAYLOAD_BYTES,
            "max_wire_record_bytes": MAX_WIRE_RECORD_BYTES,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES,
            "max_aggregate_artifact_bytes": MAX_AGGREGATE_ARTIFACT_BYTES,
            "max_agent_artifacts": MAX_AGENT_ARTIFACTS,
            "max_evaluator_artifacts": MAX_EVALUATOR_ARTIFACTS,
            "max_owned_paths": MAX_OWNED_PATHS,
            "max_evaluation_checks": MAX_EVALUATION_CHECKS,
            "max_denial_events": MAX_DENIAL_EVENTS,
            "min_confidential_fragment_characters": MIN_CONFIDENTIAL_FRAGMENT_CHARACTERS,
            "min_short_confidential_literal_characters": (
                MIN_SHORT_CONFIDENTIAL_LITERAL_CHARACTERS
            ),
            "min_raw_confidential_fragment_bytes": MIN_RAW_CONFIDENTIAL_FRAGMENT_BYTES,
        },
        "controls": ["PC-074"],
        "threats": ["TH-001", "TH-007", "TH-010", "TH-011"],
        "trust_boundaries": ["TB-03", "TB-07"],
        "evaluator_mount_time": "after-exact-terminal-proposal",
        "filename_only_access_authority": False,
        "future_ref_access_authority": False,
        "provider_call_authority": False,
        "live_benchmark_authority": False,
        "qualification_credit": QUALIFICATION_CREDIT,
        "runtime_integration_status": RUNTIME_INTEGRATION_STATUS,
        "enforcement_disposition": ENFORCEMENT_DISPOSITION,
        "limitations": [
            "authoritative accelerator and provider paths do not consume this module",
            "trusted evaluator callbacks are not sandboxed by this module",
            "same-process Python introspection is not an agent isolation boundary",
            "no provider or live benchmark was invoked",
            "qualification remains no-go until integrated observation and PCCE-076",
        ],
    }


def isolation_descriptor_cid() -> str:
    return cid_for_obj(isolation_descriptor())


__all__ = [
    "AGENT_ACCESS_GRAPH_SCHEMA",
    "AGENT_ARTIFACT_KINDS",
    "AgentAccessGraph",
    "ArtifactGrant",
    "BenchmarkIsolationSession",
    "DENIAL_REASONS",
    "ENFORCEMENT_DISPOSITION",
    "EVALUATION_SCORE_SCHEMA",
    "EVALUATOR_ACCESS_GRAPH_SCHEMA",
    "EVALUATOR_ARTIFACT_KINDS",
    "EvaluationScore",
    "EvaluatorAccessGraph",
    "EvaluatorHandle",
    "INTERFACE",
    "ISOLATION_DENIAL_SCHEMA",
    "ISOLATION_DESCRIPTOR_SCHEMA",
    "IsolationDenial",
    "IsolationError",
    "PROPOSAL_STATUSES",
    "PROVIDER_PAYLOAD_SCHEMA",
    "ProviderArtifact",
    "ProviderPayloadManifest",
    "QUALIFICATION_CREDIT",
    "RUNTIME_INTEGRATION_STATUS",
    "SCORE_STATUSES",
    "TERMINAL_PROPOSAL_SCHEMA",
    "TerminalProposal",
    "build_agent_access_graph",
    "build_evaluator_access_graph",
    "isolation_descriptor",
    "isolation_descriptor_cid",
]
