"use client";

/** Round E 6.3–6.5 — one chat exchange row: user bubble right/navy, agent
 * left; guardrail block, live/collapsed reasoning, confirm box, limits note.
 * Visuals copied from docs/ui/MOCKUP_CHAT.html into the app's tokens.
 */

import type { LimitHit } from "@/lib/api";
import type { AnswerKind, GuardrailAction, StepEvent } from "@/lib/chatApi";
import { LimitNotice } from "@/components/InsightPanel";
import ChatMarkdown from "@/components/chat/ChatMarkdown";

export interface UiStep {
  kind: string;
  step: string;
}

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  kind?: AnswerKind;
  streaming?: boolean;
  guardrail?: { tag: string; confidence?: number; action: GuardrailAction; notice: string } | null;
  steps: UiStep[];
  latencyMs?: number | null;
  limitsHit?: LimitHit[];
}

/** "PROMPT_INJECTION" → "Prompt Injection" (mockup chip casing). */
function tagLabel(tag: string): string {
  return tag
    .split("_")
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(" ");
}

function GuardrailBlock({ guardrail }: { guardrail: NonNullable<UiMessage["guardrail"]> }) {
  return (
    <div className="gr block" role="alert">
      <div className="hd">
        ⚠ Blocked <span className="tagchip">{tagLabel(guardrail.tag)}</span>
      </div>
      {guardrail.notice ||
        "Part of that message was blocked by the guardrail and was not passed to any tool."}
      <div className="meta">Tools called: 0 · Layer 1 detection · logged to the guardrail trace</div>
    </div>
  );
}

/** Live reasoning while streaming: pulsing dot on the newest step, ✓ done. */
export function LiveReasoning({ steps }: { steps: UiStep[] }) {
  if (!steps.length) {
    return (
      <div className="live">
        <div className="now">
          <span className="dot" />
          Thinking…
        </div>
      </div>
    );
  }
  const done = steps.slice(0, -1);
  const now = steps[steps.length - 1];
  return (
    <div className="live">
      <div className="now">
        <span className="dot" />
        {now.step}
      </div>
      {done.map((s, i) => (
        <div className="done" key={i}>
          {s.step}
        </div>
      ))}
    </div>
  );
}

/** Collapsed reasoning once the answer arrived (or for history rows). */
function ReasoningDetails({ steps, latencyMs }: { steps: UiStep[]; latencyMs?: number | null }) {
  if (!steps.length) return null;
  const secs = latencyMs != null ? ` · ${(latencyMs / 1000).toFixed(1)}s` : "";
  return (
    <details className="reason">
      <summary>
        Show reasoning · {steps.length} {steps.length === 1 ? "step" : "steps"}
        {secs}
      </summary>
      <div className="steps">
        {steps.map((s, i) => (
          <div key={i}>{s.step}</div>
        ))}
      </div>
    </details>
  );
}

export function stepFromEvent(e: StepEvent): UiStep {
  return { kind: e.kind, step: e.step };
}

export default function ChatMessage({
  message,
  onPrefill,
}: {
  message: UiMessage;
  /** Confirm-box buttons prefill the composer with a reply. */
  onPrefill: (text: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{message.text}</div>
      </div>
    );
  }

  const blocked = message.guardrail && message.guardrail.action !== "ALLOWED";
  const body = message.text.trim();

  return (
    <div className="msg bot">
      {blocked && message.guardrail ? <GuardrailBlock guardrail={message.guardrail} /> : null}
      {message.streaming ? (
        <LiveReasoning steps={message.steps} />
      ) : (
        <ReasoningDetails steps={message.steps} latencyMs={message.latencyMs} />
      )}
      {!message.streaming && body ? (
        message.kind === "confirm" ? (
          <div className="confirm">
            <ChatMarkdown text={body} />
            <div className="btns">
              <button type="button" className="cbtn yes" onClick={() => onPrefill("Yes, go ahead")}>
                Yes, go ahead
              </button>
              <button type="button" className="cbtn" onClick={() => onPrefill("No thanks")}>
                No thanks
              </button>
            </div>
          </div>
        ) : (
          <div className={`bubble${message.kind === "error" ? " err" : ""}`}>
            <ChatMarkdown text={body} />
          </div>
        )
      ) : null}
      {!message.streaming ? <LimitNotice limits={message.limitsHit} /> : null}
    </div>
  );
}
