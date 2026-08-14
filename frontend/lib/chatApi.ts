/** Round E Task 6 — typed client for the chat backend (Subagent B owns this).
 *
 * REST for conversations/history plus SSE streaming for messages. The stream
 * is a POST (a body is needed), so EventSource cannot be used — frames are
 * parsed off fetch's ReadableStream: "data: {json}\n\n".
 *
 * A 409 {detail:{feature_disabled:"global.chat"}} anywhere surfaces as
 * ChatApiError.disabled so the panel can show the disabled note mid-session.
 */

import type { LimitHit } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

export class ChatApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public disabled: boolean = false,
  ) {
    super(message);
    this.name = "ChatApiError";
  }
}

async function toError(response: Response): Promise<ChatApiError> {
  let disabled = false;
  let message = `${response.status} from chat API`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && detail.feature_disabled) {
      disabled = true;
      message = `Chat is turned off (${detail.feature_disabled}).`;
    } else if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    /* non-JSON body — keep the status message */
  }
  return new ChatApiError(response.status, message, disabled);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ChatApiError(0, `Chat API unreachable at ${API_BASE}`);
  }
  if (!response.ok) throw await toError(response);
  return (await response.json()) as T;
}

// ---------------------------------------------------------------- types

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview?: string;
}

/** A stored message row — the *_json columns arrive as JSON strings. */
export interface ChatMessageRow {
  message_id: string;
  seq_no: number;
  role: "user" | "assistant";
  text: string;
  tool_calls_json?: string;
  guardrail_tag?: string;
  guardrail_confidence?: number;
  guardrail_json?: string;
  reasoning_steps_json?: string;
  latency_ms?: number;
  tokens_in?: number;
  tokens_out?: number;
  est_cost_usd?: number;
  created_at?: string;
  extra_json?: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessageRow[];
}

export function listConversations(): Promise<{ conversations: ConversationSummary[] }> {
  return req("/api/chat/conversations");
}
export function createConversation(title?: string): Promise<ConversationSummary> {
  return req("/api/chat/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title || "" }),
  });
}
export function getConversation(id: string): Promise<ConversationDetail> {
  return req(`/api/chat/conversations/${encodeURIComponent(id)}`);
}
export function renameConversation(id: string, title: string): Promise<ConversationSummary> {
  return req(`/api/chat/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}
export function deleteConversation(id: string): Promise<unknown> {
  return req(`/api/chat/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// ---------------------------------------------------------------- streaming

export type GuardrailAction = "ALLOWED" | "BLOCKED" | "BLOCKED_PARTIAL";
export interface GuardrailEvent {
  event: "guardrail";
  tag: string;
  confidence: number;
  action: GuardrailAction;
  notice: string;
}
export interface StepEvent {
  event: "step";
  kind: "note" | "query" | "search" | "insight" | "generate" | "generate_done" | "limit" | "error" | "verify";
  step: string;
  query_name?: string;
  at_ms?: number;
}
export type AnswerKind = "answer" | "confirm" | "blocked" | "error";
export interface AnswerEvent {
  event: "answer";
  text: string;
  kind: AnswerKind;
  context: Record<string, unknown> | null;
  limits_hit: LimitHit[];
  latency_ms?: number;
  est_cost_usd?: number;
  notice?: string;
}
export interface DoneEvent {
  event: "done";
  message: ChatMessageRow;
}

export interface StreamHandlers {
  onGuardrail?: (e: GuardrailEvent) => void;
  onStep?: (e: StepEvent) => void;
  onAnswer?: (e: AnswerEvent) => void;
  onDone?: (e: DoneEvent) => void;
}

/** POST the message and dispatch SSE frames until the stream closes.
 * Throws ChatApiError (disabled=true on a 409) — the caller renders it. */
export async function streamChatMessage(
  conversationId: string,
  text: string,
  pageContext: Record<string, unknown> | null,
  handlers: StreamHandlers,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/chat/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, page_context: pageContext ?? undefined }),
      },
    );
  } catch {
    throw new ChatApiError(0, `Chat API unreachable at ${API_BASE}`);
  }
  if (!response.ok) throw await toError(response);
  if (!response.body) throw new ChatApiError(0, "The chat stream had no body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatch = (raw: string) => {
    const line = raw
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trim())
      .join("");
    if (!line) return;
    let frame: { event?: string } & Record<string, unknown>;
    try {
      frame = JSON.parse(line);
    } catch {
      return; // a malformed frame is skipped, never fatal
    }
    if (frame.event === "guardrail") handlers.onGuardrail?.(frame as unknown as GuardrailEvent);
    else if (frame.event === "step") handlers.onStep?.(frame as unknown as StepEvent);
    else if (frame.event === "answer") handlers.onAnswer?.(frame as unknown as AnswerEvent);
    else if (frame.event === "done") handlers.onDone?.(frame as unknown as DoneEvent);
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      dispatch(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
    }
  }
  if (buffer.trim()) dispatch(buffer);
}
