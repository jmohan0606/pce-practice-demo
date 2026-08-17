"use client";

/** Round E Task 6 — the docked chat panel (Subagent B owns this).
 *
 * Header (new / history / close) · context bar with Clear context (6.2) ·
 * message stream (6.3) with live→collapsed reasoning (6.4) and guardrail
 * blocks (6.5) · suggested questions (6.6) · composer · footer (6.7).
 *
 * Streaming is fetch+ReadableStream SSE (POST body — EventSource can't).
 * A 409 mid-session (global.chat turned off) shows the disabled note.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  ChatApiError,
  type AnswerKind,
  type ChatMessageRow,
  createConversation,
  getConversation,
  streamChatMessage,
} from "@/lib/chatApi";
import {
  type ChatPageContext,
  chatContextKey,
  getChatContext,
  subscribeChatContext,
} from "@/lib/chatContext";
import ChatMessage, { type UiMessage, type UiStep, stepFromEvent } from "@/components/chat/ChatMessage";
import ChatHistory from "@/components/chat/ChatHistory";

// ------------------------------------------------------------ row mapping

function parseJson<T>(raw: string | undefined | null): T | null {
  if (raw == null) return null;
  if (typeof raw === "object") return raw as T; // defensive: already parsed
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

interface GuardrailStored {
  tag?: string;
  confidence?: number;
  action?: "ALLOWED" | "BLOCKED" | "BLOCKED_PARTIAL";
  notice?: string;
}
interface ExtraStored {
  kind?: AnswerKind;
  blocked?: boolean;
  error?: string;
  notice?: string;
  partial_block_notice?: string | null;
  limits_hit?: UiMessage["limitsHit"];
  context?: Record<string, unknown> | null;
}

/** Rebuild a UI message from a stored row (history load, 6.4's history case). */
function fromRow(row: ChatMessageRow): UiMessage {
  if (row.role === "user") {
    return { id: row.message_id, role: "user", text: row.text, steps: [] };
  }
  const guardrail = parseJson<GuardrailStored>(row.guardrail_json);
  const extra = parseJson<ExtraStored>(row.extra_json) ?? {};
  const rawSteps = parseJson<unknown[]>(row.reasoning_steps_json) ?? [];
  const steps: UiStep[] = rawSteps.map((s) =>
    typeof s === "string"
      ? { kind: "note", step: s }
      : {
          kind: String((s as { kind?: string }).kind ?? "note"),
          step: String((s as { step?: string }).step ?? ""),
        },
  );
  const kind: AnswerKind = extra.kind ?? (extra.blocked ? "blocked" : extra.error ? "error" : "answer");
  const action = guardrail?.action ?? "ALLOWED";
  return {
    id: row.message_id,
    role: "assistant",
    text: row.text,
    kind,
    steps: steps.filter((s) => s.step),
    latencyMs: row.latency_ms ?? null,
    limitsHit: extra.limits_hit ?? [],
    guardrail:
      action !== "ALLOWED"
        ? {
            tag: guardrail?.tag ?? "UNKNOWN",
            confidence: guardrail?.confidence,
            action,
            notice: guardrail?.notice || extra.notice || extra.partial_block_notice || "",
          }
        : null,
  };
}

// ------------------------------------------------------------ context bits

function labelFromAnswerContext(c: Record<string, unknown>): string {
  if (typeof c.label === "string" && c.label) return c.label;
  const parts: string[] = [];
  const sid = typeof c.advisor_sid === "string" ? c.advisor_sid : "";
  const name = typeof c.advisor_name === "string" ? c.advisor_name : "";
  if (name || sid) parts.push(name ? `${name}${sid ? ` (${sid})` : ""}` : sid);
  if (typeof c.from_month === "string" && typeof c.to_month === "string")
    parts.push(`${c.from_month} → ${c.to_month}`);
  if (typeof c.view === "string" && c.view) parts.push(c.view);
  return parts.join(" · ");
}

function suggestionsFor(ctx: ChatPageContext | null): string[] {
  if (ctx?.advisor_sid) {
    const who = ctx.advisor_name || ctx.advisor_sid;
    return [
      `What changed for ${who} last month?`,
      `Show ${who}'s fee discount exceptions`,
      `How does ${who} rank against peers?`,
    ];
  }
  if (ctx?.page === "dashboard") {
    return [
      "Why did managed accounts go up?",
      "Which advisors declined?",
      "Show the fee discount exceptions",
    ];
  }
  return [
    "Which advisors declined?",
    "Show the fee discount exceptions",
    "What does the plan say about inheritance?",
  ];
}

// ---------------------------------------------------------------- the panel

let uiSeq = 0;
const nextId = () => `ui-${++uiSeq}`;

export default function ChatPanel({
  conversationId,
  onConversationChange,
  onClose,
}: {
  conversationId: string | null;
  onConversationChange: (id: string | null) => void;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null); // disabled/error banner
  const [clearedKey, setClearedKey] = useState<string | null>(null);
  const [answeredLabel, setAnsweredLabel] = useState<string | null>(null);

  const pageCtx = useSyncExternalStore(subscribeChatContext, getChatContext, () => null);
  const ctxKey = chatContextKey(pageCtx);
  // Clear context holds only until the page context next CHANGES (6.2).
  const cleared = clearedKey !== null && clearedKey === ctxKey;
  const effectiveCtx = cleared ? null : pageCtx;

  // When the page selection changes, the bar goes back to tracking the page.
  const prevKey = useRef(ctxKey);
  useEffect(() => {
    if (prevKey.current !== ctxKey) {
      prevKey.current = ctxKey;
      setAnsweredLabel(null);
    }
  }, [ctxKey]);

  const streamRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  // Load (rehydrate the display of) the current conversation.
  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    getConversation(conversationId)
      .then((d) => {
        if (!cancelled) setMessages(d.messages.map(fromRow));
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ChatApiError && e.status === 404) {
          onConversationChange(null); // stale stored id — start fresh
          setMessages([]);
        } else if (e instanceof ChatApiError && e.disabled) {
          setNote(e.message);
        } else {
          setNote(String((e as Error)?.message || e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, onConversationChange]);

  const patchLast = useCallback((patch: Partial<UiMessage> | ((m: UiMessage) => UiMessage)) => {
    setMessages((msgs) => {
      if (!msgs.length) return msgs;
      const last = msgs[msgs.length - 1];
      const next = typeof patch === "function" ? patch(last) : { ...last, ...patch };
      return [...msgs.slice(0, -1), next];
    });
  }, []);

  const send = useCallback(
    async (text: string) => {
      const clean = text.trim();
      if (!clean || streaming) return;
      setDraft("");
      setNote(null);
      setStreaming(true);
      setMessages((m) => [
        ...m,
        { id: nextId(), role: "user", text: clean, steps: [] },
        { id: nextId(), role: "assistant", text: "", steps: [], streaming: true },
      ]);
      try {
        let convId = conversationId;
        if (!convId) {
          const created = await createConversation();
          convId = created.conversation_id;
          onConversationChange(convId);
        }
        const pageContext = effectiveCtx ? ({ ...effectiveCtx } as Record<string, unknown>) : null;
        await streamChatMessage(convId, clean, pageContext, {
          onGuardrail: (g) => {
            if (g.action !== "ALLOWED") {
              patchLast({
                guardrail: { tag: g.tag, confidence: g.confidence, action: g.action, notice: g.notice },
              });
            }
          },
          onStep: (s) => {
            patchLast((m) => ({ ...m, steps: [...m.steps, stepFromEvent(s)] }));
          },
          onAnswer: (a) => {
            patchLast({
              text: a.text,
              kind: a.kind,
              streaming: false,
              latencyMs: a.latency_ms ?? null,
              limitsHit: a.limits_hit ?? [],
            });
            // 3.4 — the bar reflects what was actually answered.
            if (a.context) {
              const label = labelFromAnswerContext(a.context);
              if (label) setAnsweredLabel(label);
            }
          },
          onDone: (d) => {
            patchLast((m) => ({
              ...m,
              streaming: false,
              latencyMs: m.latencyMs ?? d.message.latency_ms ?? null,
            }));
          },
        });
      } catch (e) {
        const msg =
          e instanceof ChatApiError
            ? e.message
            : `The message failed: ${String((e as Error)?.message || e)}`;
        if (e instanceof ChatApiError && e.disabled) setNote(msg);
        patchLast({ streaming: false, kind: "error", text: `**Something went wrong** — ${msg}` });
      } finally {
        setStreaming(false);
        patchLast((m) => (m.streaming ? { ...m, streaming: false } : m));
      }
    },
    [conversationId, effectiveCtx, onConversationChange, patchLast, streaming],
  );

  const barLabel = answeredLabel ?? (effectiveCtx ? effectiveCtx.label : null);

  return (
    <aside className="chatpanel" aria-label="Ask Connect Coach chat panel">
      <div className="chat-h">
        <div className="t">Ask Connect Coach</div>
        <div className="btns">
          <button
            type="button"
            className="iconbtn"
            title="Start a new conversation. The current one stays in history."
            onClick={() => {
              onConversationChange(null);
              setMessages([]);
              setHistoryOpen(false);
            }}
          >
            ✚
          </button>
          <button
            type="button"
            className="iconbtn"
            title="Conversation history"
            onClick={() => setHistoryOpen((h) => !h)}
          >
            ≡
          </button>
          <button type="button" className="iconbtn" title="Close the panel" onClick={onClose}>
            ×
          </button>
        </div>
      </div>

      {historyOpen ? (
        <ChatHistory
          currentId={conversationId}
          onOpen={(id) => {
            onConversationChange(id);
            setHistoryOpen(false);
          }}
          onDeleted={(id) => {
            if (id === conversationId) {
              onConversationChange(null);
              setMessages([]);
            }
          }}
          onClose={() => setHistoryOpen(false)}
        />
      ) : (
        <>
          <div className="scope">
            {barLabel ? (
              <>
                <span>
                  Context: <b>{barLabel}</b>
                </span>
                <button
                  type="button"
                  title="Ignore what is selected on the page and answer across everything."
                  onClick={() => {
                    setClearedKey(ctxKey);
                    setAnsweredLabel(null);
                  }}
                >
                  Clear context
                </button>
              </>
            ) : (
              <span>No context — answering across everything</span>
            )}
          </div>

          <div className="stream" ref={streamRef}>
            {note ? <div className="chat-note">{note}</div> : null}
            {messages.length === 0 && !note ? (
              <div className="chat-note">
                Ask about revenue, advisors, accounts or the plan documents. Answers come from
                catalogued queries — never from the model&apos;s imagination.
              </div>
            ) : null}
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} onPrefill={setDraft} />
            ))}
          </div>

          <div className="suggest">
            {suggestionsFor(effectiveCtx).map((q) => (
              <button key={q} type="button" onClick={() => send(q)} disabled={streaming}>
                {q}
              </button>
            ))}
          </div>

          <div className="composer">
            <textarea
              value={draft}
              placeholder="Ask about revenue, advisors, accounts or the plan documents…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(draft);
                }
              }}
            />
            <button
              type="button"
              className="sendbtn"
              title="Send"
              onClick={() => send(draft)}
              disabled={streaming || !draft.trim()}
            >
              ↑
            </button>
          </div>
          <div className="foot">
            Read-only, except generating insights. Every figure comes from a query — never from the
            model.
          </div>
        </>
      )}
    </aside>
  );
}
