# LexML place mapping review (2026-10-10, round 11)

Reported: all 1,103 (now 1,153) staged LexML docs map to one place (wd:Q381733 Uberaba-MG).

Finding: those docs were correctly mapped. Every row has URN `urn:lex:br;minas.gerais;uberaba:...`,
lexml_localidade "Uberaba - MG", and IBGE code 3170107. No re-emit was needed, and no finished file was touched.
The single-place result came from the queue: it walked the sitemap in order, and the sitemap starts with
Uberaba's ~11.9k URNs.

Latent bugs found and fixed in lexml.py (backup: _lexml.bak_pre_slugfix.py):
1. LexML slugs drop Portuguese connectives (rio.grande.sul, caxias.sul, sao.joao.boa.vista), but the Wikidata key
   kept them (rio.grande.do.sul;caxias.do.sul). As a result every RS/RJ/RN/MS locality and every municipality with
   de/da/do/dos/das/e in its name would have gone to _unmatched. Fix: ns() strips the connectives on both sides.
2. Some wd_P1585.csv labels are non-Portuguese ('Uruguayana', 'Yaguarón', 'Manaos', 'Q4035'), or carry a
   disambiguator ('Palmas (Paraná)'). Fix: strip the parenthetical, use a guarded same-state difflib match
   (>=0.85, margin 0.05), and add an IBGE-code alias table for 4 cases. Slug collisions between two different
   IBGE codes are dropped, never guessed.
   Result: 3,977 of 3,997 sitemap municipal localities map (99.5%); the 20 unmatched hold 1,623 URNs and go to _unmatched/BR.
3. Queue is now round-robin across localities, so coverage spreads over places.
4. flush_all() reset the 900 s timer on every non-forced call, so a forced flush never fired. With a round-robin
   queue, nothing would have been written until each place reached 50 rows. Fix: only a forced flush resets the timer.
