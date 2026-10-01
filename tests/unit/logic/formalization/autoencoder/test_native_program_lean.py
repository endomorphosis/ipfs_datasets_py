"""Real operational lowering and fail-closed native ProgramIR contracts."""
import copy
from pathlib import Path
import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_program_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.contracts import ProgramContract


def fixture():
    inputs = panel.source_inputs(panel.rows("security_ir", "train")[0])
    program = inputs["typed_inputs"][0].document.to_dict()
    contract = inputs["typed_inputs"][1].document.to_dict()
    return program, contract


def rebuild(program):
    program.pop("program_id", None)
    return ProgramIR.from_dict(program).to_dict()


def arithmetic_fixture():
    program, contract = fixture()
    src = program["commands"][0]["source_ref_ids"]
    def symbol(key, kind):
        return dict(symbol_id=key, name=key, kind=kind, type_ref="integer", attributes={}, source_ref_ids=src, span_ids=[])
    program["symbols"] = [symbol("x", "parameter"), symbol("y", "local"), symbol("r", "result")]
    function = program["functions"][0]
    function.update(parameter_symbol_ids=["x"], local_symbol_ids=["y"], result_symbol_id="r")
    function["effects"].update(reads=["x", "y"], writes=["y"])
    template = program["expressions"][0]
    def expression(key, kind, ty, operands=(), symbols=(), operator="", value=None):
        row = copy.deepcopy(template)
        row.update(expression_id=key, kind=kind, type_ref=ty, operand_ids=list(operands), evaluation_order=list(operands),
                   symbol_ids=list(symbols), operator=operator, attributes={"value": value} if kind == "literal" else {})
        return row
    program["expressions"] = [expression("x", "symbol", "integer", symbols=["x"]),
        expression("y", "symbol", "integer", symbols=["y"]), expression("r", "result", "integer", symbols=["r"]),
        expression("one", "literal", "integer", value=1), expression("zero", "literal", "integer", value=0),
        expression("add", "binary", "integer", ["x", "one"], operator="add"),
        expression("positive", "binary", "boolean", ["y", "zero"], operator="gt"),
        expression("oldx", "old", "integer", ["x"]),
        expression("oldadd", "binary", "integer", ["oldx", "one"], operator="add"),
        expression("post", "binary", "boolean", ["r", "oldadd"], operator="eq"),
        expression("pre", "binary", "boolean", ["x", "zero"], operator="ge")]
    template = program["commands"][0]
    def command(key, kind, expr, reads, targets=()):
        row = copy.deepcopy(template)
        row.update(command_id=key, kind=kind, expression_ids=[expr], evaluation_order=[expr], target_symbol_ids=list(targets))
        row["effects"].update(reads=list(reads), writes=list(targets))
        return row
    program["commands"] = [command("assign", "assign", "add", ["x"], ["y"]),
        command("assert", "assert", "positive", ["y"]), command("return", "return", "y", ["y"])]
    function["cfg"]["blocks"][0]["command_ids"] = ["assign", "assert", "return"]
    program = rebuild(program)
    contract["frame"].update(readable_symbol_ids=["x", "y"], writable_symbol_ids=["y"])
    contract["effects"].update(reads=["x", "y"], writes=["y"])
    contract["preconditions"][0].update(expression_id="pre", statement="x >= 0")
    contract["postconditions"][0].update(expression_id="post", statement="result = old(x) + 1")
    contract = ProgramContract.from_dict(contract).to_dict()
    return program, contract


def actual_lake(source, extra=""):
    tools = sorted((Path.home()/".elan"/"toolchains").glob("*/bin/lake"))
    if not tools: pytest.skip("Installed native Lake unavailable; no download attempted")
    receipt = _execute("set_option autoImplicit false\nnamespace SecurityIR\n"+source+"\n"+extra+"\nend SecurityIR\n", "SecurityIR", tools[-1], 30)
    return receipt


def test_current_native_security_program_and_contract_have_real_operational_definitions():
    program, contract = fixture()
    source, details = emit.emit_contract(contract, program_payload=program)
    assert "Outcome.returned" in source and "def contract : Prop" in source
    assert "program_sha256" in details and "contract_sha256" in details
    receipt = actual_lake(source, "example : run {} = Outcome.returned {} 0 := by decide\nexample : contract := by simp [contract, run, precondition, postcondition, frameCondition, expression_0, expression_1]")
    assert receipt["status"] == "passed", receipt


def test_assignment_assertion_old_result_and_frame_compile_and_execute():
    program, contract = arithmetic_fixture()
    source, details = emit.emit_contract(contract, program_payload=program)
    # Native symbols are canonically sorted r,x,y, preserving their types.
    fields = emit._Program(program).fields
    s = "{ " + ", ".join(fields[key]+" := "+str(value) for key, value in [("r", 99), ("x", 2), ("y", 42)]) + " }"
    t = "{ " + ", ".join(fields[key]+" := "+str(value) for key, value in [("r", 99), ("x", 2), ("y", 3)]) + " }"
    extra = f"example : run {s} = Outcome.returned {t} 3 := by decide\nexample : postcondition {s} {t} 3 := by simp [postcondition, expression_5]\nexample : frameCondition {s} {t} := by simp [frameCondition]"
    receipt = actual_lake(source, extra)
    assert receipt["status"] == "passed", receipt
    assert details["actual_reads"] == ["x", "y"] and details["actual_writes"] == ["y"]


@pytest.mark.parametrize("kind,outcome", [("assert", "assertionFailure"), ("assume", "blocked")])
def test_false_assertion_and_assumption_remain_distinct_operational_outcomes(kind, outcome):
    program, contract = fixture()
    expression = next(row for row in program["expressions"] if row["type_ref"] == "boolean")
    expression["attributes"]["value"] = False
    command = copy.deepcopy(program["commands"][0])
    command.update(command_id="guard", kind=kind, expression_ids=[expression["expression_id"]], evaluation_order=[expression["expression_id"]])
    program["commands"].insert(0, command)
    program["functions"][0]["cfg"]["blocks"][0]["command_ids"].insert(0, "guard")
    program = rebuild(program)
    source, _ = emit.emit_program(rebuild(program))
    receipt = actual_lake(source, "example : run {} = Outcome."+outcome+" := by decide")
    assert receipt["status"] == "passed", receipt


def test_false_postcondition_is_not_asserted_by_compiling_contract_definition():
    program, contract = fixture()
    false = copy.deepcopy(next(row for row in program["expressions"] if row["type_ref"] == "boolean"))
    false["expression_id"] = "false"; false["attributes"]["value"] = False
    program["expressions"].append(false)
    program = rebuild(program)
    contract["postconditions"][0]["expression_id"] = "false"
    source, _ = emit.emit_contract(contract, program_payload=program)
    positive = actual_lake(source, "example : ¬ contract := by intro h; have bad := h {} (by simp [precondition, expression_1]); simpa [run, postcondition, frameCondition, expression_0, expression_1, expression_2] using bad")
    assert positive["status"] == "passed", positive
    negative = actual_lake(source, "example : contract := by simp [contract, run, precondition, postcondition, frameCondition, expression_0, expression_1]")
    assert negative["status"] == "failed" and negative["returncode"] != 0


@pytest.mark.parametrize("change,reason", [
    (lambda p: p["metadata"].update(opaque=True), "metadata"),
    (lambda p: p["commands"][0]["attributes"].update(opaque=True), "attributes"),
    (lambda p: p["expressions"][0]["attributes"].update(opaque=True), "literal_value"),
    (lambda p: p["commands"][0]["effects"].update(performs_io=True), "effect"),
    (lambda p: p["functions"][0]["effects"].update(nondeterministic=True), "effect"),
])
def test_unsupported_semantics_fail_closed(change, reason):
    program, _ = fixture(); change(program)
    with pytest.raises((UnsupportedNativeLean, ValueError), match=reason): emit.emit_program(rebuild(program))


def test_read_effect_and_local_initialization_are_checked():
    program, _ = arithmetic_fixture()
    assignment = next(row for row in program["commands"] if row["kind"] == "assign")
    assignment["effects"]["reads"] = []
    with pytest.raises((UnsupportedNativeLean, ValueError), match="reads|effect"): emit.emit_program(rebuild(program))
    program, _ = arithmetic_fixture()
    block = program["functions"][0]["cfg"]["blocks"][0]
    block["command_ids"] = ["assert", "assign", "return"]
    with pytest.raises(UnsupportedNativeLean, match="initialization"): emit.emit_program(rebuild(program))


def test_paired_program_and_complete_contract_are_required():
    program, contract = fixture()
    row = dict(logic_family="program", payload=contract)
    with pytest.raises(UnsupportedNativeLean, match="paired_program"): emit.emit_projection(row)
    paired = dict(logic_family="program", payload=program, ready_for_training=True)
    source, _ = emit.emit_projection(row, report={"projections": [paired]})
    assert "def contract" in source
    with pytest.raises(UnsupportedNativeLean, match="one_ready_paired"): emit.emit_projection(row, report={"projections": [paired, paired]})
    altered = copy.deepcopy(contract); altered["function_id"] = "different:function"
    with pytest.raises(ValueError): emit.emit_contract(altered, program_payload=program)


def test_unowned_routes_are_not_misrepresented_as_programs():
    with pytest.raises(NotImplementedError): emit.emit_projection({"logic_family": "program", "payload": {"schema_version": "other"}})


def test_extra_control_flow_and_unsupported_arithmetic_do_not_disappear():
    program, _ = fixture()
    cfg = program["functions"][0]["cfg"]
    block = copy.deepcopy(cfg["blocks"][0]); block.update(block_id="new-entry", command_ids=[])
    cfg["blocks"].append(block)
    cfg["edges"] = [dict(edge_id="edge", source_block_id="new-entry", target_block_id=cfg["entry_block_id"],
                         kind="normal", order=0, condition_expression_id="", exception_type="")]
    cfg["entry_block_id"] = "new-entry"
    with pytest.raises(UnsupportedNativeLean, match="single_block"): emit.emit_program(rebuild(program))
    program, _ = arithmetic_fixture()
    next(row for row in program["expressions"] if row["expression_id"] == "add")["operator"] = "div"
    with pytest.raises(UnsupportedNativeLean, match="unsupported_typed_binary"): emit.emit_program(rebuild(program))


def test_old_uninitialized_local_cannot_borrow_arbitrary_entry_store_value():
    program, _ = arithmetic_fixture()
    old = next(row for row in program["expressions"] if row["kind"] == "old")
    old["operand_ids"] = old["evaluation_order"] = ["y"]
    with pytest.raises(UnsupportedNativeLean, match="initialized_entry_symbols"): emit.emit_program(rebuild(program))


def test_boolean_and_integer_operator_definitions_are_kernel_checked_on_concrete_values():
    program, _ = fixture(); template = program["expressions"][0]
    definitions = []; expected = {}
    def expression(key, kind, ty, operands=(), operator="", value=None):
        row = copy.deepcopy(template)
        row.update(expression_id=key, kind=kind, type_ref=ty, operand_ids=list(operands), evaluation_order=list(operands),
                   symbol_ids=[], operator=operator, attributes={"value": value} if kind == "literal" else {})
        definitions.append(row)
    for key, value in [("two", 2), ("three", 3), ("yes", True), ("no", False)]:
        expression(key, "literal", "boolean" if type(value) is bool else "integer", value=value)
    for operator, value in [("add",5),("sub",-1),("mul",6),("eq",False),("ne",True),("lt",True),("le",True),("gt",False),("ge",False)]:
        expression(operator, "binary", "boolean" if type(value) is bool else "integer", ["two","three"], operator)
        expected[operator] = value
    for operator, value in [("and",False),("or",True)]:
        expression(operator,"binary","boolean",["yes","no"],operator); expected[operator]=value
    for operator, operand, value in [("not","yes",False),("neg","two",-2),("pos","two",2)]:
        expression(operator,"unary","boolean" if type(value) is bool else "integer",[operand],operator); expected[operator]=value
    expression("choose","conditional","integer",["no","two","three"]); expected["choose"]=3
    program["expressions"] = definitions
    program["commands"][0]["expression_ids"] = program["commands"][0]["evaluation_order"] = ["choose"]
    program = rebuild(program); lower = emit._Program(program); source = lower.source()
    extra = "\n".join("example : "+lower.expr_names[key]+" {} {} 0 = "+(str(value).lower() if type(value) is bool else "("+str(value)+" : Int)")+" := by decide" for key,value in expected.items())
    receipt=actual_lake(source,extra)
    assert receipt["status"] == "passed",receipt
