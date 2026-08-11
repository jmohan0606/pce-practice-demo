from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from app.config.settings import get_settings


@dataclass
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


class TigerGraphMcpStdioClient:
    """Official-pattern TigerGraph MCP client.

    Correct pattern:
    - Start MCP server using stdio transport.
    - Use mcp.ClientSession.
    - Discover tools using session.list_tools().
    - Invoke official tools using session.call_tool("tigergraph__...", arguments={...}).
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _get(self, name: str, default: Any = None) -> Any:
        value = getattr(self.settings, name, default)
        return default if value is None else value

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        tg_env = {
            "TG_HOST": os.getenv("TG_HOST", self._get("tigergraph_host", "http://127.0.0.1")),
            "TG_GRAPHNAME": os.getenv("TG_GRAPHNAME", self.settings.tigergraph_graph),
            "TG_USERNAME": os.getenv("TG_USERNAME", "tigergraph"),
            "TG_PASSWORD": os.getenv("TG_PASSWORD", "tigergraph"),
            "TG_SECRET": os.getenv("TG_SECRET", ""),
            "TG_API_TOKEN": os.getenv("TG_API_TOKEN", self._get("tigergraph_token", "")),
            "TG_JWT_TOKEN": os.getenv("TG_JWT_TOKEN", ""),
            "TG_RESTPP_PORT": os.getenv("TG_RESTPP_PORT", "9000"),
            "TG_GS_PORT": os.getenv("TG_GS_PORT", "14240"),
            "TG_SSL_PORT": os.getenv("TG_SSL_PORT", "443"),
            "TG_TGCLOUD": os.getenv("TG_TGCLOUD", "false"),
            "TG_CERT_PATH": os.getenv("TG_CERT_PATH", ""),
            "TG_PROFILE": os.getenv("TG_PROFILE", ""),
        }
        for key, value in tg_env.items():
            if value not in {None, ""}:
                env[key] = str(value)
        for key, value in os.environ.items():
            if key.endswith("_TG_HOST") or "_TG_" in key:
                env[key] = value
        return env

    async def _with_session(self, operation):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            raise RuntimeError("mcp SDK is not installed. Install: pip install tigergraph-mcp") from exc

        command = os.getenv("TIGERGRAPH_MCP_COMMAND", "tigergraph-mcp")
        args = os.getenv("TIGERGRAPH_MCP_ARGS", "-vv").split()
        server_params = StdioServerParameters(command=command, args=args, env=self._env())

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await operation(session)

    async def list_tools_async(self) -> list[McpToolSpec]:
        async def op(session):
            tools = await session.list_tools()
            return [
                McpToolSpec(
                    name=t.name,
                    description=getattr(t, "description", "") or "",
                    input_schema=getattr(t, "inputSchema", None) or getattr(t, "input_schema", {}) or {},
                )
                for t in tools.tools
            ]
        return await self._with_session(op)

    async def call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async def op(session):
            result = await session.call_tool(tool_name, arguments=arguments)
            content = []
            for item in result.content:
                text = getattr(item, "text", None)
                if text is not None:
                    try:
                        content.append(json.loads(text))
                    except Exception:
                        content.append(text)
                else:
                    content.append(str(item))
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "content": content,
                "is_error": getattr(result, "isError", False) or getattr(result, "is_error", False),
            }
        return await self._with_session(op)

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.__dict__ for tool in asyncio.run(self.list_tools_async())]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.call_tool_async(tool_name, arguments))


class TigerGraphMcpToolMapper:
    TOOL_NAMES = {
        "list_graphs": "tigergraph__list_graphs",
        "list_connections": "tigergraph__list_connections",
        "get_graph_schema": "tigergraph__get_graph_schema",
        "show_graph_details": "tigergraph__show_graph_details",
        "run_installed_query": "tigergraph__run_installed_query",
        "run_query": "tigergraph__run_query",
        "gsql": "tigergraph__gsql",
        "install_query": "tigergraph__install_query",
        "is_query_installed": "tigergraph__is_query_installed",
        "add_node": "tigergraph__add_node",
        "add_edge": "tigergraph__add_edge",
        "get_vertex_count": "tigergraph__get_vertex_count",
        "get_edge_count": "tigergraph__get_edge_count",
        "run_loading_job_with_file": "tigergraph__run_loading_job_with_file",
        "run_loading_job_with_data": "tigergraph__run_loading_job_with_data",
        "get_loading_jobs": "tigergraph__get_loading_jobs",
    }

    def __init__(self, client: TigerGraphMcpStdioClient) -> None:
        self.client = client
        self._tool_cache: dict[str, dict[str, Any]] | None = None

    def tool_catalog(self) -> dict[str, dict[str, Any]]:
        if self._tool_cache is None:
            tools = self.client.list_tools()
            self._tool_cache = {tool["name"]: tool for tool in tools}
        return self._tool_cache

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self.tool_catalog()

    def _schema_properties(self, tool_name: str) -> set[str]:
        schema = self.tool_catalog().get(tool_name, {}).get("input_schema", {}) or {}
        return set((schema.get("properties") or {}).keys())

    def _filter_args(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        props = self._schema_properties(tool_name)
        if not props:
            return {k: v for k, v in args.items() if not (v is None or v == "")}

        aliases = {
            "graph_name": ["graph_name", "graphName", "graph", "graphname"],
            "query_name": ["query_name", "queryName", "query"],
            "params": ["params", "parameters", "query_params", "queryParams"],
            "command": ["command", "gsql", "query"],
            "profile": ["profile"],
            "vertex_type": ["vertex_type", "vertexType"],
            "vertex_id": ["vertex_id", "vertexId", "primary_id"],
            "attributes": ["attributes", "attrs"],
            "edge_type": ["edge_type", "edgeType"],
            "source_vertex_type": ["source_vertex_type", "from_type", "source_type"],
            "source_vertex_id": ["source_vertex_id", "from_id", "source_id"],
            "target_vertex_type": ["target_vertex_type", "to_type", "target_type"],
            "target_vertex_id": ["target_vertex_id", "to_id", "target_id"],
        }
        output: dict[str, Any] = {}
        for canonical, value in args.items():
            if value is None or value == "":
                continue
            names = aliases.get(canonical, [canonical])
            chosen = next((name for name in names if name in props), None)
            if chosen:
                output[chosen] = value
        return output

    def call(self, logical_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        tool_name = self.TOOL_NAMES.get(logical_tool, logical_tool)
        if not self.has_tool(tool_name):
            return {
                "status": "failed",
                "message": f"MCP tool not available: {tool_name}",
                "available_tools": sorted(self.tool_catalog().keys()),
            }
        filtered = self._filter_args(tool_name, args)
        result = self.client.call_tool(tool_name, filtered)
        return {"status": "success", "tool": tool_name, "arguments": filtered, "result": result}
