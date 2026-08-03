import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  RUNTIME_MTL_INTERFACE,
  RuntimeMTLMonitor,
  evaluateCase,
  evaluatePortable,
  goldenFixtures,
  normalizeFormula,
  type MonitorEvaluationDict,
} from "../src/index.js";

function assertExpected(
  result: MonitorEvaluationDict,
  expected: Partial<MonitorEvaluationDict>,
  caseId: string,
): void {
  for (const [key, value] of Object.entries(expected)) {
    assert.equal(
      (result as unknown as Record<string, unknown>)[key],
      value,
      `${caseId}: field ${key}`,
    );
  }
  assert.equal(result.authority, "monitor", `${caseId}: authority`);
  assert.equal(result.authorizes_global_proof, false, `${caseId}: proof ceiling`);
  assert.equal(result.interface, RUNTIME_MTL_INTERFACE, `${caseId}: interface`);
}

describe("logic-runtime-mtl", () => {
  it("matches golden fixtures", () => {
    for (const fixture of goldenFixtures()) {
      const result = evaluateCase(fixture);
      assertExpected(result, fixture.expected ?? {}, fixture.case_id ?? "case");
    }
  });

  it("never authorizes global proof on clean prefixes", () => {
    const prefix = goldenFixtures().find((c) => c.case_id === "prefix-always-inconclusive");
    assert.ok(prefix);
    const result = evaluatePortable(prefix.formula, prefix.trace, 0);
    assert.equal(result.verdict, "inconclusive");
    assert.equal(result.status, "unknown");
    assert.equal(result.authorizes_global_proof, false);
    assert.equal(result.authority, "monitor");
  });

  it("agrees on closed vs open MTL interval boundaries", () => {
    const closed = goldenFixtures().find(
      (c) => c.case_id === "mtl-closed-interval-includes-boundary",
    );
    const open = goldenFixtures().find(
      (c) => c.case_id === "mtl-open-upper-excludes-boundary",
    );
    assert.ok(closed && open);
    assert.equal(evaluateCase(closed).verdict, "true");
    assert.equal(evaluateCase(open).verdict, "false");
  });

  it("flags late (non-monotonic) events without granting proof authority", () => {
    const late = goldenFixtures().find((c) => c.case_id === "late-event-malformed");
    assert.ok(late);
    const result = evaluateCase(late);
    assert.equal(result.status, "malformed");
    assert.equal(result.late_events, true);
    assert.equal(result.authority, "monitor");
    assert.equal(result.authorizes_global_proof, false);
  });

  it("serializes deterministically for parity", () => {
    const fixture = goldenFixtures()[0]!;
    const a = evaluateCase(fixture);
    const b = evaluateCase(fixture);
    assert.equal(JSON.stringify(a), JSON.stringify(b));
    const monitor = new RuntimeMTLMonitor(fixture.formula, fixture.position ?? 0);
    const again = monitor.evaluate(fixture.trace);
    assert.equal(again.verdict, a.verdict);
    assert.equal(again.authority, "monitor");
  });

  it("assigns stable structural node ids", () => {
    const formula = goldenFixtures()[0]!.formula;
    const first = normalizeFormula(formula);
    const second = normalizeFormula(formula);
    assert.equal(first.nodeId, second.nodeId);
    assert.match(first.nodeId, /^node:[0-9a-f]{16}$/);
  });

  it("treats missing explicit observations as inconclusive", () => {
    const missing = goldenFixtures().find(
      (c) => c.case_id === "explicit-missing-atom-inconclusive",
    );
    assert.ok(missing);
    const result = evaluateCase(missing);
    assert.equal(result.verdict, "inconclusive");
    assert.equal(result.missing_observation, true);
  });
});
