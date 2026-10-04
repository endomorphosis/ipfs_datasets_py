"""Source-only preparation for sealed authored evaluation, without fitting.

Caller-owned resource admission and a dedicated offline process are required.
Encoders run sequentially; no learned teacher state, target or normalization
fit enters these APIs. Native deadlines are cooperative, not kernel interrupts.
The 768D checkpoint retains its original profile while this owner restricts
every actual model input to 512 tokens. Receipts are evidence, not admission.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from . import authored_scalar_holdout as authored

PLAN_SCHEMA = "fresh-scalar-source-plan/v1"
PRODUCTION_SCHEMA = "fresh-scalar-source-production/v1"
SCHEMA = "fresh-scalar-source-inputs/v1"
FALSE = dict(admitted=False, qualified=False, formalized=False, roundtrip_ok=False,
    proof_authority=False, source_semantics_verified=False, training_executed=False,
    target_access=False, targets_attached=False, downloads_performed=False,
    teacher_checkpoint_loaded=False, historical_linguistic_teacher_modified=False,
    encoder_context_increased=False, transforms_fitted=False, checkpoint_promoted=False)
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_require = authored._require
digest = authored.digest


def _checkpoint(deadline):
    _require(type(deadline) in (int, float) and math.isfinite(deadline), "finite operation deadline required")
    if time.monotonic() >= deadline:
        raise TimeoutError("fresh source preparation deadline exceeded")


def _pins(*modules):
    paths = [Path(__file__).resolve(), Path(authored.__file__).resolve()]
    paths += [Path(module.__file__).resolve() for module in modules]
    result = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    _require(result[str(Path(__file__).resolve())] == _SELF_SHA, "resident fresh source producer changed")
    return result


def _unchanged(pins):
    _require(all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha for path, sha in pins.items()),
        "fresh source producer changed during operation")


def source_plan(source_rows, *, expected_source_rows_sha256, sealed_comparison_sha256):
    """Deduplicate complete paragraphs/clauses using source bytes only."""
    for sha in (expected_source_rows_sha256, sealed_comparison_sha256):
        _require(type(sha) is str and authored._SHA.fullmatch(sha), "explicit source and comparison hashes required")
    _require(type(source_rows) is list and len(source_rows) == 48, "exact 48-row source-only holdout required")
    rows = deepcopy(source_rows)
    ids, normalized, sources, lookup, aliases = set(), set(), [], {}, []
    lengths, clause_occurrences, total_bytes = Counter(), [], 0
    def add(text, paragraph_id, role, slot):
        sha = authored.text_sha(text); identity = "source:" + sha
        if sha in lookup:
            _require(lookup[sha] == text, "source digest collision")
        else:
            lookup[sha] = text; sources.append(dict(id=identity, source_text=text))
        aliases.append(dict(paragraph_id=paragraph_id, role=role, slot=slot, source_id=identity, source_sha256=sha))
    for row in rows:
        text, pieces = authored._source(row)
        _require(row["id"] not in ids and authored._normal(text) not in normalized,
            "duplicate holdout paragraph identity or normalized source")
        _require(len(pieces) in (1, 2, 4, 8), "unchanged one/two/four/eight clause source grouping required")
        ids.add(row["id"]); normalized.add(authored._normal(text)); lengths[len(pieces)] += 1
        total_bytes += len(text.encode())
        _require(total_bytes <= 1024**2, "holdout source byte bound exceeded")
        add(text, row["id"], "paragraph", None)
        for slot, piece in enumerate(pieces):
            clause_occurrences.append(authored._normal(piece)); add(piece, row["id"], "clause", slot)
    _require(lengths == {1:12, 2:12, 4:12, 8:12} and len(clause_occurrences) == len(set(clause_occurrences)) == 180
        and len(sources) == 216, "fixed complete source inventory or unique clauses differs")
    _require(digest(rows) == expected_source_rows_sha256, "holdout source hash differs")
    result = dict(schema=PLAN_SCHEMA, source_rows=rows, source_rows_sha256=expected_source_rows_sha256,
        sealed_comparison_sha256=sealed_comparison_sha256, source_inputs=sources, source_aliases=aliases,
        paragraph_count=48, clause_occurrences=180, unique_sources=216, source_bytes=total_bytes,
        encoder_context_tokens=512, comparison_seal_verified=False, **FALSE)
    result["plan_sha256"] = digest(result)
    return result


def _plan(plan):
    _require(type(plan) is dict and plan.get("schema") == PLAN_SCHEMA, "explicit fresh source plan required")
    actual = source_plan(plan.get("source_rows"), expected_source_rows_sha256=plan.get("source_rows_sha256"),
        sealed_comparison_sha256=plan.get("sealed_comparison_sha256"))
    _require(actual == plan, "source plan or aliases were modified")
    return actual


def _vector(values, dimension):
    _require(type(values) is list and len(values) == dimension
        and all(type(value) in (int, float) and math.isfinite(value) for value in values)
        and abs(math.fsum(float(value)**2 for value in values) - 1.) <= 1e-4,
        "finite native-width unit vector required; no repairs")


def _asset_config(dimension, config):
    expected = {8:set(), 384:{"snapshot_path"},
        768:{"manifest_path", "expected_manifest_sha256", "model_directory", "code_directory"}}[dimension]
    _require(type(config) is dict and set(config) == expected, "exact width-specific local asset configuration required")
    for key, value in config.items():
        if key == "expected_manifest_sha256":
            _require(type(value) is str and authored._SHA.fullmatch(value), "explicit asset manifest SHA256 required")
        else:
            _require(type(value) is str and Path(value).is_absolute(), "absolute local asset paths required")


def _produce8(plan, config, directory, batch_size, deadline):
    from . import legal_native_conditioning as historical
    pins = _pins(historical)
    bundle = historical.historical_features(plan["source_inputs"], backend="historical_blank_en")
    _checkpoint(deadline)
    rows = historical.stage_rows(bundle, stage=historical.HISTORICAL_STAGE, sources=plan["source_inputs"])
    vectors = [dict(id=row["id"], source_sha256=row["source_sha256"], vector=row["vector"],
        token_count=None, token_input_sha256=None) for row in rows]
    _unchanged(pins)
    return dict(vectors=vectors, native_production=bundle, producer_files=pins, source_artifact=None,
        representation=dict(kind="historical_linguistic_feature_hash", dimension=8,
            profile_id="legacy-linguistic-features-8d/v1", semantic_embedding=False,
            teacher_checkpoint_reconstruction=False, backend="historical_blank_en"))


def _source_artifact(plan, directory, codec, corpus):
    directory = Path(directory)
    _require(directory.is_absolute() and not directory.exists() and directory.parent.is_dir()
        and directory.parent.resolve() == directory.parent, "fresh absolute owned source artifact directory required")
    content, offsets = bytearray(), []
    for row in plan["source_inputs"]:
        start = len(content); content.extend(row["source_text"].encode()); end = len(content)
        offsets.append((start, end)); content.extend(b"\n\n")
    data = bytes(content); sha = hashlib.sha256(data).hexdigest()
    directory.mkdir()
    path = directory / "source-texts.txt"
    with path.open("xb") as stream:stream.write(data)
    artifact = corpus.SourceArtifact(sha, len(data))
    inputs = []
    for row, (start, end) in zip(plan["source_inputs"], offsets):
        citation = "Authored diagnostic source " + row["id"]
        span = corpus.SourceSpan(artifact, "diagnostic", plan["sealed_comparison_sha256"], row["id"],
            "en", citation, start, end)
        inputs.append(codec.EmbeddingInput(span, "authored-holdout", row["id"], row["source_text"], citation))
    return inputs, path, dict(path=str(path), bytes=len(data), sha256=sha)


def _produce384(plan, config, directory, batch_size, deadline):
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    from ....optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as corpus
    pins = _pins(producer, codec, corpus)
    inputs, path, artifact = _source_artifact(plan, directory, codec, corpus)
    _checkpoint(deadline)
    def resolve(ref):
        _require(ref == {k:artifact[k] for k in ("sha256", "bytes")}, "unexpected source artifact requested")
        return path
    receipt = producer.produce_native_embedding_receipt(inputs, resolver=resolve,
        snapshot_path=config["snapshot_path"], batch_size=batch_size)
    _checkpoint(deadline)
    payload = receipt.to_dict(); vectors = []
    _require(len(payload["results"]) == len(inputs), "native384 source coverage differs")
    for source, item, result in zip(plan["source_inputs"], inputs, payload["results"]):
        _require(result["input_id"] == item.input_id and result["status"] == "embedded",
            "native384 source refused or overlength; no substitute")
        tokens = result["tokens"]["input_ids"]
        _require(1 <= len(tokens) <= 512, "native384 token limit differs")
        vectors.append(dict(id=source["id"], source_sha256=authored.text_sha(source["source_text"]),
            vector=list(codec._decode_vector(result["vector"])), token_count=len(tokens),
            token_input_sha256=digest(tokens)))
    _unchanged(pins)
    return dict(vectors=vectors, native_production=payload, producer_files=pins, source_artifact=artifact,
        representation=dict(kind="native_gte_small_semantic_embedding", dimension=384, semantic_embedding=True,
            model_id="thenlper/gte-small", revision=producer.PINNED_REVISION, device="cpu", dtype="float32",
            experiment_token_limit=512, actual_forward_tokens_verified=True))


def _produce768(plan, config, directory, batch_size, deadline):
    from . import source_embeddings_768_complete as complete
    from . import dimension_source_inputs as bounded
    reference = complete.reference
    pins = _pins(complete, reference, reference._PROFILE, bounded)
    arguments = dict(expected_sha256=config["expected_manifest_sha256"],
        model_directory=config["model_directory"], code_directory=config["code_directory"])
    assets = reference._PROFILE.inspect_local_assets(config["manifest_path"], **arguments)
    _require(assets["status"] == "available", "verified local native768 assets unavailable")
    _checkpoint(deadline)
    torch, tokenizer, model, loading = complete._load_backend(assets)
    _require(torch.get_num_threads() == 1, "caller must reserve CPU1 and set torch threads to one")
    _checkpoint(deadline)
    rows = deepcopy(plan["source_inputs"])
    token_rows = reference._tokenize(rows, tokenizer, model.config.vocab_size)
    _require(tokenizer.padding_side == "right" and all(len(row["input_ids"]) <= 512 for row in token_rows),
        "source exceeds fixed512 token limit before any native768 forward")
    _require(reference._PROFILE.inspect_local_assets(config["manifest_path"], **arguments) == assets,
        "native768 assets changed during loading")
    events = []
    guarded, schedule, cursor = bounded._guarded_model(torch, model, token_rows, rows, batch_size, deadline, events)
    verification = complete._verify_dense_path(torch, guarded, tokenizer, token_rows[0])
    values = reference._vectors(torch, guarded, tokenizer, token_rows, batch_size)
    _checkpoint(deadline)
    _require(len(values) == len(rows) and cursor[0] == len(schedule), "incomplete actual native768 forward schedule")
    _require(reference._PROFILE.inspect_local_assets(config["manifest_path"], **arguments) == assets,
        "native768 assets changed during inference")
    _unchanged(pins)
    native = dict(schema="fresh-bounded-native768-production/v1", assets=assets, source_rows=rows, vectors=deepcopy(values),
        token_rows=token_rows, forward_observations=events, complete_checkpoint_loading=loading,
        dense_path_verification=verification, implementation=complete._implementation(),
        execution_profile=dict(batch_size=batch_size, device="cpu", dtype="float32", pooling="cls",
            normalization="l2", max_tokens_including_special_tokens=512, attention_implementation="eager"),
        historical_profile_token_limit=8192, experiment_token_limit=512, cached_profile_relabelled=False)
    native["forward_validation"] = bounded.validate_forward_observations(native)
    vectors = [dict(id=row["id"], source_sha256=authored.text_sha(row["source_text"]), vector=value,
        token_count=len(tokens["input_ids"]), token_input_sha256=digest(tokens["input_ids"]))
        for row, value, tokens in zip(rows, values, token_rows)]
    return dict(vectors=vectors, native_production=native, producer_files=pins, source_artifact=None,
        representation=dict(kind="native_gte_multilingual_semantic_embedding", dimension=768,
            semantic_embedding=True, profile_id=complete.PROFILE_ID, device="cpu", dtype="float32",
            experiment_token_limit=512, historical_profile_token_limit=8192,
            cached_profile_relabelled=False, actual_forward_tokens_verified=True))


def produce_width(plan, *, dimension, asset_config, source_artifact_directory=None,
                  batch_size=4, max_seconds=600):
    """Execute one admitted local producer; never create or alter a checkpoint.

    Resource admission is external and must precede this call. The 384D native
    producer checks its own actual tokens; this wrapper checks its deadline on
    entry/exit, while 768D also checks each forward. Use the owned guardian for
    a hard process deadline. Failed source artifacts remain available to audit.
    """
    _require(type(dimension) is int and dimension in (8, 384, 768), "explicit native width required")
    _require(type(batch_size) is int and batch_size == 4, "fixed batch size four required")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 600,
        "bounded positive preparation deadline required")
    _asset_config(dimension, asset_config)
    if dimension == 384:
        _require(isinstance(source_artifact_directory, (str, Path)) and Path(source_artifact_directory).is_absolute(),
            "native384 requires a fresh absolute source artifact directory")
    else:
        _require(source_artifact_directory is None, "unused source artifact directory forbidden")
    started = time.monotonic(); deadline = started + max_seconds
    owned = _plan(plan); config = deepcopy(asset_config); _checkpoint(deadline)
    _pins()
    payload = {8:_produce8, 384:_produce384, 768:_produce768}[dimension](
        owned, config, source_artifact_directory, batch_size, deadline)
    _checkpoint(deadline)
    result = dict(schema=PRODUCTION_SCHEMA, complete=True, dimension=dimension,
        plan_sha256=owned["plan_sha256"], source_rows_sha256=owned["source_rows_sha256"],
        sealed_comparison_sha256=owned["sealed_comparison_sha256"], asset_config=config,
        producer_files=payload["producer_files"], producer_pin_scope="named local producers; caller freezes transitive import closure",
        vectors=payload["vectors"], native_production=payload["native_production"],
        source_artifact=payload["source_artifact"], representation=payload["representation"],
        receipt_count=216, encoder_executed=dimension != 8, batch_size=batch_size,
        max_seconds=max_seconds, elapsed_seconds=time.monotonic()-started,
        deadline_cooperative=True, native_forward_interruptible=False, **FALSE)
    result["production_sha256"] = digest(result)
    _validate_report(owned, result)
    _checkpoint(deadline)
    return result


def _validate_report(plan, report):
    _require(type(report) is dict and report.get("schema") == PRODUCTION_SCHEMA
        and report.get("complete") is True and report.get("production_sha256") ==
        digest({k:v for k,v in report.items() if k != "production_sha256"}), "complete production digest differs")
    dimension = report.get("dimension")
    _require(type(dimension) is int and dimension in (8, 384, 768), "production dimension differs")
    _require(report.get("plan_sha256") == plan["plan_sha256"]
        and report.get("source_rows_sha256") == plan["source_rows_sha256"]
        and report.get("sealed_comparison_sha256") == plan["sealed_comparison_sha256"]
        and all(report.get(k) is False for k in FALSE), "production source binding or authority differs")
    _asset_config(dimension, report["asset_config"])
    rows = report.get("vectors")
    _require(type(rows) is list and len(rows) == report.get("receipt_count") == 216
        and report.get("encoder_executed") is (dimension != 8), "production source coverage or execution differs")
    for row, source in zip(rows, plan["source_inputs"]):
        _require(type(row) is dict and set(row) == {"id", "source_sha256", "vector", "token_count", "token_input_sha256"}
            and row["id"] == source["id"] and row["source_sha256"] == authored.text_sha(source["source_text"]),
            "exact ordered production source identity required")
        _vector(row["vector"], dimension)
        if dimension == 8:
            _require(row["token_count"] is None and row["token_input_sha256"] is None,
                "historical hash features cannot claim encoder token evidence")
        else:
            _require(type(row["token_count"]) is int and 1 <= row["token_count"] <= 512
                and type(row["token_input_sha256"]) is str and authored._SHA.fullmatch(row["token_input_sha256"]),
                "complete untruncated512 native token evidence required")
    _require(type(report.get("producer_files")) is dict and report["producer_files"], "producer source pins missing")
    _unchanged(report["producer_files"])
    _validate_native_binding(plan, report)
    return dimension


def _validate_native_binding(plan, report):
    """Check saved source/vector/token links without another encoder pass."""
    dimension, native = report["dimension"], report["native_production"]
    if dimension == 8:
        from . import legal_native_conditioning as historical
        rows = historical.stage_rows(native, stage=historical.HISTORICAL_STAGE, sources=plan["source_inputs"])
        expected = [dict(id=row["id"], source_sha256=row["source_sha256"], vector=row["vector"],
            token_count=None, token_input_sha256=None) for row in rows]
    elif dimension == 384:
        from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
        from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
        receipt = codec.EmbeddingProductionReceipt(codec._canonical(native))
        _require(receipt.native_execution_profile and native["producer"]["code_sha256"] ==
            hashlib.sha256(Path(producer.__file__).read_bytes()).hexdigest(), "native384 producer/profile differs")
        wanted_assets = [dict(name=name, bytes=size, sha256=sha)
            for name, (size, sha) in sorted(producer._PINNED_ASSETS.items())]
        _require(native["model_assets"] == wanted_assets, "native384 asset identity differs")
        artifact = report["source_artifact"]
        _require(type(artifact) is dict and set(artifact) == {"path", "bytes", "sha256"},
            "exact source artifact evidence required")
        def resolver(ref):
            _require(ref == {k:artifact[k] for k in ("bytes", "sha256")}, "unexpected native384 source reference")
            return artifact["path"]
        receipt.validate_sources(resolver)
        expected = []
        _require(len(receipt.inputs) == len(plan["source_inputs"]), "native384 source count differs")
        for row, source, result in zip(receipt.inputs, plan["source_inputs"], native["results"]):
            _require(row.text == source["source_text"] and row.source.document_id == source["id"]
                and row.source.source_kind == "diagnostic" and row.source.release_id == plan["sealed_comparison_sha256"]
                and result["status"] == "embedded", "native384 source contents, identity or result differs")
            tokens = result["tokens"]["input_ids"]
            expected.append(dict(id=source["id"], source_sha256=authored.text_sha(source["source_text"]),
                vector=list(codec._decode_vector(result["vector"])), token_count=len(tokens), token_input_sha256=digest(tokens)))
    else:
        from . import dimension_source_inputs as bounded
        from . import source_embeddings_768_complete as complete
        _require(type(native) is dict and native.get("schema") == "fresh-bounded-native768-production/v1"
            and native.get("source_rows") == plan["source_inputs"]
            and native.get("implementation") == complete._implementation()
            and native.get("experiment_token_limit") == 512 and native.get("historical_profile_token_limit") == 8192
            and native.get("cached_profile_relabelled") is False, "native768 source/profile binding differs")
        _require(native.get("forward_validation") == bounded.validate_forward_observations(native),
            "native768 actual token observations differ")
        _require(native["assets"].get("status") == "available"
            and native["assets"].get("manifest_sha256") == report["asset_config"]["expected_manifest_sha256"],
            "native768 asset manifest binding differs")
        values, tokens = native.get("vectors"), native["token_rows"]
        _require(type(values) is list and len(values) == len(tokens) == len(plan["source_inputs"]),
            "native768 complete vector inventory differs")
        expected = [dict(id=row["id"], source_sha256=authored.text_sha(row["source_text"]), vector=value,
            token_count=len(token["input_ids"]), token_input_sha256=digest(token["input_ids"]))
            for row, value, token in zip(plan["source_inputs"], values, tokens)]
    _require(report["vectors"] == expected, "assembled vectors differ from native source/token/vector evidence")


def assemble(plan, reports_by_dimension):
    """Assemble raw source vectors/contexts only; trained transforms stay external."""
    from . import clause_source_context as clauses
    owned = _plan(plan)
    _require(type(reports_by_dimension) is dict and set(reports_by_dimension) == {"8", "384", "768"},
        "exact three native source reports required")
    dimensions = {}
    for dimension in (8, 384, 768):
        report = reports_by_dimension[str(dimension)]
        _require(_validate_report(owned, report) == dimension, "dimension report key differs")
        vectors = {r["source_sha256"]: r["vector"] for r in report["vectors"]}
        rows = [dict(row, input=deepcopy(vectors[authored.text_sha(row["source_text"])])) for row in owned["source_rows"]]
        cache, seen = [], set()
        for row in owned["source_rows"]:
            for text in row["source_text"].split("\n\n"):
                sha = authored.text_sha(text)
                if sha not in seen:
                    seen.add(sha); cache.append(dict(id="clause:"+sha, source_text=text, input=deepcopy(vectors[sha])))
        contexts = clauses.build_source_contexts(owned["source_rows"], cache)
        dimensions[str(dimension)] = dict(rows=rows, clause_cache=cache, source_contexts=contexts,
            representation=deepcopy(report["representation"]), production_sha256=report["production_sha256"])
    result = dict(schema=SCHEMA, complete=True, dimensions=dimensions, source_plan_sha256=owned["plan_sha256"],
        source_rows_sha256=owned["source_rows_sha256"], sealed_comparison_sha256=owned["sealed_comparison_sha256"],
        source_aliases=deepcopy(owned["source_aliases"]), comparison_seal_verified=False,
        reports_sha256={key: value["production_sha256"] for key,value in reports_by_dimension.items()}, **FALSE)
    result["inputs_sha256"] = digest(result)
    return result


__all__ = ["source_plan", "produce_width", "assemble"]
