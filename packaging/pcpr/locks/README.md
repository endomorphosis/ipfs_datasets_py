# PCPR-053 declared release-profile dependency locks

These files freeze the Datasets *release* profile. The core package is
dependency-free: `setup.py` `install_requires` is empty. That empty set is
the lock, not an omission.

- `cpython312/release.lock.json` is the canonical declared-spec lock.
- `cpython312/release.txt` is the pip-installable declared-spec list (empty).
- Hash and transitive resolution remain typed unavailable. Hashes are
  never invented.
- `requirements.txt` editable sibling pins are source-checkout development
  only and are not this release lock.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
Provider-local `~/.local` tools such as `uv` are not sealed-environment
authority.
