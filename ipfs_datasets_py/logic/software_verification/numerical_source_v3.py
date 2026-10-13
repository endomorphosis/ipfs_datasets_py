"""Source-bound numerical control flow with unresolved Python protocol semantics.

Loops are CFG cycles, not unrolled/eager expression lists. Synthetic iterator
and item slots carry values across phases without repeating their producers.
Only an iterator-advance StopIteration edge denotes exhaustion. All runtime
effects, reachability, iteration counts, invariants and termination remain
unproved. The complete CFG, guarded expressions and control sidecars are needed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import PurePosixPath

from . import numerical_source as v1
from . import numerical_source_v2 as v2
from .program import BasicBlock, ControlFlowEdge, ControlFlowGraph, EffectSummary, ProgramFunction, ProgramIR, Purity

PROFILE = "python-numerical-control-structure@3"
SCHEMA = "numerical-source-structure@3"
CONTROL_SCHEMA = "numerical-control-region@1"
CONTEXT_SCHEMA = "numerical-command-context@1"
MAX_BLOCKS = 4096
MAX_EDGES = 12288
AUTHORITY = dict(v1.AUTHORITY)


@dataclass(frozen=True)
class NumericalSourceResult(v2.NumericalSourceResult):
    control_regions: tuple[dict, ...]
    command_contexts: tuple[dict, ...]

    def to_dict(self):
        wire = super().to_dict()
        wire.update(schema=SCHEMA, profile=PROFILE,
            control_regions=list(self.control_regions), command_contexts=list(self.command_contexts),
            control_extension_required=True,
            structural_completeness_scope="program_cfg_guarded_regions_and_control_regions",
            control_flow_semantics_verified=False, loop_invariants_verified=False,
            termination_verified=False, definite_assignment_verified=False)
        return json.loads(v1._wire(wire))


class _Frontend(v2._Frontend):
    def __init__(self, *args):
        self.control_regions, self.command_contexts = [], []
        super().__init__(*args)

    def _block(self, node, commands=()):
        if len(self._blocks) >= MAX_BLOCKS:
            raise ValueError("numerical control block bound exceeded")
        key = self._id("block")
        self._blocks[key] = BasicBlock(key, tuple(commands), **self._mapped(self._span(node)))
        return key

    def _edge(self, start, end, kind="normal", *, condition="", exception=""):
        if len(self._edges) >= MAX_EDGES:
            raise ValueError("numerical control edge bound exceeded")
        key = self._id("edge")
        order = sum(e.source_block_id == start for e in self._edges)
        self._edges.append(ControlFlowEdge(key, start, end, kind, order, condition, exception))
        return key

    def _connect(self, starts, end):
        return [self._edge(start, end) for start in starts]

    def _escape(self, block):
        return self._edge(block, self._exception_exit, "exception", exception="BaseException")

    def _command_block(self, node, kind, expressions=(), targets=(), attributes=None,
                       *, regions=(), loops=(), may_raise=True):
        command = self._command(node, kind, expressions=expressions, targets=targets,
            attributes={"control_extension_required": True, **(attributes or {})})
        if not may_raise:
            self.commands[-1] = replace(self.commands[-1], effects=EffectSummary(),
                attributes={**self.commands[-1].attributes.to_dict(), "external_effects_known": True})
        block = self._block(node, (command,))
        self.command_contexts.append(dict(schema=CONTEXT_SCHEMA, function_id=self._fid,
            cfg_id=self._cfg_id, block_id=block, command_id=command,
            enclosing_region_ids=list(regions), loop_contexts=[dict(x) for x in loops],
            occurrence="symbolic_block_visit", reachability_verified=False,
            iteration_count_verified=False, control_transfer=None,
            target_region_id=None, edge_ids=[]))
        return block, command

    def _state(self, role, node):
        key = self._symbol("$" + role + ":" + str(self.counter), "local", self._span(node))
        self.symbols[-1] = replace(self.symbols[-1], attributes={
            **self.symbols[-1].attributes.to_dict(), "synthetic_protocol_state": True,
            "protocol_role": role, "not_source_name_binding": True})
        self._local["$" + key] = key
        return key

    def _state_read(self, node, key):
        return self._expression(node, "symbol", symbols=(key,),
            attributes={"synthetic_protocol_state_read": True})

    def _control_region(self, node, kind, regions, loops):
        row = dict(schema=CONTROL_SCHEMA, region_id=self._id("control-region"), kind=kind,
            function_id=self._fid, source_ref_ids=[self.source_ref.ref_id], span_ids=[self._span(node)],
            enclosing_region_ids=list(regions), enclosing_loop_ids=[x["region_id"] for x in loops],
            entry_block_id=None, header_block_id=None, body_entry_block_id=None,
            else_entry_block_id=None, continuation_block_id=None,
            exceptional_exit_block_id=self._exception_exit, anchor_expression_id=None,
            edge_ids=[], break_edge_ids=[], continue_edge_ids=[], backedge_ids=[],
            source_semantics_verified=False, control_flow_semantics_verified=False,
            edge_conditions_reference_evaluated_values=True)
        self.control_regions.append(row)
        return row

    @staticmethod
    def _loop_context(row, phase):
        return dict(region_id=row["region_id"], activation_variable=row["activation_variable"],
            iteration_variable=None if phase in ("initialize", "else") else row["iteration_variable"],
            phase=phase, occurrence="exhausted_activation" if phase == "else" else
                "activation_entry" if phase == "initialize" else "symbolic_iteration_or_attempt")

    def _suite(self, statements, incoming, *, regions=(), loops=(), transfers=()):
        frontier = list(incoming)
        for statement in statements:
            if not frontier:
                self._diagnostic("python.stmt.unreachable_after_transfer", statement, self._function_name)
                continue
            entry, frontier_next = self._statement(statement, regions=regions, loops=loops, transfers=transfers)
            self._connect(frontier, entry)
            frontier = frontier_next
        return frontier

    def _fence(self, node, code, regions, loops):
        self._diagnostic(code, node, self._function_name)
        block, _ = self._command_block(node, "skip", attributes={
            "unsupported_construct": code, "body_not_linearized": True}, regions=regions, loops=loops)
        self._escape(block)
        return block, [block]

    def _statement(self, node, *, regions, loops, transfers):
        if isinstance(node, ast.If):
            return self._if(node, regions, loops, transfers)
        if isinstance(node, (ast.For, ast.While)):
            return self._loop(node, regions, loops, transfers)
        if isinstance(node, (ast.Break, ast.Continue)):
            if not transfers:
                return self._fence(node, "python.transfer.no_enclosing_loop", regions, loops)
            target = transfers[-1]
            kind = "break" if isinstance(node, ast.Break) else "continue"
            block, _ = self._command_block(node, "skip", attributes={"control_transfer": kind},
                regions=regions, loops=loops, may_raise=False)
            edge = self._edge(block, target["continuation_block_id"] if kind == "break" else target["header_block_id"], kind)
            self.command_contexts[-1].update(control_transfer=kind, target_region_id=target["region_id"])
            target[kind + "_edge_ids"].append(edge)
            return block, []
        if isinstance(node, (ast.Try, ast.TryStar, ast.With, ast.AsyncWith, ast.AsyncFor,
                             ast.Match, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return self._fence(node, "python.stmt." + type(node).__name__, regions, loops)
        attributes, expressions, targets, kind = {}, [], [], "skip"
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            nodes = node.targets if isinstance(node, ast.Assign) else [node.target]
            patterns = [self._pattern(target, self._local) for target in nodes]
            value = self._expr(node.value, self._local, self._function_name) if node.value is not None else None
            if len(patterns) != 1 or patterns[0] is None or value is None or not self._pattern_ids(patterns[0]):
                return self._fence(node, "python.assignment.unsupported_target_or_value", regions, loops)
            kind, expressions, targets = "assign", [value], self._pattern_ids(patterns[0])
            attributes["assignment_pattern"] = patterns[0]
            if isinstance(node, ast.AnnAssign):
                attributes["declared_annotation"] = self._text(node.annotation)
        elif isinstance(node, ast.Return):
            value = self._expr(node.value, self._local, self._function_name) if node.value is not None else None
            if node.value is not None and value is None:
                return self._fence(node, "python.return.unsupported_value", regions, loops)
            kind, expressions = "return", [value] if value is not None else []
        elif isinstance(node, ast.Assert):
            value = self._expr(node.test, self._local, self._function_name)
            if value is None:
                return self._fence(node, "python.assert.unsupported_predicate", regions, loops)
            kind, expressions = "assert", [value]
            attributes["assertion_semantics_verified"] = False
            if node.msg is not None:
                attributes.update(assertion_message_source=self._text(node.msg),
                    assertion_message_span_ids=[self._span(node.msg)], message_evaluated_only_on_failure=True)
        elif isinstance(node, ast.Expr):
            # Only the first literal function statement is a docstring.
            if node is self._docstring:
                attributes["docstring"] = node.value.value
            else:
                value = self._expr(node.value, self._local, self._function_name)
                if value is None:
                    return self._fence(node, "python.expr.unsupported_statement", regions, loops)
                expressions, kind = [value], "call" if isinstance(node.value, ast.Call) else "skip"
        elif not isinstance(node, ast.Pass):
            return self._fence(node, "python.stmt." + type(node).__name__, regions, loops)
        may_raise = bool(expressions) or kind == "assert"
        block, _ = self._command_block(node, kind, expressions, targets, attributes,
            regions=regions, loops=loops, may_raise=may_raise)
        if may_raise:
            self._escape(block)
        if kind == "return":
            self._edge(block, self._normal_exit, "return")
            self.command_contexts[-1]["control_transfer"] = "return"
            return block, []
        return block, [block]

    def _if(self, node, regions, loops, transfers):
        test = self._expr(node.test, self._local, self._function_name)
        if test is None:
            return self._fence(node, "python.if.unsupported_test", regions, loops)
        row = self._control_region(node, "if_statement", regions, loops)
        nested = (*regions, row["region_id"])
        header, command = self._command_block(node.test, "call", (test,), attributes={
            "control_phase": "if_test", "truthiness_semantics_verified": False}, regions=nested, loops=loops)
        body, otherwise, after = self._block(node), self._block(node), self._block(node)
        row.update(entry_block_id=header, header_block_id=header, body_entry_block_id=body,
            else_entry_block_id=otherwise, continuation_block_id=after,
            anchor_expression_id=test, test_expression_id=test, test_command_id=command,
            evaluation_policy="test_once_then_truthiness_once_then_selected_suite")
        row["edge_ids"] = [self._edge(header, body, "true", condition=test),
            self._edge(header, otherwise, "false", condition=test), self._escape(header)]
        left = self._suite(node.body, [body], regions=nested, loops=loops, transfers=transfers)
        right = self._suite(node.orelse, [otherwise], regions=nested, loops=loops, transfers=transfers)
        self._connect(left + right, after)
        return header, [after] if left or right else []

    def _loop(self, node, regions, loops, transfers):
        is_for = isinstance(node, ast.For)
        if is_for and (not isinstance(node.target, ast.Name) or not isinstance(node.target.ctx, ast.Store)):
            return self._fence(node, "python.for.unsupported_target", regions, loops)
        source_root = self._expr(node.iter if is_for else node.test, self._local, self._function_name)
        if source_root is None:
            return self._fence(node, "python.loop.unsupported_input", regions, loops)
        row = self._control_region(node, "for_statement" if is_for else "while_statement", regions, loops)
        row.update(activation_variable="activation:" + row["region_id"],
            iteration_variable="iteration:" + row["region_id"], invariant_status="unresolved",
            termination_status="unresolved", zero_iterations_possible=True,
            definite_assignment_verified=False, protocol_semantics_verified=False)
        nested = (*regions, row["region_id"])
        context = lambda phase: (*loops, self._loop_context(row, phase))
        body, otherwise, after = self._block(node), self._block(node), self._block(node)
        row.update(body_entry_block_id=body, else_entry_block_id=otherwise, continuation_block_id=after)
        if is_for:
            iterator = self._state("iterator", node.iter)
            item = self._state("iteration_item", node.target)
            initialization = self._expression(node.iter, "call", operands=(source_root,), operator="python.iterator_create",
                attributes=dict(call_kind="python.iterator_create", opaque=True, synthetic_protocol_operation=True,
                    protocol_semantics_verified=False, source_builtin_lookup=False))
            entry, init_command = self._command_block(node.iter, "assign", (initialization,), (iterator,),
                {"control_phase": "iterator_initialize", "synthetic_protocol_state_write": True},
                regions=nested, loops=context("initialize"))
            iterator_read = self._state_read(node.iter, iterator)
            advance = self._expression(node.iter, "call", operands=(iterator_read,), operator="python.iterator_advance",
                attributes=dict(call_kind="python.iterator_advance", opaque=True, synthetic_protocol_operation=True,
                    protocol_semantics_verified=False, source_builtin_lookup=False))
            header, advance_command = self._command_block(node.iter, "assign", (advance,), (item,),
                {"control_phase": "iterator_advance", "synthetic_protocol_state_write": True},
                regions=nested, loops=context("advance"))
            item_read = self._state_read(node.target, item)
            target, target_command = self._command_block(node.target, "assign", (item_read,), (self._local[node.target.id],),
                {"control_phase": "target_binding", "assignment_pattern": self._pattern(node.target, self._local)},
                regions=nested, loops=context("target"))
            init_escape = self._escape(entry)
            init_edge = self._edge(entry, header)
            yielded = self._edge(header, target)
            exhaustion = self._edge(header, otherwise, "exception", exception="StopIteration")
            other_exception = self._escape(header)
            target_escape, target_body = self._escape(target), self._edge(target, body)
            row.update(entry_block_id=entry, header_block_id=header, anchor_expression_id=advance,
                iterable_expression_id=source_root, iterator_expression_id=initialization,
                advance_expression_id=advance, iterator_symbol_id=iterator, item_symbol_id=item,
                iterator_command_id=init_command, advance_command_id=advance_command,
                target_command_id=target_command, target_symbol_id=self._local[node.target.id],
                target_block_id=target, initialization_edge_id=init_edge, iteration_edge_id=yielded,
                exhaustion_edge_id=exhaustion, other_exception_edge_id=other_exception,
                initialization_exception_edge_id=init_escape, target_exception_edge_id=target_escape,
                exception_dispatch=dict(exhaustion_only_at_expression_id=advance,
                    exhaustion_matches="StopIteration_and_subclasses", other_exception_excludes=["StopIteration"],
                    exhaustion_edge_precedes_other_exception=True),
                evaluation_policy="iterable_and_iterator_once_per_activation_then_advance_per_attempt_then_target_then_body",
                else_policy="only_iterator_advance_exhaustion_not_break_or_other_exception",
                implicit_iterator_close_claimed=False, target_may_be_unbound_after_zero_iterations=True,
                edge_ids=[init_escape, init_edge, yielded, exhaustion, other_exception, target_escape, target_body])
        else:
            header, command = self._command_block(node.test, "call", (source_root,), attributes={
                "control_phase": "while_test", "truthiness_semantics_verified": False},
                regions=nested, loops=context("test"))
            entry = header
            row.update(entry_block_id=entry, header_block_id=header, anchor_expression_id=source_root,
                test_expression_id=source_root, test_command_id=command,
                evaluation_policy="test_then_truthiness_once_per_header_visit",
                else_policy="false_truthiness_including_initial_test_not_break_or_exception")
            row["edge_ids"] = [self._edge(header, body, "true", condition=source_root),
                self._edge(header, otherwise, "false", condition=source_root), self._escape(header)]
        tails = self._suite(node.body, [body], regions=nested, loops=context("body"), transfers=(*transfers, row))
        row["backedge_ids"] = self._connect(tails, header)
        # The current loop is no longer a legal break/continue target inside
        # its else, but its exhausted activation remains provenance context.
        else_tails = self._suite(node.orelse, [otherwise], regions=nested, loops=context("else"), transfers=transfers)
        self._connect(else_tails, after)
        return entry, [after] if else_tails or row["break_edge_ids"] else []

    def _function(self, node):
        first_diagnostic, first_guard = len(self.diagnostics), len(self.guarded_regions)
        first_region, first_context = len(self.control_regions), len(self.command_contexts)
        self._fid, self._cfg_id = self._id("function"), self._id("cfg")
        function_span = self._span(node)
        self._function_name, self._local = node.name, {}
        self.mutated_import_roots = set()
        parameters = []
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None: args.append(node.args.vararg)
        if node.args.kwarg is not None: args.append(node.args.kwarg)
        if len({arg.arg for arg in args}) != len(args):
            self._diagnostic("python.function.duplicate_parameter", node, node.name)
        for arg in args:
            key = self._symbol(arg.arg, "parameter", self._span(arg), annotation=arg.annotation)
            self._local[arg.arg] = key
            parameters.append(key)
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.ctx, (ast.Store, ast.Del)):
                value = child.value
                while isinstance(value, ast.Attribute): value = value.value
                if isinstance(value, ast.Name): self.mutated_import_roots.add(value.id)
            names = []
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                names.append(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                names.extend(a.asname or (a.name.split(".")[0] if isinstance(child, ast.Import) else a.name) for a in child.names)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
                names.append(child.name)
            elif isinstance(child, ast.ExceptHandler) and child.name: names.append(child.name)
            for name in names:
                if name not in self._local:
                    self._local[name] = self._symbol(name, "local", self._span(child))
        if (node.decorator_list or node.args.defaults or any(v is not None for v in node.args.kw_defaults)
                or node.args.vararg or node.args.kwarg or getattr(node, "type_params", ())):
            self._diagnostic("python.function.definition_evaluation_or_variadics", node, node.name)
        if any(isinstance(child, (ast.Global, ast.Nonlocal)) for child in ast.walk(node)):
            self._diagnostic("python.function.global_or_nonlocal", node, node.name)
            for alias in self.aliases:
                if alias not in self._local:
                    self._local[alias] = self._symbol(alias, "local", function_span)
        result = self._symbol("result", "result", function_span, annotation=node.returns)
        self._blocks, self._edges = {}, []
        entry = self._block(node)
        self._normal_exit, self._exception_exit = self._block(node), self._block(node)
        self._docstring = (node.body[0] if node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant) and type(node.body[0].value.value) is str else None)
        tails = self._suite(node.body, [entry])
        self._connect(tails, self._normal_exit)
        reachable, pending = set(), [entry]
        while pending:
            current = pending.pop()
            if current in reachable: continue
            reachable.add(current)
            pending.extend(e.target_block_id for e in self._edges if e.source_block_id == current)
        edges = tuple(e for e in self._edges if e.source_block_id in reachable)
        blocks = tuple(b for k,b in self._blocks.items() if k in reachable)
        cfg = ControlFlowGraph(self._cfg_id, entry, blocks, edges, (self._normal_exit,),
            (self._exception_exit,) if self._exception_exit in reachable else ())
        command_ids = set(cfg.command_ids)
        for context in self.command_contexts[first_context:]:
            context["edge_ids"] = [e.edge_id for e in edges if e.source_block_id == context["block_id"]]
        for region in self.control_regions[first_region:]:
            if region["continuation_block_id"] not in reachable: region["continuation_block_id"] = None
        relevant = [c for c in self.commands if c.command_id in command_ids]
        effects = EffectSummary(reads=tuple(sorted({s for c in relevant for s in c.effects.reads})),
            writes=tuple(sorted({s for c in relevant for s in c.effects.writes})), raises=("BaseException",),
            performs_io=True, nondeterministic=True, synchronizes=True)
        self.functions.append(ProgramFunction(self._fid, node.name, cfg, parameter_symbol_ids=tuple(parameters),
            local_symbol_ids=tuple(s for s in self._local.values() if s not in parameters),
            result_symbol_id=result, return_type="python.object", purity=Purity.UNKNOWN,
            effects=effects, declared_exceptions=tuple(sorted({"BaseException"} |
                {e.exception_type for e in edges if e.exception_type})), **self._mapped(function_span)))
        for guard in self.guarded_regions[first_guard:]: guard["function_id"] = self._fid
        self.function_coverage.append(dict(function_id=self._fid, name=node.name,
            source_ref_ids=[self.source_ref.ref_id], span_ids=[function_span],
            structurally_complete=len(self.diagnostics)==first_diagnostic,
            unsupported_constructs=sorted({r["code"] for r in self.diagnostics[first_diagnostic:]})))

    def lower(self):
        # The v2 closure pass remains unchanged and validates the eager/guarded
        # expression graph before the separately versioned CFG contract.
        program = super().lower()
        if program is None: return None
        program = replace(program, program_id="", metadata={**program.metadata.to_dict(),
            "profile": PROFILE, "control_extension_required": True,
            "cfg_interpretation": "source_bound_symbolic_control_flow_with_unresolved_protocols",
            "control_flow_semantics_verified": False, "loop_invariants_verified": False,
            "termination_verified": False, "definite_assignment_verified": False})
        validate_control_structure(program, self.guarded_regions, self.control_regions, self.command_contexts)
        return program


def validate_control_structure(program, guarded_regions, control_regions, command_contexts):
    """Check closed CFG/sidecar structure; exact source replay is also required."""
    if not isinstance(program, ProgramIR) or program.metadata.get("profile") != PROFILE or program.metadata.get("control_extension_required") is not True:
        raise ValueError("v3 control ProgramIR required")
    # Reuse v2's full symbol/ownership/read closure without changing its bytes.
    v2.validate_guarded_structure(replace(program, program_id="", metadata={
        **program.metadata.to_dict(), "profile": v2.PROFILE}), guarded_regions)
    functions = {f.function_id:f for f in program.functions}
    commands = {c.command_id:c for c in program.commands}
    expressions = {e.expression_id:e for e in program.expressions}
    spans = {s.span_id:s for s in program.spans}
    regions = {}
    for row in control_regions:
        if (not isinstance(row, dict) or row.get("schema") != CONTROL_SCHEMA
                or row.get("kind") not in {"if_statement","for_statement","while_statement"}
                or type(row.get("region_id")) is not str or row["region_id"] in regions
                or row.get("function_id") not in functions or row.get("source_semantics_verified") is not False
                or row.get("control_flow_semantics_verified") is not False):
            raise ValueError("invalid control region identity or authority")
        regions[row["region_id"]] = row
    contexts = {}
    for row in command_contexts:
        if (not isinstance(row, dict) or row.get("schema") != CONTEXT_SCHEMA
                or row.get("command_id") not in commands or row["command_id"] in contexts
                or row.get("function_id") not in functions or row.get("reachability_verified") is not False
                or row.get("iteration_count_verified") is not False or row.get("occurrence") != "symbolic_block_visit"):
            raise ValueError("invalid command control context")
        function = functions[row["function_id"]]
        blocks = {b.block_id:b for b in function.cfg.blocks}
        if (row.get("cfg_id") != function.cfg.graph_id or row.get("block_id") not in blocks
                or row["command_id"] not in blocks[row["block_id"]].command_ids
                or row.get("edge_ids") != [e.edge_id for e in function.cfg.edges if e.source_block_id==row["block_id"]]):
            # CFG edges are canonical ID-sorted; creation order differs after
            # two-digit IDs, so compare the exact unique edge set separately.
            if not (row.get("cfg_id") == function.cfg.graph_id and row.get("block_id") in blocks
                    and row["command_id"] in blocks[row["block_id"]].command_ids
                    and len(row.get("edge_ids",[]))==len(set(row.get("edge_ids",[])))
                    and set(row.get("edge_ids",[]))=={e.edge_id for e in function.cfg.edges if e.source_block_id==row["block_id"]}):
                raise ValueError("command context CFG ownership differs")
        chain = row.get("enclosing_region_ids",[])
        if len(chain)!=len(set(chain)) or any(key not in regions or regions[key]["function_id"]!=function.function_id for key in chain):
            raise ValueError("foreign or repeated enclosing control region")
        for pos,key in enumerate(chain):
            if regions[key]["enclosing_region_ids"] != chain[:pos]:
                raise ValueError("control region ancestry differs")
        loop_ids = [key for key in chain if regions[key]["kind"] != "if_statement"]
        if [x.get("region_id") for x in row.get("loop_contexts",[])] != loop_ids:
            raise ValueError("loop activation context differs from ancestry")
        for item in row["loop_contexts"]:
            region = regions[item["region_id"]]
            phase = item.get("phase")
            if phase not in {"initialize","advance","target","body","test","else"} or item != _Frontend._loop_context(region,phase):
                raise ValueError("invalid loop activation or iteration scope")
        if row.get("control_transfer") in {"break","continue"}:
            active = [item["region_id"] for item in row["loop_contexts"] if item["phase"] != "else"]
            if not active or row.get("target_region_id") != active[-1]:
                raise ValueError("loop transfer does not target nearest active loop")
            outgoing=[e for e in function.cfg.edges if e.source_block_id==row["block_id"]]
            target=regions[active[-1]]
            destination=target["continuation_block_id"] if row["control_transfer"]=="break" else target["header_block_id"]
            if len(outgoing)!=1 or outgoing[0].kind.value!=row["control_transfer"] or outgoing[0].target_block_id!=destination:
                raise ValueError("transfer command has a spurious continuation")
        contexts[row["command_id"]]=row
    if set(contexts)!=set(commands): raise ValueError("missing command control context")
    expected_exhaustion_edges=set()
    expected_branch_headers=set()
    for row in control_regions:
        function=functions[row["function_id"]];cfg=function.cfg
        blocks={b.block_id:b for b in cfg.blocks};edges={e.edge_id:e for e in cfg.edges}
        if row.get("anchor_expression_id") not in expressions: raise ValueError("missing control anchor")
        if row.get("edge_conditions_reference_evaluated_values") is not True:
            raise ValueError("control edges must inspect previously evaluated values")
        for field in ("entry_block_id","header_block_id","body_entry_block_id","else_entry_block_id","exceptional_exit_block_id"):
            if row.get(field) not in blocks: raise ValueError("foreign control block")
        if row.get("continuation_block_id") is not None and row["continuation_block_id"] not in blocks:
            raise ValueError("foreign control continuation")
        if row["exceptional_exit_block_id"] not in cfg.exceptional_exit_block_ids:
            raise ValueError("control exception target is not exceptional exit")
        for field in ("edge_ids","break_edge_ids","continue_edge_ids","backedge_ids"):
            if len(row.get(field,[]))!=len(set(row.get(field,[]))) or any(key not in edges for key in row.get(field,[])):
                raise ValueError("foreign control edge")
        if not row["span_ids"] or set(row["source_ref_ids"])!=set(function.source_ref_ids):
            raise ValueError("control source binding differs")
        for key in row["span_ids"]:
            if key not in spans or not any(spans[parent].start_byte<=spans[key].start_byte<=spans[key].end_byte<=spans[parent].end_byte for parent in function.span_ids):
                raise ValueError("control span escapes function")

        def owned_command(cid,bid):
            command=commands.get(cid)
            if (command is None or bid not in blocks or cid not in blocks[bid].command_ids
                    or contexts[cid]["function_id"]!=function.function_id
                    or row["region_id"] not in contexts[cid]["enclosing_region_ids"]):
                raise ValueError("control phase command ownership differs")
            return command

        if row["kind"] in {"for_statement","while_statement"}:
            if (row.get("invariant_status")!="unresolved" or row.get("termination_status")!="unresolved"
                    or row.get("definite_assignment_verified") is not False or row.get("protocol_semantics_verified") is not False
                    or row.get("zero_iterations_possible") is not True):
                raise ValueError("loop obligations must remain unresolved")
            for key in row["backedge_ids"]:
                if edges[key].kind.value!="normal" or edges[key].target_block_id!=row["header_block_id"]:
                    raise ValueError("loop backedge does not revisit header")
        if row["kind"] in {"if_statement","while_statement"}:
            test=row.get("test_expression_id")
            command=owned_command(row.get("test_command_id"),row["header_block_id"])
            branch_edges=[e for e in edges.values() if e.source_block_id==row["header_block_id"]]
            by_kind={e.kind.value:e for e in branch_edges}
            if (test!=row["anchor_expression_id"] or command.expression_ids!=(test,)
                    or len(branch_edges)!=3 or set(by_kind)!={"true","false","exception"}
                    or by_kind["true"].condition_expression_id!=test or by_kind["false"].condition_expression_id!=test
                    or by_kind["true"].target_block_id!=row["body_entry_block_id"]
                    or by_kind["false"].target_block_id!=row["else_entry_block_id"]
                    or by_kind["exception"].target_block_id!=row["exceptional_exit_block_id"]
                    or by_kind["exception"].exception_type!="BaseException"
                    or set(row["edge_ids"])!={e.edge_id for e in branch_edges}):
                raise ValueError("header test/branch/exception cached-value contract differs")
            policy="test_once_then_truthiness_once_then_selected_suite" if row["kind"]=="if_statement" else "test_then_truthiness_once_per_header_visit"
            if row.get("evaluation_policy")!=policy:
                raise ValueError("test evaluation frequency differs")
            expected_branch_headers.add(row["header_block_id"])
        if row["kind"] == "for_statement":
            for field in ("iterable_expression_id","iterator_expression_id","advance_expression_id"):
                if row.get(field) not in expressions: raise ValueError("missing iterator protocol expression")
            init,advance=expressions[row["iterator_expression_id"]],expressions[row["advance_expression_id"]]
            init_command=owned_command(row.get("iterator_command_id"),row["entry_block_id"])
            advance_command=owned_command(row.get("advance_command_id"),row["header_block_id"])
            if (init.operand_ids!=(row["iterable_expression_id"],) or init.attributes.get("call_kind")!="python.iterator_create"
                    or advance.attributes.get("call_kind")!="python.iterator_advance" or row["anchor_expression_id"]!=advance.expression_id
                    or init_command.expression_ids!=(init.expression_id,) or init_command.target_symbol_ids!=(row["iterator_symbol_id"],)
                    or advance_command.expression_ids!=(advance.expression_id,) or advance_command.target_symbol_ids!=(row["item_symbol_id"],)):
                raise ValueError("iterator protocol operands differ")
            advance_read=expressions[advance.operand_ids[0]] if len(advance.operand_ids)==1 else None
            target=owned_command(row.get("target_command_id"),row.get("target_block_id"))
            target_read=expressions[target.expression_ids[0]] if target and len(target.expression_ids)==1 else None
            if (advance_read is None or advance_read.symbol_ids!=(row["iterator_symbol_id"],)
                    or target_read is None or target_read.symbol_ids!=(row["item_symbol_id"],)
                    or target.target_symbol_ids!=(row["target_symbol_id"],)):
                raise ValueError("protocol state must use slots without reevaluating producers")
            exhaustion=edges[row["exhaustion_edge_id"]];other=edges[row["other_exception_edge_id"]]
            if (exhaustion.kind.value!="exception" or exhaustion.exception_type!="StopIteration"
                    or exhaustion.source_block_id!=row["header_block_id"] or exhaustion.target_block_id!=row["else_entry_block_id"]
                    or other.kind.value!="exception" or other.exception_type!="BaseException"
                    or other.source_block_id!=row["header_block_id"] or other.target_block_id!=row["exceptional_exit_block_id"]
                    or exhaustion.order>=other.order or row["exception_dispatch"]!=dict(
                        exhaustion_only_at_expression_id=row["advance_expression_id"], exhaustion_matches="StopIteration_and_subclasses",
                        other_exception_excludes=["StopIteration"],exhaustion_edge_precedes_other_exception=True)):
                raise ValueError("iterator exhaustion and other exceptions are not separated")
            if (row.get("evaluation_policy")!="iterable_and_iterator_once_per_activation_then_advance_per_attempt_then_target_then_body"
                    or row.get("else_policy")!="only_iterator_advance_exhaustion_not_break_or_other_exception"
                    or row.get("implicit_iterator_close_claimed") is not False
                    or row.get("target_may_be_unbound_after_zero_iterations") is not True):
                raise ValueError("iterator activation/exhaustion contract differs")
            expected_exhaustion_edges.add(exhaustion.edge_id)
            for edge_key,source_block in (("initialization_exception_edge_id",row["entry_block_id"]),
                                         ("target_exception_edge_id",row["target_block_id"])):
                edge=edges[row[edge_key]]
                if edge.source_block_id!=source_block or edge.target_block_id!=row["exceptional_exit_block_id"] or edge.kind.value!="exception" or edge.exception_type!="BaseException":
                    raise ValueError("non-advance failure must escape instead of exhaust")
        for kind,target_field in (("break","continuation_block_id"),("continue","header_block_id")):
            for key in row[kind+"_edge_ids"]:
                edge=edges[key]
                if edge.kind.value!=kind or edge.target_block_id!=row[target_field]:
                    raise ValueError("loop transfer edge differs from region target")
    all_edges=[e for f in program.functions for e in f.cfg.edges]
    if {e.edge_id for e in all_edges if e.exception_type=="StopIteration"}!=expected_exhaustion_edges:
        raise ValueError("StopIteration exhaustion exists outside iterator advance")
    if {e.source_block_id for e in all_edges if e.kind.value in {"true","false"}}!=expected_branch_headers:
        raise ValueError("conditional CFG edges lack control contracts")
    return True


def adapt_numerical_source(source_text, *, path="source.py"):
    """Parse bounded source as data; never execute Python, a model or a solver."""
    if type(source_text) is not str or type(path) is not str:
        raise ValueError("source text and path must be strings")
    relative=PurePosixPath(path)
    if not path or relative.is_absolute() or "\\" in path or "\x00" in path or any(p in ("",".","..") for p in path.split("/")):
        raise ValueError("canonical relative Python source path required")
    try: raw=source_text.encode("utf-8")
    except UnicodeError as exc: raise ValueError("valid UTF-8 source required") from exc
    if not 0<len(raw)<=v1.MAX_SOURCE_BYTES: raise ValueError("numerical source byte bound exceeded")
    digest=hashlib.sha256(raw).hexdigest()
    try: tree=ast.parse(source_text,type_comments=True)
    except (SyntaxError,ValueError,RecursionError):
        return NumericalSourceResult(path,digest,None,(dict(code="python.syntax",function="",source_ref_ids=[],span_ids=[]),),(),(),(),(),())
    pending,count,functions=[(tree,0)],0,0
    while pending:
        node,depth=pending.pop();count+=1;functions+=isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
        if count>v1.MAX_AST_NODES or depth>v1.MAX_AST_DEPTH or functions>v1.MAX_FUNCTIONS:
            raise ValueError("numerical source AST resource bound exceeded")
        pending.extend((child,depth+1) for child in ast.iter_child_nodes(node))
    frontend=_Frontend(source_text,path,tree);program=frontend.lower()
    return NumericalSourceResult(path,digest,program,tuple(frontend.diagnostics),tuple(frontend.import_bindings),
        tuple(frontend.function_coverage),tuple(frontend.guarded_regions),tuple(frontend.control_regions),tuple(frontend.command_contexts))


def verify_numerical_source(result,source_text,*,path="source.py"):
    actual=result.to_dict() if isinstance(result,NumericalSourceResult) else result
    expected=adapt_numerical_source(source_text,path=path)
    if v1._wire(actual)!=v1._wire(expected.to_dict()):
        raise ValueError("numerical control source structure differs from exact replay")
    return expected


__all__=["PROFILE","SCHEMA","NumericalSourceResult","adapt_numerical_source","verify_numerical_source","validate_control_structure"]
