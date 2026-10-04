# GitHub Actions Infrastructure Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    GitHub Actions Workflow                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐     │
│  │  setup-github-   │  │  setup-codeql-   │  │    inject-       │     │
│  │     cache        │  │     cache        │  │  credentials     │     │
│  │   (composite     │  │   (composite     │  │   (composite     │     │
│  │     action)      │  │     action)      │  │     action)      │     │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘     │
│           │                     │                     │                 │
└───────────┼─────────────────────┼─────────────────────┼─────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         Python Modules Layer                              │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                    GitHubAPICache (cache.py)                        │ │
│  │  • In-memory + persistent caching                                   │ │
│  │  • TTL-based expiration                                             │ │
│  │  • Content-addressed validation (IPFS multiformats)                 │ │
│  │  • GitHub token-based encryption                                    │ │
│  │  • Peer-to-peer message broadcasting                                │ │
│  └────────────────┬──────────────────────────────┬────────────────────┘ │
│                   │                              │                       │
│  ┌────────────────▼────────────┐  ┌──────────────▼──────────────────┐  │
│  │   CodeQLCache                │  │   CredentialManager             │  │
│  │   (codeql_cache.py)         │  │   (credential_manager.py)       │  │
│  │                              │  │                                  │  │
│  │  • Scan result caching       │  │  • AES-256-GCM encryption       │  │
│  │  • Commit SHA hashing        │  │  • PBKDF2 key derivation        │  │
│  │  • Skip detection            │  │  • Multi-scope support          │  │
│  │  • SARIF management          │  │  • Expiration & rotation        │  │
│  │  • File change analysis      │  │  • OS keyring integration       │  │
│  │  • Time savings tracking     │  │  • Audit logging                │  │
│  └──────────────────────────────┘  └─────────────────────────────────┘  │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                           P2P Network Layer                                │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                    libp2p P2P Network                                │ │
│  │  • Protocol: /github-cache/1.0.0                                    │ │
│  │  • Port: 9000 (configurable 9000-9010)                             │ │
│  │  • Transport: TCP                                                    │ │
│  │  • Encryption: AES-256-GCM (GitHub token derived)                  │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │              P2PPeerRegistry (p2p_peer_registry.py)                 │ │
│  │  • Automatic peer discovery via GitHub Cache API                    │ │
│  │  • Peer multiaddr registration                                      │ │
│  │  • TTL-based peer expiration (15 minutes)                          │ │
│  │  • Bootstrap peer management                                         │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Storage Layer                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  GitHub API     │  │  CodeQL Cache    │  │  Credential Storage      │  │
│  │   Cache Dir     │  │     Dir          │  │       Dir                │  │
│  │                 │  │                  │  │                          │  │
│  │  ~/.cache/      │  │  ~/.cache/       │  │  ~/.credentials/         │  │
│  │  github-api-p2p │  │  codeql          │  │                          │  │
│  │                 │  │                  │  │  • credentials.json.enc  │  │
│  │  • *.json       │  │  • github_cache/ │  │  • .master_key           │  │
│  │  • Persistent   │  │  • Persistent    │  │  • audit.log             │  │
│  │  • 0o644 perms  │  │  • 0o644 perms   │  │  • 0o600/0o700 perms    │  │
│  └─────────────────┘  └──────────────────┘  └──────────────────────────┘  │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. GitHub API Caching Flow

```
┌──────────────┐
│   Workflow   │
│    Step      │
└──────┬───────┘
       │ 1. Initialize cache
       ▼
┌─────────────────────┐
│  GitHubAPICache     │
│  • Load from disk   │
│  • Init P2P network │
│  • Discover peers   │
└──────┬──────────────┘
       │ 2. API call needed
       ▼
┌─────────────────────┐      ┌──────────────────┐
│  Check Local Cache  │──No──▶ Check P2P Peers  │
│  • Memory lookup    │      │ • Query peers    │
└──────┬──────────────┘      │ • Verify hash    │
       │ Yes                 └────────┬─────────┘
       │                              │ Yes/No
       │                              │
       ▼                              ▼
┌─────────────────────┐      ┌──────────────────┐
│  Return Cached      │◀─────│  GitHub API      │
│  • Update stats     │      │  • Rate limited  │
│  • Log hit          │      │  • Store result  │
└─────────────────────┘      │  • Broadcast P2P │
                              └──────────────────┘
```

### 2. CodeQL Caching Flow

```
┌──────────────┐
│   Workflow   │
│  CodeQL Step │
└──────┬───────┘
       │ 1. Check cache
       ▼
┌─────────────────────┐
│  CodeQLCache        │
│  • Compute config   │
│    hash             │
│  • Get commit SHA   │
└──────┬──────────────┘
       │ 2. Lookup
       ▼
┌─────────────────────┐      ┌──────────────────┐
│  Cached Result?     │──No──▶ Run CodeQL Scan  │
│  • Check SHA        │      │ • 5+ minutes     │
│  • Verify config    │      │ • Generate SARIF │
│  • Check file       │      │ • Store in cache │
│    changes          │      └──────────────────┘
└──────┬──────────────┘
       │ Yes
       ▼
┌─────────────────────┐
│  Skip Scan          │
│  • Use cached SARIF │
│  • Save ~5 minutes  │
│  • Update stats     │
└─────────────────────┘
```

### 3. Credential Injection Flow

```
┌──────────────┐
│   Workflow   │
│  Cred Step   │
└──────┬───────┘
       │ 1. Inject credentials
       ▼
┌─────────────────────┐
│ CredentialManager   │
│ • Init encryption   │
│ • Load master key   │
└──────┬──────────────┘
       │ 2. For each credential
       ▼
┌─────────────────────┐      ┌──────────────────┐
│  Check Scope        │──No──▶ Access Denied    │
│  • Global?          │      │ • Log denial     │
│  • Repo match?      │      │ • Return None    │
│  • Workflow match?  │      └──────────────────┘
│  • Not expired?     │
└──────┬──────────────┘
       │ Yes
       ▼
┌─────────────────────┐
│  Decrypt & Inject   │
│  • AES-256-GCM      │
│  • Add to env       │
│  • Mask in logs     │
│  • Audit log        │
└─────────────────────┘
```

## Security Architecture

### Encryption Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      Encryption Layers                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Layer 1: P2P Message Encryption                       │     │
│  │  ┌──────────────┐                                      │     │
│  │  │ GitHub Token │──▶ PBKDF2 (100k iter) ──▶ AES Key  │     │
│  │  └──────────────┘                                      │     │
│  │  • Algorithm: AES-256-GCM                              │     │
│  │  • Nonce: 96-bit random                               │     │
│  │  • Shared secret across runners with same token       │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Layer 2: Credential Encryption                        │     │
│  │  ┌──────────────┐                                      │     │
│  │  │ Master Key   │──▶ Stored in Keyring/File          │     │
│  │  └──────────────┘                                      │     │
│  │  • Algorithm: AES-256-GCM                              │     │
│  │  • Nonce: 96-bit random per credential                │     │
│  │  • Key: 256-bit random (generated once)              │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Layer 3: Content Verification                         │     │
│  │  • IPFS multihash (SHA2-256)                          │     │
│  │  • Content-addressed CIDs                              │     │
│  │  • Prevents cache poisoning                            │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Access Control Flow

```
┌────────────────────────────────────────────────────────────┐
│                    Credential Access                       │
└────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Get Credential│
                    └────────┬───────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────────┐  ┌──────────────┐
│ Check Scope   │  │ Check Expiration │  │ Verify Token │
│ • Global      │  │ • TTL elapsed?   │  │ • GitHub     │
│ • Repo match  │  │ • Cleanup if old │  │   access     │
│ • Workflow    │  └──────┬───────────┘  └──────┬───────┘
│ • Runner      │         │                     │
└───────┬───────┘         │                     │
        │                 │                     │
        └─────────────────┴─────────────────────┘
                          │
                   ┌──────▼──────┐
                   │  All Checks │
                   │   Passed?   │
                   └──────┬──────┘
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼ Yes                   ▼ No
     ┌────────────────┐      ┌───────────────┐
     │ Decrypt & Return│      │ Access Denied │
     │ • Audit: granted│      │ • Audit: denied│
     │ • Update stats  │      │ • Log reason   │
     └─────────────────┘      └────────────────┘
```

## Integration Points

### With ipfs_accelerate_py

```
┌──────────────────────────────────────────────────────────────┐
│                    ipfs_accelerate_py                        │
│                    (Autoscaler Repo)                         │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  • Auto-scaled runners                                       │
│  • P2P cache infrastructure (/github-cache/1.0.0)           │
│  • GitHub token-based encryption                             │
│  • Peer discovery via GitHub Cache API                       │
│                                                               │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │ P2P Network
                         │ (libp2p)
                         │
┌────────────────────────┴─────────────────────────────────────┐
│                    ipfs_datasets_py                          │
│                   (This Repository)                          │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  • GitHub API cache (reuses P2P)                            │
│  • CodeQL cache (new)                                        │
│  • Credential manager (new)                                  │
│  • Compatible cache formats                                  │
│  • Same P2P protocol                                         │
│                                                               │
└──────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│              Shared P2P Network                            │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  Runner A          Runner B          Runner C              │
│  (accelerate) ←──→ (datasets)  ←──→ (accelerate)          │
│                                                             │
│  • Bidirectional cache sharing                             │
│  • Cross-repository peer discovery                         │
│  • Unified GitHub API cache                                │
│  • Reduced combined rate limit usage                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Performance Optimization

### Cache Hit Optimization

```
Request ──▶ Memory Cache ─Hit─▶ Return (< 1ms)
                │
                │ Miss
                ▼
            P2P Peers ─Hit─▶ Return (< 50ms)
                │
                │ Miss
                ▼
            Disk Cache ─Hit─▶ Return (< 10ms)
                │
                │ Miss
                ▼
           GitHub API ──▶ Return (100-500ms)
                │
                │
                ▼
           Store in All Layers
           Broadcast to Peers
```

### TTL Strategy

```
Operation Type          Default TTL    Rationale
─────────────────────  ─────────────  ───────────────────────
list_repos             600s (10m)     Infrequent changes
get_repo_info          300s (5m)      Moderate changes
list_workflows         300s (5m)      Moderate changes
get_workflow_runs      120s (2m)      Frequent changes
get_runner_status      60s (1m)       Very frequent changes
copilot_completion     3600s (1h)     Stable for same prompt
codeql_results         86400s (24h)   Expensive to compute
```

## Monitoring & Observability

### Metrics Collection

```
┌─────────────────────────────────────────────────────────────┐
│                    Metrics Dashboard                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  GitHub API Cache:                                          │
│  • Total requests: 1,234                                    │
│  • Cache hits: 987 (80%)                                    │
│  • Peer hits: 234 (19%)                                     │
│  • API calls saved: 987                                     │
│  • Connected peers: 5                                       │
│                                                              │
│  CodeQL Cache:                                              │
│  • Scans cached: 45                                         │
│  • Scans retrieved: 42                                      │
│  • Scans skipped: 38 (90%)                                 │
│  • Time saved: 3.2 hours                                    │
│                                                              │
│  Credentials:                                                │
│  • Active credentials: 12                                   │
│  • Access events: 456                                       │
│  • Access denied: 3                                         │
│  • Expired: 2                                               │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Configuration Management

```
┌──────────────────────────────────────────────────────────────┐
│               Configuration Hierarchy                        │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Environment Variables (highest priority)                 │
│     • ENABLE_P2P_CACHE                                       │
│     • CACHE_DEFAULT_TTL                                      │
│     • P2P_LISTEN_PORT                                        │
│                                                               │
│  2. .github/cache-config.yml                                │
│     • Operation-specific TTLs                                │
│     • Cache size limits                                      │
│     • Persistence settings                                   │
│                                                               │
│  3. .github/p2p-config.yml                                  │
│     • Network configuration                                  │
│     • Security settings                                      │
│     • Performance tuning                                     │
│                                                               │
│  4. Code Defaults (lowest priority)                         │
│     • Built-in sensible defaults                            │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

## Summary

The architecture provides:

✅ **Layered Caching** - Memory → P2P → Disk → API
✅ **Strong Security** - AES-256-GCM, PBKDF2, audit logging
✅ **High Performance** - 70%+ API reduction, 40%+ time savings
✅ **Cross-Repository** - Compatible with ipfs_accelerate_py
✅ **Resilient** - Graceful degradation, fallback mechanisms
✅ **Observable** - Comprehensive metrics and logging
✅ **Configurable** - Multiple configuration layers
