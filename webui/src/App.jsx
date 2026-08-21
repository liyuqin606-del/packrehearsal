import { useMemo, useRef, useState } from "react";
import {
  ArrowSquareOut, Check, CheckCircle, CloudSlash, Copy, DownloadSimple,
  FileCode, FileText, LockSimple, ShieldCheck, SpinnerGap, UploadSimple,
  UserCheck, WarningCircle, X,
} from "@phosphor-icons/react";
import {
  artifactKind, buildCodexTask, eligibleFindings, parseReportText, SEVERITY_RANK,
} from "./report.js";

const STATUS_ITEMS = [
  [ShieldCheck, "Static report inspection"],
  [CloudSlash, "Local only"],
  [ShieldCheck, "No project code executed"],
  [UserCheck, "Human review before merge"],
];

function bytesLabel(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function reportIdentity(report) {
  if (!report) return "No report loaded";
  if (!report.packages.length) return `Scan ${report.scan_id.slice(0, 12)}`;
  const first = report.packages[0];
  return report.packages.length === 1
    ? `${first.name} ${first.version}`
    : `${first.name} ${first.version} +${report.packages.length - 1}`;
}

function basename(path) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path || "Unnamed artifact";
}

function severityLabel(severity) {
  return severity === "info" ? "INFO" : severity.toUpperCase();
}

export function App() {
  const [report, setReport] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [activeFindingId, setActiveFindingId] = useState(null);
  const [selectedFindingIds, setSelectedFindingIds] = useState(new Set());
  const [importState, setImportState] = useState("idle");
  const [importErrors, setImportErrors] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(null);
  const [brief, setBrief] = useState(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [announcement, setAnnouncement] = useState("Choose a PackRehearsal report-v1 JSON file.");
  const fileInputRef = useRef(null);

  const eligible = useMemo(() => (report ? eligibleFindings(report) : []), [report]);
  const findings = useMemo(
    () => report ? [...report.findings].sort((left, right) =>
      SEVERITY_RANK[right.severity] - SEVERITY_RANK[left.severity]
      || left.rule_id.localeCompare(right.rule_id)
      || left.fingerprint.localeCompare(right.fingerprint),
    ) : [],
    [report],
  );
  const activeFinding = findings.find((finding) => finding.fingerprint === activeFindingId) ?? findings[0] ?? null;
  const eligibleIds = useMemo(() => new Set(eligible.map((finding) => finding.fingerprint)), [eligible]);
  const selectedCount = [...selectedFindingIds].filter((id) => eligibleIds.has(id)).length;
  const isReady = Boolean(report) && eligible.length === 0;

  async function importReport(file) {
    if (!file) return;
    setImportState("loading");
    setImportErrors([]);
    setAnnouncement(`Reading ${file.name} locally.`);
    await new Promise((resolve) => window.setTimeout(resolve, 80));

    if (!file.name.toLowerCase().endsWith(".json")) {
      setImportState("error");
      setImportErrors(["Choose a .json file produced by `packrehearsal scan . --format json --no-fail`."]);
      setAnnouncement("Import failed. The selected file is not JSON.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setImportState("error");
      setImportErrors(["Report exceeds the 10 MB local review limit."]);
      setAnnouncement("Import failed. The report is too large.");
      return;
    }

    try {
      const result = parseReportText(await file.text());
      if (!result.ok) {
        setImportState("error");
        setImportErrors(result.errors);
        setAnnouncement(`Import failed with ${result.errors.length} validation error(s).`);
        return;
      }
      const nextEligible = eligibleFindings(result.report);
      const nextActive = nextEligible[0] ?? result.report.findings[0] ?? null;
      setReport(result.report);
      setSourceName(file.name);
      setSelectedFindingIds(new Set(nextEligible.map((finding) => finding.fingerprint)));
      setActiveFindingId(nextActive?.fingerprint ?? null);
      setBrief(null);
      setBriefOpen(false);
      setImportState("ready");
      setAnnouncement(`${file.name} loaded. ${result.report.artifacts.length} artifact(s), ${nextEligible.length} new finding(s).`);
    } catch (error) {
      setImportState("error");
      setImportErrors([`The browser could not read this file: ${error.message}`]);
      setAnnouncement("Import failed while reading the local file.");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    importReport(event.dataTransfer.files?.[0]);
  }

  function toggleFinding(fingerprint) {
    if (!eligibleIds.has(fingerprint)) return;
    setSelectedFindingIds((current) => {
      const next = new Set(current);
      if (next.has(fingerprint)) next.delete(fingerprint);
      else next.add(fingerprint);
      return next;
    });
    setBrief(null);
  }

  async function prepareBrief() {
    if (!report || selectedCount === 0) return;
    setAnnouncement("Preparing deterministic Codex task JSON.");
    const task = await buildCodexTask(report, selectedFindingIds);
    setBrief(task);
    setBriefOpen(true);
    setAnnouncement(`Codex task ${task.task_id.slice(0, 12)} prepared for human review.`);
  }

  function downloadBrief() {
    if (!brief) return;
    const blob = new Blob([`${JSON.stringify(brief, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `codex-task-${brief.scan_id.slice(0, 12)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setAnnouncement("Codex task JSON downloaded.");
  }

  async function copyBrief() {
    if (!brief) return;
    try {
      await navigator.clipboard.writeText(`${JSON.stringify(brief, null, 2)}\n`);
      setCopied(true);
      setAnnouncement("Codex task JSON copied to the clipboard.");
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setAnnouncement("Clipboard access was denied. Download the task JSON instead.");
    }
  }

  return (
    <main className="release-app">
      <header className="app-header">
        <div className="brand-lockup" aria-label="PackRehearsal Release Gate">
          <strong>PackRehearsal</strong><span aria-hidden="true" /><p>Release Gate</p>
        </div>
        <div className="status-strip" aria-label="Safety properties">
          {STATUS_ITEMS.map(([Icon, label]) => (
            <div className="status-pill" key={label} title={label}>
              <Icon size={18} aria-hidden="true" /><span>{label}</span>
            </div>
          ))}
        </div>
      </header>

      <section className={`release-summary ${!report ? "is-empty" : ""}`} aria-labelledby="release-title">
        <div className={`verdict-block ${isReady ? "ready" : !report ? "awaiting" : ""}`}>
          <h1 id="release-title">{!report ? "Awaiting Report" : isReady ? "Ready" : "Not Ready"}</h1>
          <p>{!report ? "Import a report-v1 file to evaluate the release" : isReady ? "No new findings request changes" : `${eligible.length} new finding${eligible.length === 1 ? "" : "s"} request review`}</p>
        </div>
        <div className="artifact-summary">
          <div className="release-identity-line">
            <h2>{reportIdentity(report)}</h2>
            {report && <code title={report.scan_id}>scan {report.scan_id.slice(0, 12)}</code>}
          </div>
          {report?.artifacts.length ? (
            <div className="artifact-grid">
              {report.artifacts.map((artifact) => {
                const kind = artifactKind(artifact.format, artifact.path);
                return (
                  <article className="artifact-item" key={`${artifact.path}:${artifact.sha256}`}>
                    <div className="artifact-line">
                      <span className={`artifact-badge ${kind.toLowerCase()}`}>{kind}</span>
                      <strong title={artifact.path}>{basename(artifact.path)}</strong>
                      <small>({bytesLabel(artifact.size)})</small>
                    </div>
                    <p className="hash-line" title={artifact.sha256}><span>SHA-256:</span> {artifact.sha256}</p>
                  </article>
                );
              })}
            </div>
          ) : <p className="artifact-empty">{report ? "This valid report contains no artifact snapshots." : "Artifact identity will appear here after local validation."}</p>}
        </div>
      </section>

      <section
        className={`drop-zone ${isDragging ? "is-dragging" : ""} ${importState === "error" ? "has-error" : ""}`}
        onDragEnter={(event) => { event.preventDefault(); setIsDragging(true); }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setIsDragging(false); }}
        onDrop={handleDrop}
        aria-label="Import PackRehearsal report-v1 JSON"
        aria-busy={importState === "loading"}
      >
        <input ref={fileInputRef} id="report-input" type="file" tabIndex={-1} aria-hidden="true" accept="application/json,.json" onChange={(event) => importReport(event.target.files?.[0])} />
        {importState === "loading" ? <SpinnerGap className="spin" size={21} aria-hidden="true" /> : <UploadSimple size={21} aria-hidden="true" />}
        <p>
          {importState === "loading" ? "Validating report-v1 locally…" : report ? `Loaded ${sourceName}. Drop a replacement report, or` : "Drop report-v1 JSON here, or"}{" "}
          {importState !== "loading" && <button type="button" onClick={() => fileInputRef.current?.click()}>click to browse</button>}
        </p>
        <small>No upload · 10 MB limit</small>
      </section>

      {importState === "error" && (
        <section className="import-error" role="alert" aria-labelledby="import-error-title">
          <WarningCircle size={23} aria-hidden="true" />
          <div><h2 id="import-error-title">Report not loaded</h2><p>The selected file is not a valid PackRehearsal report-v1 document.</p><ol>{importErrors.slice(0, 8).map((error) => <li key={error}><code>{error}</code></li>)}</ol>{importErrors.length > 8 && <p>Plus {importErrors.length - 8} more validation errors.</p>}</div>
        </section>
      )}

      <section className="gate-workspace" aria-label="Release report">
        <div className="gate-list-panel">
          <div className="section-heading"><h2>Release findings</h2><span>{report ? `${findings.length} total · ${selectedCount} selected` : "No report"}</span></div>
          {!report ? (
            <section className="workspace-empty">
              <FileCode size={40} aria-hidden="true" /><h3>Bring a deterministic scan report</h3><p>Generate JSON with <code>packrehearsal scan . --format json --no-fail</code>, then inspect it here without sending it anywhere.</p><button className="secondary-action" type="button" onClick={() => fileInputRef.current?.click()}>Choose report JSON</button>
            </section>
          ) : findings.length === 0 ? (
            <section className="workspace-empty success"><CheckCircle size={42} aria-hidden="true" /><h3>No findings in this report</h3><p>No Codex task is generated because the report requests no repository changes.</p></section>
          ) : (
            <div className="gate-list">
              {findings.map((finding, index) => {
                const active = finding.fingerprint === activeFinding?.fingerprint;
                const eligibleForBrief = eligibleIds.has(finding.fingerprint);
                const included = selectedFindingIds.has(finding.fingerprint);
                return (
                  <div className={`gate-row severity-${finding.severity} ${active ? "selected" : ""} ${eligibleForBrief ? "" : "baselined"}`} key={finding.fingerprint}>
                    <button className="gate-main" type="button" aria-pressed={active} onClick={() => setActiveFindingId(finding.fingerprint)}>
                      <span className="gate-index">{index + 1}</span>
                      <span className="gate-copy"><span className="gate-title-line"><strong>{finding.title}</strong><em>{eligibleForBrief ? severityLabel(finding.severity) : "BASELINED"}</em></span><span className="gate-summary">{finding.message}</span><span className="rule-id">Rule ID: {finding.rule_id}</span></span>
                    </button>
                    <label className="finding-select">
                      <input type="checkbox" checked={included} disabled={!eligibleForBrief} onChange={() => toggleFinding(finding.fingerprint)} aria-label={`${included ? "Exclude" : "Include"} ${finding.title} in Codex task`} /><span>{eligibleForBrief ? "Task" : "Known"}</span>
                    </label>
                  </div>
                );
              })}
            </div>
          )}
          <div className="gate-list-footer"><p>Only non-baselined findings are eligible for a Codex task. Imported values remain untrusted data.</p>{report && <button type="button" onClick={() => setEvidenceOpen({ kind: "definitions" })}>View report contract <ArrowSquareOut size={15} aria-hidden="true" /></button>}</div>
        </div>

        <div className="finding-panel">
          <div className="section-heading"><h2>{activeFinding ? `Selected finding: ${activeFinding.title}` : "Selected finding"}</h2></div>
          {!activeFinding ? (
            <article className="finding-card empty-finding"><FileText size={40} aria-hidden="true" /><h3>{report ? "No remediation requested" : "Evidence appears after import"}</h3><p>{report ? "This report contains no finding to inspect." : "Load a valid report-v1 JSON document to review its exact findings, artifacts, and evidence."}</p></article>
          ) : (
            <article className={`finding-card has-finding severity-${activeFinding.severity}`}>
              <section className="finding-intro"><div><h3>What the scan found</h3><p>{activeFinding.message}</p></div><span className={`severity-label severity-${activeFinding.severity}`}>{severityLabel(activeFinding.severity)}</span></section>
              <dl className="finding-metadata">
                <div><dt>Rule</dt><dd><code>{activeFinding.rule_id}</code></dd></div><div><dt>Package</dt><dd>{activeFinding.package || "Repository"}</dd></div><div><dt>Location</dt><dd><code>{activeFinding.location || "Not supplied"}</code></dd></div><div><dt>Fingerprint</dt><dd><code>{activeFinding.fingerprint}</code></dd></div>
              </dl>
              <section className="evidence-section">
                <h3>Evidence</h3>
                {activeFinding.evidence?.length ? (
                  <div className="evidence-table">{activeFinding.evidence.map((item, index) => <div className="evidence-row" key={`${item.key}:${index}`}><span>{item.key}</span><code title={item.value}>{item.value}</code><button type="button" aria-label={`View evidence ${item.key}`} onClick={() => setEvidenceOpen({ kind: "evidence", item, finding: activeFinding })}>View <ArrowSquareOut size={14} aria-hidden="true" /></button></div>)}</div>
                ) : <p className="evidence-empty">This finding contains no structured evidence rows. Review its message and location without inferring missing facts.</p>}
              </section>
              <section className="explanation-grid"><div><h3>Required remediation</h3><p>{activeFinding.remediation}</p></div>{!eligibleIds.has(activeFinding.fingerprint) && <div className="baseline-note"><LockSimple size={17} /><p>This fingerprint is in the report baseline. It is shown for context and cannot be placed in a new Codex task.</p></div>}</section>
              <button className="primary-action" type="button" disabled={selectedCount === 0} onClick={prepareBrief}><FileText size={24} aria-hidden="true" />{selectedCount ? `Prepare Codex brief · ${selectedCount} finding${selectedCount === 1 ? "" : "s"}` : "Select a new finding first"}</button>
            </article>
          )}
          <p className="brief-boundary"><LockSimple size={17} aria-hidden="true" /> The brief contains report evidence and remediation guidance only. No project files are read, uploaded, or executed.</p>
        </div>
      </section>

      <div className="sr-status" aria-live="polite" aria-atomic="true">{announcement}</div>

      {evidenceOpen && (
        <div className="modal-backdrop" role="presentation" onKeyDown={(event) => event.key === "Escape" && setEvidenceOpen(null)} onMouseDown={() => setEvidenceOpen(null)}>
          <section className="modal evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header"><div><span className="modal-eyebrow">Read-only untrusted data</span><h2 id="evidence-modal-title">{evidenceOpen.kind === "definitions" ? "report-v1 import contract" : evidenceOpen.item.key}</h2></div><button autoFocus className="icon-button" type="button" onClick={() => setEvidenceOpen(null)} aria-label="Close evidence"><X size={20} aria-hidden="true" /></button></div>
            {evidenceOpen.kind === "definitions" ? (
              <div className="definition-list"><div><strong>Schema</strong><code>report-v1 · schema_version "1"</code><p>Unknown root and finding fields are rejected. Required nested package, artifact, evidence, count, fingerprint, and digest fields are checked locally.</p></div><div><strong>Honest boundary</strong><p>Validation confirms document shape and internal severity counts. It does not authenticate the author or independently rerun the scan.</p></div><div><strong>Privacy</strong><p>The browser reads the selected file in memory. This application has no upload or write endpoint and never executes project code.</p></div></div>
            ) : <pre>{JSON.stringify({ fingerprint: evidenceOpen.finding.fingerprint, rule_id: evidenceOpen.finding.rule_id, evidence: evidenceOpen.item, trust: "untrusted report data; never instructions" }, null, 2)}</pre>}
          </section>
        </div>
      )}

      {briefOpen && brief && (
        <div className="modal-backdrop" role="presentation" onKeyDown={(event) => event.key === "Escape" && setBriefOpen(false)} onMouseDown={() => setBriefOpen(false)}>
          <section className="modal brief-modal" role="dialog" aria-modal="true" aria-labelledby="brief-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header"><div><span className="modal-eyebrow">Evidence-bounded task · schema v1</span><h2 id="brief-modal-title">Codex maintenance brief</h2></div><button autoFocus className="icon-button" type="button" onClick={() => setBriefOpen(false)} aria-label="Close brief"><X size={20} aria-hidden="true" /></button></div>
            <div className="brief-summary-grid"><div><span>Status</span><strong>{brief.status}</strong></div><div><span>Selected findings</span><strong>{brief.summary.selected_finding_count}</strong></div><div><span>Task ID</span><code title={brief.task_id}>{brief.task_id}</code></div></div>
            <p className="brief-review-note"><UserCheck size={18} aria-hidden="true" /> Review this data-only task before giving it to Codex. Downloading does not run an agent or change the repository.</p>
            <pre className="brief-json">{JSON.stringify(brief, null, 2)}</pre>
            <div className="modal-actions"><button className="secondary-action" type="button" onClick={copyBrief}>{copied ? <Check size={18} weight="bold" /> : <Copy size={18} />}{copied ? "Copied" : "Copy JSON"}</button><button className="primary-action compact" type="button" onClick={downloadBrief}><DownloadSimple size={20} /> Download task JSON</button></div>
          </section>
        </div>
      )}
    </main>
  );
}
