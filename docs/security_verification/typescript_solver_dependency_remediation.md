# TypeScript Solver Dependency Remediation

Task: `PORTAL-CXTP-089`

The solver dependency probe in `PORTAL-CXTP-058` marked the TypeScript compiler
as a required missing dependency. The crypto-exchange workflow needs `tsc` to
compile and validate emitted proof-consumer schemas.

This remediation uses the repo-scoped toolchain under:

```text
security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin/tsc
```

It avoids a global npm install and records the exact compiler path, version, and
digest in:

```text
security_ir_artifacts/environment/typescript-remediation-report.json
```

## Command

Run from the repository root:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/provision_required_typescript_toolchain.py \
  --probe security_ir_artifacts/environment/solver-dependency-probe.json \
  --out security_ir_artifacts/environment/typescript-remediation-report.json
```

The script prepends the repo-scoped TypeScript `.bin` directory to `PATH` only
for the refreshed dependency probe. It then overwrites
`security_ir_artifacts/environment/solver-dependency-probe.json` with the
refreshed evidence.

For manual shell work, use:

```bash
export PATH="security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin:$PATH"
tsc --version
```

## Acceptance

The task is remediated when:

- the repo-scoped `tsc` executable exists;
- `tsc --version` exits zero;
- the refreshed solver dependency probe reports TypeScript as `present`;
- `typescript` no longer appears in `blocking_evidence`;
- optional solver gaps remain explicit capability gaps and do not turn into
  claimed coverage.

If the repo-scoped compiler is missing, rebuild it only after reviewing the npm
package/version:

```bash
npm install --prefix security_ir_artifacts/environment/typescript_toolchain typescript@5.5.4
```

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_typescript_dependency_remediation.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/provision_required_typescript_toolchain.py \
  --probe security_ir_artifacts/environment/solver-dependency-probe.json \
  --out security_ir_artifacts/environment/typescript-remediation-report.json
```
