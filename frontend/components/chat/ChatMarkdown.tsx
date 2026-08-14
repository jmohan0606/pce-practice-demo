"use client";

/** Round E 6.3 — the chat message markdown renderer (small, custom, no deps).
 *
 * Supported subset (the agent's output conventions, spec + mockup):
 *   paragraphs · **bold** · markdown tables (.mt styling) · lists ·
 *   links incl. rule:RULE_KEY → /rules and doc:DOCUMENT_ID → /documents ·
 *   "Name (V000002)" autolinked to /advisor?sid=SID (AdvisorLink convention) ·
 *   figures coloured and arrowed via the shared <NarrativeText> conventions
 *   (positives green ▲, parenthesised negatives red ▼ — lib/format.ts rules).
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { NarrativeText } from "@/components/Num";

// ------------------------------------------------------------- inline layer

/** "Sandra Mehta (V000002)" (or a bare "(V000002)" / "V000002") → advisor link. */
const SID_RE = /((?:[A-Z][A-Za-z'’.\-]*\s+){0,4}?)\(?(V\d{6})\)?/g;

function AutoSid({ text, keyBase }: { text: string; keyBase: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  SID_RE.lastIndex = 0;
  for (const m of text.matchAll(SID_RE)) {
    const start = m.index ?? 0;
    if (start > last) out.push(<NarrativeText key={`${keyBase}t${i++}`} text={text.slice(last, start)} />);
    const sid = m[2];
    // Only a parenthesised SID carries the preceding words as the advisor's
    // name — "Sandra Mehta (V000002)". A bare SID links alone, and whatever
    // capitalised words preceded it render as plain text.
    const parenthesised = m[0].includes("(");
    const name = parenthesised ? (m[1] || "").trim() : "";
    if (!parenthesised && m[1]) out.push(<NarrativeText key={`${keyBase}n${i++}`} text={m[1]} />);
    const label = name ? `${name} (${sid})` : sid;
    out.push(
      <Link key={`${keyBase}a${i++}`} className="advlink" href={`/advisor?sid=${encodeURIComponent(sid)}`}>
        {label}
      </Link>,
    );
    last = start + m[0].length;
  }
  if (last < text.length) out.push(<NarrativeText key={`${keyBase}t${i++}`} text={text.slice(last)} />);
  return <>{out}</>;
}

/** [label](target) — rule:KEY → /rules, doc:ID → /documents, else pass-through. */
const LINK_RE = /\[([^\]]+)\]\(([^)\s]+)\)/g;

function linkHref(target: string): string {
  if (target.startsWith("rule:")) return "/rules";
  if (target.startsWith("doc:")) return "/documents";
  return target;
}

function InlineLinks({ text, keyBase }: { text: string; keyBase: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  LINK_RE.lastIndex = 0;
  for (const m of text.matchAll(LINK_RE)) {
    const start = m.index ?? 0;
    if (start > last) out.push(<AutoSid key={`${keyBase}s${i++}`} keyBase={`${keyBase}s${i}`} text={text.slice(last, start)} />);
    const href = linkHref(m[2]);
    const external = /^https?:/.test(href);
    out.push(
      external ? (
        <a key={`${keyBase}l${i++}`} className="advlink" href={href} target="_blank" rel="noreferrer">
          {m[1]}
        </a>
      ) : (
        <Link key={`${keyBase}l${i++}`} className="advlink" href={href}>
          {m[1]}
        </Link>
      ),
    );
    last = start + m[0].length;
  }
  if (last < text.length) out.push(<AutoSid key={`${keyBase}s${i++}`} keyBase={`${keyBase}s${i}`} text={text.slice(last)} />);
  return <>{out}</>;
}

/** Bold first (so **…** can wrap links/figures), then links, SIDs, figures. */
export function ChatInline({ text, keyBase = "k" }: { text: string; keyBase?: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <b key={i}>
            <InlineLinks text={part} keyBase={`${keyBase}b${i}`} />
          </b>
        ) : part ? (
          <InlineLinks key={i} text={part} keyBase={`${keyBase}p${i}`} />
        ) : null,
      )}
    </>
  );
}

// -------------------------------------------------------------- block layer

type Block =
  | { type: "p"; lines: string[] }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "list"; ordered: boolean; items: string[] };

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((c) => c.trim());
}

const SEP_ROW = /^\s*\|?\s*:?-{2,}[-:\s|]*$/;

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && SEP_ROW.test(lines[i + 1])) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }
    const listMatch = /^\s*(?:[-*]|\d+[.)])\s+/.exec(line);
    if (listMatch) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*(?:[-*]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+[.)])\s+/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("|") &&
      !/^\s*(?:[-*]|\d+[.)])\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push({ type: "p", lines: para });
  }
  return blocks;
}

/** Numeric-looking cells get .num right-alignment, mockup-style. */
function isNumeric(cell: string): boolean {
  return /^[▲▼]?\s*[($+\-−]?[\d$]/.test(cell.replace(/\*\*/g, "").trim()) && /\d/.test(cell);
}

export default function ChatMarkdown({ text }: { text: string }) {
  const blocks = parseBlocks(text);
  return (
    <>
      {blocks.map((b, bi) => {
        if (b.type === "table") {
          const numCols = b.header.map((_, c) => b.rows.length > 0 && b.rows.every((r) => !r[c] || isNumeric(r[c])));
          return (
            <table className="mt" key={bi}>
              <thead>
                <tr>
                  {b.header.map((h, hi) => (
                    <th key={hi} className={numCols[hi] ? "num" : undefined}>
                      <ChatInline text={h} keyBase={`t${bi}h${hi}`} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri}>
                    {r.map((cell, ci) => (
                      <td key={ci} className={numCols[ci] ? "num" : undefined}>
                        <ChatInline text={cell} keyBase={`t${bi}r${ri}c${ci}`} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }
        if (b.type === "list") {
          const items = b.items.map((item, ii) => (
            <li key={ii}>
              <ChatInline text={item} keyBase={`l${bi}i${ii}`} />
            </li>
          ));
          return b.ordered ? <ol key={bi}>{items}</ol> : <ul key={bi}>{items}</ul>;
        }
        return (
          <p key={bi}>
            {b.lines.map((ln, li) => (
              <span key={li}>
                {li > 0 ? <br /> : null}
                <ChatInline text={ln} keyBase={`p${bi}l${li}`} />
              </span>
            ))}
          </p>
        );
      })}
    </>
  );
}
