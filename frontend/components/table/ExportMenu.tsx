"use client";

import { useState } from "react";
import { exportSection } from "@/lib/api";

/** Round A2B 3.6 — export select ("Export…" / PDF / PowerPoint / Excel / CSV).
 *
 * POST /api/export {section, format, params}. For dashboard_table the
 * provider (app/export/providers.py) requires params from + to and accepts
 * view ∈ all|split|recurring|non_recurring — the CALLER maps the UI's
 * rec/nrec before passing params. Choosing an option triggers the download
 * then resets the select; errors surface inline, never an alert().
 */
type ExportFormat = "pdf" | "pptx" | "xlsx" | "csv";

const OPTIONS: { label: string; format: ExportFormat }[] = [
  { label: "PDF", format: "pdf" },
  { label: "PowerPoint", format: "pptx" },
  { label: "Excel", format: "xlsx" },
  { label: "CSV", format: "csv" },
];

export default function ExportMenu({
  section,
  params,
}: {
  section: "dashboard_table" | "noncredited" | "exceptions" | "insights";
  params: Record<string, unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [value, setValue] = useState("");

  const onChange = async (fmt: string) => {
    if (!fmt) return;
    setValue(fmt);
    setBusy(true);
    setError(null);
    try {
      await exportSection(section, fmt as ExportFormat, params);
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(false);
      setValue(""); // reset to "Export…"
    }
  };

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <select
        className="btn"
        aria-label="Export"
        value={value}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{busy ? "Exporting…" : "Export…"}</option>
        {OPTIONS.map((o) => (
          <option key={o.format} value={o.format}>
            {o.label}
          </option>
        ))}
      </select>
      {error ? (
        <span role="alert" style={{ color: "var(--neg)", fontSize: 12 }}>
          {error}
        </span>
      ) : null}
    </span>
  );
}
