from app.config.settings import SCHEMA_PREFIX


def vertex_name(base_name: str) -> str:
    return f"{SCHEMA_PREFIX}{base_name.strip().lower()}"


def edge_name(base_name: str) -> str:
    return f"{SCHEMA_PREFIX}{base_name.strip().lower()}"


def query_name(base_name: str) -> str:
    return f"{SCHEMA_PREFIX}{base_name.strip()}"


def table_name(base_name: str) -> str:
    return f"{SCHEMA_PREFIX}{base_name.strip().lower()}"
