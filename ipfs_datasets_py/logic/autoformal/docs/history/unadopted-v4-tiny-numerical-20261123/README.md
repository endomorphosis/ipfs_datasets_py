# Unadopted V4 numerical proposal

This folder preserves an authored private candidate that was not adopted or executed. Its original bytes and SHA256 are recorded in the descriptor. The `.py.proposal.txt` suffix prevents normal Python or pytest discovery.

The proposal adds a V4 helper branch and a tiny optimizer/restore/RNG/mask/ranking test for step counts 0 and 3, including bounded runtime-origin recording. It does not establish producer-linked embeddings, model quality, convergence, or legal correctness.

Do not replace the current owning test module with this historical file: it lacks the subsequently preserved `test_reviewed_v4_source_query_preparation_retains_authenticated_context_set` regression. Any future integration must preserve that regression, refresh actual preimages and dependencies, and use the existing admission and resource owners before execution. The earlier required pre-fix RED and all qualification limits remain distinct; this archive supplies no execution permission.
