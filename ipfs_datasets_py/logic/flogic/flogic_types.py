"""
F-logic (Frame Logic) data types.

F-logic is an object-oriented logic programming language that extends
classical logic with frame-based structures (objects, classes, inheritance,
methods, and attributes).  See: https://en.wikipedia.org/wiki/F-logic

These types model the core F-logic constructs used by the ErgoAI/ErgoEngine
backend, and can also be used independently for in-process reasoning about
knowledge-graph ontologies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FLogicStatus(Enum):
    """Status of an F-logic operation."""

    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class FLogicFrame:
    """
    An F-logic *frame* — the basic unit of object description.

    Syntax (textual representation)::

        <object>[<method1> -> <value1>, <method2> ->> {<v1>, <v2>}, ...]

    Attributes:
        object_id: Identifier of the object (molecule).
        scalar_methods: Single-valued attribute/method pairs ``{name: value}``.
        set_methods: Multi-valued attribute/method pairs ``{name: [values]}``.
        isa: Direct super-class (``<object> : <class>``).
        isaset: All super-classes the object belongs to.
    """

    object_id: str
    scalar_methods: Dict[str, Any] = field(default_factory=dict)
    set_methods: Dict[str, List[Any]] = field(default_factory=dict)
    isa: Optional[str] = None
    isaset: List[str] = field(default_factory=list)

    def to_ergo_string(self) -> str:
        """Render the frame as an Ergo/ErgoAI rule head string."""
        parts: List[str] = []
        for name, val in self.scalar_methods.items():
            parts.append(f"{name} -> {val}")
        for name, vals in self.set_methods.items():
            val_str = "{" + ",".join(str(v) for v in vals) + "}"
            parts.append(f"{name} ->> {val_str}")
        attrs = ", ".join(parts)
        base = f"{self.object_id}[{attrs}]" if attrs else self.object_id
        if self.isa:
            base = f"{base} : {self.isa}"
        return base


@dataclass
class FLogicClass:
    """
    An F-logic class definition.

    Attributes:
        class_id: Name of the class.
        superclasses: Direct superclasses (``<class> :: <superclass>``).
        signature_methods: Method signatures with expected value types.
    """

    class_id: str
    superclasses: List[str] = field(default_factory=list)
    signature_methods: Dict[str, str] = field(default_factory=dict)

    def to_ergo_string(self) -> str:
        """Render the class hierarchy as an Ergo subclass assertion."""
        lines: List[str] = []
        for sup in self.superclasses:
            lines.append(f"{self.class_id} :: {sup}.")
        for meth, typ in self.signature_methods.items():
            lines.append(f"{self.class_id}[{meth} => {typ}].")
        return "\n".join(lines)


@dataclass
class FLogicQuery:
    """
    An F-logic query (goal clause).

    Attributes:
        goal: The query string in Ergo/ErgoAI syntax.
        bindings: Variable bindings returned after query execution.
        status: Result status.
        error_message: Human-readable error description if status is ERROR.
    """

    goal: str
    bindings: List[Dict[str, Any]] = field(default_factory=list)
    status: FLogicStatus = FLogicStatus.UNKNOWN
    error_message: Optional[str] = None


@dataclass
class FLogicOntology:
    """
    A collection of F-logic frames and class definitions forming an ontology.

    Attributes:
        name: Human-readable name for the ontology.
        frames: Object frames.
        classes: Class definitions.
        rules: Additional Ergo/Prolog rules (raw strings).
    """

    name: str
    frames: List[FLogicFrame] = field(default_factory=list)
    classes: List[FLogicClass] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)

    def to_ergo_program(self) -> str:
        """Render the whole ontology as an Ergo source program."""
        lines: List[str] = []
        for cls in self.classes:
            lines.append(cls.to_ergo_string())
        for frame in self.frames:
            lines.append(frame.to_ergo_string() + ".")
        lines.extend(self.rules)
        return "\n".join(lines)


__all__ = [
    "FLogicStatus",
    "FLogicFrame",
    "FLogicClass",
    "FLogicQuery",
    "FLogicOntology",
]
