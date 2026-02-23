"""Lightweight GraphQL query interface for KnowledgeGraph.

Implements the *GraphQL API support* feature deferred to v4.0+ in the ROADMAP.
Delivered in v3.22.26.

Supports a practical subset of GraphQL suitable for knowledge-graph exploration:

* **Entity selection by type** — top-level field name = entity type
* **Argument filters** — equality filters on ``id``, ``name``, ``type``, or
  any entity property  (``person(name: "Alice")``)
* **Field projection** — leaf fields map to ``id / entity_id``, ``name``,
  ``type / entity_type``, ``confidence``, and arbitrary ``entity.properties``
  keys
* **Relationship traversal** — nested field whose name matches a relationship
  type resolves to the targets of outgoing edges from the matched entities
  (``person { name, knows { name } }``)
* **Aliases** — ``myPeople: person { name }``
* **Float / int / bool / null / string arguments**

Response envelope follows the `GraphQL over HTTP`_ specification::

    {"data": {...}, "errors": [...optional...]}

Example::

    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor

    kg = KnowledgeGraph("example")
    alice = kg.add_entity("person", "Alice", {"age": 30, "city": "NYC"})
    bob   = kg.add_entity("person", "Bob",   {"age": 25})
    kg.add_relationship("knows", alice, bob)

    exe = KnowledgeGraphQLExecutor(kg)

    result = exe.execute('''
    {
        person(name: "Alice") {
            id
            name
            age
            knows { name age }
        }
    }
    ''')
    # {"data": {"person": [{"id": "...", "name": "Alice", "age": 30,
    #           "knows": [{"name": "Bob", "age": 25}]}]}}
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------


@dataclass
class GraphQLField:
    """A single field selection in a GraphQL document.

    Attributes:
        name:       The field name (maps to entity type or property name).
        alias:      Optional alias (``myAlias: fieldName``).
        arguments:  ``{arg_name: arg_value}`` dict of argument filters.
        sub_fields: Nested field selections (empty for leaf fields).
    """

    name: str
    alias: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    sub_fields: List["GraphQLField"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        """True when the field has no nested selections."""
        return len(self.sub_fields) == 0


@dataclass
class GraphQLDocument:
    """Top-level parsed GraphQL document (anonymous query or ``query`` keyword).

    Attributes:
        selections: Top-level field selections.
    """

    selections: List[GraphQLField]


# ---------------------------------------------------------------------------
# Parse error
# ---------------------------------------------------------------------------


class GraphQLParseError(ValueError):
    """Raised when a GraphQL query string cannot be parsed."""


# ---------------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    ("(?:[^"\\]|\\.)*")        # double-quoted string  (group 1)
    |(\d+\.\d+)                # float literal          (group 2)
    |(\d+)                     # integer literal        (group 3)
    |(true|false|null)         # boolean / null keyword (group 4)
    |([A-Za-z_][A-Za-z0-9_]*) # identifier / name      (group 5)
    |([{}\(\):,])              # single-char punctuation(group 6)
    |\s+                       # whitespace — ignored
    """,
    re.VERBOSE,
)


class GraphQLParser:
    """Simple recursive-descent parser for a practical GraphQL query subset.

    Supported grammar (informally)::

        document       := operation_opt '{' selection* '}'
        operation_opt  := ('query'|'mutation'|'subscription') name_opt
        selection      := [alias ':'] name arguments_opt selection_set_opt
        arguments_opt  := '(' argument (',' argument)* ')'
        argument       := name ':' value
        value          := string | int | float | bool | null
        selection_set  := '{' selection* '}'

    Usage::

        parser = GraphQLParser()
        doc = parser.parse('{ person(name: "Alice") { name age } }')
    """

    def parse(self, query_text: str) -> GraphQLDocument:
        """Parse a GraphQL query string.

        Args:
            query_text: GraphQL query text.

        Returns:
            Parsed :class:`GraphQLDocument`.

        Raises:
            :exc:`GraphQLParseError`: If the query cannot be parsed.
        """
        tokens: List[Tuple[str, str]] = []
        for m in _TOKEN_RE.finditer(query_text):
            raw = m.group()
            if raw.strip() == "":
                continue  # skip whitespace
            kind = self._classify(m)
            tokens.append((kind, raw))

        self._tokens = tokens
        self._pos = 0
        return self._parse_document()

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(m: re.Match) -> str:
        if m.group(1):
            return "STRING"
        if m.group(2):
            return "FLOAT"
        if m.group(3):
            return "INT"
        if m.group(4):
            return "KEYWORD"
        if m.group(5):
            return "NAME"
        return "PUNCT"

    def _peek(self) -> Optional[Tuple[str, str]]:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> Tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, value: str) -> Tuple[str, str]:
        tok = self._peek()
        if tok is None or tok[1] != value:
            got = tok[1] if tok else "EOF"
            raise GraphQLParseError(f"Expected '{value}', got '{got}'")
        return self._advance()

    # ------------------------------------------------------------------
    # Grammar rules
    # ------------------------------------------------------------------

    def _parse_document(self) -> GraphQLDocument:
        # Skip optional operation type keyword and name
        tok = self._peek()
        if tok and tok[0] == "NAME" and tok[1] in (
            "query",
            "mutation",
            "subscription",
        ):
            self._advance()
            # Optional operation name
            nxt = self._peek()
            if nxt and nxt[0] == "NAME":
                self._advance()

        selections = self._parse_selection_set()
        return GraphQLDocument(selections=selections)

    def _parse_selection_set(self) -> List[GraphQLField]:
        self._expect("{")
        selections: List[GraphQLField] = []
        while True:
            tok = self._peek()
            if tok is None:
                raise GraphQLParseError("Unexpected EOF inside selection set")
            if tok[1] == "}":
                self._advance()
                break
            # Skip stray commas between selections (non-standard but tolerated)
            if tok[1] == ",":
                self._advance()
                continue
            selections.append(self._parse_field())
        return selections

    def _parse_field(self) -> GraphQLField:
        tok = self._advance()
        if tok[0] != "NAME":
            raise GraphQLParseError(f"Expected field name, got '{tok[1]}'")
        name_or_alias = tok[1]

        # Check for alias syntax: alias ':' name
        if self._peek() and self._peek()[1] == ":":
            self._advance()  # consume ':'
            name_tok = self._advance()
            if name_tok[0] != "NAME":
                raise GraphQLParseError(
                    f"Expected field name after alias colon, got '{name_tok[1]}'"
                )
            alias: Optional[str] = name_or_alias
            name: str = name_tok[1]
        else:
            alias = None
            name = name_or_alias

        # Optional arguments
        arguments: Dict[str, Any] = {}
        if self._peek() and self._peek()[1] == "(":
            arguments = self._parse_arguments()

        # Optional sub-selection
        sub_fields: List[GraphQLField] = []
        if self._peek() and self._peek()[1] == "{":
            sub_fields = self._parse_selection_set()

        return GraphQLField(
            name=name,
            alias=alias,
            arguments=arguments,
            sub_fields=sub_fields,
        )

    def _parse_arguments(self) -> Dict[str, Any]:
        self._expect("(")
        args: Dict[str, Any] = {}
        while True:
            tok = self._peek()
            if tok is None:
                raise GraphQLParseError("Unexpected EOF inside argument list")
            if tok[1] == ")":
                self._advance()
                break
            if tok[1] == ",":
                self._advance()
                continue
            # argument name
            name_tok = self._advance()
            if name_tok[0] != "NAME":
                raise GraphQLParseError(
                    f"Expected argument name, got '{name_tok[1]}'"
                )
            self._expect(":")
            args[name_tok[1]] = self._parse_value()
        return args

    def _parse_value(self) -> Any:
        tok = self._advance()
        if tok[0] == "STRING":
            # Strip surrounding quotes; handle basic escape sequences
            inner = tok[1][1:-1]
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            return inner
        if tok[0] == "INT":
            return int(tok[1])
        if tok[0] == "FLOAT":
            return float(tok[1])
        if tok[0] == "KEYWORD":
            if tok[1] == "true":
                return True
            if tok[1] == "false":
                return False
            return None  # null
        raise GraphQLParseError(f"Unexpected value token '{tok[1]}'")


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class KnowledgeGraphQLExecutor:
    """Execute GraphQL-style queries against a :class:`KnowledgeGraph` instance.

    Supports the practical query subset described in the module docstring.
    Results are returned in the standard GraphQL-over-HTTP response envelope::

        {"data": {...}}
        {"data": {...}, "errors": [...]}  # on partial failures

    Args:
        kg: A :class:`~ipfs_datasets_py.knowledge_graphs.extraction.KnowledgeGraph`
            instance to query against.

    Example::

        exe = KnowledgeGraphQLExecutor(kg)
        result = exe.execute(\"\"\"
        {
            person(name: "Alice") {
                id
                name
                age
                knows { name }
            }
        }
        \"\"\")
    """

    def __init__(self, kg: Any) -> None:
        self._kg = kg
        self._parser = GraphQLParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, query_text: str) -> Dict[str, Any]:
        """Execute a GraphQL query against the knowledge graph.

        Args:
            query_text: GraphQL query string.

        Returns:
            ``{"data": {field_key: [entity_dicts]}}``; includes
            ``"errors"`` key when parse or resolution failures occur.
        """
        try:
            doc = self._parser.parse(query_text)
        except GraphQLParseError as exc:
            return {"data": None, "errors": [{"message": str(exc)}]}

        data: Dict[str, Any] = {}
        errors: List[Dict[str, str]] = []

        for sel in doc.selections:
            key = sel.alias or sel.name
            try:
                data[key] = self._resolve_selection(sel)
            except Exception as exc:  # noqa: BLE001 — surface as GraphQL error
                logger.debug(
                    "GraphQL resolution error for field %r (%s): %s",
                    sel.name,
                    type(exc).__name__,
                    exc,
                )
                errors.append({"message": str(exc), "path": [key]})
                data[key] = None

        result: Dict[str, Any] = {"data": data}
        if errors:
            result["errors"] = errors
        return result

    # ------------------------------------------------------------------
    # Internal resolution helpers
    # ------------------------------------------------------------------

    def _resolve_selection(self, sel: GraphQLField) -> List[Dict[str, Any]]:
        """Resolve a top-level entity-type selection."""
        entity_type = sel.name.lower()

        # Collect entities matching the type
        matches = [
            e
            for e in self._kg.entities.values()
            if e.entity_type.lower() == entity_type
        ]

        # Apply argument equality filters
        for arg_name, arg_value in sel.arguments.items():
            if arg_name in ("id", "entity_id"):
                matches = [e for e in matches if e.entity_id == str(arg_value)]
            elif arg_name == "name":
                matches = [e for e in matches if e.name == str(arg_value)]
            elif arg_name in ("type", "entity_type"):
                matches = [
                    e for e in matches if e.entity_type == str(arg_value)
                ]
            else:
                matches = [
                    e
                    for e in matches
                    if e.properties.get(arg_name) == arg_value
                ]

        if not sel.sub_fields:
            # No field selection — return default representation
            return [self._default_entity_dict(e) for e in matches]

        return [self._project_entity(e, sel.sub_fields) for e in matches]

    def _project_entity(
        self,
        entity: Any,
        fields: List[GraphQLField],
    ) -> Dict[str, Any]:
        """Project entity fields according to the GraphQL field list."""
        result: Dict[str, Any] = {}
        for fld in fields:
            key = fld.alias or fld.name
            if fld.sub_fields:
                # Nested field — resolve as relationship traversal
                result[key] = self._resolve_relationship(entity, fld)
            else:
                result[key] = self._get_entity_field(entity, fld.name)
        return result

    def _get_entity_field(self, entity: Any, field_name: str) -> Any:
        """Return a single scalar field value from an entity."""
        if field_name in ("id", "entity_id"):
            return entity.entity_id
        if field_name in ("type", "entity_type"):
            return entity.entity_type
        if field_name == "name":
            return entity.name
        if field_name == "confidence":
            return getattr(entity, "confidence", None)
        # Fall through to properties dict
        return entity.properties.get(field_name)

    def _resolve_relationship(
        self,
        source: Any,
        fld: GraphQLField,
    ) -> List[Dict[str, Any]]:
        """Resolve a nested relationship field to target entities."""
        rel_type = fld.name.lower()
        targets: List[Any] = []
        for rel in self._kg.relationships.values():
            if (
                rel.relationship_type.lower() == rel_type
                and rel.source_id == source.entity_id
            ):
                target = self._kg.entities.get(rel.target_id)
                if target is not None:
                    targets.append(target)

        if not fld.sub_fields:
            return [self._default_entity_dict(t) for t in targets]
        return [self._project_entity(t, fld.sub_fields) for t in targets]

    def _default_entity_dict(self, entity: Any) -> Dict[str, Any]:
        """Return the default dict representation of an entity."""
        result: Dict[str, Any] = {
            "id": entity.entity_id,
            "type": entity.entity_type,
            "name": entity.name,
        }
        result.update(entity.properties)
        return result


__all__ = [
    "GraphQLParseError",
    "GraphQLField",
    "GraphQLDocument",
    "GraphQLParser",
    "KnowledgeGraphQLExecutor",
]
