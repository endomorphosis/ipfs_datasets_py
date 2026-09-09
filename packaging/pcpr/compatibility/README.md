# PCPR-056 Datasets portfolio compatibility lock binding

These files bind Datasets to the one declared
proof-carrying-platform-0.1.0 portfolio compatibility lock owned by
Accelerate. They do not remint that lock, do not import sibling packages,
and do not re-encode identities.

The core `setup.py` install_requires set is empty; that empty set is the
Datasets release profile, not an omission. This binding is not a live
signed manifest, not a freeze, not a published wheel or sdist, and not a
closed PCPR release.

- `cpython312/release.binding.json` pins lock CID
  `baguqeerawsekbbbt5ccctjt4tydzeahfkahsatb6q5x7k6cy4inrii5lhqmq`.
  Exact commit and tree are bound by the PCPR-056 receipt
  `current_tree_binding`. `origin/main` is not the release identity.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
