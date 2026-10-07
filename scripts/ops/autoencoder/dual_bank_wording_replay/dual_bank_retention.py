"""Pure proposed replay schedule and metric gate; not wired into any trainer.

Caller-supplied digests and fixture metrics are data contracts, not provenance,
semantic review, proof admission or resource/execution readiness. No model,
encoder, tensor library, optimizer, checkpoint selector or numerical owner is
imported or called here.
"""
from collections import Counter
import hashlib
import json

ROLES = ("control", "balanced")
MODALITIES = ("O", "P", "F")
FIELDS = ("actor", "action", "modality", "object")
FACETS = (*FIELDS, "conditions", "exceptions", "temporal")
TRAIN_COHORTS = ("original_train48", "normative_train48", "new_balanced_train48")
FALSE = dict(qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    formalized=False, checkpoint_promoted=False, lake_executed=False,
    independent_semantic_holdout=False, fresh_holdout=False, execution_readiness_granted=False,
    source_provenance_authenticated=False, native_vectors_revalidated=False,
    models_executed=False, encoder_executed=False, training_executed=False)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def hash64(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def rule_sha(rule):
    require(type(rule) is dict and set(rule) == set(FACETS)
        and all(type(rule[k]) is str and rule[k] for k in FIELDS)
        and rule["modality"] in MODALITIES and all(type(rule[k]) is list and rule[k] == []
            for k in ("conditions", "exceptions", "temporal")),
        "exact original seven-facet empty-qualifier rule required")
    return digest(rule)


def build_schedule(*, pairing, banks_by_role, original_rules, first_bank="control"):
    """170 commits, alternating authentic banks at independent local ordinals.

    Updates2j and2j+1 present the same six original-rule/template slots across
    the two banks. A bank's local ordinal j, not global t, indexes its30-row
    orders. This prevents the parity alias that would omit half of each stratum.
    """
    require(first_bank in ROLES and type(banks_by_role) is dict and set(banks_by_role) == set(ROLES),
        "two explicitly named banks required")
    require(type(original_rules) is list and len(original_rules) == 90, "complete original90 census required")
    originals = {rule_sha(r): r for r in original_rules}
    require(len(originals) == 90 and Counter(r["modality"] for r in originals.values()) ==
        Counter({m: 30 for m in MODALITIES}), "unique balanced original90 targets required")
    require(type(pairing) is dict and pairing.get("schema") == "balanced-wording-paired-draws/v1"
        and pairing.get("pairing_sha256") == digest({k: v for k, v in pairing.items() if k != "pairing_sha256"})
        and type(pairing.get("seed")) is int and pairing["seed"] == 1729
        and type(pairing.get("steps")) is int and pairing["steps"] == 170
        and pairing["original_rules_sha256"] == digest(original_rules)
        and all(pairing.get(k) is False for k in ("qualified", "admitted", "proof_authority", "train_eligible")),
        "closed unchanged unqualified paired source declaration required")
    lookup, canonical, modality_tokens = {}, {}, {}
    identities, texts, normalized = set(), set(), set()
    for role in ROLES:
        bank = banks_by_role[role]; rows = bank["rows"]; templates = pairing["banks"][role]["templates"]
        require(type(bank.get("dimension")) is int and bank["dimension"] == 384
            and bank["bank_sha256"] == digest({k: v for k, v in bank.items() if k != "bank_sha256"})
            and bank["bank_sha256"] == pairing["banks"][role]["bank_sha256"]
            and len(rows) == len(pairing["census"][role]) == 180
            and len(templates) == len(set(templates)) == 2
            and [r["id"] for r in rows] == sorted({r["id"] for r in rows})
            and all(bank.get(k) is False for k in ("qualified", "admitted", "proof_authority")),
            "complete independently sealed native384 bank required")
        members = {}
        for i, (row, member) in enumerate(zip(rows, pairing["census"][role])):
            text = row["source_text"]
            require(type(text) is str and text.strip() and len(text.encode()) <= 32768
                and len(text.split("\n\n")) == 1, "bounded authentic single-clause literal source required")
            sha = text_sha(text); normalized_text = " ".join(text.casefold().split()); identity = rule_sha(row["target"])
            require(row["source_sha256"] == sha and row["id"] == "clause:" + sha
                and row["id"] not in identities and text not in texts and normalized_text not in normalized,
                "source ID/hash/normalized collision or relabeling")
            identities.add(row["id"]); texts.add(text); normalized.add(normalized_text)
            require(identity in originals and row["target"] == originals[identity]
                and row["modality"] == row["target"]["modality"] and row["template"] in templates,
                "unchanged original target and declared template required")
            slot = templates.index(row["template"])
            require((identity, slot) not in members, "duplicate original-rule/template occurrence")
            require(type(member["index"]) is int and member["index"] == i
                and type(member["template_slot"]) is int and member["template_slot"] == slot
                and (member["row_id"], member["source_sha256"], member["original_rule_sha256"], member["template"], member["modality"])
                == (row["id"], sha, identity, row["template"], row["modality"]), "paired member differs from authentic source")
            token = row["modality_token_id"]
            require(type(token) is int and 3 <= token < 32
                and (row["modality"] not in modality_tokens or modality_tokens[row["modality"]] == token),
                "consistent unchanged full32 modality targets required")
            modality_tokens[row["modality"]] = token
            members[identity, slot] = i
        require(set(members) == {(identity, slot) for identity in originals for slot in (0, 1)},
            "complete original90 by two template slots required")
        orders = [[members[identity, slot] for identity in sorted(
            (identity for identity, rule in originals.items() if rule["modality"] == modality),
            key=lambda identity: digest([1729, modality, slot, identity]))]
            for modality in MODALITIES for slot in (0, 1)]
        require(pairing["orders"][role] == orders and all(type(i) is int
            for order in pairing["orders"][role] for i in order), "canonical paired orders required")
        lookup[role], canonical[role] = members, orders
    require(len(set(modality_tokens.values())) == 3, "three distinct full32 modality token IDs required")
    require(len(pairing["draws"]) == 170, "complete prior committed schedule required")
    for t, prior in enumerate(pairing["draws"]):
        expected_ids = [rule_sha(banks_by_role["control"]["rows"][order[t % 30]]["target"])
            for order in canonical["control"]]
        require(type(prior["step"]) is int and prior["step"] == t
            and prior["original_rule_sha256"] == expected_ids
            and all(prior["indices"][role] == [order[t % 30] for order in canonical[role]]
                and all(type(i) is int for i in prior["indices"][role]) for role in ROLES),
            "prior paired source declaration changed")
    bank_order = (first_bank, ROLES[1 - ROLES.index(first_bank)])
    draws = []; exposures = {role: Counter() for role in ROLES}; strata = {role: Counter() for role in ROLES}
    for t in range(170):
        role = bank_order[t % 2]; local = t // 2
        indices = [order[local % 30] for order in canonical[role]]
        rows = [banks_by_role[role]["rows"][i] for i in indices]
        for row in rows:
            exposures[role][row["id"]] += 1; strata[role][row["template"], row["modality"]] += 1
        draws.append(dict(global_committed_step=t, bank_role=role, bank_local_committed_step=local,
            indices=indices, row_ids=[r["id"] for r in rows], source_sha256=[r["source_sha256"] for r in rows],
            original_rule_sha256=[rule_sha(r["target"]) for r in rows], template_slots=[0, 1, 0, 1, 0, 1],
            templates=[r["template"] for r in rows], modalities=[r["modality"] for r in rows],
            target_token_ids=[r["modality_token_id"] for r in rows], selected_bank_sha256=banks_by_role[role]["bank_sha256"]))
    require(all(len(c) == 180 and sum(c.values()) == 510 and Counter(c.values()) == Counter({3: 150, 2: 30})
        for c in exposures.values()) and all(draws[t]["original_rule_sha256"] == draws[t + 1]["original_rule_sha256"]
            for t in range(0, 170, 2)), "exact budget/full-bank coverage/pair conservation required")
    result = dict(schema="dual-authored-wording-retention-schedule/v1", seed=1729, first_bank=first_bank,
        optimizer_steps=170, auxiliary_clause_presentations=1020, batch_size=6, bank_count=2,
        source_auxiliary_weight=.05, full_vocabulary_size=32, encoder_context_tokens=512,
        rows_per_bank=180, updates_per_bank={role: 85 for role in ROLES},
        presentations_per_bank={role: 510 for role in ROLES},
        presentations_per_bank_modality={role: {m: 170 for m in MODALITIES} for role in ROLES},
        presentations_per_modality={m: 340 for m in MODALITIES},
        presentations_per_actual_template={t: sum(n for (name, _), n in c.items() if name == t)
            for c in strata.values() for t in {name for name, _ in c}},
        per_source_exposures={role: dict(c) for role, c in exposures.items()},
        bank_sha256={role: banks_by_role[role]["bank_sha256"] for role in ROLES},
        original_pairing_sha256=pairing["pairing_sha256"], draws=draws,
        immutable_bank_handles_required=True, bank_local_receipts_must_not_be_relabelled=True,
        implemented_in_real_trainer=False, qualification_is_independent_of_this_schedule=True, **FALSE)
    result["schedule_sha256"] = digest(result)
    validate_schedule(result)
    return result


def validate_schedule(schedule):
    """Replay proposed receipt coverage/order independently of declared counts."""
    require(type(schedule) is dict and schedule.get("schema") == "dual-authored-wording-retention-schedule/v1"
        and schedule.get("schedule_sha256") == digest({k: v for k, v in schedule.items() if k != "schedule_sha256"})
        and schedule.get("first_bank") in ROLES and type(schedule.get("seed")) is int and schedule["seed"] == 1729
        and all(type(schedule.get(k)) is int and schedule[k] == value for k, value in
            dict(optimizer_steps=170, auxiliary_clause_presentations=1020, batch_size=6, bank_count=2,
                rows_per_bank=180, full_vocabulary_size=32, encoder_context_tokens=512).items())
        and type(schedule.get("source_auxiliary_weight")) is float and schedule["source_auxiliary_weight"] == .05
        and all(schedule.get(k) is False for k in FALSE)
        and schedule.get("implemented_in_real_trainer") is False,
        "closed proposed-only unqualified dual schedule required")
    require(set(schedule["bank_sha256"]) == set(ROLES) and
        all(hash64(h) for h in schedule["bank_sha256"].values())
        and len(set(schedule["bank_sha256"].values())) == 2
        and hash64(schedule["original_pairing_sha256"]), "two distinct source-bank SHA bindings required")
    require(type(schedule["draws"]) is list and len(schedule["draws"]) == 170, "complete170 draw ledger required")
    roles = (schedule["first_bank"], ROLES[1 - ROLES.index(schedule["first_bank"])])
    members = {r: {} for r in ROLES}; exposures = {r: Counter() for r in ROLES}; templates = Counter()
    tokens = {}; all_sources = set()
    for t, draw in enumerate(schedule["draws"]):
        role = roles[t % 2]; local = t // 2
        require(type(draw["global_committed_step"]) is int and draw["global_committed_step"] == t
            and draw["bank_role"] == role and type(draw["bank_local_committed_step"]) is int
            and draw["bank_local_committed_step"] == local
            and draw["selected_bank_sha256"] == schedule["bank_sha256"][role], "global/bank-local committed step differs")
        arrays = ("indices", "row_ids", "source_sha256", "original_rule_sha256", "template_slots",
            "templates", "modalities", "target_token_ids")
        require(all(type(draw[k]) is list and len(draw[k]) == 6 for k in arrays)
            and draw["modalities"] == ["O", "O", "P", "P", "F", "F"]
            and draw["template_slots"] == [0, 1, 0, 1, 0, 1]
            and all(type(slot) is int for slot in draw["template_slots"])
            and all(type(i) is int and 0 <= i < 180 for i in draw["indices"])
            and len(set(draw["indices"])) == len(set(draw["row_ids"])) == 6,
            "six distinct authentic modality/template-slot observations required")
        for i, identity, sha, rule, slot, template, modality, token in zip(*(draw[k] for k in arrays)):
            require(hash64(sha) and identity == "clause:" + sha and hash64(rule)
                and type(template) is str and template and type(token) is int and 3 <= token < 32
                and (modality not in tokens or tokens[modality] == token), "authentic source/target identities required")
            tokens[modality] = token
            item = (identity, sha, rule, slot, template, modality, token)
            require(i not in members[role] or members[role][i] == item, "source member changed between committed uses")
            if i not in members[role]:
                require(sha not in all_sources, "duplicate/colliding source member across banks")
                all_sources.add(sha); members[role][i] = item
            exposures[role][identity] += 1; templates[template] += 1
        if t % 2:
            require(draw["original_rule_sha256"] == schedule["draws"][t - 1]["original_rule_sha256"],
                "corresponding original-rule/template-slot pair differs")
    require(len(tokens) == len(set(tokens.values())) == 3 and len(all_sources) == 360,
        "all360 genuine sources and three fixed target modalities required")
    for role in ROLES:
        inventory = members[role]
        require(set(inventory) == set(range(180)) and len({item[0] for item in inventory.values()}) == 180
            and Counter(item[3:4] + item[5:6] for item in inventory.values()) ==
                Counter({(slot, m): 30 for slot in (0, 1) for m in MODALITIES})
            and len({item[2] for item in inventory.values()}) == 90,
            "all180 bank members and six complete strata required")
        pairs = {(item[2], item[3]) for item in inventory.values()}
        require(len(pairs) == 180 and Counter(exposures[role].values()) == Counter({3: 150, 2: 30})
            and sum(exposures[role].values()) == 510
            and schedule["per_source_exposures"][role] == dict(exposures[role]),
            "every bank member must retain2–3 presentations and exact510 budget")
        canonical = [[i for i, item in sorted(
            ((i, item) for i, item in inventory.items() if (item[5], item[3]) == (m, slot)),
            key=lambda pair: digest([1729, m, slot, pair[1][2]]))]
            for m in MODALITIES for slot in (0, 1)]
        for draw in schedule["draws"]:
            if draw["bank_role"] == role:
                require(draw["indices"] == [order[draw["bank_local_committed_step"] % 30] for order in canonical],
                    "bank-local canonical order differs; global parity sampling is forbidden")
    require(schedule["updates_per_bank"] == {r: 85 for r in ROLES}
        and schedule["presentations_per_bank"] == {r: 510 for r in ROLES}
        and schedule["presentations_per_bank_modality"] == {r: {m: 170 for m in MODALITIES} for r in ROLES}
        and schedule["presentations_per_modality"] == {m: 340 for m in MODALITIES}
        and schedule["presentations_per_actual_template"] == dict(templates)
        and len(templates) == 4 and set(templates.values()) == {255},
        "dual bank/modality/actual-template receipt budgets differ")
    return dict(complete=True, optimizer_steps=170, source_presentations=1020,
        bank_members_validated={r: 180 for r in ROLES}, bank_local_ordinals_validated=True,
        original_rule_pairs_preserved=True, **FALSE)


def _metric_number(value, maximum, name):
    require(type(value) is int and 0 <= value <= maximum, "bounded integer " + name + " required")


def retention_gate(*, schedule, expected_bindings, baseline_panels, candidate_panels,
                   baseline_bank_fields, candidate_bank_fields):
    """Fail-closed numerical retention check, with TRAIN-only metric inputs.

    Passing only permits proposing another independently reviewed, resourced
    authored diagnostic continuation. This function grants no execution or
    checkpoint promotion. Exposed-v3 cannot be supplied as a selector here.
    """
    errors = []
    def check(ok, message):
        if not ok:
            errors.append(message)
    try:
        validate_schedule(schedule)
        require(all(type(panels) is dict and set(panels) == set(TRAIN_COHORTS)
            for panels in (expected_bindings, baseline_panels, candidate_panels)),
            "exact three TRAIN retention cohorts required; v3/sealed60 cannot select")
        require(all(type(metrics) is dict and set(metrics) == set(ROLES)
            for metrics in (baseline_bank_fields, candidate_bank_fields)), "both bank metrics required")
        source_ids, normalized = set(), set()
        baseline_tensors, candidate_tensors = set(), set()
        for cohort in TRAIN_COHORTS:
            binding = expected_bindings[cohort]; rows = binding["source_rows"]
            require(type(rows) is list and len(rows) == 48 and len({r["id"] for r in rows}) == 48
                and all(type(r) is dict and set(r) == {"id", "source_text"}
                    and type(r["id"]) is str and 0 < len(r["id"]) <= 1024 and type(r["source_text"]) is str
                    and r["source_text"].strip() and len(r["source_text"].encode()) <= 32768
                    and len(r["source_text"].split("\n\n")) in (1, 2, 4, 8)
                    and all(t.strip() for t in r["source_text"].split("\n\n")) for r in rows)
                and sum(len(r["source_text"].split("\n\n")) for r in rows) == 180,
                "complete closed48/180 source identity binding required")
            parts = {" ".join(t.casefold().split()) for r in rows
                for t in [r["source_text"], *r["source_text"].split("\n\n")]}
            require(not source_ids & {r["id"] for r in rows} and not normalized & parts,
                "retention cohort source ID/text collision")
            source_ids.update(r["id"] for r in rows); normalized.update(parts)
            require(hash64(binding["source_contexts_sha256"]) and hash64(binding["references_sha256"])
                and hash64(binding["codec_sha256"]), "explicit context/reference/codec SHA bindings required")
            expected = {k: binding[k] for k in ("source_contexts_sha256", "references_sha256", "codec_sha256")}
            expected["source_text_rows_sha256"] = digest(rows)
            for label, panel in (("baseline", baseline_panels[cohort]), ("candidate", candidate_panels[cohort])):
                require(panel["complete"] is True and type(panel["rows"]) is int and panel["rows"] == 48
                    and type(panel["expected_rules"]) is int and panel["expected_rules"] == 180
                    and panel["source_binding"] == expected and hash64(panel["model_tensor_sha256"]),
                    "complete unchanged " + label + " source/target/codec binding required")
                (baseline_tensors if label == "baseline" else candidate_tensors).add(panel["model_tensor_sha256"])
                formula = panel["formula_metrics"]
                wanted = dict(rows=48, expected_rules=180, generated_rules=180, valid_generated_rules=180,
                    eos_count=48, parsed_documents=48, syntax_valid=48, ordered_exact=48, all_rules_preserved=48,
                    whole_rules_missing=0, whole_rules_extra=0, duplicate_rules=0, invalid_rule_count=0,
                    invalid_rows=0, unscorable_generation_rows=0, prediction_missing_rows=0, order_mismatch_rows=0)
                check(all(type(formula.get(k)) is int and formula[k] == value for k, value in wanted.items()),
                    label + ": complete formula/EOS/omission/order floor failed for " + cohort)
                formula_rows = panel["formula_rows"]
                require(type(formula_rows) is list and len(formula_rows) == 48
                    and [r["id"] for r in formula_rows] == [r["id"] for r in rows],
                    "all48 unchanged positional formula rows required")
                for source, observed in zip(rows, formula_rows):
                    n = len(source["source_text"].split("\n\n"))
                    row_wanted = dict(wanted, rows=1, expected_rules=n, generated_rules=n, valid_generated_rules=n,
                        eos_count=1, parsed_documents=1, syntax_valid=1, ordered_exact=1, all_rules_preserved=1)
                    check(all(type(observed["counts"].get(k)) is int and observed["counts"][k] == value
                        for k, value in row_wanted.items()), label + ": row cardinality/fidelity/EOS failure for " + source["id"])
                    require(set(observed["by_facet"]) == set(FACETS)
                        and all(type(observed["by_facet"][f]["total"]) is int
                            and observed["by_facet"][f]["total"] == n for f in FACETS),
                        "complete per-row seven-facet denominators required")
                    check(all(type(observed["by_facet"][f]["correct"]) is int
                        and observed["by_facet"][f]["correct"] == n for f in FACETS),
                        label + ": per-row seven-facet formula floor failed for " + source["id"])
                require(all(type(formula.get(k)) is int and formula[k] == sum(r["counts"][k] for r in formula_rows)
                    for k in wanted), "formula summary differs from complete per-row metrics")
                require(set(panel["seven_facets"]) == set(FACETS)
                    and set(panel["scalar_by_field"]) == set(FIELDS), "all seven facets and four source fields required")
                for field in FACETS:
                    values = panel["seven_facets"][field]
                    require(type(values["total"]) is int and values["total"] == 180, "full180 facet denominator required")
                    _metric_number(values["correct"], 180, "facet correct")
                    require(values["total"] == sum(r["by_facet"][field]["total"] for r in formula_rows)
                        and values["correct"] == sum(r["by_facet"][field]["correct"] for r in formula_rows),
                        "facet summary differs from complete per-row metrics")
                    check(values["correct"] == 180, label + ": seven-facet formula floor failed for " + cohort + "/" + field)
                for field in FIELDS:
                    values = panel["scalar_by_field"][field]
                    require(type(values["reference_sites"]) is int and values["reference_sites"] == 180,
                        "full180 scalar denominator required")
                    for key in ("visited", "unvisited", "unavailable", "source_correct", "source_incorrect"):
                        _metric_number(values[key], 180, key)
                    require(values["visited"] + values["unvisited"] + values["unavailable"] == 180
                        and values["source_correct"] + values["source_incorrect"] == values["visited"],
                        "no dropped or double-counted scalar sites")
                    check(values["visited"] == 180 and values["unvisited"] == values["unavailable"] == 0,
                        label + ": unavailable/unvisited scalar sites for " + cohort + "/" + field)
            for field in FACETS:
                check(candidate_panels[cohort]["seven_facets"][field]["correct"] >= baseline_panels[cohort]["seven_facets"][field]["correct"],
                    "facet retention regression for " + cohort + "/" + field)
            for field in FIELDS:
                check(candidate_panels[cohort]["scalar_by_field"][field]["source_correct"] >= baseline_panels[cohort]["scalar_by_field"][field]["source_correct"],
                    "source-field retention regression for " + cohort + "/" + field)
        require(len(baseline_tensors) == len(candidate_tensors) == 1,
            "one exact baseline/candidate endpoint across TRAIN cohorts required")
        for role in ROLES:
            for metrics in (baseline_bank_fields, candidate_bank_fields):
                require(set(metrics[role]) == set(FIELDS), "all four complete source bank fields required")
                for field in FIELDS:
                    value = metrics[role][field]
                    require(type(value["total"]) is int and value["total"] == 180, "full180 source bank denominator required")
                    _metric_number(value["correct"], 180, "source bank correct")
            check(candidate_bank_fields[role]["modality"]["correct"] == 180,
                "source bank modality retention floor failed for " + role)
            for field in FIELDS:
                check(candidate_bank_fields[role][field]["correct"] >= baseline_bank_fields[role][field]["correct"],
                    "source bank field retention regression for " + role + "/" + field)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        errors.append("invalid or incomplete retention metric contract: " + str(error)[:512])
    passed = not errors
    return dict(schema="dual-authored-wording-numerical-retention-gate/v1", numerical_retention_passed=passed,
        allowed_numerical_continuation=passed,
        permission_scope="eligible to propose a bounded authored diagnostic; independent source/resource readiness remains required",
        findings=errors, training_cohorts=list(TRAIN_COHORTS), exposed_v3_used_for_selection=False,
        bank_and_formula_gates_both_required=True, implemented_in_real_trainer=False,
        no_improvement_claim=True, **FALSE)
