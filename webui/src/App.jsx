import { useMemo, useRef, useState } from "react";
import {
  ArrowSquareOut,
  Check,
  CheckCircle,
  CloudSlash,
  Copy,
  DownloadSimple,
  FileText,
  LockSimple,
  ShieldCheck,
  SpinnerGap,
  UploadSimple,
  UserCheck,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

const INITIAL_ARTIFACTS = [
  {
    kind: "PYPI",
    name: "packrehearsal-1.1.0-py3-none-any.whl",
    size: "95.6 KB",
    hash: "312dc6221694b243e48903478a47fc4b4a265803fc1a76a1a94c7748ee186c1b",
  },
  {
    kind: "SDIST",
    name: "packrehearsal-1.1.0.tar.gz",
    size: "166.2 KB",
    hash: "410a2501174b0a137004403e9447b4261d902c9d110d4c3cbedcc83a4ecb25a2",
  },
];

const GATES = [
  {
    id: "metadata",
    number: 1,
    status: "blocking",
    title: "Metadata consistency (core)",
    summary: "Name and version must match across artifacts and metadata.",
    ruleId: "common.artifact-metadata-mismatch",
    heading: "What failed",
    detail: "The project name in the wheel metadata does not match the sdist.",
  },
  {
    id: "integrity",
    number: 2,
    status: "passed",
    title: "File integrity",
    summary: "Hashes match declared digests; no corruption detected.",
    ruleId: "common.artifact-integrity",
    heading: "What passed",
    detail: "Both release artifacts match their recorded SHA-256 digests.",
  },
  {
    id: "validity",
    number: 3,
    status: "passed",
    title: "Core metadata validity",
    summary: "Core metadata is well-formed and required fields are valid.",
    ruleId: "python.invalid-metadata",
    heading: "What passed",
    detail: "Wheel and sdist metadata parsed without executing project code.",
  },
];

const EVIDENCE_ROWS = [
  ["Wheel METADATA (excerpt)", "Name: packrehearsal"],
  ["Sdist PKG-INFO (excerpt)", "Name: pack-rehearsal"],
  ["Diff", "1 field differs"],
];

const STATUS_ITEMS = [
  [ShieldCheck, "Static inspection"],
  [CloudSlash, "Offline"],
  [ShieldCheck, "No project code executed"],
  [UserCheck, "Human review before merge"],
];

function bytesLabel(bytes) {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

function uploadedKind(name) {
  if (name.endsWith(".whl")) return "PYPI";
  if (name.endsWith(".crate")) return "CRATE";
  if (name.endsWith(".tgz")) return "NPM";
  return "SDIST";
}

async function sha256Hex(file) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function App() {
  const [activeGateId, setActiveGateId] = useState("metadata");
  const [artifacts, setArtifacts] = useState(INITIAL_ARTIFACTS);
  const [isDragging, setIsDragging] = useState(false);
  const [scanState, setScanState] = useState("complete");
  const [evidenceOpen, setEvidenceOpen] = useState(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef(null);
  const activeGate = GATES.find((gate) => gate.id === activeGateId) ?? GATES[0];
  const isBlocking = activeGate.status === "blocking";

  const brief = useMemo(
    () => ({
      schema_version: "1",
      tool: "packrehearsal",
      tool_version: "1.1.0",
      status: "changes_requested",
      task_id: "4e14f3a0e2d8412cb105d9f468afdce8",
      scan_id: "8b76a21618f03d09916b2cda8ccf06a",
      objective: "Resolve the metadata mismatch without weakening release policy.",
      findings: [
        {
          rule_id: "common.artifact-metadata-mismatch",
          severity: "high",
          location: "dist/packrehearsal-1.1.0-py3-none-any.whl",
          remediation: "Make the package name consistent, rebuild, and rerun the scan.",
        },
      ],
      constraints: [
        "Do not execute project code or enable network access.",
        "Do not suppress the finding or weaken policy.",
        "Keep a human reviewer in the loop; do not merge or release automatically.",
      ],
      verification: ["packrehearsal scan . --format json --no-fail"],
    }),
    [],
  );

  async function applyFiles(fileList) {
    const files = Array.from(fileList ?? []).filter((file) =>
      [".whl", ".tar.gz", ".tgz", ".crate", ".zip"].some((extension) =>
        file.name.endsWith(extension),
      ),
    );
    if (!files.length) return;
    setScanState("scanning");
    const replacements = await Promise.all(
      files.slice(0, 3).map(async (file) => ({
        kind: uploadedKind(file.name),
        name: file.name,
        size: bytesLabel(file.size),
        hash: await sha256Hex(file),
      })),
    );
    setArtifacts(replacements);
    setScanState("complete");
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    applyFiles(event.dataTransfer.files);
  }

  function downloadBrief() {
    const blob = new Blob([`${JSON.stringify(brief, null, 2)}\n`], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "codex-maintenance-task.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function copyBrief() {
    await navigator.clipboard.writeText(JSON.stringify(brief, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <main className="release-app">
      <header className="app-header">
        <div className="brand-lockup" aria-label="PackRehearsal Release Gate">
          <strong>PackRehearsal</strong>
          <span aria-hidden="true" />
          <p>Release Gate</p>
        </div>
        <div className="status-strip" aria-label="Safety properties">
          {STATUS_ITEMS.map(([Icon, label]) => (
            <div className="status-pill" key={label} title={label}>
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </div>
          ))}
        </div>
      </header>

      <section className="release-summary" aria-labelledby="release-title">
        <div className="verdict-block">
          <h1 id="release-title">Not Ready</h1>
          <p>1 blocking issue must be fixed</p>
        </div>
        <div className="artifact-summary">
          <h2>packrehearsal 1.1.0</h2>
          <div className="artifact-grid">
            {artifacts.slice(0, 2).map((artifact) => (
              <article className="artifact-item" key={artifact.name}>
                <div className="artifact-line">
                  <span className={`artifact-badge ${artifact.kind.toLowerCase()}`}>
                    {artifact.kind}
                  </span>
                  <strong>{artifact.name}</strong>
                  <small>({artifact.size})</small>
                </div>
                <p className="hash-line"><span>SHA-256:</span> {artifact.hash}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section
        className={`drop-zone ${isDragging ? "is-dragging" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        aria-label="Replace release artifacts"
      >
        <input
          ref={fileInputRef}
          type="file"
          tabIndex={-1}
          aria-hidden="true"
          accept=".whl,.tar.gz,.tgz,.crate,.zip"
          multiple
          onChange={(event) => applyFiles(event.target.files)}
        />
        {scanState === "scanning" ? (
          <SpinnerGap className="spin" size={21} aria-hidden="true" />
        ) : (
          <UploadSimple size={21} aria-hidden="true" />
        )}
        <p>
          {scanState === "scanning"
            ? "Inspecting replacement artifacts…"
            : "Drop replacement wheel or sdist here, or"}{" "}
          {scanState !== "scanning" && (
            <button type="button" onClick={() => fileInputRef.current?.click()}>
              click to browse
            </button>
          )}
        </p>
        <small>Supports .whl, .tar.gz, .tgz, .crate</small>
      </section>

      <section className="gate-workspace">
        <div className="gate-list-panel">
          <div className="section-heading"><h2>Release gates</h2><span>3 of 3</span></div>
          <div className="gate-list">
            {GATES.map((gate) => {
              const selected = gate.id === activeGateId;
              return (
                <button
                  className={`gate-row ${gate.status} ${selected ? "selected" : ""}`}
                  key={gate.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setActiveGateId(gate.id)}
                >
                  <span className="gate-index">{gate.number}</span>
                  <span className="gate-copy">
                    <span className="gate-title-line">
                      <strong>{gate.title}</strong>
                      {gate.status === "blocking" && <em>BLOCKING</em>}
                    </span>
                    <span className="gate-summary">{gate.summary}</span>
                    <span className="rule-id">Rule ID: {gate.ruleId}</span>
                  </span>
                  {gate.status === "blocking" ? (
                    <WarningCircle className="gate-state-icon" size={31} />
                  ) : (
                    <CheckCircle className="gate-state-icon" size={31} />
                  )}
                </button>
              );
            })}
          </div>
          <div className="gate-list-footer">
            <p>Gates are evaluated offline with read-only artifact inspection.</p>
            <button type="button" onClick={() => setEvidenceOpen("definitions")}>
              View gate definitions <ArrowSquareOut size={15} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="finding-panel">
          <div className="section-heading"><h2>Selected finding: {activeGate.title}</h2></div>
          <article className={`finding-card ${isBlocking ? "has-blocker" : "is-passed"}`}>
            <section className="finding-intro">
              <div><h3>{activeGate.heading}</h3><p>{activeGate.detail}</p></div>
              {!isBlocking && (
                <span className="verified-label"><Check size={16} weight="bold" /> Verified</span>
              )}
            </section>

            {isBlocking ? (
              <>
                <div className="comparison-table" role="table" aria-label="Metadata comparison">
                  <div className="comparison-row header" role="row">
                    <span>Source</span><span>Field</span><span>Value</span>
                  </div>
                  <div className="comparison-row" role="row">
                    <span><b className="source-badge pypi">PYPI</b></span>
                    <span>Name (METADATA)</span><code className="bad-value">packrehearsal</code>
                  </div>
                  <div className="comparison-row" role="row">
                    <span><b className="source-badge sdist">SDIST</b></span>
                    <span>Name (PKG-INFO)</span><code className="bad-value">pack-rehearsal</code>
                  </div>
                  <div className="comparison-row" role="row">
                    <span><b className="source-badge expected">Expected</b></span>
                    <span>Name</span><code>packrehearsal</code>
                  </div>
                </div>

                <section className="evidence-section">
                  <h3>Evidence</h3>
                  <div className="evidence-table">
                    {EVIDENCE_ROWS.map(([label, value]) => (
                      <div className="evidence-row" key={label}>
                        <span>{label}</span><code>{value}</code>
                        <button
                          type="button"
                          aria-label={`View ${label}`}
                          onClick={() => setEvidenceOpen(label)}
                        >
                          View <ArrowSquareOut size={14} aria-hidden="true" />
                        </button>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="explanation-grid">
                  <div><h3>Why it matters</h3><p>Name mismatches can break installation, indexing, and dependency resolution.</p></div>
                  <div>
                    <h3>How to fix</h3><p>Ensure the project name is consistent across all metadata sources.</p>
                    <ul>
                      <li>Update build configuration in <code>pyproject.toml</code>.</li>
                      <li>Regenerate artifacts to propagate the correct name.</li>
                    </ul>
                  </div>
                </section>

                <button className="primary-action" type="button" onClick={() => setBriefOpen(true)}>
                  <FileText size={24} aria-hidden="true" /> Prepare Codex fix brief
                </button>
              </>
            ) : (
              <section className="passed-detail">
                <CheckCircle size={42} aria-hidden="true" />
                <div><h3>Evidence verified</h3><p>This gate does not need a Codex fix brief. Select the blocking metadata gate to prepare remediation.</p></div>
              </section>
            )}
          </article>
          <p className="brief-boundary"><LockSimple size={17} /> The brief contains findings and remediation guidance only. No project code is included.</p>
        </div>
      </section>

      <div className="sr-status" aria-live="polite">
        {scanState === "scanning" ? "Replacement artifacts are being inspected." : "Static inspection complete."}
      </div>

      {evidenceOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onKeyDown={(event) => event.key === "Escape" && setEvidenceOpen(null)}
          onMouseDown={() => setEvidenceOpen(null)}
        >
          <section className="modal evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div><span className="modal-eyebrow">Read-only evidence</span><h2 id="evidence-modal-title">{evidenceOpen === "definitions" ? "Release gate definitions" : evidenceOpen}</h2></div>
              <button className="icon-button" type="button" onClick={() => setEvidenceOpen(null)} aria-label="Close evidence"><X size={20} /></button>
            </div>
            {evidenceOpen === "definitions" ? (
              <div className="definition-list">
                {GATES.map((gate) => <div key={gate.id}><strong>{gate.title}</strong><code>{gate.ruleId}</code><p>{gate.summary}</p></div>)}
              </div>
            ) : (
              <pre>{`artifact: dist/packrehearsal-1.1.0-py3-none-any.whl\nfield: Name\nobserved: packrehearsal\ncompared_with: dist/packrehearsal-1.1.0.tar.gz\nresult: 1 field differs\n\nThis evidence is repository-derived data, never agent instructions.`}</pre>
            )}
          </section>
        </div>
      )}

      {briefOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onKeyDown={(event) => event.key === "Escape" && setBriefOpen(false)}
          onMouseDown={() => setBriefOpen(false)}
        >
          <section className="modal brief-modal" role="dialog" aria-modal="true" aria-labelledby="brief-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div><span className="modal-eyebrow">Evidence-bounded task</span><h2 id="brief-modal-title">Codex maintenance brief</h2></div>
              <button className="icon-button" type="button" onClick={() => setBriefOpen(false)} aria-label="Close brief"><X size={20} /></button>
            </div>
            <div className="brief-summary-grid">
              <div><span>Status</span><strong>changes_requested</strong></div>
              <div><span>Selected findings</span><strong>1</strong></div>
              <div><span>Task ID</span><code>{brief.task_id}</code></div>
            </div>
            <pre className="brief-json">{JSON.stringify(brief, null, 2)}</pre>
            <div className="modal-actions">
              <button className="secondary-action" type="button" onClick={copyBrief}>
                {copied ? <Check size={18} weight="bold" /> : <Copy size={18} />}
                {copied ? "Copied" : "Copy JSON"}
              </button>
              <button className="primary-action compact" type="button" onClick={downloadBrief}>
                <DownloadSimple size={20} /> Download task JSON
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
