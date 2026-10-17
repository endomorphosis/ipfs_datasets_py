# Native task headroom for the CUDA census

The 2026-10-15 census restart was refused before engine/model launch by the
unchanged native proof resource scheduler. Its recorded `proof_pid_headroom`
decision required 160 available tasks; the systemd service had `TasksMax=128`
and 127 available tasks. This was separate from CUDA memory pressure and the
160 GB campaign disk cap. Reducing or bypassing the proof check would conceal
the actual execution limit.

The reviewed local service now has this bounded drop-in:

```ini
# ~/.config/systemd/user/legacy-cuda-span-census.service.d/30-native-task-headroom.conf
[Service]
TasksMax=256
```

The installed file's SHA256 is
`0448f04c111d010e983eb4457c2bdfc2d43e9c7ca2c0f6fc1f6cae40138ff980`;
it also contains two explanatory comment lines. The actual reloaded unit must
report 256, and its live cgroup must expose that limit. The native reservation
still requests five child-process slots, three CPU slots, and 8192 MiB.
The F07 native policy, process/task safety calculation, CPU/RAM limits, CUDA
2 GiB operating reserve, 4 GiB initial headroom, and storage checks are unchanged.

Other machines must compare their actual cgroup headroom with their native
request before adopting an example value. A systemd limit is not a new native
grant and is not permission to exceed the reserved process or memory envelope.
Retain `Restart=no`; make a single controlled retry after a diagnosed execution
limit has changed. A previous native-admission failure's retained disk promise
remains charged until its own explicit supported closeout is verified. An
unbound reservation is not eligible for an arbitrary attached-attempt closeout.

The preceding CUDA backpressure change passed 173 tests on actual tmpfs under
an existing native CPU/RAM validation grant, including synthetic CUDA pressure
and cancellation cases. This does not qualify the main filesystem, demonstrate
training convergence, or provide a Lean admission. Runtime admission and work
must be observed separately after restart. See
[CUDA memory backpressure](legacy_cuda_headroom_backpressure.md) and
[campaign storage allocation](campaign_storage_allocation.md).

## Concurrent memory reservations

After the task limit was corrected, a concurrent 6144 MiB validation reservation
exposed the independent memory boundary. The unchanged admission requirement
was 24922 MiB proof headroom + 6144 MiB other root reservations + 8192 MiB for
this worker = 39258 MiB. The unit's previous 36 GiB `MemoryHigh` supplied less
than that amount even before model startup.

The reviewed additional local drop-in is:

```ini
# ~/.config/systemd/user/legacy-cuda-span-census.service.d/40-native-memory-headroom.conf
[Service]
MemoryHigh=48G
MemoryMax=52G
```

Its installed SHA256, including two explanatory comment lines, is
`499ed665b822d13db5bb16d2bd2db09cbc518822299f8a42777552cb254f548e`.
At installation, host available memory exceeded the 52 GiB hard boundary plus
the unchanged 24922 MiB proof reserve. Visible ancestors imposed no tighter
memory boundary. Verify actual `memory.high`, `memory.max`, `pids.max` and usage
from the live service cgroup after startup; systemd configuration alone is not
an admission. The native worker allowance remains 8192 MiB, with the existing
RSS watchdog, five child slots and three CPU slots. This outer kernel margin
does not increase the model context, CUDA allocator allowance, or native policy.
