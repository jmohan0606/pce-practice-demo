"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { refreshFlags } from "@/lib/flags";
import {
  type FlagHistoryRow,
  type FlagRow,
  type FlagsResponse,
  applyPreset,
  getFlagHistory,
  getFlags,
  patchFlag,
} from "@/lib/flagsApi";

/** Round A2B task 7 — Settings / Feature Flags (MOCKUP_FEATURE_FLAGS.html).
 *
 * Changes apply immediately through PATCH /api/flags/{key} (the mockup's Save
 * bar renders the live counts; there is no staged-save batch — a toggle either
 * lands durably or errors loudly). Turning a flag OFF opens the reason modal;
 * the note and full history are stored server-side. "Who" is a free-text
 * operator name persisted in localStorage. */
export default function SettingsPage() {
  const [data, setData] = useState<FlagsResponse | null>(null);
  const [history, setHistory] = useState<FlagHistoryRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | "on" | "off">("all");
  const [operator, setOperator] = useState("operator");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  // reason modal state: the flag pending turn-off
  const [pendingOff, setPendingOff] = useState<FlagRow | null>(null);
  const [reason, setReason] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem("pce_operator_name");
    if (saved) setOperator(saved);
  }, []);
  const saveOperator = (name: string) => {
    setOperator(name);
    window.localStorage.setItem("pce_operator_name", name);
  };

  const load = useCallback(() => {
    getFlags()
      .then(setData)
      .catch((e) => setError(String(e?.message || e)));
    getFlagHistory()
      .then((h) => setHistory(h.history))
      .catch(() => setHistory([]));
  }, []);
  useEffect(load, [load]);

  const afterWrite = useCallback(() => {
    refreshFlags(); // invalidate the session cache <Gated> reads
    load();
  }, [load]);

  const toggle = async (flag: FlagRow, next: boolean) => {
    if (!next) {
      // 7.3 — turning OFF requires a reason: open the modal first
      setPendingOff(flag);
      setReason("");
      return;
    }
    setBusyKey(flag.key);
    setError(null);
    try {
      await patchFlag(flag.key, true, "", operator);
      afterWrite();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusyKey(null);
    }
  };

  const confirmOff = async () => {
    if (!pendingOff || !reason.trim()) return;
    setBusyKey(pendingOff.key);
    setError(null);
    try {
      await patchFlag(pendingOff.key, false, reason.trim(), operator);
      setPendingOff(null);
      afterWrite();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusyKey(null);
    }
  };

  const preset = async (id: string) => {
    setError(null);
    try {
      setData(await applyPreset(id, operator));
      afterWrite();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    }
  };

  const visible = useMemo(() => {
    if (!data) return [];
    const q = filter.trim().toLowerCase();
    return data.flags.filter((f) => {
      if (q && !`${f.name} ${f.description} ${f.key}`.toLowerCase().includes(q)) return false;
      if (stateFilter === "on" && !f.enabled) return false;
      if (stateFilter === "off" && f.enabled) return false;
      return true;
    });
  }, [data, filter, stateFilter]);

  const byGroup = useMemo(() => {
    const map = new Map<string, FlagRow[]>();
    for (const f of visible) map.set(f.group, [...(map.get(f.group) ?? []), f]);
    return map;
  }, [visible]);

  const parentOf = (f: FlagRow): FlagRow | null =>
    f.parent ? data?.flags.find((x) => x.key === f.parent) ?? null : null;

  return (
    <section>
      <PageHeader
        title="Feature Flags"
        meta="Off means the section is hidden AND its queries do not run — nothing is computed for a hidden section."
      >
        <label className="fld" style={{ margin: 0, display: "flex", alignItems: "center", gap: 6 }}>
          Operator
          <input
            className="filter"
            type="text"
            value={operator}
            onChange={(e) => saveOperator(e.target.value)}
            style={{ width: 120 }}
            aria-label="Operator name"
          />
        </label>
      </PageHeader>

      {error ? <EmptyState title="Settings error" message={error} /> : null}

      {/* ============ Presets ============ */}
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Presets</h2>
            <p>Selecting one sets every flag below (ONE history entry names the preset); adjust individually after.</p>
          </div>
          <button className="btn sm" disabled title="not in this round">
            Save current as preset…
          </button>
        </div>
        <div className="card-b">
          <div className="presets">
            {(data?.presets ?? []).map((p) => (
              <button key={p.id} className="preset" onClick={() => preset(p.id)}>
                <div className="n">{p.name}</div>
                <div className="d">{p.description}</div>
                <div className="c">
                  {p.on_count} of {p.total} features on
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ============ Flags ============ */}
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Features</h2>
            <p>Grouped by page. A section turned off hides its sub-features too.</p>
          </div>
          <div className="ctl">
            <input
              className="filter"
              type="text"
              placeholder="Filter features…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{ width: 200 }}
            />
            <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value as "all" | "on" | "off")}>
              <option value="all">All features</option>
              <option value="on">On only</option>
              <option value="off">Off only</option>
            </select>
          </div>
        </div>

        <div className="card-b" style={{ padding: 0 }}>
          {(data?.groups ?? []).map((g) => {
            const rows = byGroup.get(g.id) ?? [];
            if (!rows.length) return null;
            const groupAll = data?.flags.filter((f) => f.group === g.id) ?? [];
            return (
              <div className="fgrp" key={g.id}>
                <div className="fgrp-h">
                  <span>{g.name}</span>
                  <span>
                    {groupAll.filter((f) => f.enabled).length} of {groupAll.length} on
                  </span>
                </div>
                {rows.map((f) => {
                  const parent = parentOf(f);
                  const parentOff = parent ? !parent.effective_enabled : false;
                  return (
                    <div key={f.key} className={`frow${f.parent ? " child" : ""}${!f.enabled || !f.effective_enabled ? " off" : ""}`}>
                      <label className="sw">
                        <input
                          type="checkbox"
                          checked={f.always_on ? true : f.enabled}
                          disabled={f.always_on || parentOff || busyKey === f.key}
                          onChange={(e) => toggle(f, e.target.checked)}
                          aria-label={`${f.name} ${f.enabled ? "on" : "off"}`}
                        />
                        <span className="track"></span>
                      </label>
                      <div>
                        <div className="name">{f.name}</div>
                        <div className="desc">{f.description}</div>
                        {f.dep ? (
                          <div className="dep">
                            <b>{f.always_on ? "Cannot be turned off." : "Required by:"}</b>{" "}
                            {f.always_on ? f.dep.replace(/^Cannot be turned off\.\s*/, "") : f.dep.replace(/^Required by:\s*/, "")}
                          </div>
                        ) : null}
                        {parentOff && parent ? (
                          <div className="dep">
                            Inherits from <b>{parent.name}</b> — parent is off, so this is effectively off; the switch
                            unlocks when the parent is turned back on.
                          </div>
                        ) : null}
                        {f.note ? (
                          <div className="flagnote">
                            Turned off {f.note.when} by {f.note.by} — “{f.note.reason}”
                          </div>
                        ) : null}
                      </div>
                      <div>
                        {f.always_on ? (
                          <span className="chip on">Always On</span>
                        ) : f.enabled && f.effective_enabled ? (
                          <span className="chip on">On</span>
                        ) : f.enabled && !f.effective_enabled ? (
                          <span className="chip warn">Off via parent</span>
                        ) : (
                          <span className="chip off">Off</span>
                        )}
                      </div>
                      <div className="cost">
                        {f.cost ? (
                          f.cost.amount_usd !== null && (f.cost.history_runs > 0 || f.cost.note) ? (
                            <>
                              <b>~${f.cost.amount_usd.toFixed(2)}</b>
                              <br />
                              {f.cost.unit}
                              {f.cost.note ? (
                                <>
                                  <br />
                                  <span style={{ color: "var(--der-tx, #8A5A00)" }}>{f.cost.note}</span>
                                </>
                              ) : null}
                            </>
                          ) : (
                            <span>no runs yet — cost unknown</span>
                          )
                        ) : (
                          "—"
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
          {data && !visible.length ? (
            <div style={{ padding: 16, color: "var(--slate)", fontSize: "12.5px" }}>No features match the filter.</div>
          ) : null}
        </div>

        <div className="warnbox" style={{ margin: "16px 20px" }}>
          <div>
            <b>A feature that stays off stops being tested.</b> Verification scripts always run with every flag on, so
            hidden sections cannot break silently — but a section left off for months will not have been seen by anyone.
            Review this page before each client session.
          </div>
        </div>

        <div className="savebar">
          <div className="count">
            <b>{data?.on_count ?? "—"}</b> of <b>{data?.total ?? "—"}</b> features on ·{" "}
            <b>{data ? data.total - data.on_count : "—"}</b> off ·{" "}
            <span style={{ color: "var(--slate-2)" }}>
              ceiling {data?.ceiling ?? 30} — add a flag only when a client has asked for something to be removable
            </span>
          </div>
          <div className="ctl">
            <span style={{ fontSize: 12, color: "var(--slate)" }}>Changes apply immediately and persist across restarts.</span>
          </div>
        </div>
      </div>

      {/* ============ History ============ */}
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Change History</h2>
            <p>Every flag change, who made it and why. Notes are required.</p>
          </div>
        </div>
        <div className="card-b" style={{ padding: 0 }}>
          {history.length ? (
            <div style={{ overflowX: "auto" }}>
              <table className="hist">
                <thead>
                  <tr>
                    <th style={{ width: "16%" }}>When</th>
                    <th style={{ width: "22%" }}>Feature</th>
                    <th style={{ width: "9%" }}>Change</th>
                    <th style={{ width: "12%" }}>By</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={i}>
                      <td>{h.when}</td>
                      <td>{h.flag === "__preset__" ? "Preset" : h.flag_name}</td>
                      <td>
                        <span className={`chip ${h.enabled ? "on" : "off"}`}>{h.enabled ? "On" : "Off"}</span>
                      </td>
                      <td>{h.by}</td>
                      <td>{h.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ padding: 16, color: "var(--slate)", fontSize: "12.5px" }}>
              No changes recorded yet — every flag is at its default (on).
            </div>
          )}
        </div>
      </div>

      {/* ============ Reason modal ============ */}
      <div className={`scrim${pendingOff ? " on" : ""}`} onClick={() => setPendingOff(null)}></div>
      <div className={`modal narrow${pendingOff ? " on" : ""}`} role="dialog" aria-modal="true" aria-label="Why are you turning this off?">
        <div className="m-head">Why are you turning this off?</div>
        <div className="m-body">
          <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--slate)" }}>
            A note is required. Six weeks from now this is the only record of why{" "}
            <b>{pendingOff?.name ?? "this section"}</b> disappeared.
          </p>
          <label className="fld">Reason</label>
          <input
            type="text"
            placeholder="e.g. client said it duplicates the drivers section"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") confirmOff();
              if (e.key === "Escape") setPendingOff(null);
            }}
          />
        </div>
        <div className="m-foot">
          <button className="btn" onClick={() => setPendingOff(null)}>
            Cancel
          </button>
          <button className="btn primary" onClick={confirmOff} disabled={!reason.trim() || busyKey !== null}>
            Turn Off
          </button>
        </div>
      </div>
    </section>
  );
}
