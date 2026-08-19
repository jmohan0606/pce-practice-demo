from __future__ import annotations

"""ONE GraphClient adapter with an automatic 4-tier fallback chain.

    Tier 1  tigergraph-mcp   (official MCP server over stdio; pyTigerGraph async
                              underneath) — primary path for agent-initiated access
    Tier 2  pyTigerGraph     (direct sync connection) — standard non-agent path
    Tier 3  RESTPP           (existing RealGraphClient, httpx against /restpp)
    Tier 4  MockGraphClient  (CSV-backed FoundationGraphStore local store) — final
                              fallback and the working default on this machine

Every tier implements the same GraphClient interface (run_query / upsert /
health / statistics) with the same result envelope, so services cannot tell
which tier served them. TieredGraphClient tries tiers in order; connection-level
failures put a tier on cooldown; every served request is recorded in
app.graph.tier_log (which tier, operation, target, latency, and which tiers were
tried and failed first) for the Admin/Data Health adapter-status display.

SDK imports (mcp, pyTigerGraph) are lazy — inside methods — so a missing package
can never break import of the mock path.
"""

import asyncio
import json
import time
from typing import Any, Callable

from app.config.settings import get_settings
from app.graph.client import (
    GraphClientError,
    MockGraphClient,
    PartialUpsertError,
    RealGraphClient,
    _coerce,
    map_entry_attributes,
)
from app.graph.tier_log import TIER_NAMES, get_tier_log
from app.shared.logging import get_logger

# Dedicated logger for the live TigerGraph connection path. Every step (connect,
# auth/token, per-batch upsert with row counts, failure-with-full-error) lands in
# logs/app.log so a first run against the client's real remote instance is
# diagnosable without attaching a debugger.
_tg_log = get_logger("app.graph.tigergraph")


def _mask(value: str | None) -> str:
    """Log-safe fingerprint of a secret/token — never the value itself."""
    if not value:
        return "<none>"
    return f"<set:{len(value)} chars, …{value[-4:]}>" if len(value) >= 4 else "<set>"


def _entry_attributes(entry: dict, row: dict, excluded: set[str]) -> dict[str, Any]:
    """Map a manifest-entry row to a graph attribute dict, fail-loud: an absent
    mapped column raises ColumnMismatchError instead of silently dropping the
    attribute, and an all-empty record refuses to write attribute-less."""
    return map_entry_attributes(entry, row, excluded, lambda _src, _attr, value: _coerce(value))


class McpGraphClient:
    """Tier 1 — official `tigergraph-mcp` server driven over stdio.

    Reuses the stdio session client/tool mapper
    (app/graph/tigergraph_mcp_stdio_client.py) which speaks the official
    `tigergraph__*` tool names (verified against tigergraph-mcp 1.0.1's
    tool_names.py). The MCP server reads TG_HOST / TG_GRAPHNAME / TG_USERNAME /
    TG_PASSWORD / TG_API_TOKEN / TG_RESTPP_PORT / TG_GS_PORT from env.
    """

    tier = 1

    def __init__(self) -> None:
        settings = get_settings()
        self.graph_name = settings.tg_graphname or settings.tigergraph_graph
        self.timeout = settings.graph_tier_probe_timeout_seconds
        self._client = None
        self._mapper = None

    def _ensure(self):
        if self._mapper is None:
            # local import: this module lazily imports the `mcp` SDK itself,
            # so a missing tigergraph-mcp/mcp install surfaces only when this
            # tier is actually exercised.
            from app.graph.tigergraph_mcp_stdio_client import (
                TigerGraphMcpStdioClient,
                TigerGraphMcpToolMapper,
            )

            self._client = TigerGraphMcpStdioClient()
            self._mapper = TigerGraphMcpToolMapper(self._client)
        return self._mapper

    @staticmethod
    def _parse_tool_response(result: dict[str, Any]) -> dict[str, Any]:
        """tigergraph-mcp 1.0.1 returns ONE TextContent whose text embeds the real
        outcome as a fenced JSON envelope: {"success": bool, "operation", "summary",
        "data", "error", ...} (see tigergraph_mcp/response_formatter.py). MCP-level
        is_error stays False even when the tool itself failed, so the envelope —
        not the transport flag — is the source of truth."""
        import re

        for item in result.get("content", []):
            if isinstance(item, dict) and "success" in item:
                return item
            if isinstance(item, str):
                match = re.search(r"```json\s*\n(.*?)\n```", item, re.S)
                if match:
                    try:
                        parsed = json.loads(match.group(1))
                        if isinstance(parsed, dict) and "success" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        pass
        return {"success": not result.get("is_error"), "data": result.get("content")}

    def _call(self, logical_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Invoke an official tigergraph__* tool and return its parsed envelope;
        raises GraphClientError when the tool reports success=false."""
        mapper = self._ensure()
        tool_name = mapper.TOOL_NAMES.get(logical_tool, logical_tool)
        if not mapper.has_tool(tool_name):
            raise GraphClientError(f"tigergraph-mcp does not expose tool {tool_name}")
        filtered = mapper._filter_args(tool_name, args)
        result = asyncio.run(
            asyncio.wait_for(self._client.call_tool_async(tool_name, filtered), timeout=self.timeout * 6)
        )
        envelope = self._parse_tool_response(result)
        if result.get("is_error") or envelope.get("success") is False:
            raise GraphClientError(
                f"tigergraph-mcp tool {tool_name} failed: "
                f"{envelope.get('error') or envelope.get('summary') or result.get('content')}"
            )
        return envelope

    def health(self) -> dict:
        try:
            envelope = self._call("list_graphs", {})
            return {
                "healthy": True,
                "mode": "mcp",
                "graph": self.graph_name,
                "graphs": envelope.get("data"),
            }
        except Exception as exc:  # noqa: BLE001 — health never raises
            return {"healthy": False, "mode": "mcp", "graph": self.graph_name, "error": str(exc)}

    def run_query(self, query_name: str, params: dict | None = None) -> dict:
        envelope = self._call(
            "run_installed_query",
            {"graph_name": self.graph_name, "query_name": query_name, "params": params or {}},
        )
        data = envelope.get("data")
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
        elif isinstance(data, list):
            results = data
        else:
            results = [data] if data is not None else []
        return {"error": False, "results": results, "mode": "mcp", "query": query_name}

    def upsert(self, entry: dict, records: list[dict]) -> dict:
        if not records:
            return {"error": False, "accepted_vertices": 0, "accepted_edges": 0, "mode": "mcp"}
        accepted = 0
        if entry["kind"] == "vertex":
            id_col = entry["id_column"]
            for row in records:
                vertex_id = str(row[id_col]).strip()
                if not vertex_id:
                    raise GraphClientError(f"Blank vertex id in {entry.get('file', entry['target'])}")
                self._call(
                    "add_node",
                    {
                        "graph_name": self.graph_name,
                        "vertex_type": entry["target"],
                        "vertex_id": vertex_id,
                        "attributes": _entry_attributes(entry, row, {id_col}),
                    },
                )
                accepted += 1
            return {"error": False, "accepted_vertices": accepted, "accepted_edges": 0, "mode": "mcp"}
        from_col, to_col = entry["from_column"], entry["to_column"]
        for row in records:
            from_id, to_id = str(row[from_col]).strip(), str(row[to_col]).strip()
            if not from_id or not to_id:
                raise GraphClientError(f"Blank edge endpoint in {entry.get('file', entry['target'])}")
            self._call(
                "add_edge",
                {
                    "graph_name": self.graph_name,
                    "edge_type": entry["target"],
                    "source_vertex_type": entry["from_type"],
                    "source_vertex_id": from_id,
                    "target_vertex_type": entry["to_type"],
                    "target_vertex_id": to_id,
                    "attributes": _entry_attributes(entry, row, {from_col, to_col}),
                },
            )
            accepted += 1
        return {"error": False, "accepted_vertices": 0, "accepted_edges": accepted, "mode": "mcp"}

    def fetch_vertices(self, vertex_type: str, limit: int = 5) -> dict:
        envelope = self._call(
            "get_nodes", {"graph_name": self.graph_name, "node_type": vertex_type, "limit": limit}
        )
        data = envelope.get("data")
        results = data if isinstance(data, list) else ([data] if data else [])
        return {"error": False, "results": results, "mode": "mcp"}

    def statistics(self, kind: str = "vertex", target_type: str = "*") -> dict:
        tool = "get_vertex_count" if kind == "vertex" else "get_edge_count"
        args: dict[str, Any] = {"graph_name": self.graph_name}
        if target_type != "*":
            key = "vertex_type" if kind == "vertex" else "edge_type"
            args[key] = target_type
        envelope = self._call(tool, args)
        return {"error": False, "results": [{"counts": envelope.get("data")}], "mode": "mcp"}


class PyTigerGraphClient:
    """Tier 2 — direct pyTigerGraph connection (the client's standard non-agent path)."""

    tier = 2

    def __init__(self) -> None:
        settings = get_settings()
        self.host = (settings.tg_host or settings.tigergraph_host or "http://127.0.0.1").rstrip("/")
        # Honor the SSL toggle: force https when TG_USE_SSL=true, else keep an explicit
        # scheme, else default to http for bare hosts.
        if "://" not in self.host:
            self.host = ("https://" if settings.tg_use_ssl else "http://") + self.host
        elif settings.tg_use_ssl and self.host.startswith("http://"):
            self.host = "https://" + self.host[len("http://"):]
        self.use_ssl = self.host.startswith("https://")
        self.verify_ssl = settings.tg_verify_ssl
        self.graph_name = settings.tg_graphname or settings.tigergraph_graph
        self.username = settings.tg_username
        self.password = settings.tg_password
        # Auth precedence: JWT → static API token → getToken(secret) → user/pass only.
        self.jwt_token = settings.tg_jwt_token or ""
        self.api_token = settings.tg_api_token or settings.tigergraph_token or ""
        self.secret = settings.tg_secret or settings.tigergraph_secret or ""
        self.token_lifetime = settings.tg_token_lifetime_seconds
        self.restpp_port = settings.tg_restpp_port
        self.gs_port = settings.tg_gs_port
        self.ssl_port = settings.tg_ssl_port
        self.timeout = settings.graph_tier_probe_timeout_seconds
        self._conn = None

    def _connection(self):
        if self._conn is not None:
            return self._conn
        from pyTigerGraph import TigerGraphConnection  # lazy — adapter rule

        _tg_log.info(
            "TigerGraph(pyTigerGraph) connecting",
            extra={
                "host": self.host, "graph": self.graph_name, "username": self.username,
                "restpp_port": self.restpp_port, "gs_port": self.gs_port, "ssl_port": self.ssl_port,
                "use_ssl": self.use_ssl, "verify_ssl": self.verify_ssl,
                "auth": ("jwt" if self.jwt_token else "api_token" if self.api_token
                         else "secret->getToken" if self.secret else "user_pass"),
                "secret": _mask(self.secret), "api_token": _mask(self.api_token),
            },
        )
        try:
            conn = TigerGraphConnection(
                host=self.host,
                graphname=self.graph_name,
                username=self.username,
                password=self.password,
                restppPort=str(self.restpp_port),
                gsPort=str(self.gs_port),
                sslPort=str(self.ssl_port),
                apiToken=(self.jwt_token or self.api_token) or None,
            )
            # Some pyTigerGraph versions expose TLS verification toggles for self-signed certs.
            if self.use_ssl and not self.verify_ssl:
                for attr in ("sslVerify", "certVerify"):
                    if hasattr(conn, attr):
                        setattr(conn, attr, False)

            # If only a secret is configured, acquire a REST++ token now (getToken) — this
            # is the path a secured instance with no pre-issued JWT needs.
            if not self.jwt_token and not self.api_token and self.secret:
                lifetime = self.token_lifetime or None
                result = conn.getToken(self.secret, lifetime=lifetime) if lifetime else conn.getToken(self.secret)
                token = result[0] if isinstance(result, (list, tuple)) else result
                expiry = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else "server-default"
                _tg_log.info(
                    "TigerGraph token acquired via getToken(secret)",
                    extra={"token": _mask(str(token)), "expires": str(expiry), "graph": self.graph_name},
                )

            echo = conn.echo()
            _tg_log.info(
                "TigerGraph(pyTigerGraph) connection established",
                extra={"host": self.host, "graph": self.graph_name, "echo": str(echo)[:120]},
            )
            self._conn = conn
        except Exception as exc:  # noqa: BLE001 — surface the full reason for a first live run
            _tg_log.error(
                "TigerGraph(pyTigerGraph) connection FAILED: %s: %s",
                type(exc).__name__, exc,
                exc_info=True,
                extra={"host": self.host, "graph": self.graph_name, "use_ssl": self.use_ssl,
                       "auth": ("secret" if self.secret else "token" if (self.jwt_token or self.api_token) else "user_pass")},
            )
            raise
        return self._conn

    def health(self) -> dict:
        try:
            echo = self._connection().echo()
            return {"healthy": True, "mode": "pytigergraph", "graph": self.graph_name, "echo": echo, "host": self.host}
        except Exception as exc:  # noqa: BLE001
            return {"healthy": False, "mode": "pytigergraph", "graph": self.graph_name, "host": self.host, "error": str(exc)}

    def run_query(self, query_name: str, params: dict | None = None) -> dict:
        results = self._connection().runInstalledQuery(query_name, params=params or {}, timeout=self.timeout * 6000)
        if not isinstance(results, list):
            results = [results] if results is not None else []
        return {"error": False, "results": results, "mode": "pytigergraph", "query": query_name}

    def upsert(self, entry: dict, records: list[dict]) -> dict:
        if not records:
            return {"error": False, "accepted_vertices": 0, "accepted_edges": 0, "mode": "pytigergraph"}
        conn = self._connection()
        if entry["kind"] == "vertex":
            id_col = entry["id_column"]
            payload = []
            for row in records:
                vertex_id = str(row[id_col]).strip()
                if not vertex_id:
                    raise GraphClientError(f"Blank vertex id in {entry.get('file', entry['target'])}")
                payload.append((vertex_id, _entry_attributes(entry, row, {id_col})))
            accepted = conn.upsertVertices(entry["target"], payload)
            _tg_log.info(
                "TigerGraph vertex batch upserted",
                extra={"vertex_type": entry["target"], "requested": len(records),
                       "accepted": accepted, "graph": self.graph_name},
            )
            if accepted != len(records):
                _tg_log.error(
                    "TigerGraph vertex upsert PARTIAL: %s of %s for %s",
                    accepted, len(records), entry["target"],
                    extra={"vertex_type": entry["target"], "requested": len(records), "accepted": accepted},
                )
                raise PartialUpsertError(
                    f"pyTigerGraph accepted {accepted} of {len(records)} vertex records for {entry['target']}",
                    {"accepted_vertices": accepted},
                    accepted,
                    len(records),
                )
            return {"error": False, "accepted_vertices": accepted, "accepted_edges": 0, "mode": "pytigergraph"}
        from_col, to_col = entry["from_column"], entry["to_column"]
        payload = []
        for row in records:
            from_id, to_id = str(row[from_col]).strip(), str(row[to_col]).strip()
            if not from_id or not to_id:
                raise GraphClientError(f"Blank edge endpoint in {entry.get('file', entry['target'])}")
            payload.append((from_id, to_id, _entry_attributes(entry, row, {from_col, to_col})))
        accepted = conn.upsertEdges(entry["from_type"], entry["target"], entry["to_type"], payload)
        _tg_log.info(
            "TigerGraph edge batch upserted",
            extra={"edge_type": entry["target"], "from_type": entry["from_type"],
                   "to_type": entry["to_type"], "requested": len(records),
                   "accepted": accepted, "graph": self.graph_name},
        )
        if accepted != len(records):
            _tg_log.error(
                "TigerGraph edge upsert PARTIAL: %s of %s for %s",
                accepted, len(records), entry["target"],
                extra={"edge_type": entry["target"], "requested": len(records), "accepted": accepted},
            )
            raise PartialUpsertError(
                f"pyTigerGraph accepted {accepted} of {len(records)} edge records for {entry['target']}",
                {"accepted_edges": accepted},
                accepted,
                len(records),
            )
        return {"error": False, "accepted_vertices": 0, "accepted_edges": accepted, "mode": "pytigergraph"}

    def fetch_vertices(self, vertex_type: str, limit: int = 5) -> dict:
        """Sample stored vertices (attribute-population proof) via pyTigerGraph getVertices."""
        rows = self._connection().getVertices(vertex_type, limit=str(limit))
        if not isinstance(rows, list):
            rows = [rows] if rows else []
        return {"error": False, "results": rows, "mode": "pytigergraph"}

    def delete_vertices(self, vertex_type: str, ids: list[str]) -> dict:
        conn = self._connection()
        deleted = conn.delVerticesById(vertex_type, [str(v) for v in ids])
        _tg_log.info(
            "TigerGraph vertices deleted",
            extra={"vertex_type": vertex_type, "requested": len(ids), "deleted": deleted,
                   "graph": self.graph_name},
        )
        return {"error": False, "deleted": int(deleted or 0), "mode": "pytigergraph", "target": vertex_type}

    def delete_all(self, target: str, kind: str = "vertex") -> dict:
        if kind != "vertex":
            raise GraphClientError(
                f"pyTigerGraph cannot bulk-delete edge type {target}; delete its endpoint vertices instead"
            )
        conn = self._connection()
        deleted = conn.delVertices(target)
        _tg_log.info(
            "TigerGraph vertex type cleared",
            extra={"vertex_type": target, "deleted": deleted, "graph": self.graph_name},
        )
        return {"error": False, "deleted": int(deleted or 0), "mode": "pytigergraph", "target": target}

    def statistics(self, kind: str = "vertex", target_type: str = "*") -> dict:
        conn = self._connection()
        if kind == "vertex":
            counts = conn.getVertexCount(target_type)
        else:
            counts = conn.getEdgeCount(target_type if target_type != "*" else "*")
        if not isinstance(counts, dict):
            counts = {target_type: counts}
        return {"error": False, "results": [{"counts": counts}], "mode": "pytigergraph"}


class TieredGraphClient:
    """ONE adapter composing the 4 tiers with automatic fallback + tier logging.

    - Requests try tiers in configured order; the first tier that succeeds
      serves the request and is recorded in the TierUsageLog together with the
      tiers that were tried and failed before it.
    - Connection-level failures (anything other than GraphClientError) put the
      tier on cooldown (GRAPH_TIER_COOLDOWN_SECONDS) so every request doesn't
      pay repeated connect timeouts; query-level GraphClientError just falls
      through for this request without cooling the tier down.
    - PartialUpsertError propagates immediately (the engine WAS reached; a data
      problem must not be silently retried against a lower-fidelity tier).
    - The final tier (mock) is always tried even if on cooldown.
    """

    def __init__(self, tiers: list[tuple[int, Callable[[], Any]]], mode_label: str) -> None:
        settings = get_settings()
        self._specs = tiers
        self.mode_label = mode_label
        self.cooldown = settings.graph_tier_cooldown_seconds
        self._instances: dict[int, Any] = {}
        self._unavailable_until: dict[int, float] = {}
        self._health_cache: tuple[float, dict] | None = None
        self._log = get_tier_log()

    # --- construction ----------------------------------------------------
    @classmethod
    def for_mode(cls, mode: str) -> "TieredGraphClient":
        full: list[tuple[int, Callable[[], Any]]] = [
            (1, McpGraphClient),
            (2, PyTigerGraphClient),
            (3, RealGraphClient),
            (4, MockGraphClient),
        ]
        if mode in {"auto", "tiered", "mcp"}:
            return cls(full, mode_label=mode)
        if mode in {"local_real", "real"}:
            # non-agent standard path: pyTigerGraph first, RESTPP, then mock
            return cls(full[1:], mode_label=mode)
        raise GraphClientError(f"TieredGraphClient does not handle mode '{mode}'")

    def _tier(self, tier_no: int) -> Any:
        if tier_no not in self._instances:
            factory = dict(self._specs)[tier_no]
            self._instances[tier_no] = factory()
        return self._instances[tier_no]

    # --- dispatch ---------------------------------------------------------
    def _dispatch(self, operation: str, target: str, call: Callable[[Any], dict]) -> dict:
        now = time.monotonic()
        failures: list[str] = []
        last_exc: Exception | None = None
        tier_numbers = [t for t, _ in self._specs]
        final_tier = tier_numbers[-1]
        self._log.enter_dispatch()
        try:
            for tier_no in tier_numbers:
                if tier_no != final_tier and self._unavailable_until.get(tier_no, 0) > now:
                    continue  # cooling down after a connection failure
                start = time.perf_counter()
                try:
                    client = self._tier(tier_no)
                    result = call(client)
                except PartialUpsertError:
                    raise  # engine reached; do NOT degrade to a lower tier
                except GraphClientError as exc:
                    # query-level failure: fall through, no cooldown
                    self._log.record(tier_no, operation, target, ok=False,
                                     duration_ms=(time.perf_counter() - start) * 1000, error=str(exc))
                    failures.append(f"tier{tier_no}:{TIER_NAMES[tier_no]}: {exc}")
                    last_exc = exc
                    continue
                except Exception as exc:  # noqa: BLE001 — connection-level failure
                    self._log.record(tier_no, operation, target, ok=False,
                                     duration_ms=(time.perf_counter() - start) * 1000, error=str(exc))
                    self._unavailable_until[tier_no] = time.monotonic() + self.cooldown
                    failures.append(f"tier{tier_no}:{TIER_NAMES[tier_no]}: {exc}")
                    last_exc = exc
                    continue
                self._log.record(tier_no, operation, target, ok=True,
                                 duration_ms=(time.perf_counter() - start) * 1000,
                                 fallback_from=list(failures))
                if isinstance(result, dict):
                    result.setdefault("served_by_tier", tier_no)
                    result.setdefault("served_by", TIER_NAMES[tier_no])
                return result
        finally:
            self._log.exit_dispatch()
        raise GraphClientError(
            f"All graph tiers failed for {operation} '{target}': {'; '.join(failures)}"
        ) from last_exc

    # --- GraphClient interface ---------------------------------------------
    def run_query(self, query_name: str, params: dict | None = None) -> dict:
        return self._dispatch("run_query", query_name, lambda c: c.run_query(query_name, params))

    def upsert(self, entry: dict, records: list[dict]) -> dict:
        return self._dispatch("upsert", entry.get("target", "?"), lambda c: c.upsert(entry, records))

    def statistics(self, kind: str = "vertex", target_type: str = "*") -> dict:
        return self._dispatch("statistics", f"{kind}:{target_type}", lambda c: c.statistics(kind, target_type))

    def delete_vertices(self, vertex_type: str, ids: list[str]) -> dict:
        return self._dispatch("delete_vertices", vertex_type, lambda c: c.delete_vertices(vertex_type, ids))

    def delete_all(self, target: str, kind: str = "vertex") -> dict:
        return self._dispatch("delete_all", target, lambda c: c.delete_all(target, kind))

    def fetch_vertices(self, vertex_type: str, limit: int = 5) -> dict:
        return self._dispatch("fetch_vertices", vertex_type, lambda c: c.fetch_vertices(vertex_type, limit))

    def health(self) -> dict:
        # probe each tier (cached 30s — the MCP probe spawns a subprocess)
        if self._health_cache and time.monotonic() - self._health_cache[0] < 30:
            return self._health_cache[1]
        tiers = []
        active_tier = None
        now = time.monotonic()
        for tier_no, _ in self._specs:
            entry: dict[str, Any] = {"tier": tier_no, "name": TIER_NAMES[tier_no]}
            cooldown_left = self._unavailable_until.get(tier_no, 0) - now
            if cooldown_left > 0:
                entry.update({"healthy": False, "cooldown_seconds_left": round(cooldown_left, 1)})
            else:
                try:
                    entry.update(self._tier(tier_no).health())
                except Exception as exc:  # noqa: BLE001
                    entry.update({"healthy": False, "error": str(exc)})
            if entry.get("healthy") and active_tier is None:
                active_tier = tier_no
            tiers.append(entry)
        payload = {
            "healthy": active_tier is not None,
            "mode": f"tiered:{self.mode_label}",
            "graph": get_settings().tigergraph_graph,
            "active_tier": active_tier,
            "active_tier_name": TIER_NAMES.get(active_tier or -1),
            "tiers": tiers,
        }
        self._health_cache = (time.monotonic(), payload)
        return payload

    # --- extras ------------------------------------------------------------
    @property
    def store(self):
        """Backing FoundationGraphStore of the mock tier. No service reads
        `get_graph_client().store` (Round 9: every read goes through
        run_catalog_query, and scripts/check_store_reads.py fails any new use
        of this property outside app/graph/) — it remains only for the mock
        tier's own plumbing and tests. In tiered modes it resolves to the
        final-fallback mock tier's store, which in real mode is NOT the data
        the app serves."""
        for tier_no, _ in self._specs:
            if tier_no == 4:
                return self._tier(4).store
        raise AttributeError("TieredGraphClient chain has no mock tier / store")

    def tier_status(self) -> dict:
        """Adapter-status payload for the Admin/Data Health page."""
        now = time.monotonic()
        return {
            "mode": self.mode_label,
            "chain": [
                {
                    "tier": tier_no,
                    "name": TIER_NAMES[tier_no],
                    "instantiated": tier_no in self._instances,
                    "cooldown_seconds_left": max(0.0, round(self._unavailable_until.get(tier_no, 0) - now, 1)),
                }
                for tier_no, _ in self._specs
            ],
            "cooldown_seconds": self.cooldown,
            "usage": self._log.summary(),
        }
