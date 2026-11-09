"""Pin ``legal-corpus.status@1`` to the status vocabulary in ``interfaces.py``.

``LawStatus``, ``StatusConfidence``, and ``STATUS_FIELD_NAMES`` are read
from that file. A status word outside the ``LawStatus`` literal is
rejected. This module does not assign a second status enum and does not
edit ``interfaces.py``.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

INTERFACE_ID = "legal-corpus.status@1"
_INTERFACES = Path(__file__).resolve().parents[1] / "interfaces.py"


class StatusBindingError(RuntimeError):
    """The status vocabulary is not the assignment in ``interfaces.py``."""


class StatusRejected(ValueError):
    """The word is not a ``LawStatus`` value from ``interfaces.py``."""


def _assigned_value(path: Path, name: str) -> ast.AST:
    if path.name != "interfaces.py" or not path.is_file():
        raise StatusBindingError(f"interfaces.py is missing at {path}")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
            value = node.value
        else:
            continue
        if value is None:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return value
    raise StatusBindingError(f"{name} is missing from {path}")


def _string_elts(node: ast.AST, label: str) -> tuple[str, ...]:
    if not isinstance(node, ast.Tuple) or not node.elts:
        raise StatusBindingError(f"{label} is not a non-empty tuple")
    words: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or item.value == "":
            raise StatusBindingError(f"{label} contains a non-string")
        if item.value in words:
            raise StatusBindingError(f"{label} repeats a word")
        words.append(item.value)
    return tuple(words)


def _literal_words(path: Path, name: str) -> tuple[str, ...]:
    value = _assigned_value(path, name)
    if not isinstance(value, ast.Subscript) or not isinstance(value.value, ast.Name):
        raise StatusBindingError(f"{name} in {path} is not a Literal")
    if value.value.id != "Literal":
        raise StatusBindingError(f"{name} in {path} is not a Literal")
    return _string_elts(value.slice, name)


def _field_names(path: Path, name: str) -> tuple[str, ...]:
    return _string_elts(_assigned_value(path, name), name)


LAW_STATUS_WORDS = _literal_words(_INTERFACES, "LawStatus")
STATUS_CONFIDENCE_WORDS = _literal_words(_INTERFACES, "StatusConfidence")
STATUS_FIELD_NAMES = _field_names(_INTERFACES, "STATUS_FIELD_NAMES")


def accept_status_word(word: str) -> str:
    """Accept one existing ``LawStatus`` word.

    Any other word, including a status word that ``interfaces.py`` does
    not list, is rejected.
    """

    if not isinstance(word, str):
        raise StatusRejected("status word must be a string")
    if word not in LAW_STATUS_WORDS:
        raise StatusRejected(f"new status word {word!r}")
    return word


def _assigned_strings(path: Path, name: str) -> tuple[str, ...]:
    """Every string constant under one assignment, in source order."""

    value = _assigned_value(path, name)
    found: list[str] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append(node.value)
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(value)
    return tuple(found)


class StatusVocabularyTest(unittest.TestCase):
    """``current`` is accepted and ``in_force`` is rejected."""

    def test_current_is_accepted_and_in_force_is_rejected(self) -> None:
        self.assertEqual(INTERFACE_ID, "legal-corpus.status@1")
        self.assertIn("current", LAW_STATUS_WORDS)
        self.assertNotIn("in_force", LAW_STATUS_WORDS)
        self.assertNotIn("in_force", STATUS_CONFIDENCE_WORDS)
        self.assertNotIn("in_force", STATUS_FIELD_NAMES)
        self.assertEqual(accept_status_word("current"), "current")
        with self.assertRaises(StatusRejected) as caught:
            accept_status_word("in_force")
        self.assertIn("in_force", str(caught.exception))
        self.assertIn("new status word", str(caught.exception))
        for value in (None, 1, True):
            with self.subTest(value=repr(value)):
                with self.assertRaises(StatusRejected) as caught_type:
                    accept_status_word(value)  # type: ignore[arg-type]
                self.assertIn("status word must be a string", str(caught_type.exception))

    def test_export_is_the_interfaces_vocabulary(self) -> None:
        text = _INTERFACES.read_text(encoding="utf-8")
        self.assertIn("\nLawStatus = Literal[", text)
        self.assertIn("\nStatusConfidence = Literal[", text)
        self.assertIn("\nSTATUS_FIELD_NAMES:", text)
        self.assertEqual(LAW_STATUS_WORDS, _assigned_strings(_INTERFACES, "LawStatus"))
        self.assertEqual(
            STATUS_CONFIDENCE_WORDS,
            _assigned_strings(_INTERFACES, "StatusConfidence"),
        )
        self.assertEqual(STATUS_FIELD_NAMES, _assigned_strings(_INTERFACES, "STATUS_FIELD_NAMES"))
        self.assertEqual(len(LAW_STATUS_WORDS), len(set(LAW_STATUS_WORDS)))
        self.assertEqual(len(STATUS_CONFIDENCE_WORDS), len(set(STATUS_CONFIDENCE_WORDS)))
        self.assertEqual(len(STATUS_FIELD_NAMES), len(set(STATUS_FIELD_NAMES)))
        self.assertGreater(len(STATUS_FIELD_NAMES), 0)
        for word in STATUS_CONFIDENCE_WORDS:
            if word in LAW_STATUS_WORDS:
                self.assertEqual(accept_status_word(word), word)
                continue
            with self.assertRaises(StatusRejected):
                accept_status_word(word)

    def test_module_does_not_define_a_parallel_status_enum(self) -> None:
        path = Path(__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        self.assertNotEqual(base.id, "Enum")
                    elif isinstance(base, ast.Attribute):
                        self.assertNotEqual(base.attr, "Enum")
            names: list[str] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                value = node.value
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                value = node.value
                names = [node.target.id]
            if value is None:
                continue
            self.assertNotIsInstance(value, (ast.Tuple, ast.List, ast.Set, ast.Subscript))
            for name in names:
                self.assertNotIn(name, {"LawStatus", "StatusConfidence"})
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in imported:
            parts = name.split(".")
            self.assertNotIn("interfaces", parts)
            self.assertNotEqual(parts[-1], "enum")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StatusVocabularyTest)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
