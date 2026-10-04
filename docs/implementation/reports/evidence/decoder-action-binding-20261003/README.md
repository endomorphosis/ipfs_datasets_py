# Action-binding decoder evidence

The complete `evidence.tar.xz` is 106,911,344 bytes. Git stores it as three ordered byte chunks so every part is at most 48 MB. No model, state, prediction, failed review, or training-pair evidence was removed.

After retrieving the three parts from this exact commit, reconstruct the logical archive named in the main decoder documentation:

```sh
cat evidence.tar.xz.part-001 evidence.tar.xz.part-002 evidence.tar.xz.part-003 > evidence.tar.xz
sha256sum evidence.tar.xz
```

The complete SHA-256 must be `1830569d1c79cfdd897531655ba3283799edf9da0f5891347cf8bbb82f487ec6`. Check the total bytes and each ordered part's SHA-256/offset against `manifest.json` before extracting. Its member hashes and original-path mapping describe the complete archive; inherited artifacts use the declared exact Git archive dependencies.

The archived builder correctly stopped at its original 95 MB single-file publication guard. `finalize_chunked_evidence.py` authenticates that exact builder and archive, keeps its original data/source/audit/resource verification, and publishes the physical chunks instead. It does not rerun or alter training. `publish_chunked.py` verifies the concatenated staged Git blobs and every tar member before creating a commit. These publication-only support files are hash-bound in the manifest.

This is unqualified development evidence: 18 fits, 54 states and 288 panels. All runs retained epoch 0 under unchanged gates. No Lake admission or production checkpoint is granted.
