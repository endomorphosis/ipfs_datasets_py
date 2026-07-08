export type SecurityRecord = Record<string, unknown>;
export type ReviewStatus = "heuristic" | "machine_extracted" | "human_reviewed" | "trusted_fixture";
export type ProofStatus = "DISPROVED" | "NOT_MODELED" | "PROVED" | "UNKNOWN";
export type ProofRisk = "blocking" | "high" | "low" | "medium";
export type ProofReportCidPolicy = "deterministic" | "nondeterministic";
export type VerificationMode = "schema_only" | "proof_critical";

export interface EvidenceRef {
  kind: string;
  path: string;
  line_start?: number;
  line_end?: number;
  sha256?: string;
  review_status: ReviewStatus;
  notes?: string;
}

export interface SecurityAssumption {
  id: string;
  description: string;
  custom?: boolean;
}

export interface SecurityModelIR {
  schema_version: string;
  model_id: string;
  entities: SecurityRecord[];
  assets: SecurityRecord[];
  wallets: SecurityRecord[];
  accounts: SecurityRecord[];
  roles: SecurityRecord[];
  principals: SecurityRecord[];
  capabilities: SecurityRecord[];
  policies: SecurityRecord[];
  events: SecurityRecord[];
  state_machines: SecurityRecord[];
  invariants: SecurityRecord[];
  assumptions: Array<SecurityAssumption | string>;
  prover_targets: string[];
  metadata: SecurityRecord;
}

export interface ProofReport {
  schema_version: string;
  claim_id: string;
  claim_version: string;
  model_cid: string;
  model_schema_version: string;
  status: ProofStatus;
  prover: string;
  solver_name: string;
  solver_version: string;
  solver_result: string;
  proof_or_trace_cid: string;
  assumptions: string[];
  compiler_cid: string;
  risk: ProofRisk;
  timeout_ms?: number | null;
  reason_unknown?: string | null;
  assertion_count?: number | null;
  evidence_refs: EvidenceRef[];
  soundness_notes: string[];
  deterministic_payload_cid: string;
  nondeterministic_report_cid: string;
  generated_at: string;
  counterexample?: SecurityRecord | null;
}

export interface ProofReceipt {
  schema_version: string;
  report_schema_version: string;
  claim_id: string;
  model_cid: string;
  proof_report_cid: string;
  accepted_assumptions: string[];
  verifier: string;
  verifier_version: string;
  valid: boolean;
  metadata: SecurityRecord;
}

export const SECURITY_MODEL_IR_SCHEMA_VERSION = "security-model-ir/v1" as const;
export const SECURITY_ARTIFACT_METADATA = {
  "assumptionIds": [
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "A7",
    "A8",
    "A9",
    "A10"
  ],
  "proofReceiptSchemaVersion": "proof-receipt/v1",
  "proofReportSchemaVersion": "proof-report/v1",
  "proofRisks": [
    "blocking",
    "high",
    "low",
    "medium"
  ],
  "proofStatuses": [
    "DISPROVED",
    "NOT_MODELED",
    "PROVED",
    "UNKNOWN"
  ],
  "proverTargets": [
    "z3"
  ],
  "requiredFields": [
    "entities",
    "assets",
    "wallets",
    "accounts",
    "roles",
    "principals",
    "capabilities",
    "policies",
    "events",
    "state_machines",
    "invariants",
    "assumptions",
    "prover_targets"
  ],
  "schemaVersion": "security-model-ir/v1"
} as const;
export const PROOF_STATUSES = SECURITY_ARTIFACT_METADATA.proofStatuses;
export const PROOF_RISKS = SECURITY_ARTIFACT_METADATA.proofRisks;

export function canonicalizeJson(value: unknown): string {
  // TODO: mirror the Python canonicalization byte-for-byte before using this for proof checking.
  const normalize = (input: unknown): unknown => {
    if (Array.isArray(input)) {
      return input.map((item) => normalize(item));
    }
    if (input && typeof input === "object") {
      return Object.fromEntries(Object.entries(input as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, normalize(item)]));
    }
    return input;
  };
  return JSON.stringify(normalize(value));
}

export function validateSecurityModelIR(value: unknown): value is SecurityModelIR {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.schema_version !== "string" || typeof candidate.model_id !== "string") {
    return false;
  }
  return SECURITY_ARTIFACT_METADATA.requiredFields.every((field) => Array.isArray(candidate[field]));
}

export function validateProofReport(value: unknown): value is ProofReport {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.schema_version === "string"
    && typeof candidate.claim_id === "string"
    && typeof candidate.model_cid === "string"
    && typeof candidate.status === "string"
    && typeof candidate.prover === "string"
    && Array.isArray(candidate.assumptions)
    && Array.isArray(candidate.evidence_refs)
    && Array.isArray(candidate.soundness_notes)
    && typeof candidate.deterministic_payload_cid === "string"
    && typeof candidate.nondeterministic_report_cid === "string";
}

export function validateProofReceipt(value: unknown): value is ProofReceipt {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.schema_version === "string"
    && typeof candidate.claim_id === "string"
    && typeof candidate.model_cid === "string"
    && typeof candidate.proof_report_cid === "string"
    && Array.isArray(candidate.accepted_assumptions)
    && typeof candidate.verifier === "string"
    && typeof candidate.verifier_version === "string"
    && typeof candidate.valid === "boolean";
}

export function validateProofReportStrict(value: unknown): value is ProofReport {
  if (!validateProofReport(value)) {
    return false;
  }
  const candidate = value as ProofReport;
  return candidate.schema_version === SECURITY_ARTIFACT_METADATA.proofReportSchemaVersion
    && (PROOF_STATUSES as readonly string[]).includes(candidate.status)
    && (PROOF_RISKS as readonly string[]).includes(candidate.risk);
}

export function validateProofReceiptStrict(value: unknown): value is ProofReceipt {
  if (!validateProofReceipt(value)) {
    return false;
  }
  const candidate = value as ProofReceipt;
  return candidate.schema_version === SECURITY_ARTIFACT_METADATA.proofReceiptSchemaVersion
    && candidate.report_schema_version === SECURITY_ARTIFACT_METADATA.proofReportSchemaVersion;
}

export function verifyProofStatus(report: ProofReport, allowedStatuses: ProofStatus[] = ["PROVED"]): boolean {
  return allowedStatuses.includes(report.status);
}

export function verifyExpectedModelAndClaim(
  receipt: ProofReceipt,
  report: ProofReport,
  options?: { expectedModelCid?: string; expectedClaimId?: string },
): boolean {
  if (options?.expectedModelCid && report.model_cid !== options.expectedModelCid) {
    return false;
  }
  if (options?.expectedClaimId && report.claim_id !== options.expectedClaimId) {
    return false;
  }
  return receipt.model_cid === report.model_cid && receipt.claim_id === report.claim_id;
}

export function verifyAcceptedAssumptions(receipt: ProofReceipt, report: ProofReport): boolean {
  return report.assumptions.every((assumption) => receipt.accepted_assumptions.includes(assumption));
}

export function verifyReportMatchesReceipt(
  receipt: ProofReceipt,
  report: ProofReport,
  proofReportCidPolicy: ProofReportCidPolicy = "nondeterministic",
): boolean {
  const expectedCid = proofReportCidPolicy === "deterministic"
    ? report.deterministic_payload_cid
    : report.nondeterministic_report_cid;
  return receipt.claim_id === report.claim_id
    && receipt.model_cid === report.model_cid
    && receipt.report_schema_version === report.schema_version
    && receipt.proof_report_cid === expectedCid;
}

export function verifyProofReceiptSchemaOnly(
  receipt: unknown,
  report: unknown,
  options?: {
    expectedModelCid?: string;
    expectedClaimId?: string;
    proofReportCidPolicy?: ProofReportCidPolicy;
    allowedStatuses?: ProofStatus[];
  },
): boolean {
  if (!validateProofReceiptStrict(receipt) || !validateProofReportStrict(report)) {
    return false;
  }
  if (receipt.valid !== true) {
    return false;
  }
  return verifyProofStatus(report, options?.allowedStatuses ?? ["PROVED"])
    && verifyExpectedModelAndClaim(receipt, report, options)
    && verifyReportMatchesReceipt(receipt, report, options?.proofReportCidPolicy ?? "nondeterministic")
    && verifyAcceptedAssumptions(receipt, report);
}

export function verifyProofReceiptProofCritical(
  receipt: unknown,
  report: unknown,
  _options?: {
    expectedModelCid?: string;
    expectedClaimId?: string;
    proofReportCidPolicy?: ProofReportCidPolicy;
    allowedStatuses?: ProofStatus[];
    requireTrustedSignature?: boolean;
  },
): boolean {
  if (!validateProofReceiptStrict(receipt) || !validateProofReportStrict(report)) {
    return false;
  }
  // Fail closed until this runtime can recompute canonical CIDs byte-for-byte or
  // verify a trusted signature over the report payload.
  return false;
}

export function verifyProofReceipt(
  receipt: unknown,
  report: unknown,
  options?: {
    expectedModelCid?: string;
    expectedClaimId?: string;
    proofReportCidPolicy?: ProofReportCidPolicy;
    allowedStatuses?: ProofStatus[];
    mode?: VerificationMode;
  },
): boolean {
  return (options?.mode ?? "schema_only") === "proof_critical"
    ? verifyProofReceiptProofCritical(receipt, report, options)
    : verifyProofReceiptSchemaOnly(receipt, report, options);
}

export function verifyProofReceiptAssumptions(receipt: ProofReceipt, report: ProofReport): boolean {
  return report.assumptions.every((assumption) => (receipt.accepted_assumptions as readonly string[]).includes(assumption));
}
