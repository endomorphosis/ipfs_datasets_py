"""Executable evidence for the reproducible spaCy linguistic adapter."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks.logic_pipeline import adapters, contracts


SHA_A = "a" * 64
SHA_B = "b" * 64
TEXT = "Agency Alpha must file the report within 30 days."


def _request(text: str = TEXT) -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id="run-spacy-001",
        case_id="case-spacy-001",
        case_manifest_sha256=SHA_A,
        variant_id="A0",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={
            "text": text,
            "document_id": "doc-001",
            "citation": "Example § 1",
            "source": "reviewed_fixture",
        },
        requested_identity={
            "implementation": "spacy",
            "model": "en_core_web_sm",
        },
        environment_sha256=SHA_B,
    )


def _telemetry() -> contracts.TelemetryRecord:
    return contracts.TelemetryRecord(
        wall_time_ms=2.0,
        cpu_time_ms=1.0,
        input_items=1,
        output_items=1,
        bytes_in=len(TEXT.encode("utf-8")),
        bytes_out=1024,
        resource_lane=contracts.ResourceLane.CPU,
    )


class _Feature:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


class _FakeToken:
    def __init__(
        self,
        *,
        index: int,
        text: str,
        lemma: str,
        pos: str,
        dep: str,
        start: int,
        head_index: int,
    ) -> None:
        self.i = index
        self.text = text
        self.lemma_ = lemma
        self.lower_ = text.lower()
        self.pos_ = pos
        self.dep_ = dep
        self.idx = start
        self.is_stop = text.lower() in {"the", "within"}
        self.is_alpha = text.isalpha()
        self.ent_type_ = ""
        self.head = SimpleNamespace(i=head_index)


@dataclass
class _FakeSpan:
    text: str
    start_char: int
    end_char: int
    label_: str = ""


class _FakeDoc:
    def __init__(self) -> None:
        specs = (
            ("Agency", "agency", "NOUN", "compound", 0, 1),
            ("Alpha", "Alpha", "PROPN", "nsubj", 7, 3),
            ("must", "must", "AUX", "aux", 13, 3),
            ("file", "file", "VERB", "ROOT", 18, 3),
            ("the", "the", "DET", "det", 23, 5),
            ("report", "report", "NOUN", "dobj", 27, 3),
            ("within", "within", "ADP", "prep", 34, 3),
            ("30", "30", "NUM", "nummod", 41, 8),
            ("days", "day", "NOUN", "pobj", 44, 6),
            (".", ".", "PUNCT", "punct", 48, 3),
        )
        self._tokens = [
            _FakeToken(
                index=index,
                text=text,
                lemma=lemma,
                pos=pos,
                dep=dep,
                start=start,
                head_index=head,
            )
            for index, (text, lemma, pos, dep, start, head) in enumerate(specs)
        ]
        self.sents = (_FakeSpan(TEXT, 0, len(TEXT)),)
        self.ents = (
            _FakeSpan("Agency Alpha", 0, 12, "ORG"),
            _FakeSpan("30 days", 41, 48, "DATE"),
        )

    def __iter__(self):
        return iter(self._tokens)


class _FakeNlp:
    pipe_names = ("tok2vec", "tagger", "parser", "ner", "sentencizer")
    meta = {"name": "core_web_sm", "version": "3.8.0", "lang": "en"}

    def __call__(self, _text: str) -> _FakeDoc:
        return _FakeDoc()


class _FakeEncoding:
    document_id = "doc-001"
    text = TEXT
    normalized_text = TEXT
    citation = "Example § 1"
    source = "reviewed_fixture"
    model_name = "en_core_web_sm"

    def __init__(self, *, used_fallback_model: bool) -> None:
        self.used_fallback_model = used_fallback_model
        self.tokens = [
            _Feature(
                text=token.text,
                lemma=token.lemma_,
                lower=token.lower_,
                pos=token.pos_,
                dep=token.dep_,
                start_char=token.idx,
                end_char=token.idx + len(token.text),
                is_stop=token.is_stop,
                is_alpha=token.is_alpha,
            )
            for token in _FakeDoc()
        ]
        self.sentences = [_Feature(text=TEXT, start_char=0, end_char=len(TEXT))]
        self.cues = [
            _Feature(
                family="deontic",
                system="standard_deontic",
                symbol="O",
                label="obligation",
                cue="must",
                start_char=13,
                end_char=17,
                token_indices=[2],
            )
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "text": self.text,
            "normalized_text": self.normalized_text,
            "tokens": [item.to_dict() for item in self.tokens],
            "sentences": [item.to_dict() for item in self.sentences],
            "cues": [item.to_dict() for item in self.cues],
            "citation": self.citation,
            "source": self.source,
            "model_name": self.model_name,
            "used_fallback_model": self.used_fallback_model,
        }


class _FakeEncoder:
    def __init__(self, *, used_fallback_model: bool = False) -> None:
        self.model_name = "en_core_web_sm"
        self.used_fallback_model = used_fallback_model
        self.nlp = _FakeNlp()

    def encode(self, _text: str, **_kwargs: object) -> _FakeEncoding:
        return _FakeEncoding(used_fallback_model=self.used_fallback_model)


class _FakeFrame:
    """Return a different volatile ID each time; the adapter must remove it."""

    serial = 0

    def __init__(self, *, source: str = "spacy") -> None:
        type(self).serial += 1
        self.frame_id = f"random-upstream-uuid-{self.serial}"
        self.predicate = "file"
        self.predicate_span = (18, 22)
        self.sentence = TEXT
        self.arguments = [
            {
                "role": "Agent",
                "text": "Agency Alpha",
                "span": (0, 12),
                "confidence": 0.8,
            },
            {
                "role": "Patient",
                "text": "the report",
                "span": (23, 33),
                "confidence": 0.8,
            },
        ]
        self.confidence = 0.8
        self.source = source

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_id": self.frame_id,
            "predicate": self.predicate,
            "predicate_span": list(self.predicate_span),
            "sentence": self.sentence,
            "arguments": self.arguments,
            "confidence": self.confidence,
            "source": self.source,
        }


class _FakeSrl:
    def __init__(self, *, source: str = "spacy") -> None:
        self.source = source

    def extract_srl(self, _text: str) -> list[_FakeFrame]:
        return [_FakeFrame(source=self.source)]


class _FakeModalIr:
    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": "doc-001",
            "formulas": [
                {
                    "formula_id": "doc-001:f0001",
                    "operator": {
                        "family": "deontic",
                        "system": "standard_deontic",
                        "symbol": "O",
                        "label": "obligation",
                    },
                    "predicate": {"name": "file", "arguments": [], "role": "rule"},
                    "provenance": {
                        "source_id": "doc-001",
                        "start_char": 0,
                        "end_char": len(TEXT),
                        "citation": "Example § 1",
                    },
                    "conditions": [],
                    "exceptions": [],
                    "metadata": {
                        "cue": "must",
                        "cue_start_char": 13,
                        "cue_end_char": 17,
                    },
                }
            ],
        }


class _FakeLegalParser:
    def parse(self, _text: str, **_kwargs: object) -> _FakeModalIr:
        return _FakeModalIr()

    def segment(self, text: str) -> list[_FakeSpan]:
        return [_FakeSpan(text=text, start_char=0, end_char=len(text))]


class _FakeModalCompiler:
    def compile(self, _encoding: object) -> _FakeModalIr:
        return _FakeModalIr()


def _factory(value: Any):
    """Make a factory tolerant of either positional or keyword construction."""

    def create(*_args: object, **_kwargs: object) -> Any:
        return value

    return create


def _adapter(
    mode: adapters.SpacyAdapterMode,
    *,
    fallback: bool = False,
) -> adapters.SpacyAdapter:
    return adapters.SpacyAdapter(
        config=adapters.SpacyAdapterConfig(
            requested_model="en_core_web_sm",
            mode=mode,
        ),
        encoder_factory=_factory(_FakeEncoder(used_fallback_model=fallback)),
        srl_factory=_factory(_FakeSrl()),
        legal_parser_factory=_factory(_FakeLegalParser()),
        modal_compiler_factory=_factory(_FakeModalCompiler()),
    )


def test_objective_symbol_schema_modes_and_config_are_public_and_versioned() -> None:
    evidence = adapters.HSSLEV0310F79()
    assert "reproducible spaCy" in evidence
    assert all(
        term in evidence
        for term in (
            "tokens",
            "sentences",
            "lemmas",
            "dependencies",
            "entities",
            "semantic roles",
            "modal cues",
            "fallback identity",
        )
    )
    assert adapters.SPACY_EVIDENCE_SCHEMA.endswith(".spacy-evidence.v1")
    assert {mode.value for mode in adapters.SpacyAdapterMode} == {
        "full_model",
        "blank_model",
        "regex_legal",
    }
    assert adapters.SpacyAdapterConfig().requested_model == "en_core_web_sm"
    assert adapters.SpacyAdapterConfig().language == "en"
    assert adapters.SpacyAdapterConfig().max_text_bytes == 4096
    assert adapters.SpacyAdapter().handler is None

    with pytest.raises(contracts.ProtocolContractError):
        adapters.SpacyAdapterConfig(requested_model="")
    with pytest.raises(contracts.ProtocolContractError):
        adapters.SpacyAdapterConfig(max_text_bytes=0)


def test_full_model_captures_all_linguistic_evidence_deterministically() -> None:
    adapter = _adapter(adapters.SpacyAdapterMode.FULL_MODEL)
    first = adapter.run(_request(), telemetry=_telemetry())
    second = adapter.run(_request(), telemetry=_telemetry())

    assert first.status is contracts.StageStatus.SUCCESS
    assert first.data["schema"] == adapters.SPACY_EVIDENCE_SCHEMA
    assert first.data["document"]["normalized_text"] == TEXT
    assert first.data["tokens"][0]["text"] == "Agency"
    assert first.data["tokens"][0]["lemma"] == "agency"
    assert [dict(item) for item in first.data["sentences"]] == [
        {"text": TEXT, "start_char": 0, "end_char": len(TEXT)}
    ]
    assert any(item["label"] == "nsubj" for item in first.data["dependencies"])
    assert first.data["entities"][0]["label"] == "ORG"
    assert first.data["semantic_roles"][0]["predicate"] == "file"
    frame_id = first.data["semantic_roles"][0]["frame_id"]
    assert frame_id.startswith("srl-")
    assert frame_id != "random-upstream-uuid-1"
    assert first.data["modal_cues"][0]["cue"] == "must"
    assert first.data["modal_ir"]["formulas"][0]["operator"]["symbol"] == "O"
    assert first.data["execution"]["effective_model"] == "en_core_web_sm"
    assert first.data["execution"]["model_version"] == "3.8.0"
    assert first.data["execution"]["model_language"] == "en"
    assert len(first.data["execution"]["model_meta_sha256"]) == 64
    assert first.data["execution"]["pipeline"] == (
        "tok2vec",
        "tagger",
        "parser",
        "ner",
        "sentencizer",
    )
    assert first.data["execution"]["parser_backend"] == "spacy_modal_codec_v1"
    assert first.data["execution"]["srl_backend"] == "spacy"
    assert first.output_sha256 == second.output_sha256
    assert first.digest == second.digest
    assert first.to_dict() == second.to_dict()
    assert contracts.StageRecord.from_dict(first.to_dict()).digest == first.digest


def test_requested_full_model_never_silently_succeeds_with_blank_fallback() -> None:
    record = _adapter(
        adapters.SpacyAdapterMode.FULL_MODEL,
        fallback=True,
    ).run(_request(), telemetry=_telemetry())

    assert record.status is contracts.StageStatus.UNAVAILABLE
    assert record.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE
    assert record.output_sha256 is None
    assert record.provenance.requested_identity["model"] == "en_core_web_sm"
    assert record.provenance.effective_identity["requested_model"] == "en_core_web_sm"
    assert record.provenance.effective_identity["effective_model"] == "spacy.blank:en"
    assert record.provenance.effective_identity["used_fallback_model"] is True


def test_explicit_blank_model_control_records_fallback_and_identity() -> None:
    record = _adapter(
        adapters.SpacyAdapterMode.BLANK_MODEL,
        fallback=True,
    ).run(_request(), telemetry=_telemetry())

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["execution"]["mode"] == "blank_model"
    assert record.data["execution"]["requested_model"] == "en_core_web_sm"
    assert record.data["execution"]["used_fallback_model"] is True
    assert record.provenance.requested_identity["model"] == "en_core_web_sm"
    assert record.provenance.effective_identity["mode"] == "blank_model"
    assert record.provenance.effective_identity["used_fallback_model"] is True


def test_blank_control_refuses_an_accidentally_loaded_full_model() -> None:
    record = _adapter(
        adapters.SpacyAdapterMode.BLANK_MODEL,
        fallback=False,
    ).run(_request(), telemetry=_telemetry())

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.SPACY_PARSE_OR_MODEL_FALLBACK
    )
    assert record.output_sha256 is None
    assert record.provenance.effective_identity["mode"] == "blank_model"
    assert record.provenance.effective_identity["used_fallback_model"] is False


def test_regex_legal_control_is_distinct_and_does_not_construct_spacy() -> None:
    encoder_calls: list[str] = []

    def forbidden_encoder(*_args: object, **_kwargs: object) -> object:
        encoder_calls.append("called")
        raise AssertionError("regex/legal mode must not construct a spaCy encoder")

    adapter = adapters.SpacyAdapter(
        config=adapters.SpacyAdapterConfig(
            requested_model="en_core_web_sm",
            mode=adapters.SpacyAdapterMode.REGEX_LEGAL,
        ),
        encoder_factory=forbidden_encoder,
        srl_factory=_factory(_FakeSrl(source="heuristic")),
        legal_parser_factory=_factory(_FakeLegalParser()),
        modal_compiler_factory=_factory(_FakeModalCompiler()),
    )
    record = adapter.run(_request(), telemetry=_telemetry())

    assert record.status is contracts.StageStatus.SUCCESS
    assert encoder_calls == []
    assert record.data["execution"]["mode"] == "regex_legal"
    assert record.data["execution"]["effective_model"] == "regex-legal-parser-v1"
    assert record.data["execution"]["used_fallback_model"] is False
    assert record.data["execution"]["parser_backend"] == "legal_modal_parser_v1"
    assert record.data["execution"]["srl_backend"] == "heuristic"
    assert record.data["tokens"][0]["text"] == "Agency"
    assert not record.data["dependencies"]
    assert not record.data["entities"]
    assert record.data["semantic_roles"][0]["source"] == "heuristic"
    assert record.data["modal_ir"]["formulas"][0]["operator"]["family"] == "deontic"
    assert record.provenance.effective_identity["mode"] == "regex_legal"


def test_linguistic_evidence_is_descriptive_and_cannot_claim_proof_authority() -> None:
    record = _adapter(adapters.SpacyAdapterMode.FULL_MODEL).run(
        _request(), telemetry=_telemetry()
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["assurance"] == {
        "evidence_only": True,
        "semantic_proof": False,
        "authoritative": False,
        "kernel_checked": False,
    }
    assert record.kernel_accepted is False
    assert record.kernel_receipt_sha256 is None
    assert "verification_authority" not in record.data


def test_spacy_adapter_rejects_unbounded_or_malformed_input_without_escaping() -> None:
    adapter = _adapter(adapters.SpacyAdapterMode.FULL_MODEL)

    oversized = adapter.run(_request("x" * 4097), telemetry=_telemetry())
    missing_text = adapter.run(
        adapters.StageRequest(
            run_id="run-spacy-002",
            case_id="case-spacy-002",
            case_manifest_sha256=SHA_A,
            input_data={"document_id": "doc-002"},
        ),
        telemetry=_telemetry(),
    )

    assert oversized.status is contracts.StageStatus.FAILED
    assert oversized.output_sha256 is None
    assert missing_text.status is contracts.StageStatus.FAILED
    assert missing_text.output_sha256 is None
