#!/usr/bin/env python3
"""Reject hidden Unicode control characters in the focused security verification surface."""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

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
# Extend this list when new source/workflow/script types are added here.
MULTILINE_TEXT_SUFFIXES = {'.py', '.yml', '.yaml', '.md', '.ts', '.js', '.sh', '.json'}
BIDI_CONTROLS = {*range(0x202A, 0x202F), *range(0x2066, 0x206A)}
ZERO_WIDTH_CONTROLS = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}
NONSTANDARD_LINE_SEPARATORS = {0x2028, 0x2029}
ALLOWED_CONTROLS = {0x09, 0x0A}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        path = ROOT / target
        if path.is_file():
            files.append(path)
            continue
        files.extend(sorted(file_path for file_path in path.rglob('*') if file_path.is_file() and '__pycache__' not in file_path.parts and file_path.suffix != '.pyc'))
    return files


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _build_violation(
    path: Path,
    *,
    category: str,
    line_number: int,
    byte_offset: int,
    char_offset: int,
    message: str,
    codepoint: int | None = None,
    unicode_category: str | None = None,
) -> dict[str, Any]:
    return {
        'path': _display_path(path),
        'line_number': line_number,
        'byte_offset': byte_offset,
        'char_offset': char_offset,
        'code_point': None if codepoint is None else f'U+{codepoint:04X}',
        'unicode_category': unicode_category,
        'category': category,
        'message': message,
    }


def _format_violation(violation: dict[str, Any]) -> str:
    code_point = violation['code_point'] or 'n/a'
    unicode_category = violation['unicode_category'] or 'n/a'
    return (
        f"{violation['path']}: byte_offset={violation['byte_offset']} "
        f"char_offset={violation['char_offset']} "
        f"line={violation['line_number']} code_point={code_point} "
        f"unicode_category={unicode_category} category={violation['category']} "
        f"message={violation['message']}"
    )


def scan_file(path: Path) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        return [
            _build_violation(
                path,
                category='invalid_utf8',
                line_number=1,
                byte_offset=exc.start,
                char_offset=exc.start,
                codepoint=None,
                unicode_category=None,
                message=f'invalid UTF-8 ({exc})',
            )
        ]
    line_number = 1
    byte_offset = 0
    char_offset = 0
    for character in text:
        codepoint = ord(character)
        unicode_category = unicodedata.category(character)
        if codepoint == 0x0A:
            line_number += 1
        elif codepoint == 0x0D:
            errors.append(
                _build_violation(
                    path,
                    category='carriage_return',
                    line_number=line_number,
                    byte_offset=byte_offset,
                    char_offset=char_offset,
                    codepoint=codepoint,
                    unicode_category=unicode_category,
                    message='carriage return bytes are not allowed; use LF newlines only',
                )
            )
        elif codepoint in BIDI_CONTROLS:
            errors.append(
                _build_violation(
                    path,
                    category='bidi_control',
                    line_number=line_number,
                    byte_offset=byte_offset,
                    char_offset=char_offset,
                    codepoint=codepoint,
                    unicode_category=unicode_category,
                    message='bidi controls are not allowed',
                )
            )
        elif codepoint in ZERO_WIDTH_CONTROLS:
            errors.append(
                _build_violation(
                    path,
                    category='zero_width_control',
                    line_number=line_number,
                    byte_offset=byte_offset,
                    char_offset=char_offset,
                    codepoint=codepoint,
                    unicode_category=unicode_category,
                    message='zero-width controls are not allowed',
                )
            )
        elif codepoint in NONSTANDARD_LINE_SEPARATORS:
            errors.append(
                _build_violation(
                    path,
                    category='nonstandard_line_separator',
                    line_number=line_number,
                    byte_offset=byte_offset,
                    char_offset=char_offset,
                    codepoint=codepoint,
                    unicode_category=unicode_category,
                    message='U+2028 and U+2029 line separators are not allowed',
                )
            )
        elif codepoint in ALLOWED_CONTROLS:
            pass
        elif unicode_category == 'Cc':
            errors.append(
                _build_violation(
                    path,
                    category='unexpected_control_character',
                    line_number=line_number,
                    byte_offset=byte_offset,
                    char_offset=char_offset,
                    codepoint=codepoint,
                    unicode_category=unicode_category,
                    message='unexpected control character is not allowed',
                )
            )
        elif unicode_category == 'Cf':
            errors.append(
                _build_violation(
                    path,
                    category='unexpected_format_character',
                    line_number=line_number,
                    byte_offset=byte_offset,
                    char_offset=char_offset,
                    codepoint=codepoint,
                    unicode_category=unicode_category,
                    message='unexpected format character is not allowed',
                )
            )
        byte_offset += len(character.encode('utf-8'))
        char_offset += 1
    if must_be_multiline(path) and file_line_count(text) <= 1:
        errors.append(
            _build_violation(
                path,
                category='single_line_file',
                line_number=1,
                byte_offset=0,
                char_offset=0,
                codepoint=None,
                unicode_category=None,
                message='expected ordinary physical newlines, found a single logical line',
            )
        )
    return errors


def must_be_multiline(path: Path) -> bool:
    """Return whether the file should never be serialized as one logical line."""
    return path.suffix in MULTILINE_TEXT_SUFFIXES


def file_line_count(text: str) -> int:
    r"""Count newline-delimited lines, treating a final unterminated fragment as one line."""
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


def build_report() -> dict[str, Any]:
    scanned_files: list[str] = []
    violations: list[dict[str, Any]] = []
    for path in _iter_files():
        scanned_files.append(_display_path(path))
        violations.extend(scan_file(path))
    return {
        'root': ROOT.as_posix(),
        'files_scanned': scanned_files,
        'file_count': len(scanned_files),
        'violations': violations,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', action='store_true', help='print detailed per-violation diagnostics')
    parser.add_argument('--report', type=Path, help='write a machine-readable JSON report to this path')
    return parser.parse_args(argv)


def write_report(report_path: Path, payload: dict[str, Any]) -> None:
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_report()
    if args.report:
        write_report(args.report, payload)
    failures = payload['violations']
    if failures:
        rendered = [_format_violation(failure) for failure in failures]
        stream = sys.stderr
        print('\n'.join(rendered), file=stream)
        return 1
    if args.verbose:
        print(json.dumps(payload, indent=2, sort_keys=True))
    print('No hidden Unicode issues found.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
