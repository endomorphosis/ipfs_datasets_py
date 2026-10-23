# Text preservation v3.4.3 (2026-10-18)

`text_preservation.patch` applies to the upstream `a1b5c73e` files (`git apply` from the ipfs_datasets_py root)
and touches `country_laws_ir/normalize.py` and `country_laws_ir/structure.py`. v3.4.3 replaces v3.4.2 (and v3.4.1, v3.4,
v3.3, v3.2, v3). `text_preservation_v3.4.3/` holds both files with the patch already applied, byte for byte as used in IR builds:
structure.py sha256 `db8f1f2fa923993ea6a0f6974ac469fdbb8ef77ba91fc343dddb2947da393397`,
normalize.py sha256 `3b454e6534908184c160cb92581b50a16caa457cc1a9d8a123073a5a2d627ca3`.

What changed in v3.4.3: an article copy never removes a line that its law row keeps.
- `normalize_legal_text(value, *, parent=None)`: `parent` is the raw text of the law row an article row was copied from.
  The article text and the parent go through the same steps up to the chrome-line cleanup (`strip_chrome_lines`). When
  the article's non-blank lines occur as one contiguous run of the parent's non-blank lines (compared with all whitespace
  removed), every article line whose matching parent line is kept by the parent's cleanup is kept in the article too. If
  the run occurs several times, a line kept in any occurrence is kept. This only adds lines; without a parent, or when the
  article is not found as such a run, the result is exactly the v3.4.2 result.
- `normalize.py`: article rows (the emitted article bodies and the child bodies used for the thin-parent decisions) are
  normalized with their law row's raw `text` as `parent` (`_article_text`). Law rows, titles and every other field are
  normalized as before.
- Why: each row used to be cleaned on its own, so an article copy could not see what its law row's rules saw (a footnote
  reference elsewhere in the law, the law's page run). The Verifier found GR article copies that dropped footnote numbers
  their law row keeps (`31` in 4701-6sarwj2 art-18, `32` in art-30, `1` in 2401-ww82w96 art-6).
- Effect on raw `endomorphosis/ipfs_greece_municipal_laws` 2b7b37b0b0: 369 article rows gain 399 lone-number lines (the
  Verifier's 391 mapped removals plus its 8 ambiguous ones); no line is removed and no law row changes. In the law rows the
  399 are kept by the lone-number rule's vetoes below: page order 273, footnote reference 107, number column 32, impossible
  page position 23, paragraph number 5, unconfirmed `1` 2 (a line can have several). So the article copy now keeps
  whatever the law row keeps, including law-row page stamps that a veto keeps conservatively.
- IE (raw 7a386bf357) builds byte-identical to a7f8759c65 (every corpus, bm25, graph and index parquet). LU (raw
  d9925146e7) differs from 6bc71ecf40 in exactly 2 of 8,323 rows: lu-mun-0208-doc-d8d3735c8b92 art-2 keeps a final `1` and
  art-3 a final `2` (page stamps that the 51-line law row keeps by the number-column veto); every other row is
  byte-identical.
- Gates: `gates_stream.py` `body_eq_shipped_normalize_raw` passes the raw law text as `parent` for article rows when the
  shipped `normalize_legal_text` accepts `parent` (v3.4.3 and later); older releases are checked as before.

`test_text_preservation.py` v3.4.3: `--cases` adds `CASES_V343`, the three Verifier rows, each with an excerpt of its law
row's raw text as `parent`: the number must be kept with the parent, the parent excerpt must keep it itself, and without the
parent the result must stay the v3.4.2 one. The v3.4.2 case for 4701 art-18 alone is kept (renamed `gr_art_copy_no_parent_4701`)
and its note now says what `31` is: a footnote number, not a page stamp. 63 cases, all pass.

The lone-number rule and every other rule are unchanged from v3.4.2:

What the rules do in v3.4.2 (the lone-number rule as in v3.4.1 plus rule 16; v3.4.2 removes a subset of what v3.4.1
removed, which was a subset of v3.4 and v3.3):
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
  9. page numbers only go up and never repeat: it is kept when a lone number with a larger or equal value (v3.4:
     larger) is at most 150 non-blank lines before it, or one with a smaller or equal value (v3.4: smaller) is at
     most 150 non-blank lines after it. Two equal lone numbers within 150 lines are therefore both kept;
  10. its value is 2 to 9, it is neither the first nor the last line, and no lone n-1 or n-2 is at most 150
      non-blank lines before it (a paragraph number such as `2` after `... mis à disposition.`).
  Kept (new in v3.4.1, also in `_page_stamp_vetoes`):
  11. footnote number: its value n is at most 99 and the text has a matching footnote reference anywhere: a run of
      3 or more letters that is all lower case, or one of the closing marks `»` `”` `"` `)` `,` `;` `:` `!` `?` not
      preceded by a digit, directly followed by n and then by neither a letter nor a digit (`renvoyé1.`,
      `alcooliques1 et`; not `0,90 m`, `PC6`, `km2`); or a line that starts with n directly followed by a letter
      that does not begin an ordinal suffix (`er`, `re`, `ère`, `ème`, `e`, `è`, `nd`, `st`, `rd`, `th`, `o`, `a`,
      `η`, `ος`, `ης`, `ου` as a whole word) (`1ART. 47 bis`; not `1er`);
  12. unconfirmed 1: its value is 1, it is not the last line, and no lone `2` is at most 150 non-blank lines after it.
      1 is also the first footnote number of every text, and an article copy can carry the footnote without its
      reference (the reference sits in another article), so a page 1 is removed only as the last line or when the
      page run goes on;
  13. sign or limit value: it is not the first line and the line before contains (case-insensitive) `signal`,
      `panneau`, `limitation`, `limite`, `vitesse`, `km/h`, `schild`, `geschwindigkeit`, `höchst`, the word `sign`,
      a word starting with `limit`, `speed`, `značk`, `rýchlos`, `obmedzen`, `πινακίδ`, `σήμα`, `όριο` or `ταχύτ`
      (`... signal C, 14 « limitation de vitesse » adapté.` / `70`);
  14. impossible page position (upper bound): its position k (0-based, non-blank lines) is at least 150 n: page n
      cannot end after more than 150 lines per page (`1` at line 622);
  15. impossible page position (lower bound): the text has at least 150 non-blank lines and k < 5 (n - 1): page n
      cannot end before n - 1 pages of at least 5 lines (`70` at line 249 of 7,171 needs 345). Shorter texts may be
      excerpts (article copies) that start in the middle of a document, so only rule 14 applies to them.
  Kept (new in v3.4.2, also in `_page_stamp_vetoes`):
  16. page reference: it is not the first line and the line before ends in a page word (`Σελ.`, `σελ.`, `Σελίδα`,
      `p.`, `pp.`, `S.`, `Seite`, `str.`, `page`, case-sensitive, each starting a word, optionally followed by
      spaces) or contains a dot leader (`..` or `…`) anywhere (rule 4 only looked at the line end):
      `ΕΠΙΧΟΡΗΓΗΣΕΙΣ` / `......Σελ.` / `26`. On GR raw this keeps 15 lines that v3.4.1 removed (12 rows):
      6 table-of-contents page references (4705-wjylweb law + art-23 `26`; 6901-9c5mw1r `9` and `42`, law + art-0 /
      art-28) and 9 page stamps whose line before contains `..` or `...` (kept conservatively; they are raw text).
  So a removed lone number is either the first line of the text or follows a sentence end, stands alone (nothing
  within 12 lines), fits a strictly rising page order and a plausible page position, is not a small paragraph
number, a footnote number, a sign value, an unconfirmed 1 or a page reference. `N/M` footers (M <= 30), `736 737`
  facing-page lines and `3 of 5` lines are removed as before.
  LU IR 176b86b271 (v3.3) removed 321 lone numbers; the Verifier classed 48 as page stamps, 196 as ToC / figure-list
  page references and 77 as content. v3.4 removes 32, all of them among the 48; it keeps the 273 others and 16 of the
  48 (5 by rule 8 alone, 3 by rule 9 alone, 1 by rule 6 alone, 1 by rule 10 alone, 6 by more than one rule; each
  is listed with its rules in `CASES_V34_NUMREM`).
  The Verifier's review of LU IR 5bc8e7f6a7 (`lu_ir_5bc8_numrem_review.tsv`, corrected verdicts for those 32) found
  10 of them are content: footnote numbers in 0304-2f7b (`renvoyé1`), 0208-7a81 (`alcooliques1`), 0305-4d41 and the
  first `1` of 0304-7f3e, and the speed-limit sign value `70` in 0213-298a, each in the law row and its article copy;
  4 are ambiguous but plausible page stamps (`42` in 0105-8654, the first-line `4` in 0304-e7ae, law and article)
  and 18 are page stamps. v3.4.1 removes 17 of the 32: the 4 ambiguous ones and 13 page stamps. It keeps all 10
  content lines and 5 page stamps (the final `1` of 0304-7f3e and its article copy by rule 9, and the mid-text `1`
  of the article copies 0204-36ee art-2, 0208-4a59 art-3 and 0304-475a art-5 by rule 12). Of the 10 content lines,
  rule 11 keeps 4 (2f7b law, 7a81 law, 4d41 law and art-47), rule 9 keeps 2 (7f3e law and art-7, together with
  rule 12), rule 13 keeps 2 (298a law, also rule 15, and art-1/6), and rule 12 alone keeps 2 (the article copies of
  2f7b and 7a81, whose footnote references are in other rows). Across the 321 rows of the 176b TSV: 17 removed,
  all 273 ToC / content lines and 31 of the 48 `page` lines kept.
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
- Zero-width and format characters (U+200B-U+200F, U+2060, U+FEFF, U+00AD soft hyphen, bidi controls) are removed,
  except that a line made only of U+00AD (with optional spaces or tabs) is kept exactly as written (new in v3.4.2):
  it is a bullet glyph (`Κατευθύνει και εποπτεύει:` / U+00AD / `Το παιδαγωγικό έργο.`), and removing it would turn
  the line into a paragraph break the raw text does not have. Soft hyphens inside words are still removed.
- Private-use glyphs are removed except a bullet glyph that opens a line; only complete HTML character references
  ending in `;` are decoded (a bare `&nbsp` stays); `#` heading marks, `__x__` underline marks and `=` rule lines
  are kept (their stripping is opt-in with `COUNTRY_LAWS_IR_LEGACY_STRIP=1`); `== Title ==` is unwrapped only for
  2 to 6 `=` on each side.

Folded in from the earlier unpublished v3.1 working copy: table-cell lone numbers, the word-character condition for
a sentence end, `__x__` underline opt-in, and the tighter `==` heading rule.

`test_text_preservation.py` (v3.4.2) also checks that no content line is lost or joined (only hyphen joins that meet the rule above
are allowed; any other glued line is a bad join), counts paragraph breaks honestly (raw = kept + merged + hyphen_join + dropped_edge + lost;
IR = kept + invented), and classes a removed lone number as a page stamp only under the v3.4.2 rule above (any other is lost content).
`--cases` runs the real-snippet regression cases: 20 v3.2 + 10 v3.3 + 13 v3.4 (ToC and figure-list columns, house number, the `1` of
`13)`, tariff and subsidy cells, a lone `0`, `entamée de` / `3`, a paragraph number, a page number after a phrase that is kept, and
true page stamps that must still be removed: last line, first line) + 12 v3.4.1 (`CASES_V341`: the 10 content lines of the 5bc8 review,
each law row and article copy, and its 2 allowed removals, `42` in 8654 and the first-line `4` in e7ae art-0). The v3.4 case
`lu_page_stamp_mid_298a` expected the `70` after `signal C, 14 « limitation de vitesse »` removed, following the Verifier's 176b TSV;
the 5bc8 review shows it is the sign value, so in v3.4.1 that case expects it kept. v3.4.2 adds 5 real GR cases (`CASES_V342`):
the ToC page reference `26` after `......Σελ.` (4705-wjylweb), U+00AD bullet lines (4705-wchwweb art-19), the 4701-6sarwj2 art-18
copy normalized on its own, without its law row (`31`, a footnote number, removed when the copy is alone; renamed
`gr_art_copy_no_parent_4701` in v3.4.3), a page stamp after `..”.` that v3.4.2 keeps (`37`, 1201-9hkow10
art-30, its actual behaviour), and `&amp;` decoded to `&` (1201-6snzw10 art-0). 60 cases in v3.4.2; v3.4.1 code fails 3 of them. v3.4.3 adds 3 (`CASES_V343`, below): 63 in all.
Known limit of the test: raw and IR lines are aligned with difflib, which can misalign a long text whose paragraphs repeat with
different page stamps (GR 3701-ada-ctxdwji-l1d, 9,028 non-blank lines). There it reports lost lines and lost / invented breaks
that do not exist: the IR lines are an exact in-order subsequence of the raw lines, the 103 skipped raw lines are all lone
numbers the rule removes, and raw paragraphs with those lines dropped equal the IR paragraphs (2,077 = 2,077).
`--numrem RAW_REPO@REV|RAW_PACK_DIR` checks all 321 removals of the Verifier's `lu_ir_176b_numrem.tsv` (`CASES_V34_NUMREM`) against raw
LU `d9925146e7`: the 273 ToC / content lines must be kept, 17 `page` lines removed, 31 kept as recorded. It also checks the 32 rows of
`lu_ir_5bc8_numrem_review.tsv` (`CASES_V341_REVIEW`): 10 content kept, 4 ambiguous removed, 13 page stamps removed, 5 kept.
