"""
Knowledge Graph Visualization.

Provides pure-Python (no external dependencies) visualization exports for
:class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
objects.

Four output formats are supported:

* **DOT** — Graphviz language; render with ``dot -Tpng`` or online Graphviz
  tools (e.g. https://viz-js.com/).
* **Mermaid** — Mermaid.js graph notation; embed in GitHub Markdown, Notion,
  GitLab, Obsidian, and https://mermaid.live.
* **D3.js JSON** — force-directed graph JSON for ``d3-force`` layouts.
* **ASCII** — human-readable tree printed to a terminal.

Example::

    from ipfs_datasets_py.knowledge_graphs.extraction import (
        KnowledgeGraph,
        KnowledgeGraphVisualizer,
    )

    kg = KnowledgeGraph("example")
    alice = kg.add_entity("person", "Alice")
    bob   = kg.add_entity("person", "Bob")
    kg.add_relationship("knows", alice, bob)

    vis = KnowledgeGraphVisualizer(kg)
    print(vis.to_dot())      # Graphviz DOT
    print(vis.to_mermaid())  # Mermaid.js
    print(vis.to_ascii())    # ASCII tree
    d3 = vis.to_d3_json()    # dict with 'nodes' + 'links'

All methods are also available directly on :class:`KnowledgeGraph` via
convenience wrappers (``kg.to_dot()``, ``kg.to_mermaid()``, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Internal escaping helpers
# ---------------------------------------------------------------------------

def _escape_dot_label(text: str) -> str:
    """Escape characters that are special in a Graphviz label string."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("|", "\\|")
    )


def _escape_mermaid(text: str) -> str:
    """Escape characters that would break a Mermaid node or edge label."""
    return (
        text.replace('"', "'")
        .replace("\n", " ")
        .replace("[", "(")
        .replace("]", ")")
    )


# ---------------------------------------------------------------------------
# KnowledgeGraphVisualizer
# ---------------------------------------------------------------------------

class KnowledgeGraphVisualizer:
    """Visualization exporter for a :class:`KnowledgeGraph`.

    All output methods are pure Python — no external libraries are required.
    The class is intentionally lightweight: it holds a reference to *kg* and
    produces text/dict output on demand.

    Args:
        kg: The knowledge graph to visualize.

    Example::

        vis = KnowledgeGraphVisualizer(kg)
        dot_src = vis.to_dot()
        mermaid_src = vis.to_mermaid()
        ascii_tree = vis.to_ascii()
        d3_data = vis.to_d3_json()
    """

    def __init__(self, kg: "KnowledgeGraph") -> None:
        self.kg = kg

    # ------------------------------------------------------------------
    # Graphviz DOT
    # ------------------------------------------------------------------

    def to_dot(
        self,
        graph_name: Optional[str] = None,
        directed: bool = True,
    ) -> str:
        """Return a Graphviz DOT-language string for the knowledge graph.

        Args:
            graph_name: Override the graph name in the DOT header.  Defaults
                to :attr:`KnowledgeGraph.name`.
            directed: When ``True`` (default) produce a ``digraph`` with
                directed edges (``->``).  When ``False`` produce an undirected
                ``graph`` with ``--`` edges.

        Returns:
            str: A DOT-language string ready to pipe to ``dot -Tpng``.

        Example::

            vis = KnowledgeGraphVisualizer(kg)
            print(vis.to_dot())
            # digraph "my_graph" {
            #   rankdir=LR;
            #   "e1" [label="Alice\\n(person)"];
            #   "e1" -> "e2" [label="knows"];
            # }
        """
        kg = self.kg
        name = _escape_dot_label(graph_name or kg.name)
        kw = "digraph" if directed else "graph"
        edge_op = "->" if directed else "--"

        lines: List[str] = [f'{kw} "{name}" {{']
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=ellipse fontname=Helvetica];")
        lines.append("  edge [fontname=Helvetica];")

        for entity in kg.entities.values():
            label = (
                f"{_escape_dot_label(entity.name)}"
                f"\\n({_escape_dot_label(entity.entity_type)})"
            )
            lines.append(f'  "{entity.entity_id}" [label="{label}"];')

        for rel in kg.relationships.values():
            label = _escape_dot_label(rel.relationship_type)
            lines.append(
                f'  "{rel.source_id}" {edge_op} "{rel.target_id}" [label="{label}"];'
            )

        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Mermaid.js
    # ------------------------------------------------------------------

    def to_mermaid(
        self,
        direction: str = "LR",
        max_entities: Optional[int] = None,
    ) -> str:
        """Return a Mermaid.js graph notation string.

        The output uses the ``graph <direction>`` format, compatible with
        GitHub Markdown, Notion, GitLab, Obsidian, and mermaid.live.

        Args:
            direction: Graph layout direction.  One of ``"LR"`` (left→right,
                default), ``"RL"``, ``"TB"`` (top→bottom), ``"BT"``.
            max_entities: When given, only the first *max_entities* entities
                (and their relationships) are included.

        Returns:
            str: Mermaid.js graph string.

        Example::

            with open("graph.md", "w") as fh:
                fh.write("```mermaid\\n")
                fh.write(vis.to_mermaid())
                fh.write("\\n```\\n")
        """
        kg = self.kg
        lines: List[str] = [f"graph {direction}"]

        entities = list(kg.entities.values())
        if max_entities is not None:
            entities = entities[:max_entities]
        included_ids = {e.entity_id for e in entities}

        for entity in entities:
            label = _escape_mermaid(
                f"{entity.name}\\n({entity.entity_type})"
            )
            lines.append(f'  {entity.entity_id}["{label}"]')

        for rel in kg.relationships.values():
            if (
                rel.source_id not in included_ids
                or rel.target_id not in included_ids
            ):
                continue
            rtype = _escape_mermaid(rel.relationship_type)
            lines.append(f'  {rel.source_id} -->|"{rtype}"| {rel.target_id}')

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # D3.js JSON
    # ------------------------------------------------------------------

    def to_d3_json(self, max_nodes: Optional[int] = None) -> Dict[str, Any]:
        """Return a D3.js force-directed graph JSON dictionary.

        The returned dict has two keys:

        * ``"nodes"`` — list of node objects with ``id``, ``name``, ``type``,
          ``confidence``, and any extra properties under ``"properties"``.
        * ``"links"`` — list of link objects with ``source``, ``target``,
          ``type``, ``confidence``, and ``"properties"``.

        Args:
            max_nodes: When given, only the first *max_nodes* entities (and
                their relationships) are included.

        Returns:
            dict: JSON-serialisable D3 force-graph dict.

        Example::

            import json
            with open("graph.json", "w") as fh:
                json.dump(vis.to_d3_json(), fh, indent=2)
        """
        kg = self.kg
        entities = list(kg.entities.values())
        if max_nodes is not None:
            entities = entities[:max_nodes]
        included_ids = {e.entity_id for e in entities}

        nodes: List[Dict[str, Any]] = [
            {
                "id": entity.entity_id,
                "name": entity.name,
                "type": entity.entity_type,
                "confidence": entity.confidence,
                "properties": dict(entity.properties or {}),
            }
            for entity in entities
        ]

        links: List[Dict[str, Any]] = [
            {
                "source": rel.source_id,
                "target": rel.target_id,
                "type": rel.relationship_type,
                "confidence": rel.confidence,
                "properties": dict(rel.properties or {}),
            }
            for rel in kg.relationships.values()
            if rel.source_id in included_ids and rel.target_id in included_ids
        ]

        return {"nodes": nodes, "links": links}

    # ------------------------------------------------------------------
    # ASCII tree
    # ------------------------------------------------------------------

    def to_ascii(
        self,
        root_entity_id: Optional[str] = None,
        max_depth: int = 3,
    ) -> str:
        """Return a human-readable ASCII-art representation of the graph.

        If *root_entity_id* is given the tree is rooted at that entity and
        shows outgoing relationships up to *max_depth* hops.  Otherwise a
        flat roster of all entities and their direct outgoing relationships
        is printed.

        Args:
            root_entity_id: Optional entity ID to use as the tree root.
            max_depth: Maximum relationship-traversal depth (default 3).
                Only used when *root_entity_id* is provided.

        Returns:
            str: Multi-line ASCII string suitable for ``print()``.

        Example::

            print(vis.to_ascii())
            # my_graph (2 entities, 1 relationship)
            # ├─ Alice (person)
            # │  └─[knows]→ Bob
            # └─ Bob (person)
        """
        kg = self.kg
        n_e = len(kg.entities)
        n_r = len(kg.relationships)
        ent_word = "entity" if n_e == 1 else "entities"
        rel_word = "relationship" if n_r == 1 else "relationships"
        header = f"{kg.name} ({n_e} {ent_word}, {n_r} {rel_word})"

        if n_e == 0:
            return header

        lines: List[str] = [header]

        if root_entity_id and root_entity_id in kg.entities:
            self._ascii_rooted(lines, root_entity_id, max_depth)
        else:
            self._ascii_flat(lines)

        return "\n".join(lines)

    def _ascii_flat(self, lines: List[str]) -> None:
        """Append a flat entity roster (no root) to *lines*."""
        kg = self.kg
        entities = list(kg.entities.values())
        for idx, entity in enumerate(entities):
            is_last_entity = idx == len(entities) - 1
            branch = "└─" if is_last_entity else "├─"
            lines.append(f"{branch} {entity.name} ({entity.entity_type})")

            out_rels = [
                r for r in kg.relationships.values()
                if r.source_id == entity.entity_id
            ]
            indent = "   " if is_last_entity else "│  "
            for ridx, rel in enumerate(out_rels):
                is_last_rel = ridx == len(out_rels) - 1
                rbranch = "└" if is_last_rel else "├"
                target = kg.entities.get(rel.target_id)
                tname = target.name if target else rel.target_id
                lines.append(f"{indent}{rbranch}─[{rel.relationship_type}]→ {tname}")

    def _ascii_rooted(
        self,
        lines: List[str],
        root_id: str,
        max_depth: int,
    ) -> None:
        """Append a depth-first ASCII tree rooted at *root_id* to *lines*."""
        kg = self.kg
        visited: set = set()

        root = kg.entities.get(root_id)
        if root:
            lines.append(f"  {root.name} ({root.entity_type})")

        def _recurse(entity_id: str, prefix: str, depth: int) -> None:
            if depth > max_depth or entity_id in visited:
                return
            visited.add(entity_id)
            out_rels = [
                r for r in kg.relationships.values()
                if r.source_id == entity_id
            ]
            for ridx, rel in enumerate(out_rels):
                is_last = ridx == len(out_rels) - 1
                branch = "└" if is_last else "├"
                target = kg.entities.get(rel.target_id)
                tname = target.name if target else rel.target_id
                ttype = target.entity_type if target else "?"
                lines.append(
                    f"{prefix}{branch}─[{rel.relationship_type}]→ {tname} ({ttype})"
                )
                child_prefix = prefix + ("   " if is_last else "│  ")
                if target:
                    _recurse(rel.target_id, child_prefix, depth + 1)

        _recurse(root_id, "  ", 1)
