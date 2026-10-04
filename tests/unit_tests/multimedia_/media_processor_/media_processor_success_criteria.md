# Success Criteria for download_and_convert Method

## 1. URL Processing Performance Criteria

### 1.1 URL Validation Speed
$T_{validation} \leq 100 \text{ ms}$

Where:
- $T_{validation}$ = Time from method entry to completion of RFC 3986 URL format validation + DNS resolution
- **Valid URL Definition**: Must pass both syntactic validation (RFC 3986) AND successful DNS resolution
- **Measurement Method**: Wall-clock time measured via `time.perf_counter()` at method entry/exit
- **Target**: ≤100ms for 95th percentile of 1000 URL validation attempts
- **Upper Bound**: 99th percentile must be ≤500ms

### 1.2 Platform Support Coverage
$P_{coverage} = \frac{N_{supported}}{N_{total}} \geq 0.95$

Where:
- $P_{coverage}$ = Platform coverage ratio
- $N_{supported}$ = Number of platforms returning HTTP 200 response for test video extraction
- $N_{total}$ = 25 (fixed test suite size)
- **Platform Test Suite** (25 platforms, ranked by Alexa Global Rank as of 2024):
  1. YouTube, 2. Facebook, 3. TikTok, 4. Instagram, 5. Twitter/X, 6. Vimeo, 7. Dailymotion, 8. Twitch, 9. Reddit, 10. LinkedIn, 11. Snapchat, 12. Pinterest, 13. Tumblr, 14. Flickr, 15. SoundCloud, 16. Bandcamp, 17. Archive.org, 18. Peertube, 19. BitChute, 20. Rumble, 21. Odysee, 22. Streamable, 23. Gfycat, 24. Imgur, 25. IPFS Gateway
- **Success Definition**: Returns valid video metadata within 30 seconds
- **Test Update Policy**: Suite reviewed annually; platforms replaced if global rank drops below top 500

### 1.3 URL Edge Case Handling
$E_{success} = \frac{N_{edge\_success}}{N_{edge\_total}} \geq 0.90$

Where:
- $E_{success}$ = Edge case success ratio
- $N_{edge\_success}$ = Number of edge cases returning status dict with appropriate error classification
- $N_{edge\_total}$ = 12 (complete enumerated test set)
- **Complete Edge Case Set**:
  1. HTTP→HTTPS redirects, 2. Shortened URLs (bit.ly, tinyurl), 3. URLs with query parameters, 4. URLs with fragments, 5. Private/restricted content, 6. Age-restricted content, 7. Geo-blocked content, 8. Deleted/404 content, 9. Malformed URLs (missing protocol), 10. Invalid domains, 11. Non-video content pages, 12. Rate-limited responses
- **Success Definition**: Returns structured error with classification: `REDIRECT`, `PRIVATE`, `RESTRICTED`, `NOT_FOUND`, `INVALID_FORMAT`, `NOT_VIDEO`, `RATE_LIMITED`
- **"Appropriate" Error Definition**: Must include error classification + human-readable message ≤200 characters

## 2. Download Performance Criteria

### 2.1 Download Throughput Efficiency
$\eta_{download} = \frac{R_{actual}}{R_{theoretical}} \geq 0.70$

Where:
- $\eta_{download}$ = Download efficiency ratio
- $R_{actual}$ = Average download rate over entire transfer (total bytes / total time)
- $R_{theoretical}$ = Minimum of: (network_speed_test_result × 0.85, platform_rate_limit)
- **Network Speed Measurement**: Fast.com API result taken ≤5 minutes before operation
- **Platform Rate Limits**: YouTube: 2MB/s, Vimeo: 5MB/s, Others: 10MB/s (conservative estimates)
- **Measurement Window**: From first byte received to last byte received
- **File Size Range**: Test files between 10MB-500MB (excludes micro-files and massive files)

### 2.2 Quality Selection Accuracy
$A_{quality} = \frac{N_{correct\_quality}}{N_{requests}} \geq 0.95$

Where:
- $A_{quality}$ = Quality selection accuracy
- $N_{correct\_quality}$ = Number of downloads where extracted video matches quality specification
- $N_{requests}$ = Total number of quality-specific download requests
- **Quality Parameter Definitions**:
  - Resolution: Height in pixels (720p = 720px height ±10px tolerance)
  - "best": Highest available resolution ≥720p
  - "worst": Lowest available resolution
  - Bitrate: Within ±20% of platform's standard for that resolution
- **Matching Criteria**: 
  - Resolution: ±10px height tolerance
  - Framerate: ±2fps tolerance  
  - Codec: Any H.264 variant acceptable for "mp4", any VP9 for "webm"

### 2.3 Network Error Recovery Rate
$R_{recovery} = \frac{N_{recovered}}{N_{network\_errors}} \geq 0.80$

Where:
- $R_{recovery}$ = Network error recovery success rate
- $N_{recovered}$ = Number of network errors resulting in eventual successful download
- $N_{network\_errors}$ = Number of HTTP errors 5xx, timeouts, connection resets during transfer
- **Recoverable Error Definition**: HTTP 429, 500-599, socket timeout, connection reset
- **Non-recoverable**: HTTP 403, 404, 401, certificate errors
- **Recovery Protocol**: Exponential backoff: 1s, 2s, 4s, max 3 attempts
- **Success Definition**: Final attempt returns HTTP 200 with complete file

## 3. Format Conversion Criteria

### 3.1 Conversion Decision Accuracy
$D_{accuracy} = \frac{N_{correct\_decisions}}{N_{total\_decisions}} = 1.0$

Where:
- $D_{accuracy}$ = Conversion decision accuracy
- $N_{correct\_decisions}$ = Number of correct convert/skip decisions based on container format comparison
- $N_{total\_decisions}$ = Total conversion decisions made
- **Decision Logic**: Convert if `input_container != output_container` where container determined by file extension
- **Container Mapping**: .mp4→MP4, .avi→AVI, .mkv→Matroska, .webm→WebM, .mov→QuickTime
- **Target**: 100% accuracy (never convert when formats match, always convert when different)

### 3.2 Conversion Speed Efficiency
$S_{conversion} = \frac{D_{video}}{T_{conversion}} \geq 1.0$

Where:
- $S_{conversion}$ = Conversion speed ratio
- $D_{video}$ = Video duration in seconds (from FFprobe metadata)
- $T_{conversion}$ = Wall-clock conversion time using `time.perf_counter()`
- **Standard Codec Definition**: H.264 baseline profile, AAC audio, progressive scan
- **Hardware Baseline**: Target assumes Intel i5-8400 equivalent (6 cores, 2.8GHz) with 16GB RAM
- **Scaling Factor**: Apply hardware multiplier: `target_speed × (cpu_benchmark_score / 15000)`
- **Measurement**: From FFmpeg process start to completion

### 3.3 Quality Preservation Rate
$Q_{preservation} = \frac{SSIM_{avg\_output}}{SSIM_{avg\_input}} \geq 0.95$

Where:
- $Q_{preservation}$ = Quality preservation ratio using Structural Similarity Index
- $SSIM_{avg\_output}$ = Average SSIM across 10 evenly-spaced sample frames from converted video
- $SSIM_{avg\_input}$ = Average SSIM across same 10 frames from source video
- **SSIM Calculation**: scikit-image `structural_similarity()` with default parameters
- **Frame Sampling**: Frames at 10%, 20%, ..., 90% of video duration
- **Reference Standard**: Compare both videos against 1080p test pattern (SMPTE color bars)
- **Resolution Handling**: Upscale/downscale to common resolution (1080p) before SSIM calculation

## 4. Asynchronous Execution Criteria

### 4.1 Non-Blocking Performance
$$T_{blocking} \leq 10 \text{ ms}$$

Where:
- $T_{blocking}$ = Maximum time main thread is blocked during method execution
- Measurement: Longest continuous blocking period
- Target: ≤10ms total blocking time

### 4.2 Concurrent Operation Scaling
$$C_{efficiency} = \frac{T_{sequential}}{T_{concurrent}} \geq N \times 0.70$$

Where:
- $C_{efficiency}$ = Concurrency efficiency factor
- $T_{sequential}$ = Time for N sequential operations
- $T_{concurrent}$ = Time for N concurrent operations
- $N$ = Number of concurrent operations
- Target: ≥70% of theoretical speedup for N≤10 concurrent operations

## 5. Resource Management Criteria

### 5.1 Memory Usage Bounds
$M_{peak} \leq M_{baseline} + (S_{largest} \times 0.10) + 50$

Where:
- $M_{peak}$ = Peak RSS memory usage during operation (MB, measured via `psutil.Process().memory_info().rss`)
- $M_{baseline}$ = RSS memory immediately after MediaProcessor initialization (MB)
- $S_{largest}$ = Size of largest file being processed concurrently (MB)
- **Measurement Window**: From method entry to method exit, sampled every 100ms
- **Concurrent Handling**: For N concurrent operations, use sum of N largest files
- **Buffer Constant**: +50MB accounts for codec buffers and temporary allocations

### 5.2 Disk Space Validation Accuracy
$V_{disk} = \frac{N_{correct\_validations}}{N_{total\_validations}} = 1.0$

Where:
- $V_{disk}$ = Disk space validation accuracy  
- $N_{correct\_validations}$ = Number of space predictions within tolerance
- $N_{total\_validations}$ = Total disk space validations performed
- **Prediction Formula**: `estimated_size = content_length × 1.5 + 100MB`
- **Safety Buffer**: 1.5× multiplier accounts for conversion overhead, +100MB for temporary files
- **Validation Tolerance**: Prediction considered correct if actual space used ≤ predicted space
- **Measurement**: Via `shutil.disk_usage()` before/after operation

### 5.3 Cleanup Completion Rate
$C_{cleanup} = \frac{N_{cleaned}}{N_{created}} = 1.0$

Where:
- $C_{cleanup}$ = Temporary file cleanup success rate
- $N_{cleaned}$ = Number of temporary files successfully deleted (verified via `os.path.exists()`)
- $N_{created}$ = Number of temporary files created (tracked via UUID naming convention)
- **Temporary File Definition**: Files matching pattern `{uuid4()}.tmp.*` in temp directory
- **Cleanup Trigger**: Python `finally` block + `atexit` handler for process termination
- **Verification Method**: File existence check 1 second after cleanup command

## 6. Error Resilience Criteria

### 6.1 Exception Coverage Rate
$E_{coverage} = \frac{N_{handled\_exceptions}}{N_{total\_exceptions}} = 1.0$

Where:
- $E_{coverage}$ = Exception handling coverage
- $N_{handled\_exceptions}$ = Number of exception types with specific `except` clauses
- $N_{total\_exceptions}$ = 15 (complete enumerated exception set)
- **Complete Exception Set**: 
  1. `URLError`, 2. `HTTPError`, 3. `TimeoutError`, 4. `ConnectionError`, 5. `OSError`, 6. `PermissionError`, 7. `FileNotFoundError`, 8. `DiskSpaceError`, 9. `CalledProcessError`, 10. `ValueError`, 11. `TypeError`, 12. `KeyError`, 13. `IndexError`, 14. `asyncio.CancelledError`, 15. `MemoryError`
- **Handling Requirement**: Each exception must have dedicated `except` block with appropriate error classification
- **No Generic Handlers**: `except Exception:` blocks not counted toward coverage

### 6.2 Error Message Clarity Score
$M_{clarity} = \frac{\sum_{i=1}^{N} S_i}{N} \geq 4.0$

Where:
- $M_{clarity}$ = Average error message clarity score
- $S_i$ = Clarity score for error message i (1-5 integer scale)
- $N$ = 15 (total number of error message types matching exception set)
- **Scoring Criteria**:
  - 5: Actionable solution provided, root cause identified, context included
  - 4: Root cause identified, general guidance provided
  - 3: Clear error description, no actionable guidance
  - 2: Vague error description, minimal context
  - 1: Generic or unhelpful message
- **Evaluation Method**: 5 software engineers rate each message independently, median score used
- **Message Requirements**: ≤200 characters, include error code, no technical jargon

### 6.3 Recovery Success Rate
$R_{success} = \frac{N_{successful\_recoveries}}{N_{recoverable\_errors}} \geq 0.90$

Where:
- $R_{success}$ = Recovery operation success rate
- $N_{successful\_recoveries}$ = Number of recoveries resulting in successful operation completion
- $N_{recoverable\_errors}$ = Number of errors classified as recoverable
- **Recoverable Error Definition**: Errors with transient causes that may succeed on retry
- **Recoverable Set**: HTTP 429, 5xx errors, DNS timeout, connection reset, temporary file conflicts
- **Non-Recoverable Set**: HTTP 403/404, authentication errors, malformed URLs, codec errors
- **Recovery Protocol**: Maximum 3 attempts with exponential backoff (1s, 2s, 4s delays)

## 7. Status Reporting Criteria

### 7.1 Metadata Completeness Rate
$M_{completeness} = \frac{N_{complete\_metadata}}{N_{successful\_operations}} \geq 0.98$

Where:
- $M_{completeness}$ = Metadata completeness rate
- $N_{complete\_metadata}$ = Number of operations returning all 8 required metadata fields
- $N_{successful\_operations}$ = Total number of operations with `status: "success"`
- **Required Metadata Fields** (8 total):
  1. `output_path` (str): Absolute file path
  2. `title` (str): Video title or filename if unavailable  
  3. `duration` (float): Duration in seconds ≥0
  4. `filesize` (int): File size in bytes ≥0
  5. `format` (str): Container format (mp4, avi, mkv, webm, mov)
  6. `resolution` (str): WIDTHxHEIGHT format (e.g., "1920x1080")
  7. `converted_path` (Optional[str]): Path if conversion occurred, None otherwise
  8. `conversion_result` (Optional[Dict]): Conversion details if conversion occurred, None otherwise

### 7.2 Status Response Time
$T_{status} \leq 5 \text{ ms}$

Where:
- $T_{status}$ = Time to generate status dictionary after operation completion
- **Measurement**: From operation completion to return statement execution
- **Timing Method**: `time.perf_counter()` before/after status dict creation
- **Exclusions**: Does not include I/O operations or external tool execution time

### 7.3 Progress Reporting Accuracy
$A_{progress} = 1 - \frac{|P_{reported} - P_{actual}|}{P_{actual}} \geq 0.95$

Where:
- $A_{progress}$ = Progress reporting accuracy
- $P_{reported}$ = Progress percentage reported to callback function (0-100)
- $P_{actual}$ = Actual progress calculated as `(bytes_downloaded / total_bytes) × 100`
- **Actual Progress Definition**: Based on Content-Length header for downloads, frame count for conversions
- **Reporting Frequency**: Progress updates every 1% change or 5 seconds, whichever occurs first
- **Accuracy Measurement**: Sample progress at 10%, 25%, 50%, 75%, 90% completion points

## 8. System Stability Criteria

### 8.1 Resource Leak Prevention
$L_{rate} = \frac{N_{leaks}}{N_{operations}} = 0$

Where:
- $L_{rate}$ = Resource leak rate
- $N_{leaks}$ = Number of detected resource leaks across all resource types
- $N_{operations}$ = Total number of operations performed (minimum 1000 for statistical significance)
- **Resource Types Monitored** (5 types):
  1. File handles (via `lsof` on Unix, `handle.exe` on Windows)
  2. Process handles (subprocess instances not properly terminated)
  3. Network connections (via `netstat` - unclosed sockets)
  4. Memory allocations (RSS memory not returned to baseline ±10MB after operation)
  5. Temporary files (files in temp directory not cleaned up)
- **Detection Method**: Snapshot before/after each operation, leak = resource count increase
- **Measurement Cycle**: 1000 operations with system resource monitoring every 10 operations

### 8.2 Operation Cancellation Safety
$C_{safety} = \frac{N_{clean\_cancellations}}{N_{total\_cancellations}} = 1.0$

Where:
- $C_{safety}$ = Cancellation safety rate
- $N_{clean\_cancellations}$ = Number of cancellations with complete cleanup verification
- $N_{total\_cancellations}$ = Total number of `asyncio.CancelledError` events triggered
- **Clean Cancellation Definition**: All 5 cleanup criteria met within 5 seconds:
  1. Subprocess termination (SIGTERM sent, process exit verified)
  2. Temporary file removal (all UUID-named temp files deleted)
  3. Network connection closure (no hanging sockets to target hosts)
  4. File handle release (no open handles to output files)
  5. Memory cleanup (RSS within 10MB of pre-operation baseline)
- **Cancellation Test**: Send `asyncio.CancelledError` at random points during 50% of test operations

### 8.3 System Impact Bounds
$I_{system} = \frac{CPU_{peak\_1min}}{CPU_{total}} \leq 0.80$

Where:
- $I_{system}$ = System impact ratio
- $CPU_{peak\_1min}$ = Peak 1-minute average CPU usage by process (measured via `psutil.Process().cpu_percent(interval=60)`)
- $CPU_{total}$ = Total system CPU cores × 100 (e.g., 8 cores = 800% max)
- **Measurement Window**: 1-minute rolling average to smooth instantaneous spikes
- **Multi-core Handling**: Process can use multiple cores, but total usage bounded by 80% of system capacity
- **Background Load**: Measurement excludes system idle processes, includes only user-space CPU time