"use client";

/** Round E task 7 — the Guardrail tab on the Trace screen.
 *
 * Every classification is logged whether or not it blocked (Layer 1 demos
 * here); the Tools-called column is the valuable one — 0 on a blocked row
 * demonstrates nothing was reached, and a tagged-but-allowed row showing only
 * catalogued queries demonstrates Layer 2's containment.
 *
 * API access is local to this component: lib/api.ts is owned by the chat
 * subagents this round, so the guardrail client lives here.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import EmptyState from "@/components/EmptyState";
import { Pager, usePager } from "@/components/Pager";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

export interface GuardrailRow {
  when: string | null;
  conversation_id: string;
  message_id: string;
  message: string;
  tag: string;
  confidence: number;
  action: "ALLOWED" | "BLOCKED" | "BLOCKED_PARTIAL" | string;
  tools_called: number;
}
interface GuardrailResponse {
  rows: GuardrailRow[];
  summary: Record<string, number>;
  total: number;
}

/** Tag chips reuse the app's existing chip palette — no new colours.
 * CLEAN grey-green (real), OFF_TOPIC neutral (tag), SOCIAL_ENGINEERING amber
 * (warn — a con, not code), the injection/exfiltration family red (neg). */
const TAG_CHIP: Record<string, string> = {
  CLEAN: "chip real",
  OFF_TOPIC: "chip tag",
  SOCIAL_ENGINEERING: "chip warn",
  PROMPT_INJECTION: "chip neg",
  JAILBREAK: "chip neg",
  SQL_INJECTION: "chip neg",
  DATA_EXFILTRATION: "chip neg",
};

const ACTION_LABEL: Record<string, { text: string; cls: string }> = {
  BLOCKED: { text: "Blocked", cls: "chip neg" },
  BLOCKED_PARTIAL: { text: "Blocked (partial)", cls: "chip warn" },
  ALLOWED: { text: "Tagged and allowed", cls: "chip tag" },
};

const TRUNCATE_AT = 80;

export default function GuardrailTab() {
  const [data, setData] = useState<GuardrailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const reload = useCallback(() => {
    const qs = tagFilter ? `?tag=${encodeURIComponent(tagFilter)}` : "";
    fetch(`${API_BASE}/api/trace/guardrail${qs}`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} for /api/trace/guardrail`);
        return r.json();
      })
      .then((d: GuardrailResponse) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, [tagFilter]);

  useEffect(reload, [reload]);

  const toggle = (messageId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) next.delete(messageId);
      else next.add(messageId);
      return next;
    });

  const summaryTags = data ? Object.keys(data.summary).sort() : [];
  // Task 12c — the classification log paginates (5/10/20, default 5)
  const pager = usePager(data?.rows ?? []);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Guardrail</h2>
          <p>
            Every classification is logged whether or not it blocked. Blocked rows show 0 tools
            called — nothing was reached; tagged-but-allowed rows show only catalogued queries —
            the containment layer.
          </p>
        </div>
        <div className="ctl">
          <button className="btn" onClick={reload}>↻ Refresh</button>
        </div>
      </div>
      <div className="card-b">
        {data && data.total > 0 ? (
          <div className="chips" style={{ justifyContent: "flex-start", marginBottom: 12 }}>
            <button
              className={tagFilter === null ? "btn primary" : "btn"}
              style={{ padding: "3px 10px", fontSize: 12 }}
              onClick={() => setTagFilter(null)}
            >
              All · {data.total}
            </button>
            {summaryTags.map((tag) => (
              <button
                key={tag}
                className={tagFilter === tag ? "btn primary" : "btn"}
                style={{ padding: "3px 10px", fontSize: 12 }}
                onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
              >
                <span className={TAG_CHIP[tag] || "chip tag"}>{tag}</span>
                <span style={{ marginLeft: 6 }}>{data.summary[tag]}</span>
              </button>
            ))}
          </div>
        ) : null}

        {error ? <EmptyState title="Guardrail trace unavailable" message={error} /> : null}

        {data && data.rows.length ? (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Message</th>
                  <th>Tag</th>
                  <th>Confidence</th>
                  <th>Action</th>
                  <th>Tools called</th>
                  <th>Conversation</th>
                </tr>
              </thead>
              <tbody>
                {pager.rows.map((r) => {
                  const isLong = r.message.length > TRUNCATE_AT;
                  const isOpen = expanded.has(r.message_id);
                  const shown =
                    isLong && !isOpen ? `${r.message.slice(0, TRUNCATE_AT)}…` : r.message;
                  const action = ACTION_LABEL[r.action] || {
                    text: r.action,
                    cls: "chip tag",
                  };
                  return (
                    <tr key={r.message_id}>
                      <td style={{ whiteSpace: "nowrap" }}>{r.when ?? "—"}</td>
                      <td
                        style={{
                          maxWidth: 420,
                          cursor: isLong ? "pointer" : undefined,
                          whiteSpace: isOpen ? "pre-wrap" : "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          wordBreak: isOpen ? "break-word" : undefined,
                        }}
                        title={isLong && !isOpen ? "Click to expand" : undefined}
                        onClick={isLong ? () => toggle(r.message_id) : undefined}
                      >
                        {shown}
                      </td>
                      <td>
                        <span className={TAG_CHIP[r.tag] || "chip tag"}>{r.tag}</span>
                      </td>
                      <td className="num">{Number(r.confidence).toFixed(2)}</td>
                      <td>
                        <span className={action.cls}>{action.text}</span>
                      </td>
                      {/* The most valuable column: 0 on a blocked row proves
                          nothing was reached. */}
                      <td className="num" style={{ fontWeight: 700 }}>
                        {r.tools_called}
                      </td>
                      <td>
                        <Link href={`/?chat=${encodeURIComponent(r.conversation_id)}`}>
                          {r.conversation_id}
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pager {...pager} noun="messages" />
          </div>
        ) : data && !error ? (
          <EmptyState
            title={
              tagFilter
                ? `No ${tagFilter} classifications`
                : "No guardrail classifications yet"
            }
            message={
              tagFilter
                ? "Nothing has been tagged with this category. Clear the filter to see the full log."
                : "Classification starts with the first chat message — every message is classified and logged here, blocked or not."
            }
          />
        ) : null}
      </div>
    </div>
  );
}
