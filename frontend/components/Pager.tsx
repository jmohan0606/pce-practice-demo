"use client";

import { useMemo, useState } from "react";

/** Round 3 task 6.1 — pagination everywhere.
 *
 * Every table and record list paginates with a page-size dropdown of
 * 5 / 10 / 20, default 5 (the only exceptions, per the spec: the dashboard
 * product table and the Top/Bottom advisors modal). Use the hook for state
 * and render <Pager> under the table:
 *
 *   const pager = usePager(rows);            // rows: any[]
 *   ...pager.rows.map(...)                   // the current page
 *   <Pager {...pager} noun="accounts" />
 */

export const PAGE_SIZES = [5, 10, 20] as const;

export interface PagerState<T> {
  rows: T[];
  total: number;
  page: number;
  pageCount: number;
  size: number;
  setPage: (p: number) => void;
  setSize: (s: number) => void;
}

export function usePager<T>(all: T[], defaultSize: number = 5): PagerState<T> {
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(defaultSize);
  const total = all.length;
  const pageCount = Math.max(1, Math.ceil(total / size));
  const safePage = Math.min(page, pageCount - 1);
  const rows = useMemo(
    () => all.slice(safePage * size, safePage * size + size),
    [all, safePage, size],
  );
  return {
    rows,
    total,
    page: safePage,
    pageCount,
    size,
    setPage,
    setSize: (s: number) => {
      setSize(s);
      setPage(0);
    },
  };
}

export function Pager<T>({
  total,
  page,
  pageCount,
  size,
  setPage,
  setSize,
  noun = "rows",
}: PagerState<T> & { noun?: string }) {
  if (total <= PAGE_SIZES[0] && pageCount <= 1) return null;
  const from = page * size + 1;
  const to = Math.min(total, (page + 1) * size);
  return (
    <div className="pager">
      <span className="pager-info">
        {from}–{to} of {total.toLocaleString("en-US")} {noun}
      </span>
      <span className="pager-ctl">
        <label>
          Show{" "}
          <select
            value={size}
            onChange={(e) => setSize(Number(e.target.value))}
            aria-label="Rows per page"
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
          aria-label="Previous page"
        >
          ‹
        </button>
        <span className="pager-page">
          {page + 1} / {pageCount}
        </span>
        <button
          type="button"
          disabled={page >= pageCount - 1}
          onClick={() => setPage(page + 1)}
          aria-label="Next page"
        >
          ›
        </button>
      </span>
    </div>
  );
}
