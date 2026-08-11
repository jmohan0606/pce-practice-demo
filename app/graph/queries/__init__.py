"""Mock (local-tier) implementations of the installed GSQL queries.

Modules in this package register a Python equivalent for each catalogued GSQL
query via the ``@mock_query("<query_name>")`` decorator from
``app.graph.client``. Importing this package (MockGraphClient does so on
construction) populates ``MOCK_QUERY_IMPLS`` so the local store can serve the
same query names, with the same result shapes, as TigerGraph.

PCE query implementations are added in later rounds.
"""
