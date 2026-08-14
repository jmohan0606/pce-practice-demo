"use client";

import { type ReactNode, useEffect, useState } from "react";

/** Round C (docs/rules) — mandatory-reason dialog, shared by deactivate/
 * reactivate, promote/demote and any other audited rule action. Mirrors the
 * Settings flag-reason modal (same .scrim/.modal.narrow classes, Enter
 * confirms, Escape cancels, confirm disabled until a reason is typed). */
export default function ReasonModal({
  open,
  title,
  prompt,
  placeholder,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  /** Explains why the reason matters — rendered above the input. */
  prompt?: ReactNode;
  placeholder?: string;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (open) setReason("");
  }, [open]);
  const confirm = () => {
    if (reason.trim() && !busy) onConfirm(reason.trim());
  };
  return (
    <>
      <div className={`scrim${open ? " on" : ""}`} onClick={onCancel}></div>
      <div className={`modal narrow${open ? " on" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="m-head">{title}</div>
        <div className="m-body">
          {prompt ? (
            <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--slate)" }}>{prompt}</p>
          ) : null}
          <label className="fld">Reason</label>
          <input
            type="text"
            placeholder={placeholder || "A reason is required — it becomes the audit record"}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") confirm();
              if (e.key === "Escape") onCancel();
            }}
          />
        </div>
        <div className="m-foot">
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn primary" onClick={confirm} disabled={!reason.trim() || !!busy}>
            {confirmLabel || "Confirm"}
          </button>
        </div>
      </div>
    </>
  );
}
