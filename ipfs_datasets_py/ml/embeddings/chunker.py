"""Text chunking utilities for embeddings.

This module provides various text chunking strategies for preparing documents
for embedding operations, migrated and adapted from a pre-migration embeddings codebase.
Supports accelerate integration for distributed processing.
"""

import logging
import re
from typing import Callable, Dict, List, Optional, AsyncIterator, TypeAlias
from abc import ABC, abstractmethod


Tokenizer: TypeAlias = Callable[[str, Optional[Dict]], str]


from .schema import DocumentChunk, ChunkingStrategy, EmbeddingConfig

try:
    import pysbd
except ImportError:
    pysbd = None

# Set the logging level to WARNING to suppress INFO and DEBUG messages
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

CHUNKING_STRATEGIES = ["semantic", "fixed", "sentences", "sliding_window"]


_UNSET_OVERLAP = object()


def _validate_chunk_limits(size, overlap=_UNSET_OVERLAP):
    if type(size) is not int or size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if overlap is not _UNSET_OVERLAP and (type(overlap) is not int or not 0 <= overlap < size):
        raise ValueError("chunk_overlap must be an integer between zero and chunk_size - 1")


def _require_text(text):
    if not isinstance(text, str):
        raise ValueError("chunk source must be a string")


def _trim_interval(text, start, end):
    raw = text[start:end]
    left = start + len(raw) - len(raw.lstrip())
    right = end - (len(raw) - len(raw.rstrip()))
    return left, max(left, right)


def _sentence_splitter():
    if pysbd is not None:
        try:
            return pysbd.Segmenter(language="en", clean=False, char_span=True)
        except Exception:
            logger.debug("Character-span sentence splitter unavailable", exc_info=True)
    return None


_ABBREVIATIONS = frozenset((
    "mr mrs ms dr prof sr jr st vs etc fig figs eq eqs no nos art arts sec secs "
    "inc ltd co corp dept approx al cf min max est misc vol vols rev ed pp"
).split())
_TERMINAL_ABBREVIATIONS = frozenset({"inc", "ltd", "co", "corp", "etc"})
_SENTENCE_END = re.compile(r"(?P<punct>[.!?]+)[\"'\u2019\u201d)\]}]*(?=\s|$)")
_TERMINAL_SENTENCE_TEXT = re.compile(r"[.!?。！？][\"'\u2019\u201d)\]}*_`]*$")


def _coalesce_nonterminal_wraps(text, intervals):
    """Prevent optional splitters from turning hard wraps into sentence cuts.

    Blank lines remain paragraph separators. Markup, lists and code need the
    structural corpus adapter; this guard only rejects cuts within prose.
    """
    result = []
    for start, end in intervals:
        if result:
            previous_start, previous_end = result[-1]
            gap = text[previous_end:start]
            if (not _TERMINAL_SENTENCE_TEXT.search(text[previous_start:previous_end])
                    and not re.search(r"\r?\n[ \t]*\r?\n", gap)):
                result[-1] = (previous_start, end)
                continue
        result.append((start, end))
    return result


def _fallback_sentence_spans(text):
    """Conservative punctuation boundaries; abbreviations may remain grouped."""
    intervals, cursor = [], 0
    for match in _SENTENCE_END.finditer(text):
        if match["punct"] == ".":
            prefix = text[cursor:match.start() + 1]
            token = prefix.rsplit(None, 1)[-1] if prefix.strip() else ""
            token = token.lstrip("([{\"'\u2018\u201c")
            abbreviation = token[:-1].casefold()
            following = text[match.end():].lstrip()
            may_end = (abbreviation in _TERMINAL_ABBREVIATIONS and following
                       and following[0].isupper())
            if not may_end and (abbreviation in _ABBREVIATIONS
                                or re.fullmatch(r"(?:[A-Za-z]\.)+", token)):
                continue
        start, end = _trim_interval(text, cursor, match.end())
        if start < end:
            intervals.append((start, end))
        cursor = match.end()
    start, end = _trim_interval(text, cursor, len(text))
    if start < end:
        intervals.append((start, end))
    return intervals


def _sentence_source_spans(text, splitter, *, diagnostics=None):
    _require_text(text)
    if diagnostics is not None:
        diagnostics.update(
            backend="source-punctuation-fallback/v1",
            pysbd_version=getattr(pysbd, "__version__", None),
            fallback_reason="splitter_unavailable" if splitter is None else None,
        )
    if not text.strip():
        if diagnostics is not None:
            diagnostics["backend"] = "not_required"
        return []
    if splitter is not None:
        try:
            intervals, cursor = [], 0
            for span in splitter.segment(text):
                start, end = getattr(span, "start", None), getattr(span, "end", None)
                if (type(start) is not int or type(end) is not int
                        or not cursor <= start < end <= len(text)
                        or text[cursor:start].strip()
                        or getattr(span, "sent", text[start:end]) != text[start:end]):
                    raise ValueError("sentence splitter did not preserve source selectors")
                left, right = _trim_interval(text, start, end)
                if left < right:
                    intervals.append((left, right))
                cursor = end
            if not intervals or text[cursor:].strip():
                raise ValueError("sentence splitter omitted source content")
            original_count = len(intervals)
            intervals = _coalesce_nonterminal_wraps(text, intervals)
            if diagnostics is not None:
                diagnostics["backend"] = "pysbd-character-spans"
                diagnostics["nonterminal_wraps_coalesced"] = original_count - len(intervals)
            return intervals
        except Exception as exc:
            if diagnostics is not None:
                diagnostics["fallback_reason"] = type(exc).__name__
            logger.debug("Using source-preserving sentence fallback", exc_info=True)
    return _fallback_sentence_spans(text)


def sentence_source_spans(text: str) -> List[tuple[int, int]]:
    """Return ordered, half-open source character intervals for whole sentences.

    Punctuation and internal whitespace stay verbatim. Whitespace between the
    returned intervals is deliberately outside them. Optional pysbd boundaries
    are accepted only with complete, exact source selectors; the fallback never
    splits a decimal, version or URL at punctuation without following whitespace.
    Neither path rewrites text or subdivides an oversized atomic sentence.
    """
    return _sentence_source_spans(text, _sentence_splitter())


def sentence_source_spans_with_diagnostics(text: str) -> Dict:
    """Return exact intervals and the backend actually used for this input."""
    diagnostics = {}
    spans = _sentence_source_spans(text, _sentence_splitter(), diagnostics=diagnostics)
    return {"spans": spans, **diagnostics}


class BaseChunker(ABC):
    """Base class for text chunking strategies."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or EmbeddingConfig(model_name="default")

    @abstractmethod
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text into DocumentChunk objects."""
        pass

    @abstractmethod
    async def chunk_text_async(
        self, text: str, metadata: Optional[Dict] = None
    ) -> AsyncIterator[DocumentChunk]:
        """Async version of chunk_text."""
        pass


class FixedSizeChunker(BaseChunker):
    """Chunks text into fixed-size pieces with optional overlap."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
        _validate_chunk_limits(self.chunk_size, self.chunk_overlap)

    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text into fixed-size pieces."""
        _validate_chunk_limits(self.chunk_size, self.chunk_overlap)
        _require_text(text)
        if not text.strip():
            return []

        chunks = []
        start = 0
        chunk_id = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_content = text[start:end]

            # Avoid cutting words in half (except for very long words)
            if end < len(text) and not text[end].isspace():
                # Find the last whitespace before the cut
                last_space = max((match.start() for match in re.finditer(r"\s", chunk_content)), default=-1)
                if (
                    last_space > self.chunk_size * 0.7
                ):  # Only adjust if we don't lose too much content
                    end = start + last_space
                    chunk_content = text[start:end]

            left, right = _trim_interval(text, start, end)
            if left < right:
                chunks.append(DocumentChunk(
                    content=text[left:right], chunk_id=f"chunk_{chunk_id}",
                    metadata=metadata or {}, start_index=left, end_index=right,
                ))
                chunk_id += 1
            if end >= len(text):
                break
            # Word-boundary shortening can exceed the requested overlap.
            # Advance even then, and stop at EOF instead of revisiting its tail.
            start = max(start + 1, end - self.chunk_overlap)

        return chunks

    async def chunk_text_async(
        self, text: str, metadata: Optional[Dict] = None
    ) -> AsyncIterator[DocumentChunk]:
        """Async version of fixed-size chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk


class SentenceChunker(BaseChunker):
    """Chunks text by sentences, grouping them to fit within size limits."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        _validate_chunk_limits(self.chunk_size)
        self.sentence_splitter = self._initialize_sentence_splitter()

    def _initialize_sentence_splitter(self):
        """Initialize sentence splitter."""
        return _sentence_splitter()

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        return [text[start:end] for start, end in _sentence_source_spans(text, self.sentence_splitter)]

    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text by sentences."""
        _validate_chunk_limits(self.chunk_size)
        _require_text(text)
        if not text.strip():
            return []

        sentences = _sentence_source_spans(text, self.sentence_splitter)
        chunks = []
        current_start = current_end = None

        def append(start, end):
            chunk_metadata = dict(metadata or {})
            if end - start > self.chunk_size:
                chunk_metadata.update(oversize_atomic_sentence=True, chunk_size_limit=self.chunk_size)
            chunks.append(DocumentChunk(content=text[start:end], chunk_id=f"chunk_{len(chunks)}",
                metadata=chunk_metadata, start_index=start, end_index=end))

        for start, end in sentences:
            if current_start is not None and end - current_start > self.chunk_size:
                append(current_start, current_end)
                current_start = None
            if current_start is None:
                current_start = start
            current_end = end
        if current_start is not None:
            append(current_start, current_end)
        return chunks

    async def chunk_text_async(
        self, text: str, metadata: Optional[Dict] = None
    ) -> AsyncIterator[DocumentChunk]:
        """Async version of sentence chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk


class SlidingWindowChunker(BaseChunker):
    """Chunks text using a sliding window approach."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        _validate_chunk_limits(self.chunk_size, self.config.chunk_overlap)
        self.step_size = self.chunk_size - self.config.chunk_overlap

    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text using sliding window."""
        if type(self.step_size) is not int:
            raise ValueError("sliding step must be an integer")
        _validate_chunk_limits(self.chunk_size, self.chunk_size - self.step_size)
        _require_text(text)
        if not text.strip():
            return []

        chunks = []
        chunk_id = 0

        for start in range(0, len(text), self.step_size):
            end = min(start + self.chunk_size, len(text))
            left, right = _trim_interval(text, start, end)
            chunk_content = text[left:right]

            if chunk_content:  # Only add non-empty chunks
                chunk = DocumentChunk(
                    content=chunk_content,
                    chunk_id=f"chunk_{chunk_id}",
                    metadata=metadata or {},
                    start_index=left,
                    end_index=right,
                )
                chunks.append(chunk)
                chunk_id += 1

            if end >= len(text):
                break

        return chunks

    async def chunk_text_async(
        self, text: str, metadata: Optional[Dict] = None
    ) -> AsyncIterator[DocumentChunk]:
        """Async version of sliding window chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk


class SemanticChunker(BaseChunker):
    """Group exact sentence intervals with an explicitly supplied embedder.

    ``embedder`` accepts a list of exact source strings and returns ordered
    vectors. It may wrap the embedding router with a pinned provider instance.
    No provider is selected implicitly. Without one, sentence fallback is
    explicit in every chunk's metadata and ``last_diagnostics``.

    This general text adapter does not parse Markdown/code. Structured corpora
    should use ``logic.formalization.coherent_spans`` to enforce block boundaries.
    """

    def __init__(self, config: Optional[EmbeddingConfig] = None, *, embedder=None,
                 embedding_eligible=None, min_chars=128, similarity_threshold=0.5,
                 max_embedding_chars=1024, on_embedding_error="structural"):
        super().__init__(config)
        _validate_chunk_limits(self.config.chunk_size)
        if embedder is not None and not callable(embedder):
            raise ValueError("embedder must be callable")
        if embedding_eligible is not None and not callable(embedding_eligible):
            raise ValueError("embedding_eligible must be callable")
        if type(min_chars) is not int or min_chars < 0:
            raise ValueError("min_chars must be a nonnegative integer")
        if on_embedding_error not in {"raise", "structural"}:
            raise ValueError("invalid on_embedding_error policy")
        self.embedder = embedder
        self.embedding_eligible = embedding_eligible
        self.min_chars = min_chars
        self.similarity_threshold = similarity_threshold
        self.max_embedding_chars = max_embedding_chars
        self.on_embedding_error = on_embedding_error
        self.last_diagnostics = {}
        self.chunkers = {}
        self._setup_semantic_chunking()

    def _setup_semantic_chunking(self):
        """Refresh compatibility configuration without loading a model."""
        self.embedding_model_name = self.config.model_name
        self.device = self.config.device
        self.batch_size = self.config.batch_size
        self.fallback_chunker = SentenceChunker(self.config)

    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        from .semantic_boundaries import group_semantic_atoms

        _require_text(text)
        _validate_chunk_limits(self.config.chunk_size)
        if not text.strip():
            self.last_diagnostics = {"embedding_status": "not_required", "embeddings_used": False}
            return []
        if self.embedder is None:
            self.last_diagnostics = {
                "embedding_status": "not_configured", "embeddings_used": False,
                "fallback": "sentences", "semantic_correctness_verified": False,
            }
            chunks = self.fallback_chunker.chunk_text(text, metadata)
            for chunk in chunks:
                chunk.metadata = {**chunk.metadata, **self.last_diagnostics}
            return chunks

        sentence_result = sentence_source_spans_with_diagnostics(text)
        sentences = sentence_result["spans"]
        # Include every character exactly once, attaching each inter-sentence
        # gap to the preceding atom. No string reconstruction or offset search.
        starts = [0] + [start for start, _ in sentences[1:]] + [len(text)]
        atoms = list(zip(starts, starts[1:]))
        result = group_semantic_atoms(
            text, atoms, embedder=self.embedder, max_chars=self.config.chunk_size,
            min_chars=min(self.min_chars, self.config.chunk_size),
            max_embedding_chars=self.max_embedding_chars,
            similarity_threshold=self.similarity_threshold,
            embedding_eligible=self.embedding_eligible,
            on_embedding_error=self.on_embedding_error,
        )
        self.last_diagnostics = result
        self.last_diagnostics["sentence_splitter"] = {
            key: value for key, value in sentence_result.items() if key != "spans"}
        chunks = []
        for i, group in enumerate(result["groups"]):
            start, end = group["start_char"], group["end_char"]
            chunks.append(DocumentChunk(
                content=text[start:end], chunk_id=f"semantic_chunk_{i}",
                start_index=start, end_index=end,
                metadata={**(metadata or {}),
                    "embedding_status": result["embedding_status"],
                    "embeddings_used": result["embeddings_used"],
                    "semantic_correctness_verified": False,
                    "token_budget_checked": result["config"]["token_budget_checked"],
                    "opaque_atom": group["opaque"],
                    "exceeds_chunk_size": group["exceeds_max_chars"],
                    "source_sha256": result["source_sha256"],
                    "embedding_input_sha256": result["embedding_input_sha256"],
                    "normalized_vectors_sha256": result["normalized_vectors_sha256"],
                },
            ))
        return chunks

    async def chunk_text_async(
        self, text: str, metadata: Optional[Dict] = None
    ) -> AsyncIterator[DocumentChunk]:
        for chunk in self.chunk_text(text, metadata):
            yield chunk

    async def delete_endpoint(self, model_name: str, endpoint: str):
        """Release references; lifetime of an injected provider belongs to caller."""
        self.chunkers.get(model_name, {}).pop(endpoint, None)


class Chunker:
    """Main chunker class that delegates to specific chunking strategies."""

    def __init__(self, resources: Optional[Dict] = None, metadata: Optional[Dict] = None):
        if resources is None:
            resources = {}
        if metadata is None:
            metadata = {}

        self.resources = resources
        self.metadata = metadata

        # Determine chunking strategy
        if "chunking_strategy" in metadata:
            chunking_strategy = metadata["chunking_strategy"]
        else:
            chunking_strategy = "semantic"

        if chunking_strategy not in CHUNKING_STRATEGIES:
            raise ValueError(f"Unsupported chunking strategy: {chunking_strategy}")

        self.chunking_strategy = chunking_strategy

        # Extract model information
        if "models" in metadata and len(metadata["models"]) > 0:
            self.embedding_model_name = metadata["models"][0]
        else:
            self.embedding_model_name = "sentence-transformers/all-MiniLM-L6-v2"

        # Create configuration
        self.config = EmbeddingConfig(
            model_name=self.embedding_model_name,
            chunking_strategy=ChunkingStrategy(chunking_strategy),
            chunk_size=metadata.get("chunk_size", 512),
            chunk_overlap=metadata.get("chunk_overlap", 50),
            batch_size=metadata.get("batch_size", 32),
            device=metadata.get("device", "cpu"),
        )

        # Initialize the appropriate chunker
        self.chunker = self._create_chunker()

        # Legacy compatibility
        self.batch_size = self.config.batch_size
        self.device = self.config.device
        self.chunkers = {}

    def _create_chunker(self) -> BaseChunker:
        """Create the appropriate chunker based on strategy."""
        match self.chunking_strategy:
            case "semantic":
                return SemanticChunker(
                    self.config,
                    embedder=self.resources.get("embedder"),
                    embedding_eligible=self.resources.get("embedding_eligible"),
                    min_chars=self.metadata.get("min_chars", 128),
                    similarity_threshold=self.metadata.get("similarity_threshold", 0.5),
                    max_embedding_chars=self.metadata.get("max_embedding_chars", 1024),
                    on_embedding_error=self.metadata.get("on_embedding_error", "structural"),
                )
            case "fixed":
                return FixedSizeChunker(self.config)
            case "sentences":
                return SentenceChunker(self.config)
            case "sliding_window":
                return SlidingWindowChunker(self.config)
            case _:
                raise ValueError(f"Unknown chunking strategy: {self.chunking_strategy}")

    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text using the configured strategy."""
        return self.chunker.chunk_text(text, metadata)

    async def chunk_text_async(
        self, text: str, metadata: Optional[Dict] = None
    ) -> AsyncIterator[DocumentChunk]:
        """Async version of text chunking."""
        async for chunk in self.chunker.chunk_text_async(text, metadata):
            yield chunk

    # Legacy methods for backward compatibility
    def chunk_semantically(
        self, text: str, tokenizer: Optional[Tokenizer] = None, **kwargs
    ) -> List[DocumentChunk]:
        """Legacy method for semantic chunking."""
        return self.chunk_text(text)

    async def _setup_semantic_chunking(
        self,
        embedding_model_name: str,
        device: Optional[str] = None,
        target_devices=None,
        embed_batch_size: Optional[int] = None,
    ):
        """Legacy method for setting up semantic chunking."""
        if isinstance(self.chunker, SemanticChunker):
            # Update configuration if needed
            self.config.model_name = embedding_model_name
            if device:
                self.config.device = device
            if embed_batch_size:
                self.config.batch_size = embed_batch_size

            # Re-setup the chunker
            self.chunker._setup_semantic_chunking()

    async def delete_endpoint(self, model_name: str, endpoint: str):
        """Delete a model endpoint."""
        if isinstance(self.chunker, SemanticChunker):
            await self.chunker.delete_endpoint(model_name, endpoint)


# Legacy alias for backward compatibility
chunker = Chunker

# Export public interface
__all__ = [
    "BaseChunker",
    "FixedSizeChunker",
    "SentenceChunker",
    "SlidingWindowChunker",
    "SemanticChunker",
    "Chunker",
    "chunker",
    "CHUNKING_STRATEGIES",
    "sentence_source_spans",
    "sentence_source_spans_with_diagnostics",
]
