/**
 * Portable finite-trace MTL/LTLf runtime monitor (RuntimeMTLMonitor@1).
 *
 * Python and TypeScript share golden fixtures and identical rational-time
 * three-valued semantics. Results always carry monitor authority;
 * no-violation-observed never becomes proof.
 */

export const RUNTIME_MTL_INTERFACE = "RuntimeMTLMonitor@1" as const;
export const RUNTIME_MTL_SCHEMA_VERSION = "runtime-mtl/v1" as const;
export const RUNTIME_MTL_RESULT_SCHEMA_VERSION = "runtime-mtl-result/v1" as const;
export const RUNTIME_MTL_FORMULA_SCHEMA_VERSION = "runtime-mtl-formula/v1" as const;
export const RUNTIME_MTL_TRACE_SCHEMA_VERSION = "runtime-mtl-trace/v1" as const;
export const RUNTIME_MTL_INTERVAL_SCHEMA_VERSION = "runtime-mtl-interval/v1" as const;

export type Logic = "ltlf" | "mtl";
export type TraceKind = "finite" | "finite_prefix";
export type Verdict = "true" | "false" | "inconclusive";
export type Observation = "true" | "false" | "unknown";
export type MonitorStatus = "satisfied" | "violated" | "unknown" | "malformed";
export type Monitorability =
  | "finite_trace"
  | "prefix"
  | "violation"
  | "satisfaction"
  | "not_finite_monitorable";
export type ObservationPolicyKind = "closed_world" | "explicit";
export type TimeUnit =
  | "nanosecond"
  | "microsecond"
  | "millisecond"
  | "second"
  | "minute"
  | "hour"
  | "logical_tick";
export type ClockDomain = "discrete" | "dense";

export interface TimeValueDict {
  numerator: number;
  denominator: number;
}

export interface TimeIntervalDict {
  lower: TimeValueDict;
  upper: TimeValueDict | null;
  unit: TimeUnit | string;
  lower_closed: boolean;
  upper_closed: boolean;
  schema_version?: string;
}

export interface FormulaDict {
  operator: string;
  logic: Logic | string;
  operands: FormulaDict[];
  proposition?: string;
  interval?: TimeIntervalDict | null;
  node_id?: string;
  schema_version?: string;
}

export interface ClockDict {
  clock_id: string;
  domain: ClockDomain | string;
  unit: TimeUnit | string;
  resolution: TimeValueDict;
}

export interface EventDict {
  event_id: string;
  event_type: string;
  time: TimeValueDict;
  true?: string[];
  false?: string[];
  true_propositions?: string[];
  false_propositions?: string[];
}

export interface TraceDict {
  clock: ClockDict;
  events: EventDict[];
  kind: TraceKind | string;
  observation_policy?: ObservationPolicyKind | string;
  schema_version?: string;
}

export interface MonitorEvaluationDict {
  authority: "monitor";
  authorizes_global_proof: false;
  interface: typeof RUNTIME_MTL_INTERFACE;
  late_events: boolean;
  logic: Logic | string;
  missing_observation: boolean;
  monitorability: Monitorability | string;
  position: number;
  reason: string;
  schema_version: typeof RUNTIME_MTL_RESULT_SCHEMA_VERSION;
  status: MonitorStatus;
  trace_kind: TraceKind | string;
  verdict: Verdict;
}

export interface EvaluationCase {
  case_id?: string;
  formula: FormulaDict;
  trace: TraceDict;
  position?: number;
  schema_version?: string;
  interface?: string;
  expected?: Partial<MonitorEvaluationDict>;
}

export class RuntimeMTLError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuntimeMTLError";
  }
}

// ---------------------------------------------------------------------------
// Exact rationals (bigint numerators/denominators)
// ---------------------------------------------------------------------------

function gcdBig(a: bigint, b: bigint): bigint {
  let x = a < 0n ? -a : a;
  let y = b < 0n ? -b : b;
  while (y !== 0n) {
    const t = x % y;
    x = y;
    y = t;
  }
  return x;
}

export class Rational {
  readonly n: bigint;
  readonly d: bigint;

  constructor(numerator: number | bigint, denominator: number | bigint = 1) {
    let n = typeof numerator === "bigint" ? numerator : BigInt(numerator);
    let d = typeof denominator === "bigint" ? denominator : BigInt(denominator);
    if (d === 0n) {
      throw new RuntimeMTLError("time denominator must be positive");
    }
    if (d < 0n) {
      n = -n;
      d = -d;
    }
    if (n < 0n) {
      throw new RuntimeMTLError("time values must be non-negative");
    }
    const g = gcdBig(n, d);
    this.n = n / g;
    this.d = d / g;
  }

  static fromDict(value: TimeValueDict | number): Rational {
    if (typeof value === "number") {
      if (!Number.isInteger(value)) {
        throw new RuntimeMTLError("floating-point timestamps are rejected; use exact rationals");
      }
      return new Rational(value, 1);
    }
    if (
      typeof value !== "object" ||
      value === null ||
      typeof value.numerator !== "number" ||
      typeof value.denominator !== "number"
    ) {
      throw new RuntimeMTLError("time value must be {numerator, denominator}");
    }
    if (!Number.isInteger(value.numerator) || !Number.isInteger(value.denominator)) {
      throw new RuntimeMTLError("time numerator/denominator must be integers");
    }
    return new Rational(value.numerator, value.denominator);
  }

  toDict(): TimeValueDict {
    return { numerator: Number(this.n), denominator: Number(this.d) };
  }

  add(other: Rational): Rational {
    return new Rational(this.n * other.d + other.n * this.d, this.d * other.d);
  }

  sub(other: Rational): Rational {
    const n = this.n * other.d - other.n * this.d;
    if (n < 0n) {
      // elapsed can be used only when non-negative in our paths; still allow internal
      return new Rational(0n, 1n); // callers only use non-negative differences
    }
    return new Rational(n, this.d * other.d);
  }

  /** Signed subtraction for comparisons; may be negative via compare. */
  private rawSub(other: Rational): { n: bigint; d: bigint } {
    return { n: this.n * other.d - other.n * this.d, d: this.d * other.d };
  }

  compare(other: Rational): number {
    const { n } = this.rawSub(other);
    if (n < 0n) return -1;
    if (n > 0n) return 1;
    return 0;
  }

  lt(other: Rational): boolean {
    return this.compare(other) < 0;
  }

  le(other: Rational): boolean {
    return this.compare(other) <= 0;
  }

  gt(other: Rational): boolean {
    return this.compare(other) > 0;
  }

  ge(other: Rational): boolean {
    return this.compare(other) >= 0;
  }

  eq(other: Rational): boolean {
    return this.compare(other) === 0;
  }

  modIsZero(resolution: Rational): boolean {
    // (n/d) % (rn/rd) == 0  <=>  n*rd is divisible by d*rn
    const left = this.n * resolution.d;
    const right = this.d * resolution.n;
    return left % right === 0n;
  }

  /** Elapsed this - other, requiring this >= other. */
  elapsedFrom(start: Rational): Rational {
    if (this.lt(start)) {
      throw new RuntimeMTLError("negative elapsed time");
    }
    const n = this.n * start.d - start.n * this.d;
    return new Rational(n, this.d * start.d);
  }
}

interface NormalizedInterval {
  lower: Rational;
  upper: Rational | null;
  unit: string;
  lowerClosed: boolean;
  upperClosed: boolean;
}

function normalizeInterval(raw: TimeIntervalDict): NormalizedInterval {
  const lower = Rational.fromDict(raw.lower);
  const upper = raw.upper === null || raw.upper === undefined ? null : Rational.fromDict(raw.upper);
  const lowerClosed = raw.lower_closed !== false;
  const upperClosed = raw.upper_closed !== false;
  if (upper !== null) {
    if (upper.lt(lower)) {
      throw new RuntimeMTLError("interval upper boundary must not precede lower boundary");
    }
    if (upper.eq(lower) && !(lowerClosed && upperClosed)) {
      throw new RuntimeMTLError("interval must not be empty");
    }
  } else if (!upperClosed) {
    throw new RuntimeMTLError(
      "an unbounded upper boundary must use upper_closed=True canonically",
    );
  }
  return {
    lower,
    upper,
    unit: String(raw.unit),
    lowerClosed,
    upperClosed,
  };
}

function intervalContains(interval: NormalizedInterval, elapsed: Rational): boolean {
  const lowerOk = interval.lowerClosed
    ? elapsed.ge(interval.lower)
    : elapsed.gt(interval.lower);
  if (interval.upper === null) {
    return lowerOk;
  }
  const upperOk = interval.upperClosed
    ? elapsed.le(interval.upper)
    : elapsed.lt(interval.upper);
  return lowerOk && upperOk;
}

function horizonIsPast(interval: NormalizedInterval, elapsed: Rational): boolean {
  if (interval.upper === null) {
    return false;
  }
  return interval.upperClosed ? elapsed.gt(interval.upper) : elapsed.ge(interval.upper);
}

// ---------------------------------------------------------------------------
// Formula / trace normalization
// ---------------------------------------------------------------------------

const NULLARY = new Set(["true", "false", "atom"]);
const UNARY = new Set(["not", "next", "previous", "eventually", "always"]);
const BINARY = new Set([
  "and",
  "or",
  "implies",
  "until",
  "release",
  "weak_until",
  "since",
]);
const TEMPORAL = new Set([
  "next",
  "previous",
  "eventually",
  "always",
  "until",
  "release",
  "weak_until",
  "since",
]);
const FUTURE = new Set([
  "next",
  "eventually",
  "always",
  "until",
  "release",
  "weak_until",
]);

const ATOM_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;

function requireId(value: unknown, label: string): string {
  if (typeof value !== "string" || !value || value.trim() !== value || value.includes("\0")) {
    throw new RuntimeMTLError(`${label} must be a non-empty trimmed string without NUL bytes`);
  }
  if (!ATOM_RE.test(value)) {
    throw new RuntimeMTLError(`${label} must be a stable identifier`);
  }
  return value;
}

function sortedUnique(values: string[], label: string): string[] {
  const sorted = [...values].map((v) => requireId(v, `${label} item`)).sort();
  if (new Set(sorted).size !== sorted.length) {
    throw new RuntimeMTLError(`${label} must not contain duplicates`);
  }
  return sorted;
}

/** FNV-1a 64-bit over UTF-8, matching the Python structural node id. */
function fnv1a64Hex(payload: string): string {
  let hash = 0xcbf29ce484222325n;
  const bytes = new TextEncoder().encode(payload);
  for (const byte of bytes) {
    hash ^= BigInt(byte);
    hash = (hash * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  return hash.toString(16).padStart(16, "0");
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(",")}}`;
}

export interface NormalizedFormula {
  operator: string;
  logic: Logic;
  operands: NormalizedFormula[];
  proposition: string;
  interval: NormalizedInterval | null;
  nodeId: string;
  semantic: FormulaDict;
}

function semanticFormula(node: {
  operator: string;
  logic: Logic;
  operands: NormalizedFormula[];
  proposition: string;
  interval: NormalizedInterval | null;
}): FormulaDict {
  return {
    interval:
      node.interval === null
        ? null
        : {
            lower: node.interval.lower.toDict(),
            upper: node.interval.upper === null ? null : node.interval.upper.toDict(),
            unit: node.interval.unit,
            lower_closed: node.interval.lowerClosed,
            upper_closed: node.interval.upperClosed,
            schema_version: RUNTIME_MTL_INTERVAL_SCHEMA_VERSION,
          },
    logic: node.logic,
    operands: node.operands.map((o) => o.semantic),
    operator: node.operator,
    proposition: node.proposition,
    schema_version: RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
  };
}

export function normalizeFormula(raw: FormulaDict): NormalizedFormula {
  const operator = String(raw.operator ?? "").toLowerCase();
  const logic = String(raw.logic ?? "ltlf") as Logic;
  if (logic !== "ltlf" && logic !== "mtl") {
    throw new RuntimeMTLError("logic must be one of 'ltlf', 'mtl'");
  }
  const operands = (raw.operands ?? []).map((item) => normalizeFormula(item));
  let proposition = raw.proposition ?? "";
  const interval =
    raw.interval === null || raw.interval === undefined
      ? null
      : normalizeInterval(raw.interval);

  let expected = 2;
  if (NULLARY.has(operator)) expected = 0;
  else if (UNARY.has(operator)) expected = 1;
  else if (BINARY.has(operator)) expected = 2;
  else throw new RuntimeMTLError(`unsupported operator ${operator}`);

  if (operands.length !== expected) {
    throw new RuntimeMTLError(`${operator} requires ${expected} operand(s)`);
  }
  if (operands.some((op) => op.logic !== logic)) {
    throw new RuntimeMTLError("every operand must use the same logic as its parent");
  }
  if (operator === "atom") {
    proposition = requireId(proposition, "proposition");
  } else if (proposition) {
    throw new RuntimeMTLError("proposition is only valid for the atom operator");
  }
  if (logic === "mtl") {
    if (TEMPORAL.has(operator) && interval === null) {
      throw new RuntimeMTLError("MTL temporal operators require an explicit interval");
    }
  } else if (interval !== null) {
    throw new RuntimeMTLError("intervals are only valid for MTL");
  }

  const partial = { operator, logic, operands, proposition, interval };
  const semantic = semanticFormula(partial);
  const nodeId = `node:${fnv1a64Hex(stableStringify(semantic))}`;
  return { ...partial, nodeId, semantic };
}

export interface NormalizedEvent {
  eventId: string;
  eventType: string;
  time: Rational;
  trueProps: string[];
  falseProps: string[];
}

export interface NormalizedTrace {
  clockId: string;
  domain: string;
  unit: string;
  resolution: Rational;
  events: NormalizedEvent[];
  kind: TraceKind;
  observationPolicy: ObservationPolicyKind;
}

export function normalizeTrace(raw: TraceDict): NormalizedTrace {
  const clock = raw.clock;
  if (!clock) throw new RuntimeMTLError("trace requires a clock");
  const clockId = requireId(clock.clock_id, "clock_id");
  const domain = String(clock.domain ?? "discrete");
  const unit = String(clock.unit ?? "logical_tick");
  const resolution = Rational.fromDict(clock.resolution ?? { numerator: 1, denominator: 1 });
  if (resolution.n === 0n) {
    throw new RuntimeMTLError("clock resolution must be greater than zero");
  }
  if (domain === "discrete" && resolution.d !== 1n) {
    throw new RuntimeMTLError("discrete clock resolution must be a whole number of units");
  }
  const kind = String(raw.kind) as TraceKind;
  if (kind !== "finite" && kind !== "finite_prefix") {
    throw new RuntimeMTLError("kind must be one of 'finite', 'finite_prefix'");
  }
  const observationPolicy = String(
    raw.observation_policy ?? "closed_world",
  ) as ObservationPolicyKind;
  if (observationPolicy !== "closed_world" && observationPolicy !== "explicit") {
    throw new RuntimeMTLError("observation_policy must be closed_world or explicit");
  }
  const eventsRaw = raw.events ?? [];
  if (eventsRaw.length === 0) {
    throw new RuntimeMTLError("trace requires at least one event");
  }
  const events: NormalizedEvent[] = [];
  const seen = new Set<string>();
  let previous: Rational | null = null;
  for (const item of eventsRaw) {
    const eventId = requireId(item.event_id, "event_id");
    if (seen.has(eventId)) {
      throw new RuntimeMTLError("event identifiers must be unique");
    }
    seen.add(eventId);
    const trueProps = sortedUnique(item.true ?? item.true_propositions ?? [], "true");
    const falseProps = sortedUnique(item.false ?? item.false_propositions ?? [], "false");
    const overlap = trueProps.filter((p) => falseProps.includes(p));
    if (overlap.length) {
      throw new RuntimeMTLError(`propositions cannot be both true and false: ${overlap}`);
    }
    const time = Rational.fromDict(item.time);
    if (!time.modIsZero(resolution)) {
      throw new RuntimeMTLError(
        `event ${eventId} time is not a multiple of clock resolution`,
      );
    }
    if (previous !== null && time.lt(previous)) {
      throw new RuntimeMTLError("event timestamps must be non-decreasing on the primary clock");
    }
    previous = time;
    events.push({
      eventId,
      eventType: requireId(item.event_type ?? "state", "event_type"),
      time,
      trueProps,
      falseProps,
    });
  }
  return {
    clockId,
    domain,
    unit,
    resolution,
    events,
    kind,
    observationPolicy,
  };
}

function observe(
  trace: NormalizedTrace,
  index: number,
  proposition: string,
): Observation {
  const event = trace.events[index]!;
  if (event.trueProps.includes(proposition)) return "true";
  if (event.falseProps.includes(proposition)) return "false";
  if (trace.observationPolicy === "closed_world") return "false";
  return "unknown";
}

// ---------------------------------------------------------------------------
// Three-valued evaluation
// ---------------------------------------------------------------------------

function notObs(value: Observation): Observation {
  if (value === "true") return "false";
  if (value === "false") return "true";
  return "unknown";
}

function andObs(left: Observation, right: Observation): Observation {
  if (left === "false" || right === "false") return "false";
  if (left === "true" && right === "true") return "true";
  return "unknown";
}

function orObs(left: Observation, right: Observation): Observation {
  if (left === "true" || right === "true") return "true";
  if (left === "false" && right === "false") return "false";
  return "unknown";
}

function foldObs(
  values: Observation[],
  op: (a: Observation, b: Observation) => Observation,
  identity: Observation,
): Observation {
  let result = identity;
  for (const value of values) {
    result = op(result, value);
  }
  return result;
}

function allFutureBoundsFinite(formula: NormalizedFormula): boolean {
  if (FUTURE.has(formula.operator)) {
    if (formula.interval === null || formula.interval.upper === null) {
      return false;
    }
  }
  return formula.operands.every(allFutureBoundsFinite);
}

export function classifyMonitorability(formula: NormalizedFormula): Monitorability {
  if (formula.logic === "ltlf") return "finite_trace";
  if (formula.logic === "mtl" && allFutureBoundsFinite(formula)) return "prefix";
  if (formula.operator === "always") return "violation";
  if (formula.operator === "eventually" || formula.operator === "until") return "satisfaction";
  if (
    [
      "true",
      "false",
      "atom",
      "not",
      "and",
      "or",
      "implies",
      "next",
      "previous",
      "since",
    ].includes(formula.operator)
  ) {
    return "prefix";
  }
  return "not_finite_monitorable";
}

function checkMetricUnit(formula: NormalizedFormula, trace: NormalizedTrace): void {
  if (formula.interval !== null && formula.interval.unit !== trace.unit) {
    throw new RuntimeMTLError("MTL interval unit does not match the trace primary clock");
  }
  for (const operand of formula.operands) {
    checkMetricUnit(operand, trace);
  }
}

function untimedFutureValues(
  operator: string,
  children: Observation[][],
  count: number,
  monitoring: boolean,
): Observation[] {
  let carry: Observation =
    operator === "eventually" || operator === "until"
      ? monitoring
        ? "unknown"
        : "false"
      : monitoring
        ? "unknown"
        : "true";
  const result: Observation[] = Array.from({ length: count }, () => "unknown");
  for (let index = count - 1; index >= 0; index -= 1) {
    if (operator === "eventually") {
      carry = orObs(children[0]![index]!, carry);
    } else if (operator === "always") {
      carry = andObs(children[0]![index]!, carry);
    } else if (operator === "until") {
      carry = orObs(children[1]![index]!, andObs(children[0]![index]!, carry));
    } else if (operator === "release") {
      carry = andObs(children[1]![index]!, orObs(children[0]![index]!, carry));
    } else {
      carry = orObs(children[1]![index]!, andObs(children[0]![index]!, carry));
    }
    result[index] = carry;
  }
  return result;
}

function metricUntilAt(
  left: Observation[],
  right: Observation[],
  eligible: number[],
  start: number,
): Observation {
  const candidates = eligible.map((witness) =>
    andObs(
      right[witness]!,
      foldObs(
        left.slice(start, witness),
        andObs,
        "true",
      ),
    ),
  );
  return foldObs(candidates, orObs, "false");
}

function metricValues(
  node: NormalizedFormula,
  children: Observation[][],
  trace: NormalizedTrace,
  monitoring: boolean,
): Observation[] {
  const interval = node.interval!;
  const count = trace.events.length;
  const times = trace.events.map((e) => e.time);
  const results: Observation[] = [];
  for (let start = 0; start < count; start += 1) {
    const eligible: number[] = [];
    for (let index = start; index < count; index += 1) {
      const elapsed = times[index]!.elapsedFrom(times[start]!);
      if (intervalContains(interval, elapsed)) {
        eligible.push(index);
      }
    }
    const elapsed = times[count - 1]!.elapsedFrom(times[start]!);
    const horizonComplete = !monitoring || horizonIsPast(interval, elapsed);
    const operator = node.operator;
    if (operator === "next") {
      if (start + 1 < count) {
        const step = times[start + 1]!.elapsedFrom(times[start]!);
        results.push(
          intervalContains(interval, step) ? children[0]![start + 1]! : "false",
        );
      } else {
        results.push(monitoring ? "unknown" : "false");
      }
      continue;
    }
    if (operator === "previous") {
      if (start === 0) {
        results.push("false");
      } else {
        const step = times[start]!.elapsedFrom(times[start - 1]!);
        results.push(
          intervalContains(interval, step) ? children[0]![start - 1]! : "false",
        );
      }
      continue;
    }
    if (operator === "eventually") {
      const observed = foldObs(
        eligible.map((i) => children[0]![i]!),
        orObs,
        "false",
      );
      results.push(observed === "true" || horizonComplete ? observed : "unknown");
      continue;
    }
    if (operator === "always") {
      const observed = foldObs(
        eligible.map((i) => children[0]![i]!),
        andObs,
        "true",
      );
      results.push(observed === "false" || horizonComplete ? observed : "unknown");
      continue;
    }
    if (operator === "until" || operator === "since") {
      if (operator === "since") {
        const candidates: number[] = [];
        for (let index = 0; index <= start; index += 1) {
          const elapsedBack = times[start]!.elapsedFrom(times[index]!);
          if (intervalContains(interval, elapsedBack)) {
            candidates.push(index);
          }
        }
        candidates.reverse();
        const candidateValues = candidates.map((witness) =>
          andObs(
            children[1]![witness]!,
            foldObs(
              children[0]!.slice(witness + 1, start + 1),
              andObs,
              "true",
            ),
          ),
        );
        results.push(foldObs(candidateValues, orObs, "false"));
      } else {
        const candidateValues = eligible.map((witness) =>
          andObs(
            children[1]![witness]!,
            foldObs(children[0]!.slice(start, witness), andObs, "true"),
          ),
        );
        const observed = foldObs(candidateValues, orObs, "false");
        const observedLeft = foldObs(
          children[0]!.slice(start, count),
          andObs,
          "true",
        );
        results.push(
          observed === "true" || observedLeft === "false" || horizonComplete
            ? observed
            : "unknown",
        );
      }
      continue;
    }
    if (operator === "release" || operator === "weak_until") {
      const untilNegated = metricUntilAt(
        children[0]!.map(notObs),
        children[1]!.map(notObs),
        eligible,
        start,
      );
      const release = notObs(untilNegated);
      let observed: Observation;
      let untilValue: Observation = "false";
      if (operator === "release") {
        observed = release;
      } else {
        untilValue = metricUntilAt(children[0]!, children[1]!, eligible, start);
        const globallyLeft = foldObs(
          eligible.map((i) => children[0]![i]!),
          andObs,
          "true",
        );
        observed = orObs(untilValue, globallyLeft);
      }
      if (
        !horizonComplete &&
        observed === "true" &&
        (operator === "release" || untilValue !== "true")
      ) {
        observed = "unknown";
      }
      results.push(observed);
      continue;
    }
    throw new RuntimeMTLError(`metric semantics are unsupported for ${operator}`);
  }
  return results;
}

function finiteTables(
  formula: NormalizedFormula,
  trace: NormalizedTrace,
  monitoring: boolean,
): Map<string, Observation[]> {
  const count = trace.events.length;
  const cache = new Map<string, Observation[]>();

  function table(node: NormalizedFormula): Observation[] {
    const cached = cache.get(node.nodeId);
    if (cached) return cached;
    const operator = node.operator;
    const children = node.operands.map((op) => table(op));
    let values: Observation[];
    if (operator === "true") {
      values = Array.from({ length: count }, () => "true" as Observation);
    } else if (operator === "false") {
      values = Array.from({ length: count }, () => "false" as Observation);
    } else if (operator === "atom") {
      values = Array.from({ length: count }, (_, index) =>
        observe(trace, index, node.proposition),
      );
    } else if (operator === "not") {
      values = children[0]!.map(notObs);
    } else if (operator === "and") {
      values = children[0]!.map((left, i) => andObs(left, children[1]![i]!));
    } else if (operator === "or") {
      values = children[0]!.map((left, i) => orObs(left, children[1]![i]!));
    } else if (operator === "implies") {
      values = children[0]!.map((left, i) => orObs(notObs(left), children[1]![i]!));
    } else if (operator === "previous" && node.interval === null) {
      values = ["false", ...children[0]!.slice(0, -1)];
    } else if (operator === "since" && node.interval === null) {
      const valuesList: Observation[] = [];
      let carry: Observation = "false";
      for (let i = 0; i < count; i += 1) {
        carry = orObs(children[1]![i]!, andObs(children[0]![i]!, carry));
        valuesList.push(carry);
      }
      values = valuesList;
    } else if (node.interval !== null) {
      values = metricValues(node, children, trace, monitoring);
    } else if (operator === "next") {
      const terminal: Observation = monitoring ? "unknown" : "false";
      values = [...children[0]!.slice(1), terminal];
    } else if (
      operator === "eventually" ||
      operator === "always" ||
      operator === "until" ||
      operator === "release" ||
      operator === "weak_until"
    ) {
      values = untimedFutureValues(operator, children, count, monitoring);
    } else {
      throw new RuntimeMTLError(`unsupported operator during evaluation: ${operator}`);
    }
    cache.set(node.nodeId, values);
    return values;
  }

  table(formula);
  return cache;
}

function hasUnknownAtom(formula: NormalizedFormula, trace: NormalizedTrace): boolean {
  if (formula.operator === "atom") {
    return trace.events.some((_, index) => observe(trace, index, formula.proposition) === "unknown");
  }
  return formula.operands.some((op) => hasUnknownAtom(op, trace));
}

function toVerdict(value: Observation): Verdict {
  if (value === "true") return "true";
  if (value === "false") return "false";
  return "inconclusive";
}

function toStatus(verdict: Verdict): MonitorStatus {
  if (verdict === "true") return "satisfied";
  if (verdict === "false") return "violated";
  return "unknown";
}

function malformedResult(
  reason: string,
  opts: {
    lateEvents?: boolean;
    logic?: Logic | string;
    traceKind?: TraceKind | string;
    monitorability?: Monitorability;
    position?: number;
  } = {},
): MonitorEvaluationDict {
  return {
    authority: "monitor",
    authorizes_global_proof: false,
    interface: RUNTIME_MTL_INTERFACE,
    late_events: opts.lateEvents ?? false,
    logic: opts.logic ?? "ltlf",
    missing_observation: false,
    monitorability: opts.monitorability ?? "prefix",
    position: opts.position ?? 0,
    reason,
    schema_version: RUNTIME_MTL_RESULT_SCHEMA_VERSION,
    status: "malformed",
    trace_kind: opts.traceKind ?? "finite",
    verdict: "inconclusive",
  };
}

export class RuntimeMTLMonitor {
  readonly formula: NormalizedFormula;
  readonly position: number;

  constructor(formula: FormulaDict | NormalizedFormula, position = 0) {
    this.formula =
      "nodeId" in formula && "semantic" in formula
        ? (formula as NormalizedFormula)
        : normalizeFormula(formula as FormulaDict);
    if (!Number.isInteger(position) || position < 0) {
      throw new RuntimeMTLError("position must be a non-negative integer");
    }
    this.position = position;
  }

  evaluate(traceRaw: TraceDict): MonitorEvaluationDict {
    let trace: NormalizedTrace;
    try {
      trace = normalizeTrace(traceRaw);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return malformedResult(message, {
        lateEvents: message.includes("non-decreasing"),
        logic: this.formula.logic,
        monitorability: classifyMonitorability(this.formula),
        position: this.position,
      });
    }
    if (this.position >= trace.events.length) {
      return malformedResult("position is outside the trace", {
        logic: this.formula.logic,
        traceKind: trace.kind,
        monitorability: classifyMonitorability(this.formula),
        position: this.position,
      });
    }
    // Finite prefixes are always monitored conservatively (LTLf or MTL).
    const monitoring = trace.kind === "finite_prefix";
    if (
      this.formula.logic === "ltlf" &&
      !monitoring &&
      trace.kind !== "finite"
    ) {
      return malformedResult("LTLf requires a complete finite or finite_prefix trace", {
        logic: this.formula.logic,
        traceKind: trace.kind,
        monitorability: classifyMonitorability(this.formula),
        position: this.position,
      });
    }
    if (this.formula.logic === "mtl") {
      try {
        checkMetricUnit(this.formula, trace);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return malformedResult(message, {
          logic: this.formula.logic,
          traceKind: trace.kind,
          monitorability: classifyMonitorability(this.formula),
          position: this.position,
        });
      }
    }
    const tables = finiteTables(this.formula, trace, monitoring);
    const value = tables.get(this.formula.nodeId)![this.position]!;
    const verdict = toVerdict(value);
    let reason: string;
    if (monitoring) {
      reason =
        "conservative finite-prefix verdict; no-violation-observed never becomes proof";
    } else if (this.formula.logic === "mtl") {
      reason = "exact MTL semantics over the supplied complete finite timed trace";
    } else {
      reason = "exact LTLf semantics over the supplied complete finite trace";
    }
    return {
      authority: "monitor",
      authorizes_global_proof: false,
      interface: RUNTIME_MTL_INTERFACE,
      late_events: false,
      logic: this.formula.logic,
      missing_observation: hasUnknownAtom(this.formula, trace),
      monitorability: classifyMonitorability(this.formula),
      position: this.position,
      reason,
      schema_version: RUNTIME_MTL_RESULT_SCHEMA_VERSION,
      status: toStatus(verdict),
      trace_kind: trace.kind,
      verdict,
    };
  }

  monitor(traceRaw: TraceDict): MonitorEvaluationDict {
    let trace: NormalizedTrace;
    try {
      trace = normalizeTrace(traceRaw);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return malformedResult(message, {
        lateEvents: message.includes("non-decreasing"),
        logic: this.formula.logic,
        monitorability: classifyMonitorability(this.formula),
        position: this.position,
      });
    }
    if (trace.kind !== "finite_prefix") {
      return malformedResult("prefix monitoring requires a finite_prefix trace", {
        logic: this.formula.logic,
        traceKind: trace.kind,
        monitorability: classifyMonitorability(this.formula),
        position: this.position,
      });
    }
    return this.evaluate(traceRaw);
  }
}

export function evaluatePortable(
  formula: FormulaDict,
  trace: TraceDict,
  position = 0,
): MonitorEvaluationDict {
  return new RuntimeMTLMonitor(formula, position).evaluate(trace);
}

export function evaluateCase(payload: EvaluationCase): MonitorEvaluationDict {
  return evaluatePortable(payload.formula, payload.trace, payload.position ?? 0);
}

// ---------------------------------------------------------------------------
// Golden fixtures (must match Python golden_fixtures())
// ---------------------------------------------------------------------------

function tv(numerator: number, denominator = 1): TimeValueDict {
  return { numerator, denominator };
}

function event(
  index: number,
  trueProps: string[] = [],
  opts: {
    false?: string[];
    time?: number | [number, number];
    event_type?: string;
  } = {},
): EventDict {
  let timeValue: TimeValueDict;
  if (opts.time === undefined) {
    timeValue = tv(index);
  } else if (typeof opts.time === "number") {
    timeValue = tv(opts.time);
  } else {
    timeValue = tv(opts.time[0], opts.time[1]);
  }
  return {
    event_id: `event:${index}`,
    event_type: opts.event_type ?? "state",
    time: timeValue,
    true: trueProps,
    false: opts.false ?? [],
  };
}

function clock(opts: {
  unit?: string;
  domain?: string;
  resolution?: [number, number];
  clock_id?: string;
} = {}): ClockDict {
  const resolution = opts.resolution ?? [1, 1];
  return {
    clock_id: opts.clock_id ?? "clock:main",
    domain: opts.domain ?? "discrete",
    unit: opts.unit ?? "logical_tick",
    resolution: tv(resolution[0], resolution[1]),
  };
}

function trace(
  kind: TraceKind,
  events: EventDict[],
  opts: { clock?: ClockDict; policy?: ObservationPolicyKind } = {},
): TraceDict {
  return {
    kind,
    clock: opts.clock ?? clock(),
    events,
    observation_policy: opts.policy ?? "closed_world",
    schema_version: RUNTIME_MTL_TRACE_SCHEMA_VERSION,
  };
}

function atomF(name: string, logic: Logic = "ltlf"): FormulaDict {
  return {
    operator: "atom",
    logic,
    operands: [],
    proposition: name,
    interval: null,
    schema_version: RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
  };
}

function unaryF(
  operator: string,
  operand: FormulaDict,
  opts: { logic?: Logic; interval?: TimeIntervalDict | null } = {},
): FormulaDict {
  return {
    operator,
    logic: opts.logic ?? (operand.logic as Logic),
    operands: [operand],
    proposition: "",
    interval: opts.interval ?? null,
    schema_version: RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
  };
}

function binaryF(
  operator: string,
  left: FormulaDict,
  right: FormulaDict,
  opts: { logic?: Logic; interval?: TimeIntervalDict | null } = {},
): FormulaDict {
  return {
    operator,
    logic: opts.logic ?? (left.logic as Logic),
    operands: [left, right],
    proposition: "",
    interval: opts.interval ?? null,
    schema_version: RUNTIME_MTL_FORMULA_SCHEMA_VERSION,
  };
}

function interval(
  lower: number | [number, number],
  upper: number | [number, number] | null,
  unit: string,
  opts: { lower_closed?: boolean; upper_closed?: boolean } = {},
): TimeIntervalDict {
  const asTv = (value: number | [number, number]): TimeValueDict =>
    typeof value === "number" ? tv(value) : tv(value[0], value[1]);
  return {
    lower: asTv(lower),
    upper: upper === null ? null : asTv(upper),
    unit,
    lower_closed: opts.lower_closed !== false,
    upper_closed: opts.upper_closed !== false,
    schema_version: RUNTIME_MTL_INTERVAL_SCHEMA_VERSION,
  };
}

export function goldenFixtures(): EvaluationCase[] {
  const safe = atomF("safe");
  const done = atomF("done");
  const readyMtl = atomF("ready", "mtl");
  const safeMtl = atomF("safe", "mtl");

  const cases: EvaluationCase[] = [
    {
      case_id: "ltlf-always-holds",
      formula: unaryF("always", safe),
      trace: trace("finite", [
        event(0, ["safe"]),
        event(1, ["safe"]),
        event(2, ["safe", "done"]),
      ]),
      position: 0,
      expected: {
        verdict: "true",
        status: "satisfied",
        authority: "monitor",
        authorizes_global_proof: false,
        trace_kind: "finite",
        logic: "ltlf",
      },
    },
    {
      case_id: "ltlf-until-done",
      formula: binaryF("until", safe, done),
      trace: trace("finite", [
        event(0, ["safe"]),
        event(1, ["safe"]),
        event(2, ["safe", "done"]),
      ]),
      position: 0,
      expected: {
        verdict: "true",
        status: "satisfied",
        authority: "monitor",
        authorizes_global_proof: false,
        trace_kind: "finite",
        logic: "ltlf",
      },
    },
    {
      case_id: "prefix-always-inconclusive",
      formula: unaryF("always", safe),
      trace: trace("finite_prefix", [event(0, ["safe"]), event(1, ["safe"])]),
      position: 0,
      expected: {
        verdict: "inconclusive",
        status: "unknown",
        authority: "monitor",
        authorizes_global_proof: false,
        trace_kind: "finite_prefix",
        logic: "ltlf",
      },
    },
    {
      case_id: "prefix-always-violation",
      formula: unaryF("always", safe),
      trace: trace(
        "finite_prefix",
        [
          event(0, ["safe"]),
          event(1, ["safe", "done"]),
          event(2, [], { false: ["safe"] }),
        ],
        { policy: "explicit" },
      ),
      position: 0,
      expected: {
        verdict: "false",
        status: "violated",
        authority: "monitor",
        authorizes_global_proof: false,
        trace_kind: "finite_prefix",
        logic: "ltlf",
      },
    },
    {
      case_id: "prefix-eventually-witness",
      formula: unaryF("eventually", done),
      trace: trace("finite_prefix", [
        event(0, ["safe"]),
        event(1, ["safe", "done"]),
      ]),
      position: 0,
      expected: {
        verdict: "true",
        status: "satisfied",
        authority: "monitor",
        authorizes_global_proof: false,
        trace_kind: "finite_prefix",
        logic: "ltlf",
      },
    },
    {
      case_id: "explicit-missing-atom-inconclusive",
      formula: atomF("unobserved"),
      trace: trace("finite", [event(0)], { policy: "explicit" }),
      position: 0,
      expected: {
        verdict: "inconclusive",
        status: "unknown",
        authority: "monitor",
        authorizes_global_proof: false,
        missing_observation: true,
        logic: "ltlf",
      },
    },
    {
      case_id: "mtl-closed-interval-includes-boundary",
      formula: unaryF("eventually", readyMtl, {
        interval: interval(0, 1, "second"),
      }),
      trace: trace(
        "finite",
        [
          event(0, [], { time: [0, 1] }),
          event(1, [], { time: [1, 2] }),
          event(2, ["ready"], { time: [1, 1] }),
        ],
        { clock: clock({ unit: "second", domain: "dense", resolution: [1, 2] }) },
      ),
      position: 0,
      expected: {
        verdict: "true",
        status: "satisfied",
        authority: "monitor",
        authorizes_global_proof: false,
        logic: "mtl",
      },
    },
    {
      case_id: "mtl-open-upper-excludes-boundary",
      formula: unaryF("eventually", readyMtl, {
        interval: interval(0, 1, "second", { upper_closed: false }),
      }),
      trace: trace(
        "finite",
        [
          event(0, [], { time: [0, 1] }),
          event(1, [], { time: [1, 2] }),
          event(2, ["ready"], { time: [1, 1] }),
        ],
        { clock: clock({ unit: "second", domain: "dense", resolution: [1, 2] }) },
      ),
      position: 0,
      expected: {
        verdict: "false",
        status: "violated",
        authority: "monitor",
        authorizes_global_proof: false,
        logic: "mtl",
      },
    },
    {
      case_id: "mtl-prefix-before-horizon-inconclusive",
      formula: unaryF("eventually", readyMtl, {
        interval: interval(0, 2, "second"),
      }),
      trace: trace(
        "finite_prefix",
        [event(0, [], { time: 0 }), event(1, [], { time: 1 })],
        { clock: clock({ unit: "second" }) },
      ),
      position: 0,
      expected: {
        verdict: "inconclusive",
        status: "unknown",
        authority: "monitor",
        authorizes_global_proof: false,
        logic: "mtl",
        trace_kind: "finite_prefix",
      },
    },
    {
      case_id: "mtl-prefix-past-horizon-false",
      formula: unaryF("eventually", readyMtl, {
        interval: interval(0, 2, "second"),
      }),
      trace: trace(
        "finite_prefix",
        [
          event(0, [], { time: 0 }),
          event(1, [], { time: 1 }),
          event(2, [], { time: 3 }),
        ],
        { clock: clock({ unit: "second" }) },
      ),
      position: 0,
      expected: {
        verdict: "false",
        status: "violated",
        authority: "monitor",
        authorizes_global_proof: false,
        logic: "mtl",
        trace_kind: "finite_prefix",
      },
    },
    {
      case_id: "late-event-malformed",
      formula: unaryF("always", safe),
      trace: {
        kind: "finite",
        clock: clock(),
        events: [event(0, ["safe"], { time: 2 }), event(1, ["safe"], { time: 1 })],
        observation_policy: "closed_world",
        schema_version: RUNTIME_MTL_TRACE_SCHEMA_VERSION,
      },
      position: 0,
      expected: {
        verdict: "inconclusive",
        status: "malformed",
        authority: "monitor",
        authorizes_global_proof: false,
        late_events: true,
      },
    },
    {
      case_id: "serialization-roundtrip-next",
      formula: unaryF("next", safe),
      trace: trace("finite", [event(0, ["ready"]), event(1, ["safe"])]),
      position: 0,
      expected: {
        verdict: "true",
        status: "satisfied",
        authority: "monitor",
        authorizes_global_proof: false,
        logic: "ltlf",
      },
    },
    {
      case_id: "mtl-always-bounded-holds",
      formula: unaryF("always", safeMtl, {
        interval: interval(0, 1, "logical_tick"),
      }),
      trace: trace("finite", [event(0, ["safe"]), event(1, ["safe"])]),
      position: 0,
      expected: {
        verdict: "true",
        status: "satisfied",
        authority: "monitor",
        authorizes_global_proof: false,
        logic: "mtl",
      },
    },
  ];

  for (const item of cases) {
    item.schema_version = RUNTIME_MTL_SCHEMA_VERSION;
    item.interface = RUNTIME_MTL_INTERFACE;
  }
  return cases;
}
