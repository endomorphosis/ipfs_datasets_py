#!/usr/bin/env python3
"""Reject hidden Unicode control characters in the focused security verification surface."""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGETS = [
    '.github/workflows/security-logic-ci.yml',
    'docs/security_verification',
    'ipfs_datasets_py/logic/security_models',
    'scripts/ops/security_verification',
    'tests/logic/security_models/crypto_exchange',
]
# These are the executable/source-facing formats that should never collapse into a
# single logical GitHub-rendered line within the focused security-verification surface.
MULTILINE_TEXT_SUFFIXES = {'.py', '.yml', '.yaml', '.md', '.ts', '.js', '.sh'}
BIDI_CONTROLS = {*range(0x202A, 0x202F), *range(0x2066, 0x206A)}
ZERO_WIDTH_CONTROLS = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}
NONSTANDARD_LINE_SEPARATORS = {0x2028, 0x2029}
ALLOWED_CONTROLS = {0x09, 0x0A, 0x0D}



def _iter_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        path = ROOT / target
        if path.is_file():
            files.append(path)
            continue
        files.extend(sorted(file_path for file_path in path.rglob('*') if file_path.is_file() and '__pycache__' not in file_path.parts and file_path.suffix != '.pyc'))
    return files



def scan_file(path: Path) -> list[str]:
    errors: list[str] = []
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        return [f'{path}: invalid UTF-8 ({exc})']
    if b'\r\n' in raw:
        errors.append(f'{path}: CRLF newlines are not allowed')
    if must_be_multiline(path) and file_line_count(text) <= 1:
        errors.append(f'{path}: expected ordinary physical newlines, found a single logical line')
    for index, character in enumerate(text, start=1):
        codepoint = ord(character)
        if codepoint in BIDI_CONTROLS:
            errors.append(f'{path}: bidi control U+{codepoint:04X} at character {index}')
        elif codepoint in ZERO_WIDTH_CONTROLS:
            errors.append(f'{path}: zero-width control U+{codepoint:04X} at character {index}')
        elif codepoint in NONSTANDARD_LINE_SEPARATORS:
            errors.append(f'{path}: nonstandard line separator U+{codepoint:04X} at character {index}')
        elif codepoint in ALLOWED_CONTROLS:
            continue
        elif unicodedata.category(character) == 'Cc':
            errors.append(f'{path}: unexpected control character U+{codepoint:04X} at character {index}')
        elif unicodedata.category(character) == 'Cf':
            errors.append(f'{path}: unexpected format character U+{codepoint:04X} at character {index}')
    return errors


def must_be_multiline(path: Path) -> bool:
    """Return whether the file should never be serialized as one logical line."""
    return path.suffix in MULTILINE_TEXT_SUFFIXES


def file_line_count(text: str) -> int:
    """Count editor-style physical lines, including a final unterminated line when present."""
    if not text:
        return 0
    return text.count('\n') + (0 if text.endswith('\n') else 1)


def file_byte_diagnostics(path: Path) -> dict[str, int]:
    """Return simple byte-level newline/separator diagnostics for a file."""
    raw = path.read_bytes()
    return {
        'lf': raw.count(b'\n'),
        'cr': raw.count(b'\r'),
        'u2028': raw.count('\u2028'.encode('utf-8')),
        'u2029': raw.count('\u2029'.encode('utf-8')),
    }



def main() -> int:
    failures: list[str] = []
    for path in _iter_files():
        failures.extend(scan_file(path))
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        return 1
    print('No hidden Unicode issues found.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
