# Text preservation v3.3 (2026-10-17)

`text_preservation.patch` applies to the upstream `a1b5c73e` files (`git apply` from the ipfs_datasets_py root)
and touches `country_laws_ir/normalize.py` and `country_laws_ir/structure.py`. v3.3 replaces v3.2 (and v3).
`text_preservation_v3.3/` holds both files with the patch already applied, byte for byte as used in IR builds:
structure.py sha256 `aaafcf905f7480988fe93769f005e9fb15abf9b4df0f570474a1bbbe3afed6ef`,
normalize.py sha256 `5e4822a164840ee6f7af1bc1a5387d295d8bb9fbe2f7c9e1ebbdbd9d74d6b4fa`.

What the rules do in v3.3 (only the hyphen-join rule changed from v3.2):
- A lone number on its own line is removed as a page stamp only when it follows a line that ends a sentence
  (`.` `!` `?` `;`, with a word character on that line; a `:` does not end a sentence), or starts the text,
  or belongs to a page run (lone numbers 1 or 2 apart, at most 150 non-blank lines per page between them).
  Kept: numbers after a `:` line ("O.S. SHEET:" / "3678"), numbers of 1000 or more that are not in a page run
  (map labels, sheet numbers), numbered-list numbers, TOC numbers after a dot leader, and table cells
  (a lone number next to another lone number line).
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

`test_text_preservation.py` (v3.3) also checks that no content line is lost or joined (only hyphen joins that meet the rule above
are allowed; any other glued line is a bad join), counts paragraph breaks honestly (raw = kept + merged + hyphen_join + dropped_edge + lost;
IR = kept + invented), and carries real-snippet regression cases from IE / LU / GR / SK: `--cases` (20 v3.2 cases + 10 v3.3 cases: the four LU
table joins, the IE / LU word joins and two single-letter cases derived from real lines).
