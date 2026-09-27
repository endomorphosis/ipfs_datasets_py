"""Map a novel IR predicate onto a symbol the system already has.

The catalog is the frame-fixture ids, the meta-ontology lexicon, and the
decompiler's reconstruction atoms. A long predicate invented from a heading
is replaced by the closest catalog symbol. The catalog does not grow.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from typing import Any

from ipfs_datasets_py.logic.autoformal.meta_ontology import LEXICON
from ipfs_datasets_py.logic.modal.decompiler import (
    _PACKET_000600_USCODE_RECONSTRUCTION_ATOMS,
    _PACKET_000901_USCODE_RECONSTRUCTION_ATOMS,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    DEFAULT_LEGAL_FRAME_FIXTURE,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _snake(text: str) -> str:
    return "_".join(str(text or "").lower().split())


@lru_cache(maxsize=1)
def known_ir_symbols() -> frozenset[str]:
    symbols = set(_PACKET_000600_USCODE_RECONSTRUCTION_ATOMS)
    symbols.update(_PACKET_000901_USCODE_RECONSTRUCTION_ATOMS)
    symbols.update(frame.frame_id for frame in DEFAULT_LEGAL_FRAME_FIXTURE)
    symbols.update(_snake(lemma) for lemma, _category in LEXICON if _snake(lemma))
    return frozenset(symbols)


_USCODE_TITLE_BANNER = re.compile(
    r"united states code,?\s*(?:\d{4}\s+edition\s+)?title\s+(\d+)\b",
    re.IGNORECASE,
)


def bluebook_symbols(text: str) -> list[str]:
    """Return every ``usc:us:`` key the Bluebook extractor finds in ``text``."""

    raw = " ".join(str(text or "").split())
    if not raw:
        return []
    found: list[str] = []
    banner = _USCODE_TITLE_BANNER.search(raw)
    if banner:
        found.append(f"usc:us:{int(banner.group(1))}")
    try:
        from ipfs_datasets_py.processors.legal_data.citation_extraction import CitationExtractor
    except ImportError:
        CitationExtractor = None
    if CitationExtractor is not None:
        for citation in CitationExtractor().extract_citations(raw):
            symbol = _citation_symbol(citation)
            if symbol:
                found.append(symbol)
    symbols: list[str] = []
    for symbol in found:
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _citation_symbol(citation: Any) -> str:
    """Use the citation-key helpers already defined for each Bluebook family."""

    kind = str(getattr(citation, "type", "") or "")
    title = str(getattr(citation, "title", "") or "").strip()
    section = str(getattr(citation, "section", "") or "").strip().lower()
    volume = str(getattr(citation, "volume", "") or "").strip()
    page = str(getattr(citation, "page", "") or "").strip()
    if kind == "usc":
        if title and section:
            return f"usc:us:{int(title)}:{section}"
        if title:
            return f"usc:us:{int(title)}"
        return ""
    from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
        citation_key_for_cfr,
        citation_key_for_fr,
        citation_key_for_public_law,
    )

    if kind == "cfr" and title and section:
        return citation_key_for_cfr(title, section)
    if kind == "federal_register" and volume and page:
        return citation_key_for_fr(volume, page)
    if kind == "public_law" and volume and page:
        return citation_key_for_public_law(volume, page)
    if kind == "case" and volume and page:
        reporter = re.sub(r"[^a-z0-9]+", "", str(getattr(citation, "reporter", "") or "").lower())
        if reporter:
            return f"{int(volume)}-{reporter}-{int(page)}"
    jurisdiction = str(getattr(citation, "jurisdiction", "") or "").strip().lower()
    if kind == "state_statute" and jurisdiction and section:
        return f"{jurisdiction}-stat-{section}"
    return ""


def bluebook_symbol(text: str) -> str:
    """Return the first existing ``usc:us:`` key for a Bluebook or OLRC code citation."""

    found = bluebook_symbols(text)
    return found[0] if found else ""


def alias_predicate(
    name: str,
    *,
    selected_frame: str | None = None,
    source_text: str | None = None,
    role: str | None = None,
) -> str:
    """Return a catalog or Bluebook symbol. An exact catalog name is kept."""

    spaced = str(name or "").replace("_", " ")
    key = _snake(spaced)
    tokens = [token for token in key.split("_") if token]
    if len(tokens) >= 4 or str(role or "") == "frame":
        cited = bluebook_symbol(spaced) or bluebook_symbol(str(source_text or ""))
        if cited:
            return cited
    catalog = known_ir_symbols()
    if key in catalog:
        return key
    tokens = [token for token in key.split("_") if token]
    best = ""
    best_overlap = 0
    for symbol in catalog:
        symbol_tokens = [token for token in symbol.split("_") if token]
        if not symbol_tokens:
            continue
        overlap = len(set(tokens) & set(symbol_tokens))
        if overlap < 2:
            continue
        if overlap / len(symbol_tokens) < 0.6:
            continue
        if overlap > best_overlap or (overlap == best_overlap and len(symbol) < len(best)):
            best = symbol
            best_overlap = overlap
    if best:
        return best
    frame = str(selected_frame or "").strip()
    if frame in catalog and len(tokens) >= 4:
        return frame
    return key


def alias_modal_ir_predicates(
    modal_ir: ModalIRDocument,
    *,
    selected_frame: str | None = None,
    source_text: str | None = None,
) -> ModalIRDocument:
    """Rewrite novel predicate names. The original name is kept in formula metadata."""

    formulas = []
    for formula in modal_ir.formulas:
        original = str(formula.predicate.name or "")
        aliased = alias_predicate(
            original,
            selected_frame=selected_frame,
            source_text=source_text or modal_ir.source,
            role=formula.predicate.role,
        )
        if not aliased or aliased == original:
            formulas.append(formula)
            continue
        formulas.append(
            replace(
                formula,
                predicate=replace(formula.predicate, name=aliased),
                metadata={**dict(formula.metadata), "aliased_from": original},
            )
        )
    return replace(modal_ir, formulas=formulas)


def append_bluebook_citation_formulas(
    modal_ir: ModalIRDocument,
    source_text: str | None = None,
) -> ModalIRDocument:
    """Add one frame formula per Bluebook citation that is not already a predicate."""

    text = str(source_text or modal_ir.source or "")
    present = {str(formula.predicate.name or "") for formula in modal_ir.formulas}
    added: list[ModalIRFormula] = []
    for index, symbol in enumerate(bluebook_symbols(text), start=1):
        if symbol in present:
            continue
        present.add(symbol)
        added.append(
            ModalIRFormula(
                formula_id=f"{modal_ir.document_id}:bluebook:f{index:04d}",
                operator=ModalIROperator(
                    family="frame",
                    system="frame",
                    symbol="Frame",
                    label="bluebook_citation",
                ),
                predicate=ModalIRPredicate(name=symbol, arguments=[], role="citation"),
                provenance=ModalIRProvenance(
                    source_id=modal_ir.document_id,
                    start_char=0,
                    end_char=len(text),
                    citation=symbol,
                ),
                metadata={"source": "bluebook_citation_extractor"},
            )
        )
    if not added:
        return modal_ir
    return replace(modal_ir, formulas=[*modal_ir.formulas, *added])


def dedupe_modal_ir_formulas(modal_ir: ModalIRDocument) -> ModalIRDocument:
    """Drop exact duplicate formulas while retaining semantic and source differences.

    Formula IDs identify occurrences, so they alone do not distinguish content.
    Conditions, exceptions, operator fields, roles, provenance, and metadata do.
    """

    seen: set[str] = set()
    kept: list[ModalIRFormula] = []
    for formula in modal_ir.formulas:
        content = formula.to_dict()
        content.pop("formula_id", None)
        key = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(formula)
    if len(kept) == len(list(modal_ir.formulas)):
        return modal_ir
    return replace(modal_ir, formulas=kept)


def ir_compression_loss(source_text: str, ir_text: str) -> tuple[float, float]:
    """Return ``(loss, ratio)``.

    The ratio is source tokens divided by IR tokens. The loss is IR tokens
    divided by source tokens, capped at 1, so a larger IR is a higher loss.
    """

    source_tokens = max(1, len(str(source_text or "").split()))
    ir_tokens = max(1, len(str(ir_text or "").split()))
    return min(1.0, ir_tokens / source_tokens), source_tokens / ir_tokens
