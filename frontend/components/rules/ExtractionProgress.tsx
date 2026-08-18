"use client";

/** Round 5 task 13.1 — live extraction progress from the job record.
 *
 * Renders the latest document_ingest job for one document:
 *   Extracting rules — 14 of 26   parse ✓ chunk ✓ embed ✓ extract ▓ compile · audit ·
 * Polls GET /api/jobs?kind=document_ingest&scope_key=<id> while the job is
 * RUNNING (or while the caller says an extraction request is in flight — the
 * extract-rules POST is synchronous, so polling is how progress is seen).
 * An INTERRUPTED job shows INTERRUPTED with an EXPLICIT Resume button —
 * nothing ever auto-resumes on page load (that could double-spend).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type IngestJob,
  RulesApiError,
  getLatestIngestJob,
  resumeJob,
} from "@/lib/rulesApi";

const POLL_MS = 1500;

function stageMark(job: IngestJob, index: number): string {
  const current = (job.stage_index ?? 1) - 1;
  if (index < current) return "✓";
  // the current stage only shows done when the whole job is COMPLETE
  if (index === current) return job.status === "COMPLETE" ? "✓" : "▓";
  return "·";
}

export default function ExtractionProgress({
  documentId,
  extracting,
  onFinished,
}: {
  documentId: string;
  /** true while this document's extract-rules request is in flight */
  extracting: boolean;
  /** called once when a previously RUNNING job reaches a terminal status */
  onFinished?: () => void;
}) {
  const [job, setJob] = useState<IngestJob | null>(null);
  const [resumeBusy, setResumeBusy] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const wasRunning = useRef(false);

  const poll = useCallback(async () => {
    try {
      const latest = await getLatestIngestJob(documentId);
      setJob(latest);
      if (latest?.status === "RUNNING") wasRunning.current = true;
      else if (wasRunning.current && latest && latest.status !== "RUNNING") {
        wasRunning.current = false;
        onFinished?.();
      }
    } catch {
      /* progress is display sugar — never break the page over a poll */
    }
  }, [documentId, onFinished]);

  useEffect(() => {
    poll(); // read once on mount — an INTERRUPTED job must be visible
  }, [poll]);

  const shouldPoll = extracting || resumeBusy || job?.status === "RUNNING";
  useEffect(() => {
    if (!shouldPoll) return;
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [shouldPoll, poll]);

  const runResume = async () => {
    if (!job) return;
    setResumeBusy(true);
    setResumeError(null);
    try {
      await resumeJob(job.job_id);
      await poll();
      onFinished?.();
    } catch (e) {
      setResumeError(
        e instanceof RulesApiError && e.status === 0
          ? "The jobs service is not reachable."
          : String((e as Error)?.message || e),
      );
    } finally {
      setResumeBusy(false);
    }
  };

  if (!job) return null;
  const stages = job.stages ?? [];
  const stageLine = stages.length ? (
    <span style={{ fontFamily: "var(--mono, monospace)", fontSize: 11.5, whiteSpace: "nowrap" }}>
      {stages.map((s, i) => `${s} ${stageMark(job, i)}`).join("  ")}
    </span>
  ) : null;

  if (job.status === "RUNNING" || (extracting && job.status !== "INTERRUPTED")) {
    if (job.status !== "RUNNING" && !extracting) return null;
    return (
      <div style={{ marginTop: 6, fontSize: 12.5, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <b>
          Extracting rules
          {job.items_total ? ` — ${job.items_done ?? 0} of ${job.items_total}` : "…"}
        </b>
        {stageLine}
      </div>
    );
  }

  if (job.status === "INTERRUPTED") {
    return (
      <div style={{ marginTop: 6, fontSize: 12.5 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <b style={{ color: "var(--neg, #B3261E)" }}>INTERRUPTED</b>
          {job.items_total ? (
            <span>
              {job.items_done ?? 0} of {job.items_total} done in the {job.stage} stage
            </span>
          ) : null}
          {stageLine}
          <button className="btn primary" style={{ padding: "3px 9px" }} disabled={resumeBusy} onClick={runResume}>
            {resumeBusy ? "Resuming…" : "Resume"}
          </button>
        </div>
        <div style={{ color: "var(--slate)", marginTop: 2 }}>
          Extraction stopped before finishing — already-extracted rules are kept and are never
          repeated. Resume is explicit; nothing restarts on its own.
          {job.error ? ` (${job.error})` : ""}
        </div>
        {resumeError ? (
          <div style={{ color: "var(--neg, #B3261E)", marginTop: 2 }}>{resumeError}</div>
        ) : null}
      </div>
    );
  }

  if (job.status === "FAILED" && job.error) {
    return (
      <div style={{ marginTop: 6, fontSize: 12.5, color: "var(--neg, #B3261E)" }}>
        Extraction failed — {job.error}
      </div>
    );
  }

  return null; // COMPLETE — the counts line on the row is the report
}
