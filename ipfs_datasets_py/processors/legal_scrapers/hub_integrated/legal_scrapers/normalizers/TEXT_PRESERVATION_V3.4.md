# Text preservation v3.4 (2026-10-17)

`text_preservation.patch` applies to the upstream `a1b5c73e` files (`git apply` from the ipfs_datasets_py root)
and touches `country_laws_ir/normalize.py` and `country_laws_ir/structure.py`. v3.4 replaces v3.3 (and v3.2, v3).
`text_preservation_v3.4/` holds both files with the patch already applied, byte for byte as used in IR builds:
structure.py sha256 `9ea44eb6759f419762ce5d190fa219f8b3362f9f7c01bb5692c64ab87237583e`,
normalize.py sha256 `5e4822a164840ee6f7af1bc1a5387d295d8bb9fbe2f7c9e1ebbdbd9d74d6b4fa` (unchanged from v3.3).

What the rules do in v3.4 (only the lone-number rule changed from v3.3; v3.4 removes a subset of what v3.3 removed):
- Lone numbers. A line that is only 1 to 4 digits is removed as a page stamp only if the text has more than one
  non-blank line and none of the following keeps it. The positions below are counted in non-blank lines of the
  text as `strip_chrome_lines` sees it; "the line before / after" is the previous / next non-blank line.
  Kept (unchanged from v3.3):
  1. the line before ends in a digit (optionally followed by `-`, `.` or `/`), in `§`, or in one of the words `d`,
     `den`, `nr`, `no`, `stk`, `af`, `kl`, `pr` (optionally followed by `.`): a wrapped date or number
     (`d. 01-06-` / `2024`);
  2. the line before or after is also a lone-number line (table cell);
  3. the value is 1000 or more and the number is not in a page run (lone numbers 1 or 2 apart, at most 150
     non-blank lines per page between them): map labels, sheet numbers;
  4. it is not the first line and the lone number before it is n-1 within 12 lines (numbered list / figure markers),
     or the line before ends in a dot leader (`..` or `…`).
  Kept (new in v3.4, `_page_stamp_vetoes`):
  5. it is written with a leading `0` (`0`, `01`);
  6. another lone-number line is at most 12 non-blank lines before or after it. Such numbers form a column
     (table of contents, list of figures, a table or a list) and the whole column is kept, never part of it
     (`17` / `Art. 10` / `17` / `Art. 11` / `18`);
  7. the line after starts with `.`, `)` or `]`, or with a list marker (1 to 3 digits or 1 to 4 letters, optionally
     after `(`, then `)` or `.`, then a space or the line end): the `1` of a split `13)` before `3) de souiller`;
  8. it is not the first line and the line before does not end a sentence (`.` `!` `?` `;`, optionally followed by
     closing brackets or quotes, with a word character on that line; `:` does not end a sentence): the number
     continues a phrase, an address or a table row (`devant la maison` / `20`, `entamée de` / `3`, `4+` / `1`).
     A page run alone no longer removes such a number;
  9. page numbers only go up: it is kept when a lone number with a larger value is at most 150 non-blank lines
     before it, or one with a smaller value is at most 150 non-blank lines after it;
  10. its value is 2 to 9, it is neither the first nor the last line, and no lone n-1 or n-2 is at most 150
      non-blank lines before it (a paragraph number such as `2` after `... mis à disposition.`).
  So a removed lone number is either the first line of the text or follows a sentence end, stands alone (nothing
  within 12 lines), fits a rising page order and is not a small paragraph number. `N/M` footers (M <= 30), `736 737`
  facing-page lines and `3 of 5` lines are removed as before.
  LU IR 176b86b271 (v3.3) removed 321 lone numbers; the Verifier classed 48 as page stamps, 196 as ToC / figure-list
  page references and 77 as content. v3.4 removes 32, all of them among the 48; it keeps the 273 others and 16 of the
  48 (5 by rule 8 alone, 3 by rule 9 alone, 1 by rule 6 alone, 1 by rule 10 alone, 6 by more than one rule; each
  is listed with its rules in `CASES_V34_NUMREM`).
- Spaced letters are closed up only on one line, only in capitals, and only for a heading keyword followed by
  a number (`A R T I C L E 5` -> `ARTICLE 5`). Letters on separate lines are never joined (`M` / `C` / `R` / `D`
  stays), other spaced words stay (`G A T S E`), and a hyphen join never takes a single letter (see next rule).
- Hyphen joins. A line that ends in a hyphen (`-`, U+2010 or U+2011) right after a letter is joined to the next
  non-blank line, with the hyphen kept and only the line break(s) removed, when all of these hold:
  1. the next line starts with a letter that is not upper case;
  2. the next word (the characters up to the first whitespace) contains at least 2 letters, so a single letter
     (`t`, `à`, `t,`) is never joined, while `à-dire` is;
  3. the next line does not start with a list marker (1 to 4 letters then `)` or `.`, then a space or the line end:
     `a)`, `b.`, `iv)`);
  4. if one or more blank lines lie between the two lines, the line ending in the hyphen is a prose line: at least
     20 characters after stripping and at least 3 runs of 2 or more letters (the hyphenated fragment counts).
  Joined: `non-` / `resident` and `di-` / `rection` (IE), `grand-` / `ducal`, `l’ayant-` / `droit`, `c’est-` /
  `à-dire` (LU), all after long prose lines. Not joined: `lave-` / `faciles` (the line `lave-` is not prose),
  `sèche-` / `à` and `12.0 m-` / `t` (single letter), `ways-` / `a)` (list marker). Still joined, because it meets
  every condition: `Suivent les signatures-` / `pour extrait conforme.` (23 characters, 3 letter runs).
- Lines made only of underscore runs (`______`, `____ ____`) are removed together with their line break, so the
  blank-line runs around them become one paragraph break; the first and the last non-blank line of a text are
  kept even if they are such a line, so no paragraph break is lost at the edges. Inline fill-ins (`__.__`,
  `/20__`, `NO.____`) are kept as written.
- Private-use glyphs are removed except a bullet glyph that opens a line; only complete HTML character references
  ending in `;` are decoded (a bare `&nbsp` stays); `#` heading marks, `__x__` underline marks and `=` rule lines
  are kept (their stripping is opt-in with `COUNTRY_LAWS_IR_LEGACY_STRIP=1`); `== Title ==` is unwrapped only for
  2 to 6 `=` on each side.

Folded in from the earlier unpublished v3.1 working copy: table-cell lone numbers, the word-character condition for
a sentence end, `__x__` underline opt-in, and the tighter `==` heading rule.

`test_text_preservation.py` (v3.4) also checks that no content line is lost or joined (only hyphen joins that meet the rule above
are allowed; any other glued line is a bad join), counts paragraph breaks honestly (raw = kept + merged + hyphen_join + dropped_edge + lost;
IR = kept + invented), and classes a removed lone number as a page stamp only under the v3.4 rule above (any other is lost content).
`--cases` runs the real-snippet regression cases: 20 v3.2 + 10 v3.3 + 13 v3.4 (ToC and figure-list columns, house number, the `1` of
`13)`, tariff and subsidy cells, a lone `0`, `entamée de` / `3`, a paragraph number, a page number after a phrase that is kept, and three
true page stamps that must still be removed: last line, first line, between a sentence end and a heading).
`--numrem RAW_REPO@REV|RAW_PACK_DIR` checks all 321 removals of the Verifier's `lu_ir_176b_numrem.tsv` (`CASES_V34_NUMREM`) against raw
LU `d9925146e7`: the 273 ToC / content lines must be kept, 32 page stamps removed, 16 page stamps kept as recorded.
