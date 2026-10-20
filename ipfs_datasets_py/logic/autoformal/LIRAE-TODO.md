# LegalIR autoencoder supervisor board

Full US Code (60077 sections, revision 5016b86a273ce5e4ffd066c5ae9f5fe494dd417e) and the Constitution inventory.
admitted and formalized stay false. Constitution roundtrip_ok stays false.

## Goal LIRAE-ROOT

- status: goal
- title: Autoformalize the full US Code and the US Constitution
- goal id: LIRAE-ROOT
- parent goal id: none
- acceptance: Every pinned section and constitution span has a span row or an explicit abstain; admitted and formalized stay false on every row; lake build Legal is the only Lean check

## Goal LIRAE-USC

- status: goal
- title: Autoformalize all 60077 ipfs_uscode sections by title shard
- goal id: LIRAE-USC
- parent goal id: LIRAE-ROOT
- acceptance: Shards cover every section exactly once; No shard sets admitted or formalized

## Goal LIRAE-CONST

- status: goal
- title: Inventory and project every Constitution span without admission
- goal id: LIRAE-CONST
- parent goal id: LIRAE-ROOT
- acceptance: roundtrip_ok stays false on every constitution span; The Twenty-First Amendment repeal stays a fixture

## Goal LIRAE-WIDTH

- status: goal
- title: Compare 8d, 384d, 768d, and 4096d on the method sample only
- goal id: LIRAE-WIDTH
- parent goal id: LIRAE-ROOT
- acceptance: Full-corpus passes use the 384d profile; No encoder retraining

## Goal LIRAE-METHOD

- status: goal
- title: Keep the pinned born-alive path as the shard template
- goal id: LIRAE-METHOD
- parent goal id: LIRAE-ROOT
- acceptance: 1 USC 8 and 10 USC 1059 hashes stay pinned; The template test still passes

## LIRAE-USC-T01 US Code title 1 sections 0:39

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=1 start=0 end=39 count=39
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T02-P01 US Code title 2 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=2 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T02-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T02-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T02-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T02-P02 US Code title 2 sections 1000:1609

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=2 start=1000 end=1609 count=609
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T02-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T02-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T02-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t02-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T03 US Code title 3 sections 0:64

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=3 start=0 end=64 count=64
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T04 US Code title 4 sections 0:47

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=4 start=0 end=47 count=47
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t04/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t04, ipfs_datasets_py/logic/autoformal/entity_cache.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, ipfs_datasets_py/logic/autoformal/span_cache_exchange.py, ipfs_datasets_py/logic/autoformal/uscode_ingest.py, tests/unit/logic/test_entity_cache.py, tests/unit/logic/test_paired_span_census.py, tests/unit/logic/test_span_cache_exchange.py, tests/unit/logic/test_uscode_ingest.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t04/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T04 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T04

## LIRAE-USC-T05-P01 US Code title 5 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=5 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T05-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T05-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T05-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T05-P02 US Code title 5 sections 1000:1179

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=5 start=1000 end=1179 count=179
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p02/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p02, ipfs_datasets_py/logic/autoformal/entity_cache.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, ipfs_datasets_py/logic/autoformal/span_cache_exchange.py, ipfs_datasets_py/logic/autoformal/uscode_ingest.py, tests/unit/logic/test_entity_cache.py, tests/unit/logic/test_paired_span_census.py, tests/unit/logic/test_span_cache_exchange.py, tests/unit/logic/test_uscode_ingest.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t05-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T05-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T05-P02

## LIRAE-USC-T06 US Code title 6 sections 0:568

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=6 start=0 end=568 count=568
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T06 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T06 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T06
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t06/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T07-P01 US Code title 7 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=7 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T07-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T07-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T07-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T07-P02 US Code title 7 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=7 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T07-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T07-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T07-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T07-P03 US Code title 7 sections 2000:2925

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=7 start=2000 end=2925 count=925
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T07-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T07-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T07-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t07-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T08 US Code title 8 sections 0:360

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=8 start=0 end=360 count=360
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T08 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T08 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T08
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t08/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T09 US Code title 9 sections 0:33

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=9 start=0 end=33 count=33
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T09 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T09 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T09
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t09/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T10-P01 US Code title 10 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T10-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T10-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T10-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T10-P02 US Code title 10 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T10-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T10-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T10-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T10-P03 US Code title 10 sections 2000:3000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T10-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T10-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T10-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T10-P04 US Code title 10 sections 3000:3847

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=3000 end=3847 count=847
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T10-P04 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T10-P04 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T10-P04
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t10-p04/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T11 US Code title 11 sections 0:280

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=11 start=0 end=280 count=280
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T11 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T11 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T11
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t11/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T12-P01 US Code title 12 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=12 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T12-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T12-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T12-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T12-P02 US Code title 12 sections 1000:1980

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=12 start=1000 end=1980 count=980
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T12-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T12-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T12-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t12-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T13 US Code title 13 sections 0:70

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=13 start=0 end=70 count=70
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T13 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T13 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T13
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t13/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T14 US Code title 14 sections 0:417

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=14 start=0 end=417 count=417
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T14 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T14 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T14
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t14/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T15-P01 US Code title 15 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=15 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T15-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T15-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T15-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T15-P02 US Code title 15 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=15 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T15-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T15-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T15-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T15-P03 US Code title 15 sections 2000:2701

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=15 start=2000 end=2701 count=701
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T15-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T15-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T15-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t15-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T16-P01 US Code title 16 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T16-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T16-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T16-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T16-P02 US Code title 16 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T16-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T16-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T16-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T16-P03 US Code title 16 sections 2000:3000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T16-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T16-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T16-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T16-P04 US Code title 16 sections 3000:4000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=3000 end=4000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T16-P04 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T16-P04 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T16-P04
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p04/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T16-P05 US Code title 16 sections 4000:5000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=4000 end=5000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T16-P05 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T16-P05 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T16-P05
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p05/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T16-P06 US Code title 16 sections 5000:5090

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=5000 end=5090 count=90
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T16-P06 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T16-P06 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T16-P06
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t16-p06/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T17 US Code title 17 sections 0:153

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=17 start=0 end=153 count=153
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T17 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T17 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T17
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t17/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T18-P01 US Code title 18 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=18 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T18-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T18-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T18-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T18-P02 US Code title 18 sections 1000:1424

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=18 start=1000 end=1424 count=424
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T18-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T18-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T18-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t18-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T19-P01 US Code title 19 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=19 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T19-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T19-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T19-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T19-P02 US Code title 19 sections 1000:1111

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=19 start=1000 end=1111 count=111
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T19-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T19-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T19-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t19-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T20-P01 US Code title 20 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=20 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T20-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T20-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T20-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T20-P02 US Code title 20 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=20 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T20-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T20-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T20-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T20-P03 US Code title 20 sections 2000:2031

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=20 start=2000 end=2031 count=31
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T20-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T20-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T20-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t20-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T21 US Code title 21 sections 0:756

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=21 start=0 end=756 count=756
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T21 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T21 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T21
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t21/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T22-P01 US Code title 22 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T22-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T22-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T22-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T22-P02 US Code title 22 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T22-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T22-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T22-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T22-P03 US Code title 22 sections 2000:3000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T22-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T22-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T22-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T22-P04 US Code title 22 sections 3000:3452

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=3000 end=3452 count=452
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T22-P04 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T22-P04 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T22-P04
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t22-p04/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T23 US Code title 23 sections 0:172

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=23 start=0 end=172 count=172
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T23 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T23 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T23
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t23/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T24 US Code title 24 sections 0:162

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=24 start=0 end=162 count=162
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T24 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T24 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T24
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t24/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T25-P01 US Code title 25 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=25 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T25-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T25-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T25-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T25-P02 US Code title 25 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=25 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T25-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T25-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T25-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T25-P03 US Code title 25 sections 2000:2396

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=25 start=2000 end=2396 count=396
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T25-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T25-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T25-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t25-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T26-P01 US Code title 26 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=26 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T26-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T26-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T26-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T26-P02 US Code title 26 sections 1000:2000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=26 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T26-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T26-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T26-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T26-P03 US Code title 26 sections 2000:2142

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=26 start=2000 end=2142 count=142
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T26-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T26-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T26-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t26-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T27 US Code title 27 sections 0:45

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=27 start=0 end=45 count=45
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T27 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T27 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T27
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t27/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T28 US Code title 28 sections 0:808

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=28 start=0 end=808 count=808
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T28 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T28 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T28
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t28/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T29 US Code title 29 sections 0:842

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=29 start=0 end=842 count=842
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T29 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T29 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T29
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t29/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T30 US Code title 30 sections 0:626

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=30 start=0 end=626 count=626
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T30 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T30 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T30
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t30/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T31 US Code title 31 sections 0:498

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=31 start=0 end=498 count=498
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T31 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T31 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T31
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t31/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T32 US Code title 32 sections 0:77

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=32 start=0 end=77 count=77
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T32 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T32 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T32
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t32/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T33-P01 US Code title 33 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=33 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T33-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T33-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T33-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T33-P02 US Code title 33 sections 1000:1565

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=33 start=1000 end=1565 count=565
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T33-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T33-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T33-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t33-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T34 US Code title 34 sections 0:793

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=34 start=0 end=793 count=793
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T34 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T34 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T34
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t34/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T35 US Code title 35 sections 0:175

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=35 start=0 end=175 count=175
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T35 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T35 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T35
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t35/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T36-P01 US Code title 36 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=36 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T36-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T36-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T36-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T36-P02 US Code title 36 sections 1000:1173

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=36 start=1000 end=1173 count=173
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T36-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T36-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T36-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t36-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T37 US Code title 37 sections 0:233

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=37 start=0 end=233 count=233
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T37 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T37 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T37
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t37/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T38-P01 US Code title 38 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=38 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T38-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T38-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T38-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T38-P02 US Code title 38 sections 1000:1195

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=38 start=1000 end=1195 count=195
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T38-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T38-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T38-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t38-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T39 US Code title 39 sections 0:181

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=39 start=0 end=181 count=181
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T39 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T39 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T39
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t39/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T40 US Code title 40 sections 0:459

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=40 start=0 end=459 count=459
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T40 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T40 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T40
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t40/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T41 US Code title 41 sections 0:241

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=41 start=0 end=241 count=241
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T41 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T41 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T41
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t41/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P01 US Code title 42 sections 0:1000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P02 US Code title 42 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P03 US Code title 42 sections 2000:3000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P03 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P03 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P03
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p03/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P04 US Code title 42 sections 3000:4000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=3000 end=4000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P04 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P04 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P04
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p04/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P05 US Code title 42 sections 4000:5000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=4000 end=5000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P05 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P05 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P05
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p05/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P06 US Code title 42 sections 5000:6000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=5000 end=6000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P06 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P06 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P06
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p06/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P07 US Code title 42 sections 6000:7000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=6000 end=7000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P07 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P07 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P07
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p07/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P08 US Code title 42 sections 7000:8000

- status: completed
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=7000 end=8000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P08 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P08 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P08
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p08/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T42-P09 US Code title 42 sections 8000:8443

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=8000 end=8443 count=443
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T42-P09 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T42-P09 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T42-P09
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t42-p09/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T43-P01 US Code title 43 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=43 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T43-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T43-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T43-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T43-P02 US Code title 43 sections 1000:1461

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=43 start=1000 end=1461 count=461
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T43-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T43-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T43-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t43-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T44 US Code title 44 sections 0:349

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=44 start=0 end=349 count=349
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T44 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T44 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T44
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t44/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T45 US Code title 45 sections 0:294

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=45 start=0 end=294 count=294
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T45 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T45 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T45
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t45/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T46 US Code title 46 sections 0:997

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=46 start=0 end=997 count=997
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T46 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T46 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T46
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t46/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T47 US Code title 47 sections 0:431

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=47 start=0 end=431 count=431
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T47 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T47 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T47
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t47/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T48 US Code title 48 sections 0:661

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=48 start=0 end=661 count=661
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T48 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T48 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T48
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t48/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T49-P01 US Code title 49 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=49 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T49-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T49-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T49-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T49-P02 US Code title 49 sections 1000:1314

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=49 start=1000 end=1314 count=314
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T49-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T49-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T49-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t49-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T50-P01 US Code title 50 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=50 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T50-P01 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T50-P01 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T50-P01
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p01/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T50-P02 US Code title 50 sections 1000:1420

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=50 start=1000 end=1420 count=420
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T50-P02 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T50-P02 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T50-P02
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t50-p02/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T51 US Code title 51 sections 0:245

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=51 start=0 end=245 count=245
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T51 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T51 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T51
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t51/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T52 US Code title 52 sections 0:171

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=52 start=0 end=171 count=171
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T52 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T52 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T52
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t52/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-T54 US Code title 54 sections 0:363

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=54 start=0 end=363 count=363
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-T54 task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-T54 && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-T54
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-t54/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-USC-TNA US Code title NA sections 0:9

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=NA start=0 end=9 count=9
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/sections.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/spans.zip, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/entities.zip
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-USC-TNA task_kind=uscode status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. source={repository:justicedao/ipfs_uscode,revision:5016b86a273ce5e4ffd066c5ae9f5fe494dd417e}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache. Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_uscode_ingest.py tests/unit/logic/test_span_cache_exchange.py tests/unit/logic/test_paired_span_census.py tests/unit/logic/test_entity_cache.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-USC-TNA && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-USC-TNA
- provider role: deterministic-only
- context budget tokens: 0
- proposal artifact envelope: {"binary_paths":["docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/sections.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/spans.zip","docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-usc-tna/entities.zip"],"max_file_bytes":8000000,"max_output_bytes":24000000,"max_patch_bytes":16000000,"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}

## LIRAE-CONST-PREAMBLE Constitution Preamble span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-preamble/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-preamble, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-preamble/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-PREAMBLE task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=preamble; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-PREAMBLE

## LIRAE-CONST-A1 Constitution Article 1 span inventory

- Status: completed
- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a1/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a1, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a1/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A1 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-1; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A1

## LIRAE-CONST-A2 Constitution Article 2 span inventory

- Status: completed
- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a2/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a2, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a2/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A2 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-2; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A2

## LIRAE-CONST-A3 Constitution Article 3 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a3/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a3, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a3/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A3 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-3; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A3

## LIRAE-CONST-A4 Constitution Article 4 span inventory

- Status: completed
- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a4/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a4, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a4/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A4 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-4; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A4

## LIRAE-CONST-A5 Constitution Article 5 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a5/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a5, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a5/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A5 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-5; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A5

## LIRAE-CONST-A6 Constitution Article 6 span inventory

- Status: completed
- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a6/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a6, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a6/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A6 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-6; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A6

## LIRAE-CONST-A7 Constitution Article 7 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a7/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a7, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-a7/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-A7 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=art-7; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-A7

## LIRAE-CONST-AM01 Constitution Amendment 1 span inventory

- Status: completed
- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am01/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am01, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM01 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-1; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM01

## LIRAE-CONST-AM02 Constitution Amendment 2 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am02/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am02, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am02/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM02 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-2; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM02

## LIRAE-CONST-AM03 Constitution Amendment 3 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am03/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am03, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am03/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM03 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-3; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM03

## LIRAE-CONST-AM04 Constitution Amendment 4 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am04/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am04, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am04/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM04 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-4; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM04

## LIRAE-CONST-AM05 Constitution Amendment 5 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am05/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am05, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am05/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM05 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-5; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM05

## LIRAE-CONST-AM06 Constitution Amendment 6 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am06/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am06, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am06/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM06 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-6; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM06

## LIRAE-CONST-AM07 Constitution Amendment 7 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am07/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am07, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am07/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM07 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-7; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM07

## LIRAE-CONST-AM08 Constitution Amendment 8 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am08/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am08, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am08/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM08 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-8; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM08

## LIRAE-CONST-AM09 Constitution Amendment 9 span inventory

- Status: completed
- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am09/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am09, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am09/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM09 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-9; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM09

## LIRAE-CONST-AM10 Constitution Amendment 10 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am10/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am10, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am10/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM10 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-10; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM10

## LIRAE-CONST-AM11 Constitution Amendment 11 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am11/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am11, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am11/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM11 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-11; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM11

## LIRAE-CONST-AM12 Constitution Amendment 12 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am12/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am12, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am12/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM12 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-12; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM12

## LIRAE-CONST-AM13 Constitution Amendment 13 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am13/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am13, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am13/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM13 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-13; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM13

## LIRAE-CONST-AM14 Constitution Amendment 14 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am14/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am14, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am14/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM14 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-14; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM14

## LIRAE-CONST-AM15 Constitution Amendment 15 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am15/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am15, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am15/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM15 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-15; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM15

## LIRAE-CONST-AM16 Constitution Amendment 16 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am16/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am16, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am16/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM16 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-16; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM16

## LIRAE-CONST-AM17 Constitution Amendment 17 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am17/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am17, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am17/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM17 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-17; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM17

## LIRAE-CONST-AM18 Constitution Amendment 18 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am18/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am18, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am18/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM18 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-18; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM18

## LIRAE-CONST-AM19 Constitution Amendment 19 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am19/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am19, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am19/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM19 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-19; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM19

## LIRAE-CONST-AM20 Constitution Amendment 20 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am20/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am20, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am20/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM20 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-20; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM20

## LIRAE-CONST-AM21 Constitution Amendment 21 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false; The repeal stays a fixture and is not sent as an obligation
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am21/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am21, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am21/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM21 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-21; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM21

## LIRAE-CONST-AM22 Constitution Amendment 22 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am22/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am22, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am22/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM22 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-22; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM22

## LIRAE-CONST-AM23 Constitution Amendment 23 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am23/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am23, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am23/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM23 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-23; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM23

## LIRAE-CONST-AM24 Constitution Amendment 24 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am24/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am24, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am24/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM24 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-24; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM24

## LIRAE-CONST-AM25 Constitution Amendment 25 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am25/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am25, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am25/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM25 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-25; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM25

## LIRAE-CONST-AM26 Constitution Amendment 26 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am26/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am26, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am26/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM26 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-26; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM26

## LIRAE-CONST-AM27 Constitution Amendment 27 span inventory

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am27/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am27, ipfs_datasets_py/logic/autoformal/constitution_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_shard_inventory.py, ipfs_datasets_py/logic/autoformal/constitution_unit_projection.py, ipfs_datasets_py/logic/autoformal/paired_span_census.py, tests/unit/logic/test_constitution_article_1_inventory.py, tests/unit/logic/test_constitution_inventory.py, tests/unit/logic/test_paired_span_census.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-am27/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-AM27 task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=amend-27; Amendment21 requires repeal_treated_as_obligation=false.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-AM27

## LIRAE-WIDTH-08 Reuse the 8d donor on the born-alive sample

- status: todo
- goal id: LIRAE-WIDTH
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: No new 8d training run; Donor is not the corpus profile
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-08/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-08, ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_dimensions.py, tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py, tests/unit/logic/test_paired_span_census.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_dimensions.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-08/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-WIDTH-08 task_kind=width status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. JSON observation artifact carries dimension,source_hashes for both born-alive inputs,profile_id,checkpoint_sha256,status=observed,training_executed=false,admitted=false,formalized=false,metrics={cosine_similarity,reconstruction_loss}. Retain actual checkpoint artifact kind checkpoint and replay evidence; hashes/metrics alone are insufficient. The required source-bound replay capability is currently unavailable: retain a blocked-input diagnostic, never claim this task completed from unavailable inventory or a different authored cohort. evidence.dimension matches. 8d role=donor corpus_default=false;384d corpus_default=true;768d token_ceiling=512;4096d encoder_executed=false development_result={successful:0,total:12}.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py tests/unit/logic/test_paired_span_census.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_dimensions.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-WIDTH-08
- required validation executables: legal-ir-born-alive-width-replay-v1

## LIRAE-WIDTH-384 Score the born-alive sample with the 384d profile

- status: todo
- goal id: LIRAE-WIDTH
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Record cosine and reconstruction loss; This profile is the later full-corpus default
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-384/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-384, ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_dimensions.py, tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py, tests/unit/logic/test_paired_span_census.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_dimensions.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-384/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-WIDTH-384 task_kind=width status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. JSON observation artifact carries dimension,source_hashes for both born-alive inputs,profile_id,checkpoint_sha256,status=observed,training_executed=false,admitted=false,formalized=false,metrics={cosine_similarity,reconstruction_loss}. Retain actual checkpoint artifact kind checkpoint and replay evidence; hashes/metrics alone are insufficient. The required source-bound replay capability is currently unavailable: retain a blocked-input diagnostic, never claim this task completed from unavailable inventory or a different authored cohort. evidence.dimension matches. 8d role=donor corpus_default=false;384d corpus_default=true;768d token_ceiling=512;4096d encoder_executed=false development_result={successful:0,total:12}.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py tests/unit/logic/test_paired_span_census.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_dimensions.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-WIDTH-384
- required validation executables: legal-ir-born-alive-width-replay-v1

## LIRAE-WIDTH-768 Pair 768d on the same born-alive sample

- status: todo
- goal id: LIRAE-WIDTH
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Same source access as the 384d run; 512-token ceiling stays recorded
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-768/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-768, ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_dimensions.py, tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py, tests/unit/logic/test_paired_span_census.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_dimensions.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-768/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-WIDTH-768 task_kind=width status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. JSON observation artifact carries dimension,source_hashes for both born-alive inputs,profile_id,checkpoint_sha256,status=observed,training_executed=false,admitted=false,formalized=false,metrics={cosine_similarity,reconstruction_loss}. Retain actual checkpoint artifact kind checkpoint and replay evidence; hashes/metrics alone are insufficient. The required source-bound replay capability is currently unavailable: retain a blocked-input diagnostic, never claim this task completed from unavailable inventory or a different authored cohort. evidence.dimension matches. 8d role=donor corpus_default=false;384d corpus_default=true;768d token_ceiling=512;4096d encoder_executed=false development_result={successful:0,total:12}.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py tests/unit/logic/test_paired_span_census.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_dimensions.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-WIDTH-768
- required validation executables: legal-ir-born-alive-width-replay-v1

## LIRAE-WIDTH-4096 Reuse saved Leanstral 4096 vectors on the sample

- status: todo
- goal id: LIRAE-WIDTH
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: No encoder execution; The 0/12 development result stays attached
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-4096/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-4096, ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_4096.py, tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py, tests/unit/logic/test_paired_span_census.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_4096.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-4096/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-WIDTH-4096 task_kind=width status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. JSON observation artifact carries dimension,source_hashes for both born-alive inputs,profile_id,checkpoint_sha256,status=observed,training_executed=false,admitted=false,formalized=false,metrics={cosine_similarity,reconstruction_loss}. Retain actual checkpoint artifact kind checkpoint and replay evidence; hashes/metrics alone are insufficient. The required source-bound replay capability is currently unavailable: retain a blocked-input diagnostic, never claim this task completed from unavailable inventory or a different authored cohort. evidence.dimension matches. 8d role=donor corpus_default=false;384d corpus_default=true;768d token_ceiling=512;4096d encoder_executed=false development_result={successful:0,total:12}.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py tests/unit/logic/test_paired_span_census.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_4096.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-WIDTH-4096
- required validation executables: legal-ir-born-alive-width-replay-v1

## LIRAE-METHOD-01 Reconfirm the born-alive template test

- status: completed
- goal id: LIRAE-METHOD
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: lake_ok true; admitted false; formalized false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-method-01/receipt.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-method-01, ipfs_datasets_py/logic/autoformal/lean_units.py, ipfs_datasets_py/logic/autoformal/legal_source_definition_bridge_v2.py, tests/unit/logic/autoformal/test_uscode_born_alive_definition_v1.py, tests/unit/logic/test_lean_units.py
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-method-01/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-METHOD-01 task_kind=method status=inventory|implemented authority={admitted:false,formalized:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. lean_source artifact holds actual Lean source. evidence includes both pinned source_hashes; host sealed validator supplies lake_ok by running real lake build Legal with the trusted deployed toolchain. Do not invent a provider-side compiler observation. Skipped pinned-source tests supply no completion evidence.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/autoformal/test_uscode_born_alive_definition_v1.py tests/unit/logic/test_lean_units.py -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-METHOD-01
- required validation executables: lake, lean

## LIRAE-CONST-ANCILLARY Retain unassigned Constitution notes and signature spans

- status: completed
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- acceptance: Retain exactly 83 non-operative notes and signature spans from the pinned source inventory; Preserve exact source span IDs, plaintext, status and reason; admitted, formalized and roundtrip_ok remain false
- completion: manual
- priority: P1
- track: legal-ir
- outputs: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-ancillary/receipt.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-ancillary/source.json, docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-ancillary/spans.json
- allowed paths: docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-ancillary
- receipt instructions: Write docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-const-ancillary/receipt.json schema=legal-ir-supervisor-task-receipt/v1 task_id=LIRAE-CONST-ANCILLARY task_kind=constitution status=inventory|implemented authority={admitted:false,formalized:false,roundtrip_ok:false}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. Use exact retained plaintext docs/implementation/reports/evidence/legal_ir_autoencoder/inputs/constitution.txt, sha256=9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=ancillary; Amendment21 requires repeal_treated_as_obligation=false. Retain exactly the 83 source-derived non-operative note/signature rows omitted by the original 35 unit tasks. Preserve their actual status and reason. Independent tests and the protected checker remain mandatory; only native proposal/merge admission decides completion.
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/test_constitution_inventory.py tests/unit/logic/test_constitution_article_1_inventory.py tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution -q --tb=line; IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/materialize_legal_ir_inventory.py --task LIRAE-CONST-ANCILLARY && IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 scripts/ops/legal_ir/legal_ir_supervisor_contract.py --check-task LIRAE-CONST-ANCILLARY
- provider role: deterministic-only
- context budget tokens: 0
