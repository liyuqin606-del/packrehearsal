import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  artifactKind,
  buildCodexTask,
  eligibleFindings,
  parseReportText,
  validateReport,
} from "../src/report.js";

const exampleUrl = new URL("../../examples/self-scan.json", import.meta.url);
const demoUrl = new URL("../public/artifact-parity-demo.json", import.meta.url);
const taskSchemaUrl = new URL("../../schemas/codex-task-v1.schema.json", import.meta.url);

function assertSchema(value, schema, root, path = "$") {
  if (schema.$ref) {
    const target = schema.$ref.slice(2).split("/").reduce((current, key) => current[key], root);
    return assertSchema(value, target, root, path);
  }
  if (schema.const !== undefined) assert.equal(value, schema.const, path);
  if (schema.enum) assert.ok(schema.enum.includes(value), `${path} is not in its enum`);
  if (schema.type === "object") {
    assert.ok(value && typeof value === "object" && !Array.isArray(value), `${path} is not an object`);
    for (const key of schema.required ?? []) assert.ok(key in value, `${path}.${key} is required`);
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) assert.ok(key in (schema.properties ?? {}), `${path}.${key} is not allowed`);
    }
    for (const [key, child] of Object.entries(schema.properties ?? {})) {
      if (key in value) assertSchema(value[key], child, root, `${path}.${key}`);
    }
  } else if (schema.type === "array") {
    assert.ok(Array.isArray(value), `${path} is not an array`);
    if (schema.minItems !== undefined) assert.ok(value.length >= schema.minItems, `${path} has too few items`);
    if (schema.uniqueItems) assert.equal(new Set(value.map(JSON.stringify)).size, value.length, `${path} must be unique`);
    value.forEach((item, index) => assertSchema(item, schema.items, root, `${path}[${index}]`));
  } else if (schema.type === "string") {
    assert.equal(typeof value, "string", `${path} is not a string`);
    if (schema.minLength !== undefined) assert.ok(value.length >= schema.minLength, `${path} is too short`);
    if (schema.pattern) assert.match(value, new RegExp(schema.pattern), path);
  } else if (schema.type === "integer") {
    assert.ok(Number.isInteger(value), `${path} is not an integer`);
    if (schema.minimum !== undefined) assert.ok(value >= schema.minimum, `${path} is below minimum`);
  }
}

async function exampleReport() {
  return JSON.parse(await readFile(exampleUrl, "utf8"));
}

function finding(overrides = {}) {
  return {
    fingerprint: "a".repeat(24),
    message: "The packaged entry point is missing.",
    remediation: "Restore the declared entry point and rebuild the artifact.",
    rule_id: "common.missing-entrypoint",
    severity: "high",
    title: "Missing packaged entry point",
    package: "packrehearsal",
    location: "dist/example.whl",
    evidence: [{ key: "declared", value: "packrehearsal=packrehearsal.cli:main" }],
    ...overrides,
  };
}

test("accepts a real report-v1 emitted by PackRehearsal", async () => {
  const report = await exampleReport();
  assert.deepEqual(validateReport(report), { ok: true, errors: [] });
  assert.deepEqual(parseReportText(JSON.stringify(report)), { ok: true, report });
});

test("bundled artifact drift demo is valid and produces a bounded task", async () => {
  const report = JSON.parse(await readFile(demoUrl, "utf8"));
  assert.deepEqual(validateReport(report), { ok: true, errors: [] });
  assert.equal(report.findings[0].rule_id, "python.artifact-set-mismatch");
  assert.equal(report.artifacts.length, 2);

  const task = await buildCodexTask(
    report,
    new Set([report.findings[0].fingerprint]),
  );
  assert.equal(task.status, "changes_requested");
  assert.equal(task.summary.selected_finding_count, 1);
  assert.equal(task.summary.artifact_count, 2);
});

test("rejects malformed JSON, unknown root fields, and dishonest counts", async () => {
  assert.equal(parseReportText("{").ok, false);

  const report = await exampleReport();
  report.unknown = true;
  report.findings = [finding()];
  const result = validateReport(report);

  assert.equal(result.ok, false);
  assert.ok(result.errors.some((error) => error.includes("$.unknown")));
  assert.ok(result.errors.some((error) => error.includes("$.counts.high") && error.includes("findings contain 1")));
});

test("excludes baseline findings from eligible Codex work", async () => {
  const report = await exampleReport();
  const known = finding({ fingerprint: "b".repeat(24), severity: "medium" });
  const fresh = finding();
  report.findings = [known, fresh];
  report.baseline_fingerprints = [known.fingerprint];
  report.counts = { critical: 0, high: 1, info: 0, low: 0, medium: 1 };

  assert.deepEqual(eligibleFindings(report).map((item) => item.fingerprint), [fresh.fingerprint]);
});

test("builds deterministic schema-shaped codex-task-v1 data", async () => {
  const report = await exampleReport();
  const selected = finding();
  report.findings = [selected];
  report.counts = { critical: 0, high: 1, info: 0, low: 0, medium: 0 };
  report.artifacts = [{
    entries: [],
    format: "wheel",
    path: "dist/example.whl",
    sha256: "c".repeat(64),
    size: 2048,
  }];

  const first = await buildCodexTask(report, new Set([selected.fingerprint]));
  const second = await buildCodexTask(report, new Set([selected.fingerprint]));

  assert.deepEqual(first, second);
  assert.match(first.task_id, /^[0-9a-f]{64}$/);
  assert.equal(first.schema_version, "1");
  assert.equal(first.tool, "packrehearsal");
  assert.equal(first.status, "changes_requested");
  assert.equal(first.minimum_severity, "high");
  assert.equal(first.summary.selected_finding_count, 1);
  assert.equal(first.summary.artifact_count, 1);
  assert.deepEqual(Object.keys(first.artifacts[0]).sort(), ["format", "path", "sha256", "size"]);
  assert.ok(first.constraints.some((item) => item.includes("do not merge")));
  assert.ok(first.untrusted_data_policy.includes("untrusted data"));

  const taskSchema = JSON.parse(await readFile(taskSchemaUrl, "utf8"));
  assertSchema(first, taskSchema, taskSchema);
});

test("labels common release artifact formats", () => {
  assert.equal(artifactKind("wheel", "dist/a.whl"), "PYPI");
  assert.equal(artifactKind("npm", "dist/a.tgz"), "NPM");
  assert.equal(artifactKind("crate", "dist/a.crate"), "CRATE");
  assert.equal(artifactKind("sdist", "dist/a.tar.gz"), "SDIST");
});
