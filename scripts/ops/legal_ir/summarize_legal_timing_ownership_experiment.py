#!/usr/bin/env python3
"""Independent timing-token ownership qualification.

Supplied-boundary clause fidelity, learned boundary/scope decisions, and complete
document fidelity have separate denominators. Compilation is a distinct gate.
Historical retention tolerances are retained exactly; new comparisons never
silently trade newly accepted unsupported documents for other rejections.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import argparse
import math
import multiprocessing
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_scope_retention_experiment as legacy

require, digest, read_ref, ref, write, sha = (getattr(legacy, name) for name in
    ('require', 'digest', 'read_ref', 'ref', 'write', 'sha'))
boundary, retained, previous, clauses = legacy.boundary, legacy.retained, legacy.previous, legacy.clauses
SCHEMA = 'legal-timing-ownership-independent-qualification/v1'
ARCHITECTURES = ('continuation', 'grounding')
OBJECTIVES = ('common', 'ownership')
STAGES = (100, 200)
OPTIONAL = ('conditions', 'exceptions', 'temporal')
SPAN_FIELDS = ('actor', 'action', 'object', *OPTIONAL)
OPTIONAL_FIELDS = ('object', *OPTIONAL)
PRIMARY_BOUNDARIES = ('original', 'distill')
ATOM_PANELS = ('atom_tuning', 'atom_fresh')
ROLE_PANELS = ('role_tuning', 'role_fresh')
GATE_DOCUMENT_PANELS = ('new', *ATOM_PANELS, 'prior_condition', *ROLE_PANELS)


def standard_auxiliary_loss_oracle(torch, output, records):
    """Seven equal semantic components; absent endpoints contribute exact zero."""
    require(len(records) == 4, 'four auxiliary rows required')
    ce = lambda logits, gold: torch.logsumexp(logits, dim=0) - logits[gold]
    total = output['modality'].sum() * 0
    for row, record in enumerate(records):
        labels = record['labels']
        value = ce(output['modality'][row], labels['modality'])
        for index, field in enumerate(SPAN_FIELDS):
            present = bool(labels['presence'][index])
            if present:
                start, end = labels['spans'][index]
                value = value + (ce(output['start'][row, index], start)
                                 + ce(output['end'][row, index], end)) / 2
            else:
                require(labels['spans'][index] == [-100, -100]
                        or labels['spans'][index] == (-100, -100), 'absent pointer labels require ignore indices')
            if field in OPTIONAL_FIELDS:
                value = value + ce(output['presence'][row, OPTIONAL_FIELDS.index(field)], int(present))
        total = total + value
    return total / 28


def ownership_loss_oracle(torch, output, records):
    """Enumerate every valid interval independently of the runtime algorithm.

    Token membership is presence times span coverage. Its complement is a
    disjoint mixture of absent-facet mass and present intervals not containing
    the token, evaluated in log space without subtracting nearly equal values.
    """
    require(len(records) == 4, 'four balanced auxiliary rows required')
    mean = lambda values: torch.stack(values).mean()
    components = {}; facets = []
    for field in ('conditions', 'temporal'):
        index, optional_index = SPAN_FIELDS.index(field), OPTIONAL_FIELDS.index(field)
        groups = {False: [], True: []}; positive_tokens = negative_tokens = token_groups = 0
        for row, record in enumerate(records):
            length = len(record['tokens']); labels = record['labels']
            require(length > 0, 'nonempty unpadded token inventory required')
            present = bool(labels['presence'][index])
            start, end = labels['spans'][index]
            require((present and 0 <= start <= end < length) or
                    (not present and [start, end] == [-100, -100]), 'gold ownership span differs')
            indices = torch.triu_indices(length, length, device=output['start'].device)
            scores = output['start'][row, index, indices[0]] + output['end'][row, index, indices[1]]
            log_z = torch.logsumexp(scores, dim=0)
            presence = output['presence'][row, optional_index]
            log_presence = presence - torch.logsumexp(presence, dim=0)
            tokens = torch.arange(length, device=scores.device)
            contains = (indices[0][None, :] <= tokens[:, None]) & (tokens[:, None] <= indices[1][None, :])
            inside_log = torch.logsumexp(scores[None, :].expand(length, -1).masked_fill(~contains, -torch.inf), 1) - log_z
            outside_scores = scores[None, :].expand(length, -1).masked_fill(contains, -torch.inf)
            has_outside = (~contains).any(1)
            outside_scores = torch.where(has_outside[:, None], outside_scores, torch.zeros_like(outside_scores))
            outside_log = torch.logsumexp(outside_scores, 1) - log_z
            outside_log = torch.where(has_outside, outside_log, torch.full_like(outside_log, -torch.inf))
            owned_losses = -(log_presence[1] + inside_log)
            unowned_losses = -torch.logaddexp(log_presence[0].expand(length), log_presence[1] + outside_log)
            gold = (tokens >= start) & (tokens <= end) if present else torch.zeros(length, dtype=torch.bool, device=scores.device)
            positive_tokens += int(gold.sum()); negative_tokens += int((~gold).sum())
            values = ([owned_losses[gold].mean()] if bool(gold.any()) else [])
            values += ([unowned_losses[~gold].mean()] if bool((~gold).any()) else [])
            token_groups += len(values)
            groups[present].append(mean(values))
        require(len(groups[True]) == len(groups[False]) == 2,
                'each timing ownership facet needs two present and two absent rows')
        positive, negative = mean(groups[True]), mean(groups[False])
        value = (positive + negative) / 2
        components[field] = {'present_loss': positive, 'absent_loss': negative,
                             'ownership_loss': value, 'positive_tokens': positive_tokens,
                             'negative_tokens': negative_tokens, 'present_rows': 2, 'absent_rows': 2, 'token_groups': token_groups}
        facets.append(value)
    return mean(facets), components


def clause_metrics(generation, sources, references):
    """Score literal full-rule and facet equality on every supplied clause.

Occurrence IDs must be unique even when source strings or canonical rules are
identical. An abstention fails both present and absent facet accuracy.
"""
    targets = {row['id']: row for row in references}
    ids = [row['id'] for row in sources]
    predictions = generation['rows']
    require(len(ids) == len(set(ids)) == len(targets) == len(references) == len(predictions)
            and set(ids) == set(targets), 'complete unique clause occurrence inventory required')
    result = {'count': len(ids), 'fullrule_exact': 0, 'decoded': 0, 'actor_exact': 0,
              'modality_fullrule': {value: {'count': 0, 'exact': 0} for value in 'OPF'},
              'optional_facet': {field: {label: {'count': 0, 'exact': 0}
                                 for label in ('present', 'absent')} for field in OPTIONAL}}
    rows = []
    for source, prediction in zip(sources, predictions, strict=True):
        identity, text = source['id'], source['source_text']
        source_sha = boundary.text_sha(text)
        target = targets[identity]
        require(source.get('source_sha256', source_sha) == source_sha
                and prediction['source_sha256'] == source_sha
                and target['source_text'] == text, 'clause source join differs')
        require(prediction.get('id', identity) == identity
                and prediction['status'] in ('decoded', 'abstained'), 'clause prediction identity or status differs')
        canonical = target['canonical_ir']
        require(len(canonical['rules']) == 1, 'one reference rule required per supplied occurrence')
        gold = canonical['rules'][0]
        accepted = prediction['status'] == 'decoded'
        if accepted:
            require(type(prediction['canonical_ir']) is dict and len(prediction['canonical_ir']['rules']) == 1,
                    'one decoded rule required per supplied occurrence')
            actual = prediction['canonical_ir']['rules'][0]
        else:
            require(prediction['canonical_ir'] is None, 'abstention cannot carry a canonical rule')
            actual = None
        exact = bool(accepted and prediction['canonical_ir'] == canonical)
        actor = bool(accepted and actual['actor'] == gold['actor'])
        result['fullrule_exact'] += exact
        result['decoded'] += accepted
        result['actor_exact'] += actor
        require(gold['modality'] in 'OPF', 'declared normative modality required')
        cell = result['modality_fullrule'][gold['modality']]
        cell['count'] += 1
        cell['exact'] += exact
        detail = {'id': identity, 'source_sha256': source_sha, 'decoded': accepted,
                  'fullrule_exact': exact, 'actor_exact': actor, 'modality': gold['modality'],
                  'optional_facet': {}, 'reason': prediction.get('reason')}
        for field in OPTIONAL:
            label = 'present' if gold[field] else 'absent'
            equal = bool(accepted and actual[field] == gold[field])
            cell = result['optional_facet'][field][label]
            cell['count'] += 1
            cell['exact'] += equal
            detail['optional_facet'][field] = {'label': label, 'exact': equal}
        rows.append(detail)
    validate_clause_metrics(result)
    return {'metrics': result, 'rows': rows,
            'abstentions_count_as_facet_and_rule_failures': True}


def validate_clause_metrics(value):
    fields = {'count', 'fullrule_exact', 'decoded', 'actor_exact', 'modality_fullrule', 'optional_facet'}
    require(set(value) == fields and type(value['count']) is int and value['count'] > 0,
            'closed nonempty clause metric inventory required')
    count = value['count']
    for key in ('fullrule_exact', 'decoded', 'actor_exact'):
        require(type(value[key]) is int and 0 <= value[key] <= count, 'bounded integer clause count required')
    require(value['fullrule_exact'] <= value['actor_exact'] <= value['decoded'],
            'actor/full-rule correctness cannot exceed decoded count')
    require(set(value['modality_fullrule']) == set('OPF') and set(value['optional_facet']) == set(OPTIONAL),
            'complete modality and optional facet inventory required')
    for group in (value['modality_fullrule'], *value['optional_facet'].values()):
        require(set(group) == (set('OPF') if group is value['modality_fullrule'] else {'present', 'absent'}),
                'complete facet class partition required')
        for cell in group.values():
            require(set(cell) == {'count', 'exact'} and all(type(cell[key]) is int for key in cell)
                    and 0 <= cell['exact'] <= cell['count'] <= count, 'bounded exact class metric required')
        require(sum(cell['count'] for cell in group.values()) == count, 'class counts must partition full denominator')
        require(value['fullrule_exact'] <= sum(cell['exact'] for cell in group.values()) <= value['decoded'],
                'facet totals contradict full-rule or abstention counts')
    require(sum(cell['exact'] for cell in value['modality_fullrule'].values()) == value['fullrule_exact'],
            'modality full-rule strata must partition exact total')
    return True


def retains_clauses(current, parent):
    validate_clause_metrics(current)
    validate_clause_metrics(parent)
    require(current['count'] == parent['count'], 'clause comparison dropped sources')
    for group in ('modality_fullrule', 'optional_facet'):
        a, b = current[group], parent[group]
        values = [(a, b)] if group == 'modality_fullrule' else [(a[field], b[field]) for field in OPTIONAL]
        for left, right in values:
            require(all(left[label]['count'] == right[label]['count'] for label in left),
                    'clause class reference denominators changed')
    return (current['fullrule_exact'] >= parent['fullrule_exact']
            and current['actor_exact'] >= parent['actor_exact']
            and all(current['modality_fullrule'][modality]['exact'] >= parent['modality_fullrule'][modality]['exact']
                    for modality in 'OPF')
            and all(current['optional_facet'][field][label]['exact'] >= parent['optional_facet'][field][label]['exact']
                    for field in OPTIONAL for label in ('present', 'absent')))


def document_metrics(scored_rows):
    """Complete source-level gate identity prevents cancellation of guard errors."""
    require(scored_rows and len({row['id'] for row in scored_rows}) == len(scored_rows),
            'complete unique document scored rows required')
    for row in scored_rows:
        require(type(row['supported']) is bool and type(row['joint_exact']) is bool
                and type(row['composed']) is bool and (not row['joint_exact'] or row['supported'] and row['composed']),
                'invalid document truth or joint-exact status')
    supported = sorted(row['id'] for row in scored_rows if row['supported'])
    unsupported = sorted(row['id'] for row in scored_rows if not row['supported'])
    exact = sorted(row['id'] for row in scored_rows if row['joint_exact'])
    accepted = sorted(row['id'] for row in scored_rows if not row['supported'] and row['composed'])
    return {'count': len(scored_rows), 'supported': len(supported), 'unsupported': len(unsupported),
            'joint_exact': len(exact), 'supported_ids': supported, 'unsupported_ids': unsupported,
            'joint_exact_ids': exact, 'unsupported_accepted_ids': accepted}


def validate_document_metrics(value):
    keys = {'count', 'supported', 'unsupported', 'joint_exact', 'supported_ids', 'unsupported_ids',
            'joint_exact_ids', 'unsupported_accepted_ids'}
    require(set(value) == keys, 'closed source-level document gate metrics required')
    for key in ('count', 'supported', 'unsupported', 'joint_exact'):
        require(type(value[key]) is int and value[key] >= 0, 'integer document denominator required')
    for key in ('supported_ids', 'unsupported_ids', 'joint_exact_ids', 'unsupported_accepted_ids'):
        require(type(value[key]) is list and all(type(item) is str for item in value[key])
                and value[key] == sorted(set(value[key])), 'sorted unique document identity lists required')
    supported, unsupported = set(value['supported_ids']), set(value['unsupported_ids'])
    require(value['supported'] == len(supported) and value['unsupported'] == len(unsupported)
            and value['count'] == len(supported) + len(unsupported) and value['count'] > 0
            and not supported & unsupported and value['joint_exact'] == len(value['joint_exact_ids'])
            and set(value['joint_exact_ids']) <= supported
            and set(value['unsupported_accepted_ids']) <= unsupported, 'document identity partitions differ')
    return True


def document_churn(current, parent):
    validate_document_metrics(current)
    validate_document_metrics(parent)
    require(current['supported_ids'] == parent['supported_ids']
            and current['unsupported_ids'] == parent['unsupported_ids'], 'document retention source population differs')
    old, new = set(parent['joint_exact_ids']), set(current['joint_exact_ids'])
    old_guards, new_guards = set(parent['unsupported_accepted_ids']), set(current['unsupported_accepted_ids'])
    return {'supported_wins': sorted(new - old), 'supported_losses': sorted(old - new),
            'new_unsupported_accepts': sorted(new_guards - old_guards),
            'removed_unsupported_accepts': sorted(old_guards - new_guards)}


def retains_documents(current, parent):
    churn = document_churn(current, parent)
    return current['joint_exact'] >= parent['joint_exact'] and not churn['new_unsupported_accepts']


def normalize_legacy(fields):
    """Bind new runner's unchanged historical fields to the frozen independent gate."""
    result = {}
    for panel in legacy.TUNING:
        result[{'prior_role': 'role', 'prior_facet': 'facet'}.get(panel, panel)] = fields['tuning_' + panel + '_exact']
    result['new_positive'] = fields['tuning_new_Tpresent_exact']
    result['new_negative'] = fields['tuning_new_Tabsent_exact']
    result['retention_metrics'] = deepcopy(fields['retention_metrics'])
    result['condition_metrics'] = deepcopy(fields['condition_metrics'])
    for panel, prefix in legacy.DOCUMENT_PREFIX.items():
        for policy in ('parent', 'expanded'):
            result[prefix + 'document_' + policy] = fields['tuning_' + prefix + 'document_' + policy + '_exact']
            result[prefix + 'guard_' + policy] = fields['tuning_' + prefix + 'document_' + policy + '_unsupported_accepted']
    return result


def eligible(stage, parent):
    if not legacy.clause_eligible(normalize_legacy(stage), normalize_legacy(parent)):
        return False
    if not retains_clauses(stage['new_single_metrics'], parent['new_single_metrics']):
        return False
    if not retains_clauses(stage['prior_condition_metrics'], parent['prior_condition_metrics']):
        return False
    require(stage['new_single_metrics']['count'] == parent['new_single_metrics']['count'] == 192,
            'all192 new tuning clauses required')
    require(stage['prior_condition_metrics']['count'] == parent['prior_condition_metrics']['count'] == 192,
            'all192 exposed condition retention clauses required')
    for key, panels in (('role_retention_metrics', ('tuning', 'fresh')), ('role_oracle_metrics', ROLE_PANELS)):
        require(set(stage[key]) == set(parent[key]) == set(panels), 'both prior role retention panels required')
        for panel in panels:
            if not retains_clauses(stage[key][panel], parent[key][panel]): return False
    for value in (stage, parent):
        require(set(value['old_atom_oracle_metrics']) == set(ATOM_PANELS)
                and set(value['oracle_document_metrics']) == set(GATE_DOCUMENT_PANELS)
                and set(value['fixed_document_metrics']) == set(GATE_DOCUMENT_PANELS),
                'complete new and exposed atom gate panel inventory required')
        for panel in value['fixed_document_metrics']:
            require(set(value['fixed_document_metrics'][panel]) == set(PRIMARY_BOUNDARIES),
                    'both fixed primary boundary policies required')
    for panel in ATOM_PANELS:
        if not retains_clauses(stage['old_atom_oracle_metrics'][panel], parent['old_atom_oracle_metrics'][panel]):
            return False
    for panel in GATE_DOCUMENT_PANELS:
        if not retains_documents(stage['oracle_document_metrics'][panel], parent['oracle_document_metrics'][panel]):
            return False
        require(stage['oracle_document_metrics'][panel]['unsupported'] == 0,
                'oracle supplied flat clauses cannot assign unsupported nested document targets')
        for policy in PRIMARY_BOUNDARIES:
            if not retains_documents(stage['fixed_document_metrics'][panel][policy], parent['fixed_document_metrics'][panel][policy]):
                return False
    return (stage['new_single_metrics']['fullrule_exact'] > parent['new_single_metrics']['fullrule_exact']
            or stage['oracle_document_metrics']['new']['joint_exact'] > parent['oracle_document_metrics']['new']['joint_exact'])


def ranking(stage):
    historical = legacy.clause_ranking({**normalize_legacy(stage), 'steps': stage['steps']})
    return (stage['new_single_metrics']['fullrule_exact'], stage['oracle_document_metrics']['new']['joint_exact'],
            stage['fixed_document_metrics']['new']['distill']['joint_exact'],
            stage['fixed_document_metrics']['new']['original']['joint_exact'],
            sum(stage['old_atom_oracle_metrics'][panel]['fullrule_exact'] for panel in ATOM_PANELS),
            *historical[:-1], -stage['steps'])


def select_stage(stages, parent):
    require(type(stages) is list and [row['steps'] for row in stages] == list(STAGES),
            'ordered100/200 candidate stages required')
    candidates = [row for row in stages if eligible(row, parent)]
    return max(candidates, key=ranking) if candidates else None


def auxiliary_blocks(rows, pairs, blocks):
    """Independent exact meaning-pair and complement-mask block audit."""
    by_id = {row['id']: row for row in rows}
    require(len(by_id) == len(rows) == 768 and len(pairs) == 384 and len(blocks) == 192,
            'complete separate768-row auxiliary inventory required')
    pair_rows, used = {}, set()
    for pair in pairs:
        require(set(pair) == {'pair_id', 'case_group', 'left_id', 'right_id', 'canonical_ir_sha256'}
                and pair['pair_id'] not in pair_rows, 'closed unique auxiliary semantic pair required')
        identities = [pair['left_id'], pair['right_id']]
        require(len(set(identities)) == 2 and set(identities) <= set(by_id) and not used.intersection(identities),
                'auxiliary pair member missing or reused')
        a, b = (by_id[identity] for identity in identities)
        require(a['canonical_ir'] == b['canonical_ir'] and digest(a['canonical_ir']) == pair['canonical_ir_sha256']
                and a['source_text'] != b['source_text'], 'same-meaning pair changed canonical meaning or surface identity')
        pair_rows[pair['pair_id']] = identities
        used.update(identities)
    require(used == set(by_id), 'auxiliary pair coverage incomplete')
    used_pairs, block_ids, result = set(), set(), []
    for block in blocks:
        require(set(block) == {'block_id', 'pair_ids'} and block['block_id'] not in block_ids
                and len(block['pair_ids']) == len(set(block['pair_ids'])) == 2
                and set(block['pair_ids']) <= set(pair_rows)
                and not used_pairs.intersection(block['pair_ids']), 'two new unused semantic pairs per auxiliary block required')
        identities = [identity for pair in block['pair_ids'] for identity in pair_rows[pair]]
        rules = [by_id[identity]['canonical_ir']['rules'][0] for identity in identities]
        require(all(sum(bool(rule[field]) for rule in rules) == 2 for field in OPTIONAL),
                'four-row block must balance each optional facet independently')
        require(all(rule['actor'] for rule in rules), 'all auxiliary actor labels required')
        result.append(identities)
        used_pairs.update(block['pair_ids']); block_ids.add(block['block_id'])
    require(used_pairs == set(pair_rows), 'auxiliary block pair coverage incomplete')
    return result


def expected_batch(seed, step, pools, blocks, block_rows):
    require(type(step) is int and 1 <= step <= 200 and len(blocks) == len(block_rows) == 192,
            'bounded step and complete192-block schedule required')
    main = legacy.prior.expected_batch(seed, step, pools)
    epoch, index = divmod(step - 1, len(blocks))
    order = list(range(len(blocks)))
    random.Random(f'timing-ownership/v1:{seed}:auxiliary_blocks:{epoch}').shuffle(order)
    choice = order[index]
    return {**main, 'indices_by_pool': {**main['indices_by_pool'], 'auxiliary_block': [choice]},
            'auxiliary_ids': block_rows[choice], 'auxiliary_block_id': blocks[choice]['block_id'],
            'auxiliary_pair_ids': blocks[choice]['pair_ids']}


def verify_auxiliary_receipt(receipt, records, parts, *, step):
    import torch
    require(set(receipt) == {'optimizer_step', 'ids', 'token_counts', 'labels', 'logits', 'ownership_masks', 'ownership_masks_sha256'}
            and receipt['optimizer_step'] == step and receipt['ids'] == [row['id'] for row in records]
            and receipt['token_counts'] == [len(row['tokens']) for row in records]
            and digest(receipt['labels']) == digest([row['labels'] for row in records]), 'auxiliary receipt changed source IDs or authoritative labels')
    require(set(receipt['logits']) == {'modality', 'presence', 'start', 'end'}, 'complete auxiliary semantic logits required')
    width = max(len(row['tokens']) for row in records)
    shapes = {'modality': (4, 3), 'presence': (4, 4, 2), 'start': (4, 6, width), 'end': (4, 6, width)}
    output = {}
    for key, shape in shapes.items():
        tensor = torch.tensor(receipt['logits'][key], dtype=torch.float64)
        require(tuple(tensor.shape) == shape and bool(torch.isfinite(tensor).all()),
                'finite complete auxiliary logit tensor required')
        output[key] = tensor
    standard = standard_auxiliary_loss_oracle(torch, output, records)
    ownership, independent = ownership_loss_oracle(torch, output, records)
    expected = {'auxiliary_standard_ce': standard, 'timing_ownership_nll': ownership}
    wanted_masks = []
    for record in records:
        masks = {}
        for field in ('conditions', 'temporal'):
            index = SPAN_FIELDS.index(field)
            present = bool(record['labels']['presence'][index])
            start, end = record['labels']['spans'][index]
            masks[field] = [bool(present and start <= token <= end) for token in range(len(record['tokens']))]
        wanted_masks.append(masks)
    require(all(type(value) is bool for row in receipt['ownership_masks'] for values in row.values() for value in values)
            and receipt['ownership_masks'] == wanted_masks and receipt['ownership_masks_sha256'] == digest(receipt['ownership_masks']) == digest(wanted_masks), 'token ownership mask differs from authoritative source span')
    for field in ('conditions', 'temporal'):
        for actual, wanted in (('present_nll', 'present_loss'), ('absent_nll', 'absent_loss'), ('nll', 'ownership_loss')):
            expected['ownership_' + field + '_' + actual] = independent[field][wanted]
        for actual, wanted in (('present_rows','present_rows'),('absent_rows','absent_rows'),
                               ('owned_tokens','positive_tokens'),('nonowned_tokens','negative_tokens'),('token_groups','token_groups')):
            require(parts['ownership_' + field + '_' + actual] == independent[field][wanted],
                    'ownership group denominator differs')
    errors = []
    for key, tensor in expected.items():
        value = float(tensor)
        require(type(parts[key]) in (float, int) and math.isfinite(parts[key])
                and math.isclose(parts[key], value, rel_tol=2e-5, abs_tol=2e-6),
                'independent auxiliary loss differs: ' + key)
        errors.append(abs(parts[key] - value))
    return {'rows': 4, 'maximum_numerical_error': max(errors),
            'standard_CE_and_token_ownership_recomputed_from_saved_logits': True,
            'logits_generated_by_model_independently_replayed': False}


def verify_training_report(report, preceding, checkpoint, inputs, eligibility, auxiliary_records, block_rows):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    start, finish = (value['progress']['optimizer_steps'] for value in (preceding, checkpoint))
    require((start, finish) in ((0, 100), (100, 200)), 'complete two-stage200-update chain required')
    updates = finish - start
    config, model_config = checkpoint['training_config'], checkpoint['model_config']
    objective = config['objective']; enabled = model_config['trigger_enabled']
    require(objective in OBJECTIVES and report['schema'] == 'timing-ownership-training/v1'
            and report['objective'] == objective and report['optimizer_steps'] == updates
            and report['new_optimizer_steps_total'] == finish and report['training_executed'] is True
            and report['stopped_reason'] == 'step_limit' and report['tuning_used_for_fit'] is False,
            'complete matched training budget and training-only provenance required')
    require(report['checkpoint_sha256'] == digest(checkpoint)
            and report['frozen_parent_checkpoint_sha256'] == checkpoint['frozen_parent_checkpoint_sha256']
            and report['frozen_parent_kind'] == checkpoint['frozen_parent_kind']
            and report['frozen_parent_optimizer_steps'] == checkpoint['frozen_parent_optimizer_steps'],
            'exact heterogeneous pretrained parent binding differs')
    for name in ('auxiliary_manifest_sha256', 'auxiliary_pairs_sha256', 'auxiliary_blocks_sha256'):
        require(report[name] == checkpoint[name], 'auxiliary source manifest commitment differs')
    require(all(len(report[key]) == updates for key in ('batch_losses', 'batch_loss_components',
                'batch_exposures', 'auxiliary_loss_receipts')) and report['domain_exposures'] == {'earlier': 3*updates, 'new': 9*updates}
            and report['pair_exposures'] == 3*updates and report['auxiliary_source_exposures'] == 4*updates
            and report['auxiliary_block_exposures'] == updates, 'main and auxiliary exposure denominator differs')
    require(report['teacher_training_labels_only'] is report['teacher_state_unchanged'] is report['teacher_gradients_disabled'] is True
            and report['teacher_state_sha256_before'] == report['teacher_state_sha256_after'] == mixed._state_digest(eligibility.model),
            'frozen parent teacher state changed or lost provenance')
    require(type(report['elapsed_seconds']) in (int, float) and math.isfinite(report['elapsed_seconds'])
            and report['elapsed_seconds'] > 0 and math.isfinite(report['gradient_norm_max'])
            and report['gradient_norm_max'] >= 0, 'finite timing and gradient evidence required')
    pools = legacy.prior.training_pools(inputs)
    close = lambda a, b: math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-6)
    checks, errors = [], []
    for step, (exposure, parts, loss, receipt) in enumerate(zip(report['batch_exposures'], report['batch_loss_components'],
            report['batch_losses'], report['auxiliary_loss_receipts'], strict=True), start+1):
        require(exposure == expected_batch(config['seed'], step, pools, inputs['aux_blocks'], block_rows),
                'independent main and auxiliary minibatch schedule differs')
        require(parts['domain_rows'] == {'earlier': 3, 'new': 9} and parts['supervised_trigger_rows'] == 9
                and parts['trigger_loss_rows'] == (9 if enabled else 0) and parts['pair_count'] == 3
                and parts['consistency_weight'] == .25 and parts['auxiliary_rows'] == 4,
                'main semantic pair/domain/trigger or auxiliary row count differs')
        numerical = [key for key in parts if key not in {'domain_rows'}]
        require(all(type(parts[key]) in (int, float) and math.isfinite(parts[key]) and parts[key] >= -2e-6 for key in numerical)
                and type(loss) in (int, float) and math.isfinite(loss) and loss >= -2e-6,
                'nonfinite or negative objective receipt')
        require(all(parts[key] <= math.log(2)+2e-6 for key in ('js_modality', 'js_presence', 'js_endpoints', 'consistency_js')),
                'JS component exceeds probability bound')
        require(close(parts['semantic'], (parts['semantic_earlier']+parts['semantic_new'])/2)
                and close(parts['actor'], (parts['actor_earlier']+parts['actor_new'])/2)
                and close(parts['base_ce'], parts['semantic']+model_config['trigger_loss_weight']*parts['trigger']
                          +model_config['actor_loss_weight']*parts['actor'])
                and close(parts['consistency_js'], sum(parts[key] for key in ('js_modality','js_presence','js_endpoints'))/3)
                and close(parts['weighted_consistency'], .25*parts['consistency_js'])
                and close(parts['base_objective'], parts['base_ce']+parts['weighted_consistency']),
                'independent inherited semantic and JS objective arithmetic differs')
        expected = {key: sum(eligibility[identity][key] for identity in exposure['ids'][:6])
                    for key in ('teacher_presence_terms', 'teacher_endpoint_terms')}
        expected['overlap_facet_pairs'] = sum(eligibility[identity]['overlap_facet_pairs'] for identity in exposure['ids'])
        if any(parts[key] != expected[key] for key in ('teacher_presence_terms','teacher_endpoint_terms')):
            exact = eligibility.exact_batch_counts(exposure['ids'])
            checks.append({'step': step, 'cached': {key: expected[key] for key in exact}, 'exact_batch': exact})
            expected.update(exact)
        require(all(parts[key] == value for key, value in expected.items()), 'teacher eligibility or overlap pair counts differ')
        require(parts['teacher_weight'] == .5 and parts['overlap_weight'] == .1
                and -2e-6 <= parts['span_overlap'] <= 1+2e-6
                and close(parts['teacher_kl'], (parts['teacher_presence_kl']+parts['teacher_endpoint_kl'])/2)
                and close(parts['weighted_teacher'], .5*parts['teacher_kl'])
                and close(parts['weighted_overlap'], .1*parts['span_overlap']),
                'frozen teacher/overlap objective accounting differs')
        auxiliary = [auxiliary_records[identity] for identity in exposure['auxiliary_ids']]
        result = verify_auxiliary_receipt(receipt, auxiliary, parts, step=step)
        errors.append(result['maximum_numerical_error'])
        weight = .25 if objective == 'ownership' else 0.
        require(parts['auxiliary_standard_ce_weight'] == .25 and parts['ownership_weight'] == weight
                and close(parts['weighted_auxiliary_standard_ce'], .25*parts['auxiliary_standard_ce'])
                and close(parts['common_objective'], parts['base_objective']+parts['weighted_teacher']
                          +parts['weighted_overlap']+parts['weighted_auxiliary_standard_ce'])
                and close(parts['weighted_ownership'], weight*parts['timing_ownership_nll'])
                and close(parts['total'], parts['common_objective']+parts['weighted_ownership'])
                and close(loss, parts['total']), 'matched intervention total or coefficients differ')
        if not enabled:
            require(all(parts[key] == 0 for key in ('actor','trigger','actor_earlier','actor_new')),
                    'disabled grounding heads received main auxiliary loss')
    gradients = report['auxiliary_gradient_norm_max']
    require(set(gradients) == {'trigger_boundary', 'trigger_modality', 'actor_boundary'}
            and all(type(value) in (int,float) and math.isfinite(value) and value >= 0 for value in gradients.values()),
            'complete finite auxiliary gradient inventory required')
    if not enabled:
        require(all(value == 0 for value in gradients.values()), 'disabled grounding head gradient changed')
        for name, value in preceding['model_state'].items():
            if name.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.')):
                require(checkpoint['model_state'][name] == value, 'disabled grounding head parameter changed')
    changed = [name for name, value in checkpoint['model_state'].items() if value != preceding['model_state'][name]]
    require(changed and sorted(changed) == sorted(report['changed_parameter_names'])
            and len(changed) == len(report['changed_parameter_names']), 'actual changed parameter inventory differs')
    return {'additional_steps_before': start, 'additional_steps_after': finish, 'optimizer_updates': updates,
            'main_source_exposures': 12*updates, 'auxiliary_source_exposures': 4*updates,
            'batch_trace_sha256': digest(report['batch_exposures']), 'teacher_exact_batch_rechecks': checks,
            'auxiliary_loss_maximum_error': max(errors), 'optimizer_trajectory_replayed': False}


def document_selection(records, sources, *, toolchain):
    """Variable-size source-only lowering using the frozen calendar gate.

Oracle48 and learned96 document panels retain their actual source inventories;
no synthetic rows, padding, deduplication, or assumed minimum size is used.
"""
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(1 <= len(sources) <= 192 and len(records) == len(sources)
            and len({row['candidate_id'] for row in records}) == len(records),
            'complete bounded unique document predictions required')
    by_id = {source['candidate_id']: source for source in sources}
    require(len(by_id) == len(sources) and {row['candidate_id'] for row in records} == set(by_id),
            'document lowering source identity coverage differs')
    entries, excluded = [], []
    for record in records:
        source = by_id[record['candidate_id']]
        require(record['source_sha256'] == source['source_sha256'] == boundary.text_sha(source['source_text']),
                'document source commitment differs during lowering')
        if record['composition'] is None:
            require(record['status'] == 'abstained', 'missing composition must be an explicit abstention')
            excluded.append({'candidate_id': record['candidate_id'], 'reason': record['reason'], 'status': record['status']})
            continue
        require(record['status'] == 'composed', 'composition status differs')
        value = record['composition']; plan_hash = value['source_plan_sha256']
        require(value['source_plan']['source'] == source, 'composition source plan differs from pinned document')
        candidate = retained.compose.calendar_candidate(value, expected_plan_sha256=plan_hash)
        try:
            interpretation = retained.calendar.synthetic_interpretation(candidate, policy=retained.calendar.POLICY)
            require(interpretation == retained.calendar_summary.expected_interpretation(candidate),
                    'independent calendar interpretation policy differs')
            retained.compose.prepare_calendar_composition(value, interpretation, expected_plan_sha256=plan_hash)
            entry = {'candidate': candidate, 'interpretation': interpretation}
            require(gate.prepare_qualified_legal([entry], toolchain=toolchain).to_dict()['all_candidates_supported'],
                    'unsupported canonical calendar lowering')
            entries.append(entry)
        except (ValueError, KeyError, TypeError) as error:
            excluded.append({'candidate_id': record['candidate_id'], 'reason': str(error), 'status': 'interpretation_unsupported'})
    require(len(entries) + len(excluded) == len(sources), 'lowering discarded a source outcome')
    return {'rows': entries, 'excluded': excluded, 'source_count': len(sources)}


def verify_scope_invariance(original, distill, sources):
    """Scope evidence is independent of delivered boundaries and clause success."""
    legacy.verify_scope_logits(original)
    legacy.verify_scope_logits(distill)
    expected = {row['candidate_id']: row for row in sources}
    a = {row['candidate_id']: row for row in original['rows']}
    b = {row['candidate_id']: row for row in distill['rows']}
    require(len(a) == len(b) == len(expected) == len(sources) == len(original['rows']) == len(distill['rows'])
            and set(a) == set(b) == set(expected), 'scope invariance source inventory differs')
    for identity, source in expected.items():
        require(a[identity]['source_sha256'] == b[identity]['source_sha256'] == source['source_sha256']
                and source['source_sha256'] == boundary.text_sha(source['source_text']), 'scope comparison source commitment differs')
        for key in ('scope_logits', 'scope_supported_probability', 'raw_learned_scope_supported'):
            require(a[identity][key] == b[identity][key], 'fixed original scope changed under boundary diagnostic: ' + key)
    return {'source_documents': len(sources), 'all_raw_scope_logits_and_decisions_exactly_equal': True,
            'scope_training_updates': 0, 'boundary_or_clause_accuracy_does_not_prove_scope_accuracy': True}


def verify_oracle_sources(sources, mapping, document_sources, plans):
    """Validate explicit supplied segmentation without semantic reference access."""
    documents = {row['candidate_id']: row for row in document_sources}
    lookup = {row['id']: row for row in sources}
    require(len(lookup) == len(sources) == len(mapping) and len(documents) == len(document_sources)
            and sources and document_sources, 'complete unique oracle sources and occurrence mapping required')
    require([row['id'] for row in sources] == [row['id'] for row in mapping],
            'oracle occurrence source and mapping order differ')
    require(set(plans) == set(documents), 'every oracle-supported document must retain a source plan')
    grouped = {identity: [] for identity in documents}
    seen = set()
    keys = {'id', 'document_id', 'document_source_sha256', 'source_sha256',
            'char_start', 'char_end', 'occurrence_index'}
    for occurrence in mapping:
        require(set(occurrence) == keys and occurrence['id'] in lookup and occurrence['id'] not in seen
                and occurrence['document_id'] in documents, 'oracle occurrence identity or closed schema differs')
        source, document = lookup[occurrence['id']], documents[occurrence['document_id']]
        start, end = occurrence['char_start'], occurrence['char_end']
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(document['source_text'])
                and source['source_text'] == document['source_text'][start:end]
                and occurrence['source_sha256'] == boundary.text_sha(source['source_text'])
                and source.get('source_sha256', occurrence['source_sha256']) == occurrence['source_sha256']
                and occurrence['document_source_sha256'] == document['source_sha256'] == boundary.text_sha(document['source_text']),
                'oracle occurrence substring, offsets or complete source hash differs')
        require(type(occurrence['occurrence_index']) is int and occurrence['occurrence_index'] >= 0,
                'integer oracle occurrence ordinal required')
        require(occurrence['id'] == 'oracle-' + digest([occurrence['document_id'], occurrence['occurrence_index'],
                start, end, occurrence['source_sha256']]), 'opaque oracle identity commitment differs')
        grouped[occurrence['document_id']].append(occurrence)
        seen.add(occurrence['id'])
    rebuilt = {}
    for identity, occurrences in grouped.items():
        rows = sorted(occurrences, key=lambda row: row['occurrence_index'])
        require(rows and [row['occurrence_index'] for row in rows] == list(range(len(rows))),
                'oracle occurrence ordinals must exhaust each document')
        declarations = [{'clause_id': row['id'], 'char_start': row['char_start'], 'char_end': row['char_end'],
                         'scope': retained.compose.FLAT_SCOPE} for row in rows]
        plan = retained.compose.prepare_source_plan(documents[identity], declarations)
        require(plan == plans[identity], 'oracle source plan is not exact deterministic occurrence regeneration')
        rebuilt[identity] = plan
    require(seen == set(lookup), 'oracle occurrence source dropped')
    return {'documents': len(documents), 'occurrences': len(sources),
            'all_supplied_intervals_and_occurrences_reconstructed': True,
            'oracle_segmentation_and_supported_membership_supplied': True,
            'semantic_reference_access': False, 'learned_boundary_accuracy_claimed': False}


def verify_fitting(inputs):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    old = inputs['legacy']
    inherited = legacy.verify_fitting(old)
    require(len(old['training']) == 4080 and digest(old['training']) == inputs['manifest']['main_training_sha256'],
            'original4080 main training sources or labels changed')
    artifacts = inputs['manifest']['artifacts']
    for key in ('aux_rows', 'aux_pairs', 'aux_blocks', 'new_tuning', 'runtime_tuning'):
        require(key in inputs, 'complete admitted fitting data required: ' + key)
    for key in ('aux_rows', 'aux_pairs', 'aux_blocks', 'new_tuning'):
        require(inputs[key] == read_ref(artifacts[key]), 'pinned new fitting inventory differs: ' + key)
    prior_role = inputs['prior_role_inputs']
    for key, extra in (('aux_rows', 'ownership_rows'), ('aux_pairs', 'ownership_pairs'), ('aux_blocks', 'ownership_blocks')):
        require(inputs[key] == prior_role[key] + inputs[extra]
                and prior_role[key] == read_ref(inputs['manifest']['retained_auxiliary_refs'][key]),
                'exact admitted role auxiliary prefix or new timing extension differs')
    require(len(inputs['ownership_rows']) == 192 and len(inputs['ownership_pairs']) == 96
            and len(inputs['ownership_blocks']) == 48, 'bounded new timing augmentation inventory differs')
    blocks = auxiliary_blocks(inputs['aux_rows'], inputs['aux_pairs'], inputs['aux_blocks'])
    legacy.verify_pairs(inputs['new_tuning'], inputs['tuning_pairs'])
    require(len(inputs['new_tuning']) == 192 and len(inputs['tuning_pairs']) == 96,
            'new192 tuning clauses and96 same-meaning pairs required')
    main_records, auxiliary = mixed._splits(old['training'], inputs['aux_rows'])
    _, tuning = mixed._splits(old['training'], inputs['runtime_tuning'])
    require(len(main_records) == 4080 and len(auxiliary) == 768
            and all(row['domain'] == 'new' and row['trigger_supervised'] is True for row in inputs['aux_rows']),
            'separate authored auxiliary coordinates or main inventory changed')
    main_texts = {row['source_text'] for row in old['training']}
    aux_texts = {row['source_text'] for row in inputs['aux_rows']}
    tuning_texts = {row['source_text'] for row in inputs['runtime_tuning']}
    require(len(main_texts) == 4080 and len(aux_texts) == 768 and len(tuning_texts) == len(tuning)
            and not main_texts & aux_texts and not (main_texts | aux_texts) & tuning_texts,
            'main/auxiliary/tuning source isolation differs')
    masks = Counter(tuple(bool(row['canonical_ir']['rules'][0][field]) for field in OPTIONAL)
                    for row in inputs['aux_rows'])
    modalities = Counter(row['canonical_ir']['rules'][0]['modality'] for row in inputs['aux_rows'])
    require(len(masks) == 8 and set(masks.values()) == {96} and modalities == {'O': 256, 'P': 256, 'F': 256},
            'full optional-mask and modality TRAIN balance differs')
    oracle_audits = {}
    for panel in GATE_DOCUMENT_PANELS:
        records = inputs['oracle_boundaries'][panel]
        require(all(row['status'] == 'planned' and row['supplied_boundary_policy'] ==
            'author_supplied_supported_eligibility_and_exact_occurrence_intervals' for row in records),
            'oracle boundaries must explicitly declare segmentation assistance')
        plans = {row['candidate_id']: row['source_plan'] for row in records}
        oracle_audits[panel] = verify_oracle_sources(inputs['oracle_sources'][panel],
            inputs['oracle_occurrences'][panel], inputs['oracle_document_sources'][panel], plans)
    return {'inherited': inherited, 'main_training_rows': 4080, 'separate_auxiliary_rows': 768,
            'auxiliary_pairs': 384, 'auxiliary_blocks': 192, 'runtime_tuning_unique_sources': len(tuning),
            'new_tuning_rows': 192, 'auxiliary_optional_mask_counts': {''.join('1' if v else '0' for v in key): count
                for key, count in sorted(masks.items())}, 'oracle_admitted_inputs': oracle_audits,
            'fresh_oracle_inputs_used_for_fit': False, 'real_source_supervision_rows': 0}, {
                'auxiliary_records': {row['id']: row for row in auxiliary}, 'block_rows': blocks}


def oracle_document_score(generation, sources, targets, *, selection=None, batches=None):
    """No boundary/scope accuracy is inferred from supplied oracle intervals."""
    require(generation['supplied_oracle_segmentation'] is True and all(row['supported'] for row in targets),
            'oracle document scoring requires explicitly supplied supported scope')
    for row in generation['rows']:
        require(row['segmentation_learned'] is False and row['supplied_oracle_segmentation'] is True,
                'oracle rows cannot claim learned segmentation')
        require(row['clause_generation'] is not None, 'oracle supplied document lost all occurrence predictions')
    measured = retained.score_documents(generation, sources, targets)
    normalized = [{'id': row['id'], 'supported': row['supported'], 'joint_exact': row['exact'],
                   'composed': row['composed'], 'canonical_exact': row['canonical_rule_list_exact'],
                   'occurrence_exact': row['occurrence_boundaries_exact']} for row in measured['rows']]
    result = {'metrics': document_metrics(normalized), 'rows': normalized,
              'supplied_oracle_segmentation': True, 'learned_scope_or_boundary_accuracy_claimed': False}
    if selection is None:
        require(batches is None, 'oracle build batches require a corresponding source-only selection')
        result['native_build_not_executed_on_this_panel'] = True
        return result
    chosen = [row['candidate']['candidate_id'] for row in selection['rows']]
    excluded = [row['candidate_id'] for row in selection['excluded']]
    identities = {row['candidate_id'] for row in sources}
    require(len(chosen) == len(set(chosen)) and len(excluded) == len(set(excluded))
            and not set(chosen) & set(excluded) and set(chosen) | set(excluded) == identities
            and len(chosen) + len(excluded) == len(sources) == selection['source_count'],
            'oracle build selection dropped or duplicated source outcomes')
    require([identity for batch in batches for identity in batch['candidate_ids']] == chosen,
            'oracle native batches differ from complete source-only selection')
    built = {identity for batch in batches if batch['build_passed'] for identity in batch['candidate_ids']}
    exact = set(result['metrics']['joint_exact_ids'])
    generated = {row['candidate_id']: row for row in generation['rows']}
    statuses = Counter()
    for row in normalized:
        identity = row['id']
        if generated[identity]['composition'] is None: stage = 'clause_decode_or_composition_abstained'
        elif identity not in chosen: stage = 'lowering_unsupported'
        elif identity not in built: stage = 'native_build_failed'
        elif identity in exact: stage = 'built_joint_exact'
        else: stage = 'built_reference_mismatch'
        row['terminal_stage'] = stage
        statuses[stage] += 1
    require(sum(statuses.values()) == len(sources), 'oracle build funnel lost a supported document')
    result.update(terminal_stages=dict(statuses), builds={'count': len(sources), 'supported_for_lowering': len(chosen),
        'built': len(built), 'built_exact': len(built & exact), 'built_reference_mismatch': len(built - exact),
        'build_invocations': len(batches), 'actual_lake_build_invocations': sum(batch['backend_executed'] for batch in batches)})
    return result


def source_rows(rows):
    return [{'id': row['id'], 'source_text': row['source_text'],
             'source_sha256': boundary.text_sha(row['source_text'])} for row in rows]


def score_document_gate(generation, sources, targets):
    measured = retained.score_documents(generation, sources, targets)
    rows = [{**row, 'joint_exact': row['exact']} for row in measured['rows']]
    return document_metrics(rows)


def tuning_audit(fields, model, inputs, frozen, label):
    historical_freeze = {'boundaries': {'parent': frozen['legacy_boundaries']['parent'],
                                      'expanded-1730': frozen['legacy_boundaries']['expanded']}}
    jobs, _ = legacy.tuning_audit(fields, model, inputs['legacy'], historical_freeze, label + '/legacy')
    for name, targets in (('new_single', inputs['new_tuning']), ('prior_condition', inputs['prior_condition_targets'])):
        sources = source_rows(targets); payload = read_ref(fields[name])
        metric = clause_metrics(payload['generation'], sources, targets)['metrics']
        require(payload['metrics'] == fields[name + '_metrics'] == metric,
                'independent extended single tuning metrics differ: ' + name)
        jobs.append({'kind': 'single', 'name': label + '/' + name, 'model': model,
                     'sources': sources, 'generation': fields[name], 'stage': True})
    require(set(fields['role_retention_metrics']) == {'tuning', 'fresh'}
            and set(fields['role_oracle_metrics']) == set(ROLE_PANELS), 'both role retention panels required')
    for panel in ('tuning', 'fresh'):
        name = 'role_retention_' + panel; targets = inputs['role_retention_targets'][panel]
        sources = source_rows(targets); payload = read_ref(fields[name])
        metric = clause_metrics(payload['generation'], sources, targets)['metrics']
        require(payload['metrics'] == fields['role_retention_metrics'][panel] == metric, 'prior role single metric changed')
        jobs.append({'kind': 'single', 'name': label + '/' + name, 'model': model,
                     'sources': sources, 'generation': fields[name], 'stage': True})
    require(set(fields['old_atom_oracle_metrics']) == set(ATOM_PANELS)
            and set(fields['oracle_document_metrics']) == set(GATE_DOCUMENT_PANELS)
            and set(fields['fixed_document_metrics']) == set(GATE_DOCUMENT_PANELS),
            'complete extended stage panel inventory required')
    for panel in GATE_DOCUMENT_PANELS:
        targets = inputs['oracle_targets'][panel]
        sources = source_rows(inputs['oracle_sources'][panel])
        key = 'oracle_clauses_' + panel; payload = read_ref(fields[key])
        metric = clause_metrics(payload['generation'], sources, targets)['metrics']
        require(payload['metrics'] == metric, 'independent oracle occurrence metric differs: ' + panel)
        if panel in ATOM_PANELS:
            require(fields['old_atom_oracle_metrics'][panel] == metric, 'old atom oracle gate metric differs')
        if panel in ROLE_PANELS:
            require(fields['role_oracle_metrics'][panel] == metric, 'prior role oracle gate metric differs')
        jobs.append({'kind': 'single', 'name': label + '/' + key, 'model': model,
                     'sources': sources, 'generation': fields[key], 'stage': True, 'supplied_oracle_segmentation': True})
        key = 'oracle_documents_' + panel; payload = read_ref(fields[key])
        targets = [row for row in inputs['modern_document_targets'][panel] if row['supported']]
        sources = inputs['oracle_document_sources'][panel]
        metric = oracle_document_score(payload['generation'], sources, targets)['metrics']
        require(payload['metrics'] == fields['oracle_document_metrics'][panel] == metric,
                'independent oracle whole-document gate metric differs: ' + panel)
        jobs.append({'kind': 'oracle', 'name': label + '/' + key, 'model': model,
                     'sources': sources, 'generation': fields[key], 'stage': True,
                     'authored_plans': inputs['oracle_boundaries'][panel]})
        require(set(fields['fixed_document_metrics'][panel]) == set(PRIMARY_BOUNDARIES),
                'both original and fixed diagnostic boundary gates required')
        for policy in PRIMARY_BOUNDARIES:
            key = 'fixed_documents_' + panel + '_' + policy; payload = read_ref(fields[key])
            sources = inputs['modern_document_sources'][panel]
            metric = score_document_gate(payload['generation'], sources, inputs['modern_document_targets'][panel])
            require(payload['metrics'] == fields['fixed_document_metrics'][panel][policy] == metric,
                    'independent fixed-boundary whole-document gate metric differs')
            jobs.append({'kind': 'document', 'name': label + '/' + key, 'model': model,
                         'sources': sources, 'generation': fields[key], 'stage': True,
                         'boundary': frozen['boundaries'][policy][panel]})
    return jobs


def regenerate_oracle_documents(decoder, plans, sources):
    require(len(plans) == len(sources) and all(row['status'] == 'planned' and row['source_plan'] is not None for row in plans),
            'complete supplied supported source plans required')
    supplied = {'rows': [{'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'],
                         'status': 'planned', 'plan': row['source_plan'], 'reason': None} for row in plans]}
    rows = clauses.integrate(supplied, sources, decoder)
    for row in rows:
        row['segmentation_learned'] = False
        row['supplied_oracle_segmentation'] = True
    return {'rows': rows, 'target_access': False, 'references_supplied': True, 'training_executed': False,
            'target_access_scope': 'canonical_semantics_only',
            'segmentation_learned': False, 'supplied_oracle_segmentation': True, 'supplied_supported_eligibility': True,
            'semantic_targets_supplied': False,
            'assistance': 'Exact clause intervals and supported eligibility supplied by authored reference; semantic labels withheld.'}


def replay_with_decoder(job, decoder):
    if job['kind'] != 'oracle':
        return {**legacy.replay_with_decoder(job, decoder), 'initial_parity': job.get('initial_parity', False)}
    expected = read_ref(job['generation'])
    if job.get('stage'):
        expected = expected['generation']
    actual = regenerate_oracle_documents(decoder, job['authored_plans'], job['sources'])
    require(actual == expected, 'independent full oracle numerical output replay differs: ' + job['name'])
    copied = occurrences = 0
    plans = {row['candidate_id']: row['source_plan'] for row in job['authored_plans']}
    for row in actual['rows']:
        plan = plans[row['candidate_id']]
        retained.compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
        require(len(row['clause_generation']['rows']) == plan['clause_count'], 'oracle replay lost a clause occurrence')
        for source, prediction in zip(plan['clauses'], row['clause_generation']['rows'], strict=True):
            copied += retained.prior.source_audit.assert_source_copy(prediction, source)
            occurrences += 1
        if row['composition'] is not None:
            require(row['composition']['source_plan'] == plan, 'oracle composition changed supplied intervals')
            retained.compose.validate_composition(row['composition'], expected_plan_sha256=plan['plan_sha256'])
    return {'kind': 'oracle', 'name': job['name'], 'rows': len(job['sources']), 'generation': job['generation'],
            'checkpoint': job['model']['checkpoint'], 'source_inputs_sha256': digest(job['sources']),
            'supplied_plans_sha256': digest(job['authored_plans']), 'recorded_generation_sha256': digest(actual),
            'exact_recorded_payload_replay': True, 'clause_occurrences_replayed': occurrences,
            'copied_facets_verified': copied, 'stage_tuning': job.get('stage', False),
            'training_diagnostic': False, 'recomputed_for_this_saved_panel': True,
            'semantic_target_access': False, 'supplied_oracle_segmentation': True}


def replay_group(group):
    import torch
    from scripts.ops.legal_ir import run_legal_timing_ownership_experiment as runner
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as atom
    torch.set_num_threads(1)
    if group['decoder_kind'] == 'boundary':
        decoder = atom.decoder(read_ref(group['checkpoint']))
    else:
        decoder = runner.load_decoder(group['checkpoint'], group['decoder_kind'])
    results = []
    for job in group['jobs']:
        checkpoint = job['checkpoint'] if job['kind'] == 'boundary' else job['model']['checkpoint']
        require(checkpoint['sha256'] == group['checkpoint']['sha256'], 'checkpoint replay group changed model identity')
        read_ref(checkpoint, parse=False)
        results.append(replay_with_decoder(job, decoder))
        print({'phase': 'replayed', 'name': job['name'], 'rows': len(job['sources'])}, flush=True)
    return results


def verify_training(inputs, frozen, selection, fitting_data):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_timing_ownership as runtime
    require(selection['executed_optimizer_updates'] == 800
            and selection['fresh_targets_opened'] is selection['fresh_oracle_inputs_opened'] is False,
            'complete training and selection freeze before oracle input release required')
    models = {row['name']: row for row in frozen['models']}
    trials = selection['trials']; old = inputs['legacy']
    require(len(trials) == 4 and {(row['objective'], row['architecture'], row['seed']) for row in trials}
            == {(objective, architecture, 1730) for objective in OBJECTIVES for architecture in ARCHITECTURES},
            'four complete matched trials required')
    parents = read_ref(selection['parent_tuning'])
    require(set(parents) == set(ARCHITECTURES) and frozen['parent_tuning'] == selection['parent_tuning'],
            'both exact parent reference evaluations required')
    jobs, caches, audits, traces = [], {}, [], []
    for architecture in ARCHITECTURES:
        name = 'parent_' + architecture + '-1730'; model = models[name]
        parent_item = old['parents'][(architecture, 1730)]
        require(model['checkpoint'] == model['parent'] == parent_item['checkpoint']
                and model['decoder_kind'] == parent_item['decoder_kind'] and model['selected_steps'] == 0
                and model['objective'] == 'parent' and model['selection'] == 'unchanged_parent',
                'immutable no-update parent slot differs')
        jobs += tuning_audit(parents[architecture], model, inputs, frozen, 'parent/' + architecture)
        caches[architecture] = legacy.prior.teacher_cache(read_ref(parent_item['checkpoint']), old)
    for trial in trials:
        architecture, objective, name = (trial[key] for key in ('architecture', 'objective', 'name'))
        parent_item = old['parents'][(architecture, 1730)]; parent_pin = parent_item['checkpoint']
        kind = parent_item['decoder_kind']; parent = read_ref(parent_pin)
        require(trial == models[name] and name == objective + '_' + architecture + '-1730'
                and trial['parent'] == parent_pin and trial['parent_kind'] == kind
                and trial['enabled'] is (architecture == 'grounding') and trial['executed_steps'] == 200
                and trial['parent_tuning'] == parents[architecture] and trial['fresh_targets_opened'] is False
                and trial['historical_optimizer_resumed'] is False
                and trial['trial_wall_limit_seconds'] == 1800 and 0 < trial['trial_wall_seconds'] <= 1800,
                'matched trial identity, exact parent, budget or target access differs')
        require({key: value for key, value in trial.items() if key != 'selection_record'} == read_ref(trial['selection_record']),
                'saved selection record changed')
        initial = runtime.load_checkpoint(trial['initial_checkpoint']['path'], expected_sha256=trial['initial_checkpoint']['sha256'])
        rebuilt = runtime.build_checkpoint(parent, old['training'], inputs['runtime_tuning'], old['runtime_pairs'],
            inputs['aux_rows'], inputs['aux_pairs'], inputs['aux_blocks'], parent_kind=kind, objective=objective, seed=1730)
        require(initial == rebuilt and initial['model_state'] == parent['model_state']
                and initial['optimizer_state'] == {'schema': 'adam-default-betas-eps/v1', 'parameters': {}}
                and initial['progress']['optimizer_steps'] == 0, 'exact full initialization or fresh Adam differs')
        init = read_ref(trial['initialization'])
        require(init['parent'] == parent_pin and init['parent_kind'] == kind and init['initial'] == trial['initial_checkpoint']
                and init['initial_model_state_sha256'] == init['parent_model_state_sha256'] == digest(parent['model_state'])
                and init['all_initial_tensors_equal'] is init['optimizer_reset'] is init['all_parity_numerical_predictions_equal'] is True
                and init['historical_optimizer_resumed'] is init['full_legacy_initial_replay_performed'] is False
                and init['parity_panel'] == 'new_single' and init['parity_count'] == 192,
                'initialization parity scope or lineage differs')
        require(init['generation']['rows'] == read_ref(parents[architecture]['new_single'])['generation']['rows'],
                'initial numerical clause predictions/logits changed from parent')
        jobs.append({'kind': 'single', 'name': name + '/initial-new192',
            'model': {**trial, 'checkpoint': trial['initial_checkpoint'], 'decoder_kind': 'timing_ownership'},
            'sources': source_rows(inputs['new_tuning']), 'generation': trial['initialization'], 'stage': True,
            'initial_parity': True})
        require([row['steps'] for row in trial['stages']] == list(STAGES), 'both declared candidate stages required')
        preceding, exposures, stage_audits = initial, [], []
        for stage in trial['stages']:
            checkpoint = runtime.load_checkpoint(stage['checkpoint']['path'], expected_sha256=stage['checkpoint']['sha256'])
            require(stage['previous_checkpoint_sha256'] == checkpoint['parent_checkpoint_sha256'] == digest(preceding)
                    and checkpoint['progress']['optimizer_steps'] == stage['steps'], 'staged checkpoint resume chain differs')
            require(set(checkpoint) == set(initial), 'checkpoint field inventory changed')
            for key in set(initial) - {'model_state', 'optimizer_state', 'progress', 'parent_checkpoint_sha256'}:
                require(checkpoint[key] == initial[key], 'frozen checkpoint lineage/configuration changed: ' + key)
            report = read_ref(stage['training_report'])
            audit = verify_training_report(report, preceding, checkpoint,
                {**old, 'aux_blocks': inputs['aux_blocks']}, caches[architecture],
                fitting_data['auxiliary_records'], fitting_data['block_rows'])
            exposures += report['batch_exposures']
            stage_model = {**trial, 'checkpoint': stage['checkpoint'], 'decoder_kind': 'timing_ownership'}
            jobs += tuning_audit(stage, stage_model, inputs, frozen, name + '/stage-' + str(stage['steps']))
            admissible = eligible(stage, parents[architecture])
            require(stage['eligible'] is admissible, 'independent full inherited/new retention decision differs')
            stage_audits.append({**audit, 'checkpoint': stage['checkpoint'], 'training_report': stage['training_report'],
                'eligible': admissible, 'ranking': list(ranking(stage)), 'gate_failures_reported': stage['failures']})
            preceding = checkpoint
        chosen = select_stage(trial['stages'], parents[architecture])
        selected_pin = chosen['checkpoint'] if chosen else parent_pin
        selected_steps = chosen['steps'] if chosen else 0
        status = 'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'
        require(trial['checkpoint'] == selected_pin and trial['selected_steps'] == selected_steps
                and trial['selection'] == status and trial['decoder_kind'] == ('timing_ownership' if chosen else kind),
                'independent selected stage or explicit fallback differs')
        chosen_fields = chosen or parents[architecture]
        require(read_ref(frozen['files'][name]['prior_role_fresh']) == read_ref(chosen_fields['role_retention_fresh'])['generation'],
                'selected prior role source predictions changed from selection')
        panel = 'role_fresh'
        require(read_ref(frozen['files'][name]['oracle_' + panel]) == read_ref(chosen_fields['oracle_clauses_' + panel])['generation']
                and read_ref(frozen['oracle_files'][name][panel]) == read_ref(chosen_fields['oracle_documents_' + panel])['generation'],
                'selected supplied-oracle predictions changed from selection')
        for policy in PRIMARY_BOUNDARIES:
            pipeline = name + '__boundary_' + policy
            require(read_ref(frozen['document_files'][pipeline][panel]) == read_ref(chosen_fields['fixed_documents_' + panel + '_' + policy])['generation'],
                    'selected prior role document predictions changed from selection')
        pools = legacy.prior.training_pools(old)
        trace = {'name': name, 'architecture': architecture, 'objective': objective, 'parent': parent_pin,
            'updates': len(exposures), 'batch_exposures_sha256': digest(exposures),
            'main_draws': sum(len(row['ids']) for row in exposures),
            'auxiliary_draws': sum(len(row['auxiliary_ids']) for row in exposures),
            'unique_main_ids': len({identity for row in exposures for identity in row['ids']}),
            'unique_auxiliary_ids': len({identity for row in exposures for identity in row['auxiliary_ids']}),
            'pool_coverage': {pool: {'entries': len(values), 'draws': sum(len(row['indices_by_pool'][pool]) for row in exposures),
                'unique_entries': len({index for row in exposures for index in row['indices_by_pool'][pool]})} for pool, values in pools.items()}}
        traces.append(trace)
        audits.append({'name': name, 'architecture': architecture, 'objective': objective, 'parent': parent_pin,
            'stages': stage_audits, 'selection': status, 'selected_steps': selected_steps,
            'checkpoint': selected_pin, 'executed_optimizer_updates': 200, 'optimizer_trajectory_replayed': False})
    require(traces == selection['trial_update_audit'] and len({row['batch_exposures_sha256'] for row in traces}) == 1,
            'all four complete main/auxiliary schedules must be identical')
    for architecture in ARCHITECTURES:
        candidates = [(trial, stage) for trial in trials if trial['architecture'] == architecture
                      for stage in trial['stages'] if eligible(stage, parents[architecture])]
        chosen = max(candidates, key=lambda pair: (*ranking(pair[1]), -OBJECTIVES.index(pair[0]['objective']))) if candidates else None
        expected = {'model': chosen[0]['name'] if chosen else 'parent_' + architecture + '-1730',
                    'steps': chosen[1]['steps'] if chosen else 0,
                    'selection': 'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'}
        require(selection['primary_choices'][architecture] == frozen['primary_choices'][architecture] == expected,
                'pre-reference primary clause choice differs from frozen ranking/common tie break')
    return jobs, {'trials': audits, 'matched_schedule_audit': traces, 'total_optimizer_updates': 800,
        'independent_teacher_source_evaluations': 7776,
        'teacher_exact_batch_recheck_source_evaluations': sum(12*len(cache.batch_counts) for cache in caches.values()),
        'additional_initial_parity_source_evaluations': 768, 'optimizer_trajectory_replayed': False,
        'legacy_retention_tolerances_unchanged': True}


def verify_protocol(plan, inputs, frozen):
    expected = {'schema': 'legal-timing-ownership-experiment/v1', 'objectives': list(OBJECTIVES),
        'architectures': list(ARCHITECTURES), 'seed': 1730, 'stages': [100, 200],
        'total_optimizer_updates': 800, 'updates_per_trial': 200, 'main_training_rows': 4080,
        'auxiliary_rows': 768, 'main_batch_size': 12, 'auxiliary_batch_size': 4,
        'main_inventory_cap_unchanged': 4096, 'auxiliary_inventory_cap': 1024,
        'common_auxiliary_standard_ce_weight': .25, 'ownership_weight': {'common': 0., 'ownership': .25},
        'optimizer': 'fresh_Adam', 'learning_rate': .00025, 'trial_wall_limit_seconds': 1800,
        'trial_budget_includes_initialization_and_stage_evaluation': True,
        'fixed_boundary_heads': inputs['fixed_heads'], 'boundary_training': False, 'joint_stage_search': False,
        'initial_parity_rows': 768, 'postselection_training_diagnostic_rows': 29088,
        'native_fresh_logical_slots': 40, 'oracle_supported_eligibility_and_exact_boundaries_supplied': True,
        'oracle_rejection_metric_claimed': False, 'inference_changed': False, 'latent_dimension': 0,
        'fresh_targets_opened': False}
    require(all(type(plan[key]) is type(value) and plan[key] == value for key, value in expected.items()),
            'prospective timing ownership protocol differs from approved contract')
    require(frozen['schema'] == expected['schema'] and frozen['executed_optimizer_updates'] == 800
            and frozen['all_training_selection_and_generation_complete'] is True
            and frozen['fresh_targets_opened'] is False and frozen['fresh_oracle_inputs_opened_after_selection'] is True,
            'complete staged semantic-target-blind generation freeze required')
    require(plan['config'] == frozen['config'] and plan['study_design'] == inputs['config']['study_design'],
            'prospective fitting design reference changed')
    for path, expected_sha in plan['producer_pins'].items():
        require(sha(path) == expected_sha, 'frozen fitting producer drift: ' + path)
    read_ref(plan['study_design'], parse=False)
    read_ref(plan['config'], parse=False)


def verify_inventory(inputs, frozen):
    old = inputs['legacy']
    sources = read_ref(frozen['sources']); documents = read_ref(frozen['document_sources'])
    oracle_sources = read_ref(frozen['oracle_sources']); oracle_documents = read_ref(frozen['oracle_document_sources'])
    oracle_plans = read_ref(frozen['oracle_boundaries']); occurrences = read_ref(frozen['oracle_occurrences'])
    training_sources = read_ref(frozen['training_sources'])
    source_panels = {'fresh', 'prior_role_fresh', 'real_exposed', 'oracle_fresh', 'oracle_role_fresh'}
    doc_panels = {'fresh', 'role_fresh'}
    require(set(sources) == source_panels and set(documents) == set(oracle_sources) == set(oracle_documents)
            == set(oracle_plans) == set(occurrences) == doc_panels, 'bounded source/occurrence inventories required')
    require(sources['prior_role_fresh'] == source_rows(inputs['role_retention_targets']['fresh'])
            and sources['fresh'] == source_rows(inputs['fresh_sources'])
            and sources['real_exposed'] == old['sources']['real_exposed'], 'standalone source panel changed')
    panel = 'role_fresh'
    require(documents[panel] == inputs['modern_document_sources'][panel]
            and oracle_sources[panel] == source_rows(inputs['oracle_sources'][panel])
            and oracle_documents[panel] == inputs['oracle_document_sources'][panel]
            and oracle_plans[panel] == inputs['oracle_boundaries'][panel]
            and occurrences[panel] == inputs['oracle_occurrences'][panel], 'admitted role document/oracle panel changed')
    require(documents['fresh'] == inputs['fresh_document_sources'] and len(documents['fresh']) == 96
            and len(oracle_documents['fresh']) == 48 and len(oracle_sources['fresh']) == 120,
            'full fresh and supported-only oracle denominators differ')
    oracle_audits = {}
    for panel in doc_panels:
        require(sources['oracle_' + panel] == oracle_sources[panel], 'oracle single/source map differs')
        require(len(oracle_plans[panel]) == len(oracle_documents[panel])
                and all(row['status'] == 'planned' for row in oracle_plans[panel]), 'oracle supported plans dropped a document')
        oracle_audits[panel] = verify_oracle_sources(oracle_sources[panel], occurrences[panel], oracle_documents[panel],
            {row['candidate_id']: row['source_plan'] for row in oracle_plans[panel]})
    require(training_sources == {'main': source_rows(old['training']), 'auxiliary': source_rows(inputs['aux_rows'])},
            'full postselection TRAIN diagnostic source population changed')
    base_names = {objective + '_' + architecture + '-1730' for objective in OBJECTIVES for architecture in ARCHITECTURES}
    parent_names = {'parent_' + architecture + '-1730' for architecture in ARCHITECTURES}
    final_names = {name + '_final200' for name in base_names}
    names = base_names | parent_names | final_names
    models = {row['name']: row for row in frozen['models']}
    require(len(models) == len(frozen['models']) == 10 and set(models) == names
            and read_ref(frozen['heads']) == frozen['models'] and set(frozen['files']) == set(frozen['oracle_files']) == names,
            'all ten selected, fallback, parent and final diagnostic slots required')
    for name in names:
        require(set(frozen['files'][name]) == source_panels and set(frozen['oracle_files'][name]) == doc_panels,
                'selected or diagnostic slot omitted source panels')
    for name in final_names:
        model = models[name]; trial = models[name[:-9]]
        require(model['selection'] == 'unselected_final200_diagnostic' and model['selected_steps'] == model['executed_steps'] == 200
                and model['checkpoint'] == trial['stages'][-1]['checkpoint'] and model['decoder_kind'] == 'timing_ownership'
                and model['challenge_diagnostics_used_for_selection'] is False,
                'predeclared final200 diagnostic identity or selection status changed')
    require(set(frozen['training_files']) == parent_names | final_names
            and all(set(panels) == {'main', 'auxiliary'} for panels in frozen['training_files'].values()),
            'all six full TRAIN diagnostic inventories required')
    pipeline_names = {name + '__boundary_' + policy for name in names for policy in PRIMARY_BOUNDARIES}
    require(len(frozen['pipelines']) == 20 and {row['name'] for row in frozen['pipelines']} == pipeline_names
            and set(frozen['document_files']) == pipeline_names
            and all(set(panels) == doc_panels for panels in frozen['document_files'].values()),
            'all twenty fixed-factor predicted pipelines required')
    for pipeline in frozen['pipelines']:
        model = models[pipeline['source_model_name']]; policy = pipeline['boundary_policy']
        require(policy in PRIMARY_BOUNDARIES and pipeline['name'] == model['name'] + '__boundary_' + policy
                and pipeline['boundary_checkpoint'] == inputs['fixed_heads'][policy]
                and all(pipeline[key] == model[key] for key in ('architecture', 'objective', 'selection', 'selected_steps', 'checkpoint', 'decoder_kind')),
                'pipeline changed fixed clause model or boundary factor')
    require(set(frozen['boundaries']) == set(PRIMARY_BOUNDARIES)
            and all(set(panels) == {*GATE_DOCUMENT_PANELS, 'fresh'} for panels in frozen['boundaries'].values())
            and set(frozen['legacy_boundaries']) == {'parent', 'expanded'}
            and all(set(panels) == set(legacy.DOCUMENT_TUNING) for panels in frozen['legacy_boundaries'].values()),
            'fixed boundary source inventory differs')
    return {'sources': sources, 'documents': documents, 'oracle_sources': oracle_sources,
            'oracle_documents': oracle_documents, 'oracle_plans': oracle_plans, 'occurrences': occurrences,
            'training_sources': training_sources, 'boundary_documents': {**inputs['modern_document_sources'], 'fresh': documents['fresh']}}, {
        'single_model_slots': 10, 'predicted_pipeline_slots': 20, 'oracle_pipeline_slots': 10,
        'predeclared_final200_diagnostic_slots': 4,
        'selected_single_rows': 10*sum(map(len, sources.values())),
        'selected_predicted_document_rows': 20*sum(map(len, documents.values())),
        'selected_oracle_document_rows': 10*sum(map(len, oracle_documents.values())),
        'postselection_training_diagnostic_rows': 6*sum(map(len, training_sources.values())),
        'oracle_supplied_source_audits': oracle_audits}


def verify_generation_aliases(frozen, data):
    receipt = read_ref(frozen['generation_aliases'])
    models = {model['name']: model for model in frozen['models']}
    require(receipt['schema'] == 'legal-timing-ownership-generation-aliases/v1'
            and receipt['logical_models'] == len(models) == 10 and receipt['all_logical_slots_retained'] is True
            and set(receipt['logical_job_mapping']) == set(models), 'all logical generation slots require alias provenance')
    groups = {}
    for model in models.values():
        groups.setdefault((model['decoder_kind'], model['checkpoint']['sha256']), []).append(model)
    descriptor = {'single_sources_sha256': digest(data['sources']), 'document_sources_sha256': digest(data['documents']),
        'oracle_document_sources_sha256': digest(data['oracle_documents']), 'oracle_plans_sha256': digest(data['oracle_plans']),
        'fixed_boundaries_sha256': digest({policy: {panel: read_ref(frozen['boundaries'][policy][panel])
            for panel in data['documents']} for policy in PRIMARY_BOUNDARIES}),
        'training_sources_sha256': digest(data['training_sources'])}
    require(receipt['numerically_executed_models'] == len(groups), 'generation executed-model denominator changed')
    for values in groups.values():
        representative = min(values, key=lambda m: (0 if m['objective']=='parent' else 1 if m['name'].endswith('_final200') else 2, m['name']))
        origin = representative['name']
        for model in values:
            name = model['name']
            expected = {'executed_model': origin, 'decoder_kind': model['decoder_kind'],
                'checkpoint_sha256': model['checkpoint']['sha256'], **descriptor,
                'training_logical_slot': model['objective']=='parent' or name.endswith('_final200')}
            require(receipt['logical_job_mapping'][name] == expected, 'generation alias changed exact model/source closure')
            require(frozen['files'][name] == frozen['files'][origin] and frozen['oracle_files'][name] == frozen['oracle_files'][origin],
                    'generation alias must share exact immutable output references')
            for policy in PRIMARY_BOUNDARIES:
                require(frozen['document_files'][name+'__boundary_'+policy] == frozen['document_files'][origin+'__boundary_'+policy],
                        'pipeline alias output references differ')
            if expected['training_logical_slot']:
                require(frozen['training_files'][name] == frozen['training_files'][origin], 'training alias references differ')
    return {'logical_models': 10, 'executed_models': len(groups), 'generation_aliases': frozen['generation_aliases'],
            'all_model_source_and_payload_reference_aliases_verified': True}


def selected_replay_jobs(inputs, frozen, data):
    jobs = []
    models = {row['name']: row for row in frozen['models']}
    for name, model in models.items():
        for panel, pin in frozen['files'][name].items():
            jobs.append({'kind': 'single', 'name': name + '/selected/' + panel,
                'model': model, 'sources': data['sources'][panel], 'generation': pin})
        for panel, pin in frozen['oracle_files'][name].items():
            jobs.append({'kind': 'oracle', 'name': name + '/oracle/' + panel,
                'model': model, 'sources': data['oracle_documents'][panel], 'generation': pin,
                'authored_plans': data['oracle_plans'][panel]})
        for panel, pin in frozen['training_files'].get(name, {}).items():
            jobs.append({'kind': 'single', 'name': name + '/full-training/' + panel,
                'model': model, 'sources': data['training_sources'][panel], 'generation': pin, 'training_diagnostic': True})
    for pipeline in frozen['pipelines']:
        for panel, pin in frozen['document_files'][pipeline['name']].items():
            jobs.append({'kind': 'document', 'name': pipeline['name'] + '/' + panel,
                'model': models[pipeline['source_model_name']], 'sources': data['documents'][panel],
                'generation': pin, 'boundary': frozen['boundaries'][pipeline['boundary_policy']][panel]})
    for policy in PRIMARY_BOUNDARIES:
        for panel, pin in frozen['boundaries'][policy].items():
            jobs.append({'kind': 'boundary', 'name': 'fixed-boundary/' + policy + '/' + panel,
                'checkpoint': inputs['fixed_heads'][policy], 'sources': data['boundary_documents'][panel], 'generation': pin})
    for policy, old_name in (('parent', 'parent'), ('expanded', 'expanded-1730')):
        checkpoint = inputs['legacy']['boundary_heads'][old_name]['checkpoint']
        for panel, pin in frozen['legacy_boundaries'][policy].items():
            jobs.append({'kind': 'boundary', 'name': 'legacy-boundary/' + policy + '/' + panel,
                'checkpoint': checkpoint, 'sources': inputs['legacy']['document_sources'][panel], 'generation': pin})
    return jobs


def historical_annotation_inputs(inputs):
    from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as old_corpus
    _, pools, excluded, _, _, _ = old_corpus.historical_inputs(old_corpus.DEFAULT_PRIOR)
    pools = dict(pools); excluded = set(excluded); old = inputs['legacy']; prior_role = inputs['prior_role_inputs']
    pools.update(main_training=old['training'],
        **{'legacy_tuning_' + key: rows for key, rows in old['tuning'].items()},
        **{'legacy_retention_' + key: rows for key, rows in old['retention_targets'].items()},
        prior_condition=inputs['prior_condition_targets'],
        **{'oracle_' + key: inputs['oracle_targets'][key] for key in (*ATOM_PANELS, 'prior_condition')})
    atom_manifest = read_ref(prior_role['manifest']['inputs']['prior_atom_corpus'])
    for name, pin in atom_manifest['retention_target_references'].items():
        rows = read_ref(pin)
        excluded.update(row['source_text'] for row in rows)
        pools['old_document_' + name] = retained.document_audit_clauses(rows)
    for panel in (old['sources'], old['document_sources']):
        for rows in panel.values():
            excluded.update(row['source_text'] for row in rows)
    for key in (*ATOM_PANELS, 'prior_condition'):
        excluded.update(row['source_text'] for row in inputs['modern_document_targets'][key])
    pools.update(prior_role_train=prior_role['aux_rows'], prior_role_tuning=inputs['role_retention_targets']['tuning'],
                 prior_role_fresh=inputs['role_retention_targets']['fresh'],
                 prior_role_document_tuning=inputs['oracle_targets']['role_tuning'],
                 prior_role_document_fresh=inputs['oracle_targets']['role_fresh'])
    for rows in inputs['role_documents'].values(): excluded.update(row['source_text'] for row in rows)
    for rows in pools.values():
        excluded.update(row['source_text'] for row in rows)
    return {'historical_layout_pools': pools, 'historical_source_inventory': sorted(excluded)}


def init_worker(sealed):
    global _worker_guard
    _worker_guard = legacy.SealedReadGuard(sealed)
    sys.addaudithook(_worker_guard.event)


def score_predicted_documents(generation, sources, targets, boundary_scores, *, selection=None, batches=None):
    if selection is not None:
        return legacy.boundary_qualification.pipeline_funnel(generation, boundary_scores, sources, targets, selection, batches)
    metric = retained.score_documents(generation, sources, targets)
    truth = {row['candidate_id']: row for row in targets}
    boundary_rows = {row['id']: row for row in boundary_scores['rows']}
    rows = [legacy.boundary_qualification.attribution.pipeline_record(row, truth[row['candidate_id']],
            boundary_rows[row['candidate_id']]) for row in generation['rows']]
    return {'metrics': {key: value for key, value in metric.items() if key != 'rows'}, 'rows': rows,
            'attribution': legacy.boundary_qualification.attribution.pipeline_counts(rows),
            'native_build_not_executed_on_this_panel': True}


def replay_identity(job):
    """Only byte-pinned models and identical complete inputs may share inference."""
    checkpoint = job['checkpoint'] if job['kind'] == 'boundary' else job['model']['checkpoint']
    kind = 'boundary' if job['kind'] == 'boundary' else job['model']['decoder_kind']
    context = None
    if job['kind'] == 'document':
        context = digest(read_ref(job['boundary']))
    elif job['kind'] == 'oracle':
        context = digest(job['authored_plans'])
    return (job['kind'], kind, checkpoint['sha256'], digest(job['sources']), context)


def saved_payload(job):
    value = read_ref(job['generation'])
    return value['generation'] if job.get('stage') else value


def deduplicate_replay_jobs(jobs):
    """Verify all saved payload aliases before scheduling unique inference jobs."""
    require(len({job['name'] for job in jobs}) == len(jobs), 'unique logical replay names required')
    groups, unique, aliases, payload_cache = {}, [], [], {}
    for job in jobs:
        key = replay_identity(job)
        payload_key = (digest(job['generation']), bool(job.get('stage')))
        if payload_key not in payload_cache:
            payload_cache[payload_key] = digest(saved_payload(job))
        payload_sha = payload_cache[payload_key]
        if key not in groups:
            groups[key] = (job, payload_sha)
            unique.append(job)
        representative, expected = groups[key]
        require(payload_sha == expected, 'identical checkpoint and source inputs changed saved outputs')
        aliases.append({'name': job['name'], 'executed_name': representative['name'],
            'rows': len(job['sources']), 'generation': job['generation'],
            'generation_payload_sha256': payload_sha, 'input_identity_sha256': digest(key),
            'independent_inference_executed': representative['name'] == job['name']})
    return unique, aliases


def expand_replay_aliases(jobs, actual, aliases):
    executed = {row['name']: row for row in actual}
    mapping = {row['name']: row for row in aliases}
    require(len(executed) == len(actual) and set(executed) == {a['executed_name'] for a in aliases},
            'unique execution coverage differs from alias contract')
    result = []; payload_cache = {}
    for job in jobs:
        alias = mapping[job['name']]; representative = executed[alias['executed_name']]
        payload_key = (digest(job['generation']), bool(job.get('stage')))
        if payload_key not in payload_cache: payload_cache[payload_key] = digest(saved_payload(job))
        require(payload_cache[payload_key] == alias['generation_payload_sha256'], 'saved payload changed after alias freeze')
        row = {**representative, 'name': job['name'], 'generation': job['generation'],
               'checkpoint': job['checkpoint'] if job['kind'] == 'boundary' else job['model']['checkpoint'],
               'stage_tuning': job.get('stage', False), 'training_diagnostic': job.get('training_diagnostic', False),
               'initial_parity': job.get('initial_parity', False),
               'recomputed_for_this_saved_panel': alias['independent_inference_executed'],
               'inference_alias_of': None if alias['independent_inference_executed'] else alias['executed_name'],
               'saved_payload_alias_independently_verified': True,
               'logical_clause_occurrences': representative.get('clause_occurrences_replayed', 0)}
        if job['kind'] == 'document': row['boundary'] = job['boundary']
        if not alias['independent_inference_executed']:
            row['clause_occurrences_replayed'] = 0
            row['copied_facets_verified'] = 0
        result.append(row)
    return result


def build_identity(selected, args):
    return digest({'complete_selection': selected, 'lake_executable': str(Path(args.lake_executable).resolve()),
                   'lake_sha256': sha(args.lake_executable), 'toolchain': args.toolchain,
                   'gate_policy': retained.calendar.POLICY})


def attribute_build_execution(metric, alias):
    """Keep supported/built fidelity counts while identifying reused compiler evidence."""
    result = dict(metric)
    result['bound_build_invocations'] = result.get('build_invocations', 0)
    count = alias['actual_backend_invocations_for_this_slot']
    result.update(build_evidence_executed_slot=alias['executed_slot'],
                  build_evidence_reused=alias['slot'] != alias['executed_slot'],
                  build_invocations=count, actual_lake_build_invocations=count,
                  actual_lake_build_executed=count > 0)
    return result


def run(args):
    import torch
    from scripts.ops.legal_ir import run_legal_timing_ownership_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_timing_ownership_corpus as corpus
    from scripts.ops.legal_ir import summarize_legal_timing_ownership_annotations as annotations
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_timing_ownership as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    torch.set_num_threads(1)
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three replay workers required')
    frozen_ref, config_ref = ref(args.generation), ref(args.config)
    frozen, config = read_ref(frozen_ref), read_ref(config_ref)
    require(frozen['config'] == config_ref, 'qualification config differs from fitting freeze')
    manifest = read_ref(config['corpus_manifest'])
    required_seals = {'fresh_targets', 'fresh_pairs', 'fresh_document_targets', 'fresh_document_pairs',
                      'fresh_oracle_targets', 'annotation_ledger', 'exposure_audit'}
    require(set(manifest['sealed_artifacts']) == required_seals, 'all seven current semantic/evidence seals required')
    evidence_refs = {key: manifest['artifacts'][key] for key in sorted(required_seals)}
    sealed = list(evidence_refs.values()); guard = legacy.SealedReadGuard(sealed)
    sys.addaudithook(guard.event)
    inputs = runner.load_config(args.config)
    plan = read_ref(frozen['plan']); verify_protocol(plan, inputs, frozen)
    data, inventory = verify_inventory(inputs, frozen)
    inventory['generation_alias_audit'] = verify_generation_aliases(frozen, data)
    pins = dict(plan['producer_pins'])
    modules = (sys.modules[__name__], runner, corpus, corpus.previous, annotations, annotations.previous, runtime, legacy, legacy.prior,
        legacy.prior.prior, retained, retained.prior, retained.calendar, retained.calendar_summary,
        retained.compose, legacy.boundary_qualification, legacy.boundary_qualification.attribution,
        previous, clauses, boundary, gate, corpus.temporal, corpus.construction)
    pins.update({str(Path(module.__file__).resolve()): sha(module.__file__) for module in modules})
    require(all(sha(path) == value for path, value in pins.items()), 'qualification producer drift')
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    qualification_plan = write(output / 'qualification-plan.json', {'schema': SCHEMA,
        'generation_freeze': frozen_ref, 'config': config_ref, 'producer_pins': pins,
        'sealed_semantic_references': sealed, 'fixed_boundary_heads': inputs['fixed_heads'],
        'native_fresh_single_slots': 10, 'native_fresh_oracle_document_slots': 10,
        'native_fresh_predicted_document_slots': 20, 'fresh_semantic_targets_opened': False,
        'oracle_segmentation_and_supported_eligibility_supplied': True,
        'old_fresh_atom_condition_and_role_panels_are_admitted_retention': True})
    print({'phase': 'auditing_training', 'output': str(output)}, flush=True)
    fitting, fitting_data = verify_fitting(inputs)
    jobs, training = verify_training(inputs, frozen, read_ref(frozen['selections']), fitting_data)
    training_ref = write(output / 'training-and-selection-audit.json', {'schema': SCHEMA,
        'selections': frozen['selections'], 'fitting': fitting, **training})
    jobs += selected_replay_jobs(inputs, frozen, data)
    unique_jobs, replay_aliases = deduplicate_replay_jobs(jobs)
    groups = legacy.group_replay_jobs(unique_jobs)
    require(sum(len(job['sources']) for job in jobs if job.get('initial_parity')) == 768,
            'additional initial parity denominator changed')
    alias_ref = write(output / 'replay-aliases-frozen.json', {'schema': SCHEMA,
        'logical_jobs': len(jobs), 'executed_jobs': len(unique_jobs), 'mapping': replay_aliases,
        'fresh_semantic_targets_opened': False})
    actual_replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn'),
                             initializer=init_worker, initargs=(sealed,)) as pool:
        for future in as_completed([pool.submit(replay_group, group) for group in groups]):
            actual_replays.extend(future.result())
    replays = expand_replay_aliases(jobs, actual_replays, replay_aliases)
    require(len(replays) == len(jobs), 'logical numerical replay job omitted')
    singles = {name: {panel: read_ref(pin) for panel, pin in panels.items()} for name, panels in frozen['files'].items()}
    oracle = {name: {panel: read_ref(pin) for panel, pin in panels.items()} for name, panels in frozen['oracle_files'].items()}
    documents = {name: {panel: read_ref(pin) for panel, pin in panels.items()} for name, panels in frozen['document_files'].items()}
    boundaries = {policy: {panel: read_ref(pin) for panel, pin in panels.items()} for policy, panels in frozen['boundaries'].items()}
    scope_invariance = {panel: verify_scope_invariance(boundaries['original'][panel], boundaries['distill'][panel], rows)
                        for panel, rows in data['boundary_documents'].items()}
    for left in frozen['models']:
        for right in frozen['models']:
            if left['name'] < right['name'] and left['checkpoint'] == right['checkpoint']:
                require(singles[left['name']] == singles[right['name']] and oracle[left['name']] == oracle[right['name']],
                        'duplicate selected/fallback checkpoint changed source outputs')
                for policy in PRIMARY_BOUNDARIES:
                    require(documents[left['name'] + '__boundary_' + policy] == documents[right['name'] + '__boundary_' + policy],
                            'duplicate fallback pipeline changed predictions')
    saved = [row for row in replays if not row.get('initial_parity')]
    actual_saved = [row for row in actual_replays if not row.get('initial_parity')]
    require(sum(row['rows'] for row in actual_replays if row.get('initial_parity')) == 768, 'initial parity cannot be silently aliased')
    replay_ref = write(output / 'replay-frozen.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'training_and_selection_audit': training_ref, 'panels': sorted(replays, key=lambda row: row['name']),
        'grouped_checkpoint_loads': len(groups), 'prediction_memoization_used': True,
        'exact_input_output_aliases': alias_ref, 'numerical_replay_executed_in_this_attempt': True,
        'actual_numerical_source_evaluations': sum(row['rows'] for row in actual_replays),
        'logical_source_rows_validated': sum(row['rows'] for row in replays),
        'saved_source_rows': sum(row['rows'] for row in saved),
        'actual_saved_source_rows_replayed': sum(row['rows'] for row in actual_saved),
        'logical_saved_source_rows_validated': sum(row['rows'] for row in saved),
        'additional_initial_parity_source_evaluations': sum(row['rows'] for row in replays if row.get('initial_parity')),
        'postselection_training_diagnostic_rows': sum(row['rows'] for row in saved if '/full-training/' in row['name']),
        'legacy_training_diagnostic_rows': sum(row['rows'] for row in saved if row.get('training_diagnostic') and '/full-training/' not in row['name']),
        'rows_by_kind': {kind: sum(row['rows'] for row in saved if row['kind'] == kind) for kind in ('single','document','oracle','boundary')},
        'scope_invariance': scope_invariance, 'fresh_semantic_targets_opened': False,
        'reference_derived_layout_evidence_opened': False,
        'oracle_segmentation_and_supported_membership_already_supplied': True})
    print({'phase': 'replay_frozen', 'saved_source_rows': sum(row['rows'] for row in saved),
        'actual_saved_source_rows_replayed': sum(row['rows'] for row in actual_saved),
        'logical_saved_source_rows_validated': sum(row['rows'] for row in saved), 'replay': replay_ref}, flush=True)
    selections = {'single': {}, 'oracle': {}, 'document': {}}
    for name in singles:
        sources, predictions = data['sources']['fresh'], singles[name]['fresh']['rows']
        selected = retained.calendar.select_candidates(sources, predictions, toolchain=args.toolchain, policy=retained.calendar.POLICY)
        lookup = {source['id']: (source, prediction) for source, prediction in zip(sources, predictions, strict=True)}
        for entry in selected['rows']:
            retained.calendar_summary.verify_entry(*lookup[entry['candidate']['candidate_id']], entry)
        require(selected['source_count'] == len(selected['rows']) + len(selected['excluded']) == 192,
                'fresh standalone lowering lost sources')
        selections['single'][name] = selected
        selections['oracle'][name] = document_selection(oracle[name]['fresh']['rows'], data['oracle_documents']['fresh'], toolchain=args.toolchain)
    for name in documents:
        selections['document'][name] = document_selection(documents[name]['fresh']['rows'], data['documents']['fresh'], toolchain=args.toolchain)
    build_selection_ref = write(output / 'build-selection-frozen.json', {'schema': SCHEMA, **selections,
        'replay': replay_ref, 'fresh_semantic_targets_opened': False, 'canonical_references_used_for_selection': False,
        'logical_build_slots': 40, 'single_source_slots': 1920, 'oracle_document_slots': 480,
        'predicted_document_slots': 1920, 'oracle_assisted_segmentation_supplied': True})
    builds = {kind: {} for kind in selections}; unique_builds = {}; build_aliases = []
    for kind, selected_slots in selections.items():
        for name, selected in selected_slots.items():
            key = build_identity(selected, args)
            origin = kind + '/' + name
            fresh_execution = key not in unique_builds
            if fresh_execution:
                batches = retained.build_batches(selected['rows'], output / 'builds' / kind / name, args)
                unique_builds[key] = {'executed_slot': origin, 'batches': batches}
            item = unique_builds[key]; builds[kind][name] = item['batches']
            build_aliases.append({'slot': origin, 'executed_slot': item['executed_slot'],
                'identity_sha256': key, 'build_group_created_for_this_slot': fresh_execution,
                'actual_backend_invocations_for_this_slot': sum(batch['backend_executed'] for batch in item['batches']) if fresh_execution else 0})
            print({'phase': 'built' if fresh_execution else 'build_alias_verified', 'kind': kind, 'model': name,
                   'sources': selected['source_count'], 'supported_for_lowering': len(selected['rows']),
                   'attempts_executed': len(item['batches']) if fresh_execution else 0}, flush=True)
    builds_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, **builds, 'selections': build_selection_ref,
        'unique_executions': unique_builds, 'logical_slot_aliases': build_aliases,
        'replay': replay_ref, 'fresh_semantic_targets_opened': False, 'prior_role_fresh_explicitly_admitted_as_retention': True,
        'reference_derived_layout_evidence_opened': False, 'oracle_assisted_segmentation_supplied': True})
    build_alias_by_slot = {row['slot']: row for row in build_aliases}
    read_ref(frozen['selections'], parse=False)
    require(not guard.events, 'sealed semantic reference access attempted before native build freeze')
    guard.released = True
    print({'phase': 'references_released_after_build_freeze', 'builds': builds_ref}, flush=True)
    evidence = {key: read_ref(pin) for key, pin in evidence_refs.items()}
    single_targets = {'prior_role_fresh': inputs['role_retention_targets']['fresh'], 'fresh': evidence['fresh_targets'],
                      'oracle_role_fresh': inputs['oracle_targets']['role_fresh'], 'oracle_fresh': evidence['fresh_oracle_targets']}
    require(set(single_targets) | {'real_exposed'} == set(data['sources']), 'reference-bearing single panel inventory differs')
    target_documents = {**inputs['modern_document_targets'], 'fresh': evidence['fresh_document_targets']}
    audit_inputs = {**inputs, 'document_tuning_pairs': read_ref(manifest['artifacts']['document_tuning_pairs'])}
    fresh_oracle_inputs = {'sources': [{'id': row['id'], 'source_text': row['source_text']} for row in data['oracle_sources']['fresh']],
        'occurrences': data['occurrences']['fresh'], 'boundaries': data['oracle_plans']['fresh'],
        'document_sources': data['oracle_documents']['fresh']}
    exposure = annotations.audit_timing_annotations(audit_inputs, evidence['fresh_targets'], evidence['fresh_pairs'],
        evidence['fresh_document_targets'], evidence['fresh_document_pairs'], evidence['fresh_oracle_targets'],
        evidence['annotation_ledger'], evidence['exposure_audit'], **historical_annotation_inputs(inputs),
        fresh_oracle_inputs=fresh_oracle_inputs)
    exposure_ref = write(output / 'authored-exposure-audit.json', exposure)
    boundary_scores = {policy: {panel: legacy.boundary_qualification.score_boundaries(generation, data['boundary_documents'][panel], target_documents[panel])
        for panel, generation in panels.items()} for policy, panels in boundaries.items()}
    single_scores, oracle_scores, document_scores, real_diagnostics, train_diagnostics = {}, {}, {}, {}, {}
    model_reports = []
    for model in frozen['models']:
        name = model['name']; single_scores[name] = {}
        for panel, targets in single_targets.items():
            metric = clause_metrics(singles[name][panel], data['sources'][panel], targets)
            metric['errors'] = legacy.single_error_metrics(singles[name][panel], data['sources'][panel], targets, enabled=model['enabled'])
            single_scores[name][panel] = metric
        exact = {row['id']: row['fullrule_exact'] for row in single_scores[name]['fresh']['rows']}
        single_builds = attribute_build_execution(retained.prior.build_accounting(selections['single'][name], builds['single'][name], exact), build_alias_by_slot['single/' + name])
        oracle_scores[name] = {}
        for panel, generation in oracle[name].items():
            targets = [row for row in target_documents[panel] if row['supported']]
            oracle_scores[name][panel] = oracle_document_score(generation, data['oracle_documents'][panel], targets,
                selection=selections['oracle'][name] if panel == 'fresh' else None,
                batches=builds['oracle'][name] if panel == 'fresh' else None)
            if panel == 'fresh': oracle_scores[name][panel]['builds'] = attribute_build_execution(oracle_scores[name][panel]['builds'], build_alias_by_slot['oracle/' + name])
        real = singles[name]['real_exposed']['rows']
        require(len(real) == 86, 'all86 exposed real-source predictions required')
        real_diagnostics[name] = {'count': 86, 'decoded': sum(row['status'] == 'decoded' for row in real),
            'abstained': sum(row['status'] == 'abstained' for row in real),
            'abstention_reasons': dict(Counter(row.get('reason') for row in real if row['status'] == 'abstained')),
            'reference_count': 0, 'semantic_accuracy': None, 'used_for_selection': False}
        if name in frozen['training_files']:
            train_diagnostics[name] = {panel: clause_metrics(read_ref(pin), data['training_sources'][panel],
                inputs['legacy']['training'] if panel == 'main' else inputs['aux_rows']) for panel, pin in frozen['training_files'][name].items()}
        model_reports.append({**model, 'single_metrics': {panel: result['metrics'] for panel, result in single_scores[name].items()},
            'single_builds': single_builds, 'oracle_metrics': {panel: {key: value for key, value in result.items() if key != 'rows'}
                for panel, result in oracle_scores[name].items()}, 'real_source_diagnostics': real_diagnostics[name]})
    pipeline_reports = []
    for pipeline in frozen['pipelines']:
        name, policy = pipeline['name'], pipeline['boundary_policy']; document_scores[name] = {}
        for panel, generation in documents[name].items():
            document_scores[name][panel] = score_predicted_documents(generation, data['documents'][panel], target_documents[panel],
                boundary_scores[policy][panel], selection=selections['document'][name] if panel == 'fresh' else None,
                batches=builds['document'][name] if panel == 'fresh' else None)
            if panel == 'fresh': document_scores[name][panel]['builds'] = attribute_build_execution(document_scores[name][panel]['builds'], build_alias_by_slot['document/' + name])
        pipeline_reports.append({**pipeline, 'panels': {panel: {key: value for key, value in result.items() if key != 'rows'}
            for panel, result in document_scores[name].items()}})
    details_ref = write(output / 'scored-details.json', {'single': single_scores, 'oracle_document': oracle_scores,
        'document': document_scores, 'boundary': boundary_scores, 'real_source_diagnostics': real_diagnostics,
        'postselection_training_diagnostics': train_diagnostics})
    require(all(sha(path) == value for path, value in pins.items()) and runner.load_config(args.config) == inputs,
            'producer or fitting/source closure changed during qualification')
    for pin in (frozen_ref, config_ref, frozen['plan'], frozen['selections'], frozen['heads'], *sealed):
        read_ref(pin, parse=False)
    opens_ref = write(output / 'phase-open-audit.json', {'schema': SCHEMA, 'sealed_paths': sorted(guard.paths),
        'events': guard.events, 'before_build_freeze_attempts': sum(not row['after_build_freeze'] for row in guard.events),
        'build_freeze': builds_ref, 'all_new_semantic_reference_reads_after_build_freeze': True,
        'replay_workers_had_same_seven_file_OS_open_denial': True,
        'oracle_segmentation_reference_inputs_supplied_before_builds': True})
    result = {'schema': SCHEMA, 'qualification_plan': qualification_plan, 'generation_freeze': frozen_ref,
        'training_and_selection_audit': training_ref, 'replay': replay_ref, 'builds': builds_ref,
        'exact_input_output_aliases': alias_ref, 'numerical_replay_executed_in_this_attempt': True,
        'actual_numerical_source_evaluations': sum(row['rows'] for row in actual_replays),
        'logical_source_rows_validated': sum(row['rows'] for row in replays),
        'postselection_training_metrics': {name: {panel: result['metrics'] for panel, result in scores.items()}
                                          for name, scores in train_diagnostics.items()},
        'details': details_ref, 'authored_exposure_audit': exposure_ref, 'phase_open_audit': opens_ref,
        'posthoc_evidence': evidence_refs, 'producer_pins': pins, 'models': model_reports, 'pipelines': pipeline_reports,
        'boundary_metrics': {policy: {panel: {key: value for key, value in score.items() if key not in ('rows','legacy_counts')}
            for panel, score in panels.items()} for policy, panels in boundary_scores.items()},
        'scope_invariance': scope_invariance, 'inventory': inventory, 'primary_choices': frozen['primary_choices'],
        'parent_fallbacks': frozen['parent_fallbacks'], 'executed_optimizer_updates': 800, 'boundary_optimizer_updates': 0,
        'saved_source_rows_replayed': sum(row['rows'] for row in actual_saved),
        'logical_saved_source_rows_validated': sum(row['rows'] for row in saved),
        'saved_rows_verified_by_exact_alias': sum(row['rows'] for row in saved) - sum(row['rows'] for row in actual_saved),
        'additional_initial_parity_source_evaluations': 768, 'independent_teacher_source_evaluations': 7776,
        'teacher_exact_batch_recheck_source_evaluations': training['teacher_exact_batch_recheck_source_evaluations'],
        'clause_occurrences_replayed': sum(row.get('clause_occurrences_replayed', 0) for row in replays),
        'actual_lake_build_invocations': sum(batch['backend_executed'] for item in unique_builds.values() for batch in item['batches']),
        'build_attempts': sum(len(item['batches']) for item in unique_builds.values()),
        'native_fresh_single_build_slots': 10, 'native_fresh_oracle_document_build_slots': 10,
        'native_fresh_predicted_document_build_slots': 20,
        'fresh_reference_files_opened_after_replay_and_build_freezes': True,
        'fresh_semantic_reference_files_opened_after_replay_and_build_freezes': True,
        'reference_release_flag_scope': 'Seven sealed semantic target/pair/layout files; explicitly supplied oracle segmentation inputs are excluded.',
        'reference_derived_layout_evidence_opened_after_build_freeze': True,
        'oracle_segmentation_and_supported_eligibility_supplied': True,
        'test_results_used_for_selection_or_gate_revision': False, 'optimizer_trajectory_replayed': False,
        'production_ready': False, 'statutory_gold_available': False, 'all_logic_families_supported': False,
        'actual_latent_conditioning_validated': False,
        'scope': 'Two fixed pretrained clause architectures, one seed each, matched200-update common loss versus timing ownership loss. '
            'Both arms receive the same768 authored auxiliary sources and standard semantic CE. Selected comparisons include the frozen selection policy; '
            'final200 slots are predeclared diagnostics. Inherited parent-minus-one tolerances remain explicit; new clause/optional-facet and per-source '
            'guard retention is strict. Original and unqualified atom-distill boundaries are fixed factors; scope logits are identical and no scope model trains. '
            'Oracle evaluations openly supply supported membership and exact cuts. Canonical reference exactness, valid native compilation, and unmeasured statutory semantics remain distinct.'}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'saved_replay_rows': result['saved_source_rows_replayed'],
           'actual_lake_build_invocations': result['actual_lake_build_invocations']}, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--lake-executable', required=True)
    parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
