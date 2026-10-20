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

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=1 start=0 end=39 count=39
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T02-P01 US Code title 2 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=2 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T02-P02 US Code title 2 sections 1000:1609

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=2 start=1000 end=1609 count=609
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T03 US Code title 3 sections 0:64

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=3 start=0 end=64 count=64
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T04 US Code title 4 sections 0:47

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=4 start=0 end=47 count=47
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T05-P01 US Code title 5 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=5 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T05-P02 US Code title 5 sections 1000:1179

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=5 start=1000 end=1179 count=179
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T06 US Code title 6 sections 0:568

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=6 start=0 end=568 count=568
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T07-P01 US Code title 7 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=7 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T07-P02 US Code title 7 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=7 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T07-P03 US Code title 7 sections 2000:2925

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=7 start=2000 end=2925 count=925
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T08 US Code title 8 sections 0:360

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=8 start=0 end=360 count=360
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T09 US Code title 9 sections 0:33

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=9 start=0 end=33 count=33
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T10-P01 US Code title 10 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T10-P02 US Code title 10 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T10-P03 US Code title 10 sections 2000:3000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T10-P04 US Code title 10 sections 3000:3847

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=10 start=3000 end=3847 count=847
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T11 US Code title 11 sections 0:280

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=11 start=0 end=280 count=280
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T12-P01 US Code title 12 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=12 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T12-P02 US Code title 12 sections 1000:1980

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=12 start=1000 end=1980 count=980
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T13 US Code title 13 sections 0:70

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=13 start=0 end=70 count=70
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T14 US Code title 14 sections 0:417

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=14 start=0 end=417 count=417
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T15-P01 US Code title 15 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=15 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T15-P02 US Code title 15 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=15 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T15-P03 US Code title 15 sections 2000:2701

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=15 start=2000 end=2701 count=701
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T16-P01 US Code title 16 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T16-P02 US Code title 16 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T16-P03 US Code title 16 sections 2000:3000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T16-P04 US Code title 16 sections 3000:4000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=3000 end=4000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T16-P05 US Code title 16 sections 4000:5000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=4000 end=5000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T16-P06 US Code title 16 sections 5000:5090

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=16 start=5000 end=5090 count=90
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T17 US Code title 17 sections 0:153

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=17 start=0 end=153 count=153
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T18-P01 US Code title 18 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=18 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T18-P02 US Code title 18 sections 1000:1424

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=18 start=1000 end=1424 count=424
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T19-P01 US Code title 19 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=19 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T19-P02 US Code title 19 sections 1000:1111

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=19 start=1000 end=1111 count=111
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T20-P01 US Code title 20 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=20 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T20-P02 US Code title 20 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=20 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T20-P03 US Code title 20 sections 2000:2031

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=20 start=2000 end=2031 count=31
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T21 US Code title 21 sections 0:756

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=21 start=0 end=756 count=756
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T22-P01 US Code title 22 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T22-P02 US Code title 22 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T22-P03 US Code title 22 sections 2000:3000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=2000 end=3000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T22-P04 US Code title 22 sections 3000:3452

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=22 start=3000 end=3452 count=452
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T23 US Code title 23 sections 0:172

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=23 start=0 end=172 count=172
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T24 US Code title 24 sections 0:162

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=24 start=0 end=162 count=162
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T25-P01 US Code title 25 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=25 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T25-P02 US Code title 25 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=25 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T25-P03 US Code title 25 sections 2000:2396

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=25 start=2000 end=2396 count=396
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T26-P02 US Code title 26 sections 1000:2000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=26 start=1000 end=2000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T26-P03 US Code title 26 sections 2000:2142

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=26 start=2000 end=2142 count=142
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T27 US Code title 27 sections 0:45

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=27 start=0 end=45 count=45
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T28 US Code title 28 sections 0:808

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=28 start=0 end=808 count=808
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T32 US Code title 32 sections 0:77

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=32 start=0 end=77 count=77
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T36-P01 US Code title 36 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=36 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T38-P01 US Code title 38 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=38 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-USC-T38-P02 US Code title 38 sections 1000:1195

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=38 start=1000 end=1195 count=195
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T40 US Code title 40 sections 0:459

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=40 start=0 end=459 count=459
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T42-P01 US Code title 42 sections 0:1000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=0 end=1000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-USC-T42-P08 US Code title 42 sections 7000:8000

- status: todo
- goal id: LIRAE-USC
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: title=42 start=7000 end=8000 count=1000
- acceptance: Each section gets a span row or an explicit abstain; Entity rows cite those span ids; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-CONST-PREAMBLE Constitution Preamble span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A1 Constitution Article 1 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A2 Constitution Article 2 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A3 Constitution Article 3 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A4 Constitution Article 4 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A5 Constitution Article 5 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A6 Constitution Article 6 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-A7 Constitution Article 7 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM01 Constitution Amendment 1 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM02 Constitution Amendment 2 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM03 Constitution Amendment 3 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM04 Constitution Amendment 4 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM05 Constitution Amendment 5 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM06 Constitution Amendment 6 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM07 Constitution Amendment 7 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM08 Constitution Amendment 8 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM09 Constitution Amendment 9 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM10 Constitution Amendment 10 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM11 Constitution Amendment 11 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM12 Constitution Amendment 12 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM13 Constitution Amendment 13 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM14 Constitution Amendment 14 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM15 Constitution Amendment 15 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM16 Constitution Amendment 16 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM17 Constitution Amendment 17 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM18 Constitution Amendment 18 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM19 Constitution Amendment 19 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM20 Constitution Amendment 20 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM21 Constitution Amendment 21 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false; The repeal stays a fixture and is not sent as an obligation
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM22 Constitution Amendment 22 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM23 Constitution Amendment 23 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM24 Constitution Amendment 24 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM25 Constitution Amendment 25 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM26 Constitution Amendment 26 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

## LIRAE-CONST-AM27 Constitution Amendment 27 span inventory

- status: todo
- goal id: LIRAE-CONST
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: Spans come from the existing constitution inventory; roundtrip_ok stays false; admitted and formalized stay false
- completion: manual
- priority: P1
- track: legal-ir

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

## LIRAE-METHOD-01 Reconfirm the born-alive template test

- status: todo
- goal id: LIRAE-METHOD
- depends on: none
- board namespace: legal-ir-autoencoder-v1
- shard: none
- acceptance: lake_ok true; admitted false; formalized false
- validation: IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest tests/unit/logic/autoformal/test_uscode_born_alive_definition_v1.py -q --tb=line
- completion: manual
- priority: P1
- track: legal-ir
