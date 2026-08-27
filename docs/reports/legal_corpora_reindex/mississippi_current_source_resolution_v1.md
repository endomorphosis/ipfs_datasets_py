# Mississippi current-source resolution v1

Observation date: 2026-08-26 UTC

## Outcome

Mississippi's authoritative current catalog source is now identified, but its
statute-body frontier is not acquired and the jurisdiction remains blocked for
materialization, indexing, or publication.

The Mississippi Legislature's home and help pages direct the public to the
LexisNexis Mississippi Code link.  The Mississippi Secretary of State's
Mississippi Law page independently describes its searchable *Unannotated
Mississippi Code* link as pointing to LexisNexis, the official publisher.  The
publisher entry redirects to the following exact free-public-access container:

```text
http://www.lexisnexis.com/hottopics/mscode/
https://advance.lexis.com/container?config=00JAAzNzhjOTYxNC0wZjRkLTQzNzAtYjJlYS1jNjExZWYxZGFhMGYKAFBvZENhdGFsb2cMlW40w5iIH7toHnTBIEP0
```

The old prospective route
`https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/`
returned HTTP 404 on the observation date.  Its 2025 and 2026 counterparts
also returned 404.  It is not a current Code root and remains only in legacy
parser fixtures.

This resolves the catalog authority question.  It does **not** authorize any
statute body: the audit intentionally opened no document page and retained no
new corpus artifact.

## Authority and scope

Primary delegation pages:

- `https://www.legislature.ms.gov/`
- `https://www.legislature.ms.gov/help/`
- `https://www.sos.ms.gov/publications-external-affairs/mississippi-law`
- delegated entry `http://www.lexisnexis.com/hottopics/mscode/`

The direct audit observed 56,402 rendered bytes for the Legislature home page
(diagnostic SHA-256 prefix `28b6ba2d…`) and 41,181 rendered bytes for its help
page (diagnostic SHA-256 prefix `77ea5e44…`).  Those observations established
the delegation but were not retained as authorizing parser inputs.  A future
authorizing ledger must therefore retain at least one exact Legislature
response containing the delegation, the publisher-entry redirect receipt, and
the delegated container response.  The Secretary of State page is independent
corroboration and should be retained when available, but it is not a substitute
for the Legislature-to-container chain.

The delegated container identifies itself as “Mississippi Code Of 1972
Unannotated - Free Public Access” and states that it is maintained by
LexisNexis.  The authority chain is therefore the State's designation of the
publisher's public, unannotated Code—not a claim that publisher presentation is
itself enacted law.

The admissible public-law scope is:

- enacted statutory section text;
- statutory section numbers and captions; and
- legislative histories attached to those sections.

Publisher annotations, case notes, arrangement, navigation, pricing/access
state, and visual presentation are outside the corpus.  They are excluded
because they are editorial or secondary content, not because Mississippi can
copyright its public laws.

The separately handled Mississippi Constitution, administrative rules, court
rules, session bills, and bill histories are not members of this Code-body
frontier.

## Exact delegated source identity

The source exposed these stable identifiers:

| Field | Exact value |
|---|---|
| container origin | `https://advance.lexis.com` |
| allowed container path | `/container` |
| stable container parameter | the exact `config` value above |
| permitted ephemeral parameters | one `crid` and one `prid` only |
| TOC pod/root | `6gf5kkk` |
| TOC endpoint | `/r/tocprovider/6gf5kkk/toc/6gf5kkk` |
| TOC URN | `/shared/tableofcontents/urn:contentItem:8S5T-PM12-D6RV-H00W-00008-00` |
| source ID | `urn:contentItem:csi:1091205` |
| source filter | `MTA5MTIwNQ` |
| document `pdmfid` | `1000516` |
| document config | `00JABhZDIzMTViZS04NjcxLTQ1MDItOTllOS03MDg0ZTQxYzU4ZTQKAFBvZENhdGFsb2f8inKxYiqNVSihJeNKRlUp` |
| results config | `0146JABiODViNTc0Yy01MGJlLTRjYTQtOWNhMy04MzAzODZhY2M2MzcKAFBvZENhdGFsb2fv1hcZRCKiV89wcvA448We` |
| current document path family | `/shared/document/statutes-legislation/urn:contentItem:…` |
| future-effectiveness path family | `/shared/document/fe/urn:contentItem:…` |

A stable document request is derived from the exact content-item path:

```text
https://advance.lexis.com/documentpage/?pdmfid=1000516&config=<document-config>&pddocfullpath=<exact-content-item-path>
```

Direct navigation to a document page triggered robot validation in this
environment.  No access control was bypassed.  The content-item paths remain
exact archive lookup and future browser-retrieval identities.

## Exact hierarchy and request membership

The rendered root contains exactly 51 source roots in this order:

- `AAB`: `Mississippi New Sections Added by Recent Legislation`;
- `AAC` through `AAZ`: Titles 1 through 47, odd numbers only; and
- `ABA` through `ABZ`: Titles 49 through 99, odd numbers only.

Thus the statutory catalog contains exactly 50 titles:

```text
1, 3, 5, 7, 9, 11, 13, 15, 17, 19,
21, 23, 25, 27, 29, 31, 33, 35, 37, 39,
41, 43, 45, 47, 49, 51, 53, 55, 57, 59,
61, 63, 65, 67, 69, 71, 73, 75, 77, 79,
81, 83, 85, 87, 89, 91, 93, 95, 97, 99
```

For each root, the UI advertises its supported `open-to` levels.  One PATCH at
the maximum advertised level returns that root's complete hierarchy.  The
exact catalog request set is therefore 51 source-native requests—not thousands
of node-by-node expansions:

```json
{
  "id": "6gf5kkk",
  "props": {
    "action": "open-to",
    "items": [
      {"fieldName": "nodeId", "value": "<one of AAB..ABZ>"},
      {"fieldName": "targetLevel", "value": "<source-advertised maximum>"}
    ]
  }
}
```

The adapter rejects a missing, inserted, reordered, duplicated, cross-title,
or orphaned node.  Lexis can serialize one identical node object in more than
one JSON collection; an exact semantic repeat is deduplicated, while any
conflicting ID/path reuse fails closed.

## Metadata-only live result

The final adapter-native replay observed the source at
`2026-08-26T01:33:48.867054+00:00`.  It did not retain response bytes and is
diagnostic rather than authorizing.

| Measure | Result |
|---|---:|
| root nodes | 51 |
| title roots | 50 |
| recent-legislation roots | 1 |
| complete `open-to` responses | 51 |
| descendant nodes | 33,600 |
| all nodes including roots | 33,651 |
| hierarchy, duplicate-ID, or cross-title residuals | 0 |
| full content-item locators | 30,430 |
| bare future structural placeholders | 2 |
| main-Code full locators | 30,415 |
| recent-legislation full locators | 15 |
| main current-path locators | 30,335 |
| main `/fe/` future-path locators | 80 |
| individually section-labeled main locators | 30,349 |
| unique main section identities | 30,172 |
| repeated section identities | 158 |
| extra variant locators | 177 |
| current section candidates | 30,270 |
| current multi-section collection candidates | 3 |
| current untyped document residuals | 3 |
| publisher/editorial structural documents | 59 |
| TOC frontier closed | yes |
| document bodies acquired | 0 |
| body/full-corpus frontier closed | no |

Adapter-native diagnostic hashes for that observation:

```text
root rendered bytes:        69710a43c4c9f0f37606e8aed41a1e4bc9c3e5ec8bf1b1c7baa664bffc3d2da7
51-response hash manifest:  7e84b255f0806dd18af7cba3a3ea8a2b06049ff025393c110d431859af85fc88
root semantic membership:   f5b4d0126272bd114e50a92f7dee937b543cb4ccb1181f73d6dc033f14849e69
all-node semantic members:  85bff81bbb5b3af648dabbb0832e6d5af108ea4079d806b91b6bc1be3fb6660c
main-document membership:   cfa917901e8e03f35986047051e4877a07ea5b3972afae54a9f81e03a2adfea3
```

The rendered root and raw TOC JSON contain session-local fields and changed
hash across diagnostic runs.  A future authorizing run must retain every exact
raw response while separately binding the stable semantic membership.  It
must not require raw bytes from two distinct observations to be identical.

## Legal-as-of and variant semantics

The old catalog-first artifact claimed `legal_as_of=2026-07-01` without source
support.  That date must not be reused.

The new source contract uses the observation timestamp as the catalog's
legal-as-of boundary and applies source-native temporal typing:

1. `/shared/document/statutes-legislation/…` is a current-path candidate, not
   by itself a finally admitted statute body.
2. `/shared/document/fe/…` is a future-effectiveness exclusion for this
   observation.  There are 80 full future paths and two structural placeholder
   paths.
3. Labels such as “Effective until …”, “Effective …”, and “Repealed effective
   …” constrain selection at the observation date.
4. All variants for a repeated current citation remain unresolved until their
   exact bodies and any required source-effective-date material are retained.
5. The 15 recent-legislation documents are current-source members but are not
   assumed to have stable Code identities from weak labels such as “§ 1. Needs
   catchline”.  Their bodies must establish the enacted section identity.

The live source proves 158 repeated main citation identities with 177 extra
variant locators.  No variant is silently deduplicated by citation alone.

## Existing-byte reuse and residual

No retained local object is an authorizing current-source parser input.
Therefore the reusable authoritative body-byte count is **zero**.

The exact prospective current body residual from the observed catalog is
30,291 same-domain requests:

- 30,270 individually labeled current section candidates;
- 3 current multi-section collection candidates;
- 3 untyped current document locators that require body classification; and
- 15 recent-legislation locators that require body-based identity resolution.

The following 141 document-like nodes are typed catalog exclusions and are not
body-acquisition targets for the current Code:

- 80 full future-effectiveness locators;
- 2 bare future structural placeholders; and
- 59 publisher/editorial structural documents.

This algebra closes exactly:

```text
30,291 residual body requests + 141 catalog exclusions = 30,432 document-like nodes
```

Within the 30,291 body residual, repeated current citation variants are fetched
as distinct URNs and reconciled only after exact-body parsing.  The acquisition
must never discard one merely because another row has the same citation.

## Retained-artifact audit

### Catalog-first `MS` directory

The existing directory at
`~/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/catalog-first/MS`
is nonauthorizing:

- `request.bin` is only `GET /legislation/` and has SHA-256
  `8fa9d26334758149c496837c904ea40d3bbc9b9eac3a56bf505045e655eb4c2e`;
- `response.bin` is a 32,839-byte live legislation landing page with SHA-256
  `2f9ad7ba2981a453b94350a5b464b739b1bea86b964792bc44a96c8449420d68`;
- that page contains measure/session navigation and no Mississippi Code catalog
  link;
- `body.bin` is a 38,389-byte repaired JSON object with SHA-256
  `b14bc30cb95929b102ec8f2c67e7b86f87578267de684f411e64bd343efd6b40`;
- it invents 99 title rows, including nonexistent even-numbered titles, and
  points them to the dead 2024 bill-status path;
- `rows.jsonl` has SHA-256
  `43fc3b3b3507b6de540989de316ac480c412d98541bc49d07e10112a8d3a406e`;
- `frontier.json` has SHA-256
  `0bdef7c5ef1ec3d8db98add53869eeb608296a2c414e76aa1889d8c2ae3db112`,
  says `bundle_closed=false`, and asserts an unsupported 2026-07-01 legal date;
  and
- the checkpoint names `receipt.json`, but that file is absent.

The exact landing-page bytes may remain historical evidence that
`/legislation/` was observed.  The repaired body, 99 rows, frontier claims, and
dead source URLs are not reusable catalog or body inputs.

### Older broad scrapes

The readiness audit's retained 984-page candidate was characterized as
predominantly a 1997 bill-history snapshot.  Direct inspection of a related
553-row May JSON-LD artifact confirms that its first rows are Wayback UI plus
“HB 1 - History of Actions/Background”, “HB 2”, and similar 1997 regular-session
bill histories—not current Code sections.  Those records are session-history
evidence, not members of this statutory corpus.

A separate 28,508-row checkpoint uses `unicourt.github.io` release `r78` and
SHA-256
`2fe4efee85be38459aa908d5c98e04a47c98f61ececce7ae890922df8616700d`.
It is a secondary transformation without the new delegated URN frontier or a
strict acquisition ledger.  It may be consulted as a recovery candidate only
after exact citation/edition matching; it cannot authorize current membership
or suppress any of the 30,291 exact delegated residual requests.

The current singleton local JSON-LD is only Justia section 97-3-7.  It is also
secondary and not a corpus-completeness proof.

## Required grouped archival recovery

Before body acquisition, acquire and retain the small authority/catalog
prelude separately: at least one exact Legislature delegation response, the
publisher-entry redirect, the rendered container root, and the 51 complete TOC
responses.  These authority and catalog inputs are not part of the 30,291 body
count.  Replay that byte ledger with zero network and require the same semantic
membership (or seal and explain a newly observed membership) before admitting
any body frontier.

All 30,291 residual document URLs are on `advance.lexis.com`.  A future body
run must pass the ordered URL set to the shared plural archival-aware transport
as one source-domain inventory scope.  Implementations may bound concurrent
HTTP work or payload memory, but may not turn the archive inventory into a
per-page loop.

Required invariants:

```text
source_domain = advance.lexis.com
common_crawl_inventory_query_upper_bound = 1
wayback_prefix_inventory = true
group_warc_ranges_by_warc_filename = true
per_page_archive_inventory_loop = false
retry_residual_urls_only = true
```

After one Common Crawl inventory, matching WARC byte ranges must be grouped by
WARC filename and coalesced where safe.  Direct/browser successes are retained
first; archive recovery receives only aligned residual URLs.  A second pass
must replay the exact retained ledger with zero network requests before any
normalization or materialization can be admitted.

## Code boundary

`mississippi_lexis.py` now implements:

- exact container and root-membership validation;
- one complete `open-to` request per source root;
- hierarchy and cross-title validation;
- stable semantic-membership hashing separate from raw receipts;
- current, future, recent-law, editorial, and untyped dispositions;
- stable document URL derivation; and
- a same-domain plural body-acquisition contract that forbids per-page archive
  inventory loops.

`MississippiScraper` binds that module into its source-software identity.
Strict full-corpus mode inventories the delegated catalog, records the blocked
frontier, and raises `MississippiDelegatedCorpusBlockedError`.  It no longer
attempts the dead bill-status tree, fabricates 50/99 title rows, or proceeds to
secondary materialization.

The resulting source-software identity is:

```text
ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi.MississippiScraper@sha256:47adb7288b80a3e7bc9cff8994ce19a9fdfb0b8b174cf1790fa044bf413b6080
```

## Safe next commands

The next safe command is container-catalog-only.  It retains the exact rendered
container root and 51 TOC responses in a fresh directory and still opens no
document body:

```bash
MISSISSIPPI_LEXIS_PUBLIC_ACCESS_ENABLE=1 python - <<'PY'
import asyncio
from pathlib import Path
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_lexis import discover_live_inventory

async def main():
    root = Path("/tmp/ms-lexis-catalog-v1")
    inventory = await discover_live_inventory(
        require_enabled=True,
        retries=2,
        request_delay_seconds=0.05,
        timeout_ms=60_000,
        evidence_dir=root,
    )
    inventory.write(root / "inventory.json")
    assert inventory.frontier["toc_frontier_closed"] is True
    assert inventory.frontier["body_frontier_closed"] is False

asyncio.run(main())
PY
```

That command remains diagnostic until the exact Legislature delegation input
and publisher-entry redirect have also been acquired into the same authorizing
ledger.  It must not be treated as a complete authority-chain receipt by
itself.

After the 30,291-body plural acquisition/reconciliation path is implemented,
the isolated strict command should use fresh output and evidence roots and
disable materialization, publication, registry mutation, startup sync, and
reuse of an older completed state:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states MS \
  --scrape \
  --strict-full-text \
  --max-statutes 0 \
  --parallel-workers 1 \
  --per-state-timeout-seconds 14400 \
  --output-root /tmp/state-laws-ms-strict-v1 \
  --acquisition-evidence-root /tmp/state-laws-ms-evidence-v1 \
  --strict-acquisition-evidence \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-materialize \
  --no-incremental-state-publish \
  --json
```

With the present code, that second command is expected to stop after the
catalog probe with the delegated-body-frontier blocker.  That is the intended
safe failure until exact body acquisition, parsing, temporal reconciliation,
retained replay, and closure algebra are implemented.
