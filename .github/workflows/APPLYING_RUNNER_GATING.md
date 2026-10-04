# Applying Runner Gating to Existing Workflows

This guide explains how to add runner gating to existing workflows without creating duplicate files.

## Approach

Instead of creating separate `-gated.yml` files, we'll modify existing workflows to add the gating mechanism. This keeps the codebase cleaner and ensures a single source of truth.

## Pattern

For each workflow that uses `runs-on: [self-hosted, ...]`:

### Step 1: Add Gate Job at the Beginning

```yaml
jobs:
  # Add this as the first job
  check-runner:
    uses: ./.github/workflows/templates/check-runner-availability.yml
    with:
      runner_labels: "self-hosted,linux,x64"  # Adjust labels as needed
      skip_if_unavailable: true
```

### Step 2: Add Dependencies to Existing Jobs

For each existing job that uses self-hosted runners:

```yaml
  existing-job:
    needs: [check-runner]  # Add this line
    if: ${{ needs.check-runner.outputs.should_run == 'true' }}  # Add this line
    runs-on: [self-hosted, linux, x64]
    # ... rest of job definition
```

### Step 3: Update Summary Jobs

If there's a summary/aggregate job, make it conditional:

```yaml
  summary:
    needs: [check-runner, job1, job2]
    if: always()  # Run regardless of whether other jobs ran
    runs-on: ubuntu-latest  # Use GitHub-hosted for summary
    steps:
      - name: Generate summary
        run: |
          if [ "${{ needs.check-runner.outputs.should_run }}" != "true" ]; then
            echo "⏭️ Workflow skipped - self-hosted runners not available"
          else
            # Normal summary logic
          fi
```

## Workflows to Update

1. **docker-build-test.yml**
   - Runner labels: `self-hosted,linux,x64` for x86_64 jobs
   - Runner labels: `self-hosted,linux,arm64` for ARM64 jobs
   - Jobs to gate: `test-self-hosted-x86`, `test-self-hosted-arm64`

2. **graphrag-production-ci.yml**
   - Runner labels: `self-hosted,linux,x64`
   - Jobs to gate: `test`, `build-docker`, etc.

3. **mcp-integration-tests.yml**
   - Runner labels: `self-hosted,linux,x64`
   - Jobs to gate: All integration test jobs

4. **pdf_processing_ci.yml**
   - Runner labels: `self-hosted,linux,x64`
   - Jobs to gate: All processing jobs

## Benefits of In-Place Updates

1. **Single source of truth** - No duplicate workflow files to maintain
2. **Gradual rollout** - Can update one workflow at a time
3. **Easy rollback** - Just remove the gate job and conditions
4. **Clear history** - Git history shows what changed
5. **Less confusion** - Users don't need to choose between gated/non-gated versions

## Testing

After modifying each workflow:

1. Test with runners available (should work normally)
2. Test with runners offline (should skip gracefully)
3. Verify workflow summaries show correct status
4. Check that summary jobs still run

## Example: Before and After

### Before
```yaml
jobs:
  test:
    runs-on: [self-hosted, linux, x64]
    steps:
      - uses: actions/checkout@v4
      - run: pytest
```

### After
```yaml
jobs:
  check-runner:
    uses: ./.github/workflows/templates/check-runner-availability.yml
    with:
      runner_labels: "self-hosted,linux,x64"
      skip_if_unavailable: true
  
  test:
    needs: [check-runner]
    if: ${{ needs.check-runner.outputs.should_run == 'true' }}
    runs-on: [self-hosted, linux, x64]
    steps:
      - uses: actions/checkout@v4
      - run: pytest
```

## Next Steps

1. Start with gpu-tests.yml (already has -gated version as example)
2. Apply pattern to docker-build-test.yml
3. Apply pattern to graphrag-production-ci.yml
4. Apply pattern to mcp-integration-tests.yml
5. Apply pattern to pdf_processing_ci.yml
6. Document results
7. Monitor for 48 hours
