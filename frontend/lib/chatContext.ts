/** Round E Task 6.2 — tiny pub/sub for the chat panel's page context.
 *
 * Pages that own a selection publish it here (one call in their existing
 * state-change path); the chat panel subscribes and shows the label. Module
 * singleton, no dependencies. Context is a HINT, not a filter (spec 3.4) —
 * the panel decides whether to send it with a message.
 */

export interface ChatPageContext {
  page: string; // "dashboard" | "advisor" | ...
  advisor_sid?: string;
  advisor_name?: string;
  from_month?: string;
  to_month?: string;
  view?: string;
  label: string; // what the context bar shows, e.g. "All Advisors · Apr → May 2026"
}

let current: ChatPageContext | null = null;
const listeners = new Set<(ctx: ChatPageContext | null) => void>();

/** Stable identity for "has the context CHANGED?" (Clear-context scoping). */
export function chatContextKey(ctx: ChatPageContext | null): string {
  if (!ctx) return "";
  return JSON.stringify([
    ctx.page,
    ctx.advisor_sid ?? "",
    ctx.from_month ?? "",
    ctx.to_month ?? "",
    ctx.view ?? "",
    ctx.label,
  ]);
}

export function publishChatContext(ctx: ChatPageContext | null): void {
  if (chatContextKey(ctx) === chatContextKey(current)) return; // no-op on same selection
  current = ctx;
  listeners.forEach((fn) => fn(current));
}

export function getChatContext(): ChatPageContext | null {
  return current;
}

export function subscribeChatContext(fn: (ctx: ChatPageContext | null) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
