# Canonical CID memo qualification

All 63 focused tests passed on the final producer after reboot. The 4096-entry caches preserve exact identities, original validation errors, live registration/profile bindings, body rehashing and CAS tamper/deletion checks. They retain only small digest encodings or validated native strings. Observed registry drift during a miss cannot populate an earlier registration key.

The reviewed multiformats 0.3.1 native dictionary path avoids repeated generic argument validation while rereading current registry bindings. Getter, class, property, code and version changes select the public API fallback; missing raw entries retain JIT registration. The 30 memo tests include these controls and the previous hit/miss drift cases.

The first pre-restart run had 48 passes and one missing optional fixture; its logs are retained. The final pre-restart run was interrupted and is not counted. The initial post-restart producer passed 53 tests and has separate source/timing evidence. The final 63-test producer has its own frozen sources and four alternating warm timing pairs, each with 1024 body digests and identical hashed byte counts. These microbenchmarks are not official benchmark results or end-to-end speedup claims.
