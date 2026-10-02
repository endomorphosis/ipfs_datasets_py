"""Additive neural search recovery with a source-independent syntax grammar."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from . import rich_decoder as direct
from . import rich_grammar as grammar
from . import rich_search_policy as policy
from .copy_roundtrip import generation_usable
from .rich_logic import project_rich_intent_logic

SCHEMA = 'intent-grammar-searched-roundtrip/v1'
METHOD = 'grammar_constrained_neural_roundtrip'


def prepare_searched_rich_intent(instruction, checkpoint=None, *, context=None, base_report=None,
                                beam_width=None, weight_ablation=None):
    from . import compositional_decoder
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_grammar_search as backend
    if type(instruction) is not str or (base_report is not None and type(base_report) is not dict):
        raise ValueError('source instruction and optional direct inference report required')
    selected_beam = (base_report.get('beam_width', 16) if base_report is not None else 16) if beam_width is None else beam_width
    selected_ablation = base_report.get('weight_ablation') if base_report is not None and weight_ablation is None else weight_ablation
    if type(selected_beam) is not int or not 1 <= selected_beam <= 16:
        raise ValueError('bounded positive grammar search width required')
    reused = base_report is not None
    if reused:
        compositional_decoder._check_cached_base(base_report, instruction, checkpoint, context, selected_beam, selected_ablation)
        baseline = deepcopy(base_report)
    else:
        baseline = direct.prepare_rich_intent_instruction(instruction, checkpoint, context=context,
            beam_width=selected_beam, weight_ablation=selected_ablation)
    if baseline['rich_ir'] is not None or baseline['counts']['encoder_executions'] == 0:
        if reused:
            direct.validate_rich_intent_report(baseline, instruction=instruction, checkpoint_descriptor=checkpoint)
        return baseline
    counts = dict(baseline['counts'])
    report = {'schema': SCHEMA, 'decoding_method': METHOD, 'instruction': instruction,
        'instruction_sha256': direct.sha(instruction.encode()), 'checkpoint': deepcopy(checkpoint),
        'status': 'fail_open_no_grammar_searched_roundtrip', 'source_agreement': False,
        'learned': {'encoder': None, 'decoder': None, 'ast': None, 'normalized_text': None},
        'rich_ir': None, 'logic': None, 'direct_report': baseline,
        'encoder_search': None, 'decoder_searches': [], 'counts': counts,
        'encoder_candidate_origin': None,
        'phase_counts': {'direct': dict(counts), 'grammar_search': {key: 0 for key in counts}},
        'executed_here_counts': {key: 0 if reused else value for key, value in counts.items()},
        'cached_direct_stage_reused': reused, 'context': deepcopy(context),
        'cached_encoder_predictions_consumed': False,
        'beam_width': selected_beam, 'weight_ablation': selected_ablation, 'project': True,
        'whole_AST_generated_by_neural_encoder': True, 'whole_inverse_generated_by_neural_decoder': True,
        'syntax_constraints_are_semantic_evidence': False, 'constraint_receives_source_or_expected_AST': False,
        'policy': policy.policy_identity(), 'producer_pins': {**direct._pins(),
            **{module.__name__: direct.sha(Path(module.__file__).read_bytes()) for module in (policy, backend, compositional_decoder)},
            __name__: direct.sha(Path(__file__).read_bytes())},
        'continue_planning': True, 'raw_instruction_preserved': True, 'training_steps': 0, 'llm_calls': 0,
        **direct.AUTHORITY}

    def count(direction):
        key = 'encoder_executions' if direction == 'encode' else 'decoder_executions'
        for target in (report['counts'], report['phase_counts']['grammar_search'], report['executed_here_counts']):
            target[key] += 1

    try:
        selected = direct.load_rich_intent_checkpoint(checkpoint)['backend_descriptor']
        options = {**policy.policy_identity(), 'beam_width': selected_beam,
            'max_new_tokens': 160, 'weight_ablation': selected_ablation}
        def candidates():
            # A previous forward pass may already be correct while its inverse
            # failed. Reuse those genuine neural outputs before a new encoder
            # search; no parser-produced sequence replaces an encoder output.
            # A caller can re-sign a fabricated cached report. Its encoder
            # predictions therefore cannot establish neural provenance. Only
            # predictions executed inside this invocation can be reused.
            if not reused:
                first = baseline['learned']['encoder']
                if first is not None:
                    yield first, 'fresh_direct_search'
                for candidate in (baseline.get('encoder_search') or {}).get('rows', []):
                    yield candidate, 'fresh_direct_search'
            search = backend.infer_paired_copy_grammar_beam(selected, grammar.model_input(instruction), 'encode',
                prefix_constraint=policy.RichPrefixConstraint('encode'), **options)
            report['encoder_search'] = search
            count('encode')
            for candidate in search['rows']:
                yield candidate, 'grammar_constrained_search'

        tried = set()
        for candidate, origin in candidates():
            if not generation_usable(candidate):
                continue
            try:
                ast = grammar.sequence_to_ast(candidate['generated_text'])
            except (ValueError, TypeError):
                continue
            identity = direct.sha(direct.wire(ast))
            if identity in tried:
                continue
            tried.add(identity)
            # Source labels are consulted only after a full neural prediction.
            if ast != grammar.parse_instruction(instruction):
                continue
            inverse = backend.infer_paired_copy_grammar_beam(selected, grammar.ast_to_sequence(ast), 'decode',
                prefix_constraint=policy.RichPrefixConstraint('decode'), **options)
            report['decoder_searches'].append(inverse)
            count('decode')
            for decoded in inverse['rows']:
                if not generation_usable(decoded):
                    continue
                text = re.sub(r'\s+,', ',', grammar._unspace(decoded['generated_text']))
                if grammar.parse_instruction(text, normalized_inverse=True) != ast:
                    continue
                report.update(status='source_supported_grammar_searched_candidate', source_agreement=True,
                    encoder_candidate_origin=origin,
                    rich_ir={'schema': 'intent-rich-ir/v1', 'ast': ast, 'source_sha256': report['instruction_sha256']},
                    logic=project_rich_intent_logic(ast, instruction=instruction, context=context),
                    learned={'encoder': candidate, 'decoder': decoded, 'ast': ast, 'normalized_text': text})
                break
            # Only one AST can equal the complete source. A repeated encoding
            # of that AST would give exactly the same inverse search.
            break
    except Exception as exc:
        report.update(status='fail_open_grammar_search_error', reason=str(exc), error_type=type(exc).__name__)
    report['report_sha256'] = direct.sha(direct.wire(report))
    return report


def validate_searched_rich_intent(report, *, instruction, checkpoint=None, checkpoint_descriptor=None):
    if checkpoint is not None and checkpoint_descriptor is not None and checkpoint != checkpoint_descriptor:
        raise ValueError('conflicting grammar search checkpoint identities')
    selected = checkpoint if checkpoint is not None else checkpoint_descriptor
    if type(report) is not dict:
        raise ValueError('grammar search inference report required')
    if report.get('schema') == direct.SCHEMA:
        return direct.validate_rich_intent_report(report, instruction=instruction, checkpoint_descriptor=selected)
    if report.get('schema') != SCHEMA:
        raise ValueError('known grammar search report required')
    base = None
    if report.get('cached_direct_stage_reused') is True:
        base = direct.prepare_rich_intent_instruction(instruction, selected, context=report['context'],
            beam_width=report['beam_width'], weight_ablation=report['weight_ablation'])
    expected = prepare_searched_rich_intent(instruction, selected, context=report['context'],
        beam_width=report['beam_width'], weight_ablation=report['weight_ablation'], base_report=base)
    if expected.get('schema') != SCHEMA:
        raise ValueError('grammar search differs from actual numerical replay')
    if direct.wire(expected) != direct.wire(report):
        raise ValueError('grammar search differs from actual numerical replay')
    return report
