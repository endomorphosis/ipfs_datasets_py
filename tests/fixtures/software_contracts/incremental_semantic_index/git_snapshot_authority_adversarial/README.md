# Git snapshot authority adversarial fixture

This fixture reserves the public-contract namespace for Git snapshot
authority probes.  The focused tests construct repositories, commits, staged
changes, conflicts, invalid-byte path names, and acquisition races at runtime
so the cases are portable across supported Git versions and do not inherit
machine-specific repository metadata.

The fixture intentionally contains no `.git` directory or precomputed object
identifiers: test setup is the authority for each adversarial repository.
