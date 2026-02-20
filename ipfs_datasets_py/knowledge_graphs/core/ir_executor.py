"""IR (Intermediate Representation) operations executor.

This module contains the implementation of the IR execution loop previously
embedded in `QueryExecutor._execute_ir_operations`.

It is designed to be stateless; all per-execution state is local to the
`execute_ir_operations` call.
"""

from __future__ import annotations

import logging
import itertools
from typing import Any, Callable, Dict, List, Optional

from ..neo4j_compat.result import Record


logger = logging.getLogger(__name__)


def execute_ir_operations(
    *,
    graph_engine: Any,
    operations: List[Dict[str, Any]],
    parameters: Dict[str, Any],
    resolve_value: Callable[[Any, Dict[str, Any]], Any],
    apply_operator: Callable[[Any, str, Any], bool],
    evaluate_compiled_expression: Callable[[Any, Dict[str, Any]], Any],
    evaluate_expression: Callable[[str, Dict[str, Any]], Any],
    compute_aggregation: Callable[[str, List[Any]], Any],
) -> List[Record]:
    """Execute IR operations using a GraphEngine-like backend."""

    if not graph_engine:
        logger.warning("No GraphEngine available, returning empty results")
        return []

    # Track intermediate results
    result_set: Dict[str, List[Any]] = {}  # variable → values
    final_results: List[Record] = []
    bindings: List[Dict[str, Any]] = []
    union_parts: List[Dict[str, Any]] = []

    for op in operations:
        op_type = op.get("op")

        if op_type == "ScanLabel":
            label = op.get("label")
            variable = op.get("variable")
            nodes = graph_engine.find_nodes(labels=[label])
            result_set[variable] = nodes
            logger.debug("ScanLabel %s: found %d nodes", label, len(nodes))

        elif op_type == "ScanAll":
            variable = op.get("variable")
            nodes = graph_engine.find_nodes()
            result_set[variable] = nodes
            logger.debug("ScanAll: found %d nodes", len(nodes))

        elif op_type == "Filter":
            if "expression" in op:
                expression = op["expression"]
                filtered_results = []

                if bindings:
                    for binding in bindings:
                        result = evaluate_compiled_expression(expression, binding)
                        if result:
                            filtered_results.append(binding)
                    bindings = filtered_results
                else:
                    for var_name, items in list(result_set.items()):
                        filtered_items = []
                        for item in items:
                            binding = {var_name: item}
                            result_val = evaluate_compiled_expression(expression, binding)
                            if result_val:
                                filtered_items.append(item)
                        result_set[var_name] = filtered_items

                logger.debug(
                    "Filter (complex expression): filtered to %d results",
                    len(filtered_results)
                    if filtered_results
                    else sum(len(v) for v in result_set.values()),
                )

            else:
                variable = op.get("variable")
                property_name = op.get("property")
                operator = op.get("operator")
                value = resolve_value(op.get("value"), parameters)

                if variable in result_set:
                    filtered = []
                    for item in result_set[variable]:
                        item_value = item.get(property_name)
                        if apply_operator(item_value, operator, value):
                            filtered.append(item)
                    result_set[variable] = filtered
                    logger.debug(
                        "Filter %s.%s %s %s: %d results",
                        variable,
                        property_name,
                        operator,
                        value,
                        len(filtered),
                    )

        elif op_type == "Expand":
            from_var = op.get("from_variable")
            to_var = op.get("to_variable")
            rel_var = op.get("rel_variable")
            direction = op.get("direction", "out")
            rel_types = op.get("rel_types")
            target_labels = op.get("target_labels")

            if direction == "right":
                direction = "out"
            elif direction == "left":
                direction = "in"

            if from_var not in result_set:
                logger.warning("Expand: source variable %s not found", from_var)
                continue

            new_results: List[Dict[str, Any]] = []

            for from_node in result_set[from_var]:
                rels = graph_engine.get_relationships(
                    from_node.id,
                    direction=direction,
                    rel_type=rel_types[0] if rel_types else None,
                )

                for rel in rels:
                    if direction == "in":
                        target_id = rel._start_node
                    else:
                        target_id = rel._end_node

                    target_node = graph_engine.get_node(target_id)
                    if not target_node:
                        continue

                    if target_labels:
                        node_labels = getattr(target_node, "labels", [])
                        if not any(label in node_labels for label in target_labels):
                            continue

                    new_results.append({from_var: from_node, rel_var: rel, to_var: target_node})

            bindings = new_results
            if bindings:
                for binding in bindings:
                    for var, val in binding.items():
                        if var not in result_set:
                            result_set[var] = []
                        if val not in result_set[var]:
                            result_set[var].append(val)

            logger.debug(
                "Expand %s-[%s]->%s: found %d relationships",
                from_var,
                rel_var,
                to_var,
                len(new_results),
            )

        elif op_type == "OptionalExpand":
            from_var = op.get("from_variable")
            to_var = op.get("to_variable")
            rel_var = op.get("rel_variable")
            direction = op.get("direction", "out")
            rel_types = op.get("rel_types")
            target_labels = op.get("target_labels")

            if direction == "right":
                direction = "out"
            elif direction == "left":
                direction = "in"

            if from_var not in result_set:
                logger.warning("OptionalExpand: source variable %s not found", from_var)
                continue

            new_results = []

            for from_node in result_set[from_var]:
                rels = graph_engine.get_relationships(
                    from_node.id,
                    direction=direction,
                    rel_type=rel_types[0] if rel_types else None,
                )

                matched = False
                if rels:
                    for rel in rels:
                        if direction == "in":
                            target_id = rel._start_node
                        else:
                            target_id = rel._end_node

                        target_node = graph_engine.get_node(target_id)
                        if not target_node:
                            continue

                        if target_labels:
                            node_labels = getattr(target_node, "labels", [])
                            if not any(label in node_labels for label in target_labels):
                                continue

                        new_results.append({from_var: from_node, rel_var: rel, to_var: target_node})
                        matched = True

                if not matched:
                    new_results.append({from_var: from_node, rel_var: None, to_var: None})

            bindings = new_results
            if bindings:
                for binding in bindings:
                    for var, val in binding.items():
                        if var not in result_set:
                            result_set[var] = []
                        if val is not None and val not in result_set[var]:
                            result_set[var].append(val)

            logger.debug(
                "OptionalExpand %s-[%s]->%s: found %d relationships (including NULL rows)",
                from_var,
                rel_var,
                to_var,
                len(new_results),
            )

        elif op_type == "Aggregate":
            aggregations = op.get("aggregations", [])
            group_by = op.get("group_by", [])

            if bindings:
                data_rows = bindings
            else:
                data_rows = []
                if result_set:
                    var_names = list(result_set.keys())
                    if var_names:
                        first_var = var_names[0]
                        for item in result_set[first_var]:
                            data_rows.append({first_var: item})

            if group_by:
                groups: Dict[tuple, List[Dict[str, Any]]] = {}
                for row in data_rows:
                    group_key_parts = []
                    for group_spec in group_by:
                        expr = group_spec["expression"]
                        value = evaluate_expression(expr, row)
                        group_key_parts.append(str(value))
                    group_key = tuple(group_key_parts)
                    groups.setdefault(group_key, []).append(row)
            else:
                groups = {(): data_rows}

            agg_results: List[Dict[str, Any]] = []
            for _group_key, group_rows in groups.items():
                result_row: Dict[str, Any] = {}

                for group_spec in group_by:
                    alias = group_spec["alias"]
                    expr = group_spec["expression"]
                    value = evaluate_expression(expr, group_rows[0])
                    result_row[alias] = value

                for agg_spec in aggregations:
                    func = agg_spec["function"]
                    expr = agg_spec["expression"]
                    alias = agg_spec["alias"]
                    distinct = agg_spec.get("distinct", False)

                    if expr == "*":
                        values = group_rows
                    else:
                        values = [evaluate_expression(expr, row) for row in group_rows]
                        values = [v for v in values if v is not None]

                    if distinct and expr != "*":
                        values = list(set(values))

                    result_row[alias] = compute_aggregation(func, values)

                agg_results.append(result_row)

            for row in agg_results:
                keys = list(row.keys())
                values = list(row.values())
                final_results.append(Record(keys, values))

            logger.debug(
                "Aggregate: %d groups, %d results", len(groups), len(final_results)
            )

        elif op_type == "Union":
            all_flag = op.get("all", False)
            first_results = final_results.copy()
            final_results = []
            union_parts.append({"results": first_results, "all": all_flag})
            logger.debug(
                "Union: stored %d results from first part (all=%s)",
                len(first_results),
                all_flag,
            )

        elif op_type == "Project":
            items = op.get("items", [])

            if bindings:
                for binding in bindings:
                    record_data: Dict[str, Any] = {}
                    for item in items:
                        expr = item.get("expression")
                        alias = item.get(
                            "alias", expr if isinstance(expr, str) else "result"
                        )
                        record_data[alias] = evaluate_compiled_expression(expr, binding)
                    final_results.append(Record(list(record_data.keys()), list(record_data.values())))
            else:
                for var_name, values in result_set.items():
                    for value in values:
                        record_data = {}
                        for item in items:
                            expr = item.get("expression")
                            alias = item.get(
                                "alias", expr if isinstance(expr, str) else "result"
                            )
                            binding = {var_name: value}
                            record_data[alias] = evaluate_compiled_expression(expr, binding)
                        final_results.append(Record(list(record_data.keys()), list(record_data.values())))

            logger.debug("Project: %d results", len(final_results))

        elif op_type == "WithProject":
            # Like Project but writes projected rows to *bindings* so that
            # a subsequent WHERE/Filter and final RETURN can reference the
            # projected column names (e.g. `age` instead of `n.age`).
            items = op.get("items", [])
            new_bindings_wp: List[Dict[str, Any]] = []

            if bindings:
                for binding in bindings:
                    row: Dict[str, Any] = {}
                    for item in items:
                        expr = item.get("expression")
                        alias = item.get("alias", expr if isinstance(expr, str) else "result")
                        row[alias] = evaluate_compiled_expression(expr, binding)
                    new_bindings_wp.append(row)
            else:
                keys = list(result_set.keys())
                for combo in itertools.product(*[result_set[k] for k in keys]):
                    base = {keys[i]: combo[i] for i in range(len(keys))}
                    row = {}
                    for item in items:
                        expr = item.get("expression")
                        alias = item.get("alias", expr if isinstance(expr, str) else "result")
                        row[alias] = evaluate_compiled_expression(expr, base)
                    new_bindings_wp.append(row)

            # Apply DISTINCT if requested
            if op.get("distinct"):
                seen_wp: set = set()
                deduped: List[Dict[str, Any]] = []
                for row in new_bindings_wp:
                    key = tuple(sorted((k, str(v)) for k, v in row.items()))
                    if key not in seen_wp:
                        seen_wp.add(key)
                        deduped.append(row)
                new_bindings_wp = deduped

            # Apply SKIP / LIMIT if requested
            if op.get("skip") is not None:
                new_bindings_wp = new_bindings_wp[op["skip"]:]
            if op.get("limit") is not None:
                new_bindings_wp = new_bindings_wp[: op["limit"]]

            bindings = new_bindings_wp
            result_set = {}  # consumed
            final_results = []  # reset; will be populated by following Project
            logger.debug("WithProject: %d bindings", len(bindings))

        elif op_type == "Limit":
            count = op.get("count")
            final_results = final_results[:count]
            logger.debug("Limit: keeping %d results", len(final_results))

        elif op_type == "Skip":
            count = op.get("count")
            final_results = final_results[count:]
            logger.debug("Skip: %d results remaining", len(final_results))

        elif op_type == "OrderBy":
            order_items = op.get("items", [])
            if not order_items:
                logger.debug("OrderBy: no items specified")
                continue
            if not final_results:
                logger.debug("OrderBy: no results to sort")
                continue

            def make_sort_key(record: Record):
                key_parts = []
                for item in order_items:
                    expr = item["expression"]
                    ascending = item.get("ascending", True)

                    value: Optional[Any]
                    if isinstance(expr, dict):
                        if "property" in expr and len(expr) == 1:
                            prop_name = expr["property"]
                            value = record.get(prop_name)
                        else:
                            binding = record._data.copy() if hasattr(record, "_data") else {}
                            for key, val in list(binding.items()):
                                if hasattr(val, "labels") or hasattr(val, "type"):
                                    if "." in key:
                                        var_name = key.split(".")[0]
                                        binding[var_name] = val
                            value = evaluate_compiled_expression(expr, binding)
                    elif isinstance(expr, str):
                        if "." in expr:
                            var_name, prop_name = expr.split(".", 1)
                            try:
                                value = record.get(expr)
                                if value is None and hasattr(record, "_values"):
                                    obj = record._values.get(var_name)  # type: ignore[attr-defined]
                                    if (
                                        obj is not None
                                        and hasattr(obj, "properties")
                                        and prop_name in obj.properties
                                    ):
                                        value = obj.properties[prop_name]
                                    elif obj is not None and hasattr(obj, prop_name):
                                        value = getattr(obj, prop_name)
                            except (AttributeError, KeyError, TypeError):
                                value = None
                        else:
                            value = record.get(expr)
                    else:
                        value = None

                    if value is None:
                        value_key: Any = (1, None)
                    else:
                        value_key = (0, value)

                    if not ascending:
                        if isinstance(value_key[1], (int, float)):
                            value_key = (
                                value_key[0],
                                -value_key[1] if value_key[1] is not None else None,
                            )
                        elif isinstance(value_key[1], str):
                            value_key = (value_key[0], value_key[1])

                    key_parts.append(value_key)

                return tuple(key_parts)

            try:
                final_results.sort(key=make_sort_key)
                logger.debug(
                    "OrderBy: sorted %d results by %d expressions",
                    len(final_results),
                    len(order_items),
                )
            except (TypeError, ValueError, KeyError) as e:
                logger.warning(
                    "OrderBy: failed to sort results (%s): %s",
                    type(e).__name__,
                    e,
                )

        elif op_type == "CreateNode":
            variable = op.get("variable")
            labels = op.get("labels", [])
            properties = op.get("properties", {})
            node = graph_engine.create_node(labels=labels, properties=properties)
            result_set[variable] = [node]
            logger.debug("CreateNode: created node %s", node.id)

        elif op_type == "Delete":
            variable = op.get("variable")
            if variable in result_set:
                for item in result_set[variable]:
                    graph_engine.delete_node(item.id)
                logger.debug("Delete: deleted %d nodes", len(result_set[variable]))

        elif op_type == "SetProperty":
            variable = op.get("variable")
            property_name = op.get("property")
            value = resolve_value(op.get("value"), parameters)

            if variable in result_set:
                for item in result_set[variable]:
                    graph_engine.update_node(item.id, {property_name: value})
                logger.debug("SetProperty: updated %d nodes", len(result_set[variable]))

        elif op_type == "Unwind":
            # UNWIND <expr> AS <variable>
            # Expands the list expression into individual bindings.
            expr = op.get("expression")
            unwind_var = op.get("variable")
            # Evaluate the list expression against the current bindings
            if bindings:
                new_bindings: List[Dict[str, Any]] = []
                for binding in bindings:
                    lst = evaluate_compiled_expression(expr, binding)
                    if isinstance(lst, (list, tuple)):
                        for item in lst:
                            new_binding = dict(binding)
                            new_binding[unwind_var] = item
                            new_bindings.append(new_binding)
                    elif lst is not None:
                        # Non-list: treat as single-element list
                        new_binding = dict(binding)
                        new_binding[unwind_var] = lst
                        new_bindings.append(new_binding)
                bindings = new_bindings
            elif result_set:
                # Convert result_set rows to bindings and unwind
                new_bindings = []
                # Build cross-product bindings from result_set
                keys = list(result_set.keys())
                for combo in itertools.product(*[result_set[k] for k in keys]):
                    base = {keys[i]: combo[i] for i in range(len(keys))}
                    lst = evaluate_compiled_expression(expr, base)
                    if isinstance(lst, (list, tuple)):
                        for item in lst:
                            b = dict(base)
                            b[unwind_var] = item
                            new_bindings.append(b)
                    elif lst is not None:
                        b = dict(base)
                        b[unwind_var] = lst
                        new_bindings.append(b)
                bindings = new_bindings
                result_set = {}  # consumed
            else:
                # No bindings yet — evaluate against empty binding
                lst = evaluate_compiled_expression(expr, {})
                if isinstance(lst, (list, tuple)):
                    bindings = [{unwind_var: item} for item in lst]
                elif lst is not None:
                    bindings = [{unwind_var: lst}]
            logger.debug("Unwind: expanded to %d bindings", len(bindings))

    if union_parts:
        all_parts: List[Record] = []
        for part in union_parts:
            all_parts.extend(part["results"])
        all_parts.extend(final_results)

        remove_duplicates = not union_parts[0]["all"]
        if remove_duplicates:
            seen = set()
            unique_results: List[Record] = []
            for record in all_parts:
                record_tuple = tuple(record._values)  # type: ignore[attr-defined]
                if record_tuple not in seen:
                    seen.add(record_tuple)
                    unique_results.append(record)
            final_results = unique_results
            logger.debug("Union: removed duplicates, %d unique results", len(final_results))
        else:
            final_results = all_parts
            logger.debug("Union ALL: combined %d total results", len(final_results))

    return final_results
