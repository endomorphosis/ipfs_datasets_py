# Git snapshot truth fixture

Commit these files after configuring `filter.semantic-index-fixture` with a
clean transform from `smudged` to `indexed` and a smudge transform in the
opposite direction.  The committed blob is the source of truth; a clean
worktree may display the smudged form.
