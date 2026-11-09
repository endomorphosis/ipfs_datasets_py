"""Explicit source-bound claim control on the existing SpanCache owner.

Only this opt-in interface provides fenced completion/release. Legacy SpanCache
helpers remain unqualified. All records and row/term mutations use the same
native connection and transaction; this module opens no DuckDB connection.
Source revisions are caller supplied immutable identities, not inferred legal
authority. Compile-cache seals and durable receipts never admit or formalize.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid

from .span_cache import MAX_BATCH, SpanCacheError, _sha

SCHEMA = "span-cache-fenced-claims/v1"
CLAIM_SCHEMA = "span-cache-source-claim/v1"
MAX_COMMAND_BYTES = 65_536
MAX_LEASE_SECONDS = 86_400
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,511}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:(?:(?:git|hub):)?[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
_FALSE = dict(qualified=False, admitted=False, formalized=False, roundtrip_ok=False)
_LEASE_FIELDS = frozenset(("schema", "source_span_id", "source_revision", "source_sha256", "legal_id",
    "claim_worker", "claim_token", "owner_generation", "fence", "expires_at"))
_RESULT_FIELDS = frozenset(("claim", "agrees", "decompiled", "rule", "repair", "reason"))
_DDL = (
    "CREATE TABLE IF NOT EXISTS span_claim_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, owner_generation BIGINT NOT NULL, next_fence BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS span_source_bindings (source_span_id VARCHAR PRIMARY KEY, source_revision VARCHAR NOT NULL, source_sha256 VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS span_fenced_claims (source_span_id VARCHAR PRIMARY KEY, envelope VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS span_claim_operations (operation_id VARCHAR PRIMARY KEY, payload_digest VARCHAR NOT NULL, receipt VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS span_claim_results (operation_id VARCHAR NOT NULL, source_span_id VARCHAR NOT NULL, result_json VARCHAR NOT NULL, code_identity VARCHAR NOT NULL, path_hashes VARCHAR NOT NULL, PRIMARY KEY(operation_id,source_span_id))",
)


class SpanClaimError(SpanCacheError):
    """Invalid source binding, owner, stale claim or conflicting operation."""


def _require(condition, message):
    if not condition:
        raise SpanClaimError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), f"closed {label} schema required")


def _token(value, label):
    _require(type(value) is str and _TOKEN.fullmatch(value) is not None, f"bounded {label} required")
    return value


def _revision(value):
    _require(type(value) is str and _REVISION.fullmatch(value) is not None,
        "explicit pinned 40-hex Git/Hub or sha256:64-hex source revision required")
    return value


def _hash(value):
    _require(type(value) is str and _HASH.fullmatch(value) is not None, "exact lowercase source SHA256 required")
    return value


def _raw(value, *, bound=MAX_COMMAND_BYTES):
    def check(item):
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        else:
            _require(item is None or type(item) in (str, bool, int, float), "plain JSON values required")
    try:
        check(value)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise SpanClaimError("finite valid UTF-8 JSON required") from error
    _require(bound is None or len(raw) <= bound, "claim control payload exceeds byte bound")
    return raw


def _copy(value):
    return json.loads(_raw(value))


def _batch(values, label):
    _require(type(values) is list and 0 < len(values) <= MAX_BATCH, f"bounded nonempty {label} list required")


class SpanCacheClaims:
    """A native SpanCache facade, not another catalog or a worker writer.

    Only one facade attaches to each native connection. Persisted generation
    comparison fences older connection incarnations; DuckDB retains its own
    writer transaction and file locks. Legacy writers are not transformed into
    qualified writers. Their source/status edits are checked again before every
    new mutation. Historical receipts never assert present lease eligibility.
    """

    def __init__(self, cache, *, clock=None):
        _require(not cache._claim_owner_closed and cache._claim_owner_identity ==
            (os.getpid(), threading.get_ident()), "foreign or closed span catalog owner")
        _require(cache._fenced_claim_control is None, "native connection already has its fenced facade")
        self.cache, self.clock = cache, clock if clock is not None else time.time
        _require(callable(self.clock), "owner clock must be callable")
        self._connection = cache._db
        self._owner = cache._claim_owner_identity
        self._closed, self._broken, self._depth, self._failed = False, False, 0, False
        _require(str(cache.path) != ":memory:" and cache.path.is_file(), "durable existing native SpanCache required")
        try:
            with self._transaction():
                for statement in _DDL:
                    self._connection.execute(statement)
                row = self._connection.execute("SELECT schema_id,owner_generation,next_fence FROM span_claim_owner WHERE singleton=1").fetchone()
                if row is None:
                    self._connection.execute("INSERT INTO span_claim_owner VALUES (1,?,0,0)", [SCHEMA])
                    generation = 1
                else:
                    _require(row[0] == SCHEMA and type(row[1]) is int and row[1] >= 0
                        and type(row[2]) is int and row[2] >= 0, "fenced owner metadata differs")
                    generation = row[1] + 1
                # Both owner transitions and command admission advance this
                # same fence column. Do not rely on a no-op or disjoint-column
                # write to provide the required native MVCC conflict.
                self._connection.execute("UPDATE span_claim_owner SET owner_generation=?,next_fence=next_fence+1 WHERE singleton=1", [generation])
                self.owner_generation = generation
            cache._fenced_claim_control = self
        except BaseException:
            self._closed = True
            raise

    def _check_owner(self):
        _require(not self._closed and not self._broken and not self.cache._claim_owner_closed
            and self._owner == (os.getpid(), threading.get_ident())
            and self.cache._claim_owner_identity == self._owner
            and self.cache._db is self._connection, "foreign, closed or failed span claim owner")

    def close(self):
        if self._closed:
            return
        # Close must remain possible after a failed rollback, but never from a
        # fork or foreign thread which inherited the connection.
        _require(self._owner == (os.getpid(), threading.get_ident()) and
                 self.cache._db is self._connection, "foreign span claim owner")
        _require(not self._depth, "cannot close owner during a transaction")
        self._closed = True

    @contextmanager
    def _transaction(self):
        self._check_owner()
        if self._depth:
            try:
                yield self._connection
            except BaseException:
                self._failed = True
                raise
            return
        self._connection.execute("BEGIN TRANSACTION")
        self._depth, self._failed = 1, False
        try:
            yield self._connection
            _require(not self._failed, "nested failure poisons the transaction")
            self._connection.execute("COMMIT")
        except BaseException as original:
            try:
                self._connection.execute("ROLLBACK")
            except BaseException as rollback_error:
                self._broken = True
                original.add_note("Rollback failed; fenced owner is closed to further commands: " + type(rollback_error).__name__)
            raise
        finally:
            self._depth, self._failed = 0, False

    def _current_generation(self, cx, *, for_write=False):
        row = cx.execute("SELECT owner_generation,next_fence FROM span_claim_owner WHERE singleton=1").fetchone()
        _require(row is not None and row[0] == self.owner_generation
            and type(row[1]) is int and row[1] > 0, "stale native owner generation")
        if for_write:
            # Actually write the same native MVCC column that a new incarnation
            # advances, rather than relying on a no-op to lock the generation.
            # A SELECT-only snapshot could otherwise miss a generation change
            # committed concurrently with output writes in another table.
            # On the installed DuckDB 1.5.5, native overlap probes found that
            # UPDATE ... RETURNING allowed a concurrent incarnation and lost
            # its generation update. Plain UPDATE plus count/read preserves
            # the real write conflict. Keep the actual native overlap test.
            changed = cx.execute("UPDATE span_claim_owner SET next_fence=next_fence+1 WHERE singleton=1 AND owner_generation=?", [self.owner_generation]).fetchall()
            current = cx.execute("SELECT owner_generation,next_fence FROM span_claim_owner WHERE singleton=1").fetchone()
            _require(changed == [(1,)] and current == (self.owner_generation, row[1] + 1),
                "native owner generation compare-and-swap conflict")

    def _now(self):
        now = self.clock()
        _require(type(now) in (int, float) and math.isfinite(now), "owner clock must be finite")
        return now

    @staticmethod
    def _digest(operation_id, command, payload):
        _token(operation_id, "operation ID")
        _token(command, "command")
        return hashlib.sha256(_raw(dict(command=command, payload=payload))).hexdigest()

    @staticmethod
    def _receipt(cx, operation_id, digest, command):
        old = cx.execute("SELECT payload_digest,receipt FROM span_claim_operations WHERE operation_id=?", [operation_id]).fetchone()
        if old is None:
            return None
        _require(old[0] == digest, "operation ID conflicts with committed command or payload")
        try:
            receipt = json.loads(old[1])
        except (ValueError, TypeError) as error:
            raise SpanClaimError("invalid stored claim receipt") from error
        _require(type(receipt) is dict and receipt.get("schema") == SCHEMA
            and receipt.get("operation_id") == operation_id
            and receipt.get("command") == command
            and type(receipt.get("owner_generation")) is int and receipt["owner_generation"] > 0
            and receipt.get("historical_receipt_only") is True
            and all(receipt.get(name) is False for name in _FALSE), "invalid stored claim receipt")
        return receipt

    def resolve_operation(self, operation_id, command, payload):
        """Resolve an exact historical retry; never grant a current lease."""
        digest = self._digest(operation_id, command, payload)
        with self._transaction() as cx:
            return self._receipt(cx, operation_id, digest, command)

    def _mutate(self, operation_id, command, payload, apply):
        # Freeze JSON before inspecting any database state. Full command and
        # payload identity are persisted, not just a worker-supplied digest.
        payload = _copy(payload)
        digest = self._digest(operation_id, command, payload)
        with self._transaction() as cx:
            old = self._receipt(cx, operation_id, digest, command)
            if old is not None:
                return old
            self._current_generation(cx, for_write=True)
            result = apply(cx, payload)
            self._check_deadlines(cx, command, payload, result)
            receipt = dict(schema=SCHEMA, operation_id=operation_id, command=command,
                owner_generation=self.owner_generation, historical_receipt_only=True,
                **_FALSE, **result)
            raw = _raw(receipt).decode("utf-8")
            self._store_receipt(cx, operation_id, digest, raw)
            self._check_deadlines(cx, command, payload, result)
            return json.loads(raw)

    def _check_deadlines(self, cx, command, payload, result):
        """New writes must finish within the original live-claim deadline.

        Completion/release have removed live claim rows, so check the original
        exact envelopes already validated inside this transaction. Historical
        retries return before this check and never acquire a present lease.
        """
        self._current_generation(cx)
        if command == "ClaimSpans":
            claims = result["claims"]
        elif command == "CompleteSpans":
            claims = [row["claim"] for row in payload["rows"]]
        elif command == "ReleaseSpans":
            claims = payload["claims"]
        else:
            return
        now = self._now()
        _require(all(claim["owner_generation"] == self.owner_generation
            and type(claim["expires_at"]) in (int, float)
            and math.isfinite(claim["expires_at"]) and claim["expires_at"] > now
            for claim in claims), "source claim deadline crossed before commit")

    @staticmethod
    def _store_receipt(cx, operation_id, digest, raw):
        cx.execute("INSERT INTO span_claim_operations VALUES (?,?,?)", [operation_id, digest, raw])

    @staticmethod
    def _span(cx, span_id):
        row = cx.execute("SELECT source_sha256,source_text,coalesce(legal_id,''),status,sealed,coalesce(claim_worker,''),coalesce(claim_token,'') FROM span_cache WHERE source_span_id=?", [span_id]).fetchone()
        _require(row is not None, "unknown source span")
        _require(type(row[1]) is str and _sha(row[1]) == row[0], "cached complete source bytes/hash differ")
        return dict(source_sha256=row[0], text=row[1], legal_id=row[2], status=row[3], sealed=row[4],
                    claim_worker=row[5], claim_token=row[6])

    @staticmethod
    def _binding(cx, span_id):
        row = cx.execute("SELECT source_revision,source_sha256 FROM span_source_bindings WHERE source_span_id=?", [span_id]).fetchone()
        return None if row is None else dict(source_revision=row[0], source_sha256=row[1])

    def bind_sources_fenced(self, operation_id, bindings):
        """Owner CAS binding/rebinding; no source version is synthesized.

        Each row contains source_span_id, source_revision, source_sha256 and
        expected_binding (None initially, or exact prior revision/hash).
        A changed explicit binding retires its live claim and cached term links
        atomically. It establishes identity only, never source legal meaning.
        """
        def apply(cx, data):
            rows = data["bindings"]
            _batch(rows, "source binding")
            selected, seen = [], set()
            for row in rows:
                _closed(row, ("source_span_id", "source_revision", "source_sha256", "expected_binding"), "source binding")
                span_id = _token(row["source_span_id"], "span ID")
                _require(span_id not in seen, "duplicate source span")
                seen.add(span_id)
                _revision(row["source_revision"])
                _hash(row["source_sha256"])
                expected = row["expected_binding"]
                if expected is not None:
                    _closed(expected, ("source_revision", "source_sha256"), "expected source binding")
                    _revision(expected["source_revision"])
                    _hash(expected["source_sha256"])
                current = self._binding(cx, span_id)
                _require(current == expected, "source binding compare-and-swap conflict")
                span = self._span(cx, span_id)
                _require(span["source_sha256"] == row["source_sha256"], "source binding differs from cached source hash")
                selected.append((span_id, row, current, span))
            retired = []
            for span_id, row, current, span in selected:
                binding = dict(source_revision=row["source_revision"], source_sha256=row["source_sha256"])
                if current != binding:
                    cx.execute("INSERT OR REPLACE INTO span_source_bindings VALUES (?,?,?)", [span_id, row["source_revision"], row["source_sha256"]])
                    # A binding transition invalidates old claim and cache
                    # interpretation, but retains original rule evidence.
                    if current is not None or span["status"] == "claimed":
                        cx.execute("UPDATE span_cache SET status='pending',sealed=FALSE,claim_worker='',claim_token='',reason='source_binding_changed',admitted=FALSE,formalized=FALSE WHERE source_span_id=?", [span_id])
                        cx.execute("DELETE FROM span_terms WHERE source_span_id=?", [span_id])
                        retired.append(span_id)
                    cx.execute("DELETE FROM span_fenced_claims WHERE source_span_id=?", [span_id])
            return dict(bound=len(selected), source_span_ids=[row[0] for row in selected], retired_claims=retired)
        return self._mutate(operation_id, "BindSpanSources", dict(bindings=bindings), apply)

    def _validate_claim(self, cx, claim):
        _closed(claim, _LEASE_FIELDS, "source claim")
        _require(claim["schema"] == CLAIM_SCHEMA, "source claim schema differs")
        span_id = _token(claim["source_span_id"], "span ID")
        _revision(claim["source_revision"])
        _hash(claim["source_sha256"])
        _token(claim["claim_worker"], "claim worker")
        _token(claim["claim_token"], "claim token")
        _require(type(claim["legal_id"]) is str, "claim legal ID must be a string")
        for field in ("owner_generation", "fence"):
            _require(type(claim[field]) is int and claim[field] > 0, "positive claim generation/fence required")
        expiry = claim["expires_at"]
        _require(type(expiry) in (int, float) and math.isfinite(expiry) and expiry > self._now(), "expired or invalid source claim")
        _require(claim["owner_generation"] == self.owner_generation, "stale source claim generation")
        stored = cx.execute("SELECT envelope FROM span_fenced_claims WHERE source_span_id=?", [span_id]).fetchone()
        _require(stored is not None and _raw(claim) == stored[0].encode("utf-8"), "current persisted claim differs")
        span = self._span(cx, span_id)
        _require(span["status"] == "claimed" and span["sealed"] is False
            and span["claim_worker"] == claim["claim_worker"] and span["claim_token"] == claim["claim_token"], "current cached span claim differs")
        _require(span["legal_id"] == claim["legal_id"] and span["source_sha256"] == claim["source_sha256"]
            and self._binding(cx, span_id) == dict(source_revision=claim["source_revision"], source_sha256=claim["source_sha256"]), "current source identity differs from claim")
        return span

    def claim_batch_fenced(self, operation_id, worker_id, span_ids, *, lease_seconds=300):
        """Claim an explicit bounded set, returning leases without copying text."""
        def apply(cx, data):
            _token(data["worker_id"], "worker ID")
            _batch(data["span_ids"], "span ID")
            seconds = data["lease_seconds"]
            _require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= MAX_LEASE_SECONDS, "finite bounded lease_seconds required")
            now = self._now()
            _require(math.isfinite(now + seconds) and now + seconds > now, "lease expiry must advance finite owner clock")
            seen, selected = set(), []
            for span_id in data["span_ids"]:
                _token(span_id, "span ID")
                _require(span_id not in seen, "duplicate source span")
                seen.add(span_id)
                span, binding = self._span(cx, span_id), self._binding(cx, span_id)
                _require(binding is not None and binding["source_sha256"] == span["source_sha256"], "current explicit source binding required")
                _revision(binding["source_revision"])
                if span["status"] == "claimed":
                    old = cx.execute("SELECT envelope FROM span_fenced_claims WHERE source_span_id=?", [span_id]).fetchone()
                    _require(old is not None, "legacy or unknown current claim cannot be replaced")
                    old = json.loads(old[0])
                    _require(old["owner_generation"] != self.owner_generation or old["expires_at"] <= now, "span already has a live claim")
                else:
                    _require(span["status"] in ("pending", "unsealed") and span["sealed"] is False, "span is not pending or unsealed")
                selected.append((span_id, span, binding))
            # _mutate already reserved this operation's monotonic native fence.
            fence = cx.execute("SELECT next_fence FROM span_claim_owner WHERE singleton=1").fetchone()[0]
            claims = []
            for span_id, span, binding in selected:
                claim = dict(schema=CLAIM_SCHEMA, source_span_id=span_id, **binding, legal_id=span["legal_id"],
                    claim_worker=data["worker_id"], claim_token=uuid.uuid4().hex,
                    owner_generation=self.owner_generation, fence=fence, expires_at=now + seconds)
                cx.execute("UPDATE span_cache SET status='claimed',claim_worker=?,claim_token=? WHERE source_span_id=?", [data["worker_id"], claim["claim_token"], span_id])
                cx.execute("INSERT OR REPLACE INTO span_fenced_claims VALUES (?,?)", [span_id, _raw(claim).decode("utf-8")])
                claims.append(claim)
            return dict(claims=claims)
        return self._mutate(operation_id, "ClaimSpans", dict(worker_id=worker_id, span_ids=span_ids, lease_seconds=lease_seconds), apply)

    def read_claim_source_fenced(self, claim):
        """Read verified source through its live owner; no historical retry grant."""
        claim = _copy(claim)
        with self._transaction() as cx:
            self._current_generation(cx)
            span = self._validate_claim(cx, claim)
            provenance = self.cache._source_coordinate_provenance(
                claim["source_span_id"], span["text"], span["legal_id"])
            return dict(claim=claim, text=span["text"], legal_id=span["legal_id"], **provenance, **_FALSE)

    def complete_claimed_fenced(self, operation_id, rows, *, code_identity, path_hashes):
        """Commit all validated outputs, terms and receipt in one transaction.

        Each closed result is claim/agrees/decompiled/rule/repair/reason. Source
        text and legal IDs are copied from the owner, never from worker output.
        An agrees=true seal is solely a compile cache disposition, including for
        Constitution spans; roundtrip_ok and all authority flags stay false.
        """
        def apply(cx, data):
            _token(data["code_identity"], "compiler identity")
            _require(type(data["path_hashes"]) is dict and data["path_hashes"], "explicit compiler path hashes required")
            for path, digest in data["path_hashes"].items():
                _require(type(path) is str and 0 < len(path) <= 1024, "bounded compiler path required")
                _hash(digest)
            _batch(data["rows"], "completion")
            selected, seen = [], set()
            for row in data["rows"]:
                _closed(row, _RESULT_FIELDS, "completion result")
                span = self._validate_claim(cx, row["claim"])
                span_id = row["claim"]["source_span_id"]
                _require(span_id not in seen, "duplicate completion source span")
                seen.add(span_id)
                _require(type(row["agrees"]) is bool and type(row["decompiled"]) is str
                    and type(row["reason"]) is str and type(row["rule"]) is dict and type(row["repair"]) is dict,
                    "typed completion facets required")
                selected.append(dict(row, source_span_id=span_id, text=span["text"], legal_id=span["legal_id"], source_sha256=span["source_sha256"]))
            self.cache._validate_text_batch(selected)
            sealed = 0
            for row in selected:
                span_id = row["source_span_id"]
                if row["agrees"]:
                    self.cache._seal_row(row, code_identity=data["code_identity"], path_hashes=data["path_hashes"])
                    sealed += 1
                else:
                    cx.execute("UPDATE span_cache SET decompiled=?,reason=?,rule_json=?,status='gap',sealed=FALSE,code_identity=?,path_hashes=?,claim_worker='',claim_token='',admitted=FALSE,formalized=FALSE WHERE source_span_id=?", [row["decompiled"], row["reason"], _raw(row["repair"]).decode("utf-8"), data["code_identity"], _raw(data["path_hashes"]).decode("utf-8"), span_id])
                    cx.execute("DELETE FROM span_terms WHERE source_span_id=?", [span_id])
                cx.execute("UPDATE span_cache SET claim_worker='',claim_token='' WHERE source_span_id=?", [span_id])
                cx.execute("DELETE FROM span_fenced_claims WHERE source_span_id=?", [span_id])
                # Preserve both agreement and disagreement evidence. The
                # legacy rule_json cache column alone conflates rule/repair and
                # cannot retain all diagnostics. No source bytes are duplicated.
                self._store_result(cx, operation_id, span_id,
                    {field: row[field] for field in _RESULT_FIELDS},
                    data["code_identity"], data["path_hashes"])
            return dict(sealed=sealed, gaps=len(selected)-sealed, source_span_ids=[row["source_span_id"] for row in selected])
        return self._mutate(operation_id, "CompleteSpans", dict(rows=rows, code_identity=code_identity, path_hashes=path_hashes), apply)

    @staticmethod
    def _store_result(cx, operation_id, span_id, result, code_identity, path_hashes):
        cx.execute("INSERT INTO span_claim_results VALUES (?,?,?,?,?)", [operation_id, span_id,
            _raw(result).decode("utf-8"), code_identity, _raw(path_hashes).decode("utf-8")])

    def read_completion_results_fenced(self, operation_id, rows, *, code_identity, path_hashes):
        """Owner-local exact historical evidence lookup for later export.

        Requires the complete original completion payload, not just a guessed
        operation ID. Full rule/repair/reason/decompilation and original claims
        are retained together. The bounded response is either complete or
        refused; no truncation, current-lease or legal-meaning assertion occurs.
        Older receipts without a full result ledger are explicitly unavailable.
        """
        payload = _copy(dict(rows=rows, code_identity=code_identity, path_hashes=path_hashes))
        digest = self._digest(operation_id, "CompleteSpans", payload)
        with self._transaction() as cx:
            receipt = self._receipt(cx, operation_id, digest, "CompleteSpans")
            _require(receipt is not None, "no exact committed completion operation")
            stored = cx.execute("SELECT source_span_id,result_json,code_identity,path_hashes FROM span_claim_results WHERE operation_id=?", [operation_id]).fetchall()
            _require(len(stored) == len(payload["rows"]), "complete historical result ledger unavailable")
            by_span = {record[0]: record for record in stored}
            results = []
            for row in payload["rows"]:
                span_id = row["claim"]["source_span_id"]
                _require(span_id in by_span, "historical result span closure differs")
                record = by_span[span_id]
                _require(record[1].encode("utf-8") == _raw(row)
                    and record[2] == payload["code_identity"]
                    and record[3].encode("utf-8") == _raw(payload["path_hashes"]), "historical result content differs")
                results.append(dict(source_span_id=span_id, result=json.loads(record[1]),
                    code_identity=record[2], path_hashes=json.loads(record[3])))
            response = dict(schema=SCHEMA, operation_id=operation_id, historical_receipt_only=True,
                results=results, **_FALSE)
            return json.loads(_raw(response))

    def release_claims_fenced(self, operation_id, claims):
        """Release only exact live claims; preserve existing source/term evidence."""
        def apply(cx, data):
            _batch(data["claims"], "release claim")
            seen = set()
            for claim in data["claims"]:
                self._validate_claim(cx, claim)
                _require(claim["source_span_id"] not in seen, "duplicate release source span")
                seen.add(claim["source_span_id"])
            for claim in data["claims"]:
                span_id = claim["source_span_id"]
                cx.execute("UPDATE span_cache SET status='pending',claim_worker='',claim_token='' WHERE source_span_id=?", [span_id])
                cx.execute("DELETE FROM span_fenced_claims WHERE source_span_id=?", [span_id])
            return dict(released=len(data["claims"]), source_span_ids=[claim["source_span_id"] for claim in data["claims"]])
        return self._mutate(operation_id, "ReleaseSpans", dict(claims=claims), apply)


__all__ = ["SpanCacheClaims", "SpanClaimError", "SCHEMA", "CLAIM_SCHEMA", "MAX_COMMAND_BYTES"]
