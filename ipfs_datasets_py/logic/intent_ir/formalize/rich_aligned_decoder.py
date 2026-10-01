"""Opt-in rich inference for aligned shared sequence checkpoints.

Numerical forward and inverse predictions must independently agree with the
complete input. The source-free inverse codec preserves generated tokens. This
module does not change the default supervisor route or the frozen v1 adapter.
"""
from pathlib import Path
from . import rich_grammar as grammar
from .rich_decoder import wire, sha, AUTHORITY
SCHEMA = 'intent-aligned-copy-roundtrip/v2'


def _backend(descriptor):
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_aligned as aligned
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as old
    if type(descriptor) is not dict: raise ValueError('explicit backend checkpoint required')
    if descriptor.get('schema') == aligned.SCHEMA:return aligned
    if descriptor.get('schema') == old.SCHEMA:return old
    raise ValueError('unsupported aligned inference backend')


def _pins():
    from . import rich_logic, rich_inverse_codec, rich_decoder
    return {m.__name__:sha(Path(m.__file__).read_bytes()) for m in
            (grammar,rich_logic,rich_inverse_codec,rich_decoder)} | {__name__:sha(Path(__file__).read_bytes())}


def prepare_aligned_rich_intent(instruction, checkpoint_descriptor=None, *, context=None,
                                    beam_width=8, weight_ablation=None, project=True):
    from .rich_inverse_codec import recover_generated_inverse
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import tokenize
    from .copy_roundtrip import generation_usable
    from .rich_logic import project_rich_intent_logic
    if (type(instruction) is not str or type(beam_width) is not int or not 0 <= beam_width <= 16
            or type(project) is not bool):
        raise ValueError('source instruction and explicit bounded inference options required')
    report = {'schema':SCHEMA,'instruction_sha256':sha(instruction.encode()),'status':'fail_open_no_checkpoint',
        'checkpoint':checkpoint_descriptor,'learned':{'encoder':None,'decoder':None,'ast':None,'normalized_text':None},
        'encoder_search':None,'decoder_searches':[],'rich_ir':None,'logic':None,
        'source_agreement':False,'counts':{'encoder_executions':0,'decoder_executions':0},
        'continue_planning':True,'raw_instruction_preserved':True,'training_steps':0,'llm_calls':0,
        'weight_ablation':weight_ablation,'context':context,'beam_width':beam_width,'project':project,
        'producer_pins':_pins(),'inverse_decoding_method':None,**AUTHORITY}
    def finish():
        report['report_sha256']=sha(wire(report))
        return report
    try:
        # This scope check exports no parser labels to either neural direction.
        grammar.parse_instruction(instruction)
    except (ValueError,TypeError) as exc:
        report.update(status='fail_open_input_out_of_scope',reason=str(exc))
        return finish()
    if checkpoint_descriptor is None:
        return finish()
    try:
        backend = _backend(checkpoint_descriptor)
        backend.load_paired_copy_continuation(checkpoint_descriptor)
        selected = checkpoint_descriptor
        options = {'weight_ablation':weight_ablation,'max_new_tokens':160}
        encoded = backend.infer_paired_copy_continuation(selected,grammar.model_input(instruction),'encode',**options)
        report['counts']['encoder_executions']+=1
        report['learned']['encoder']=encoded
        encoder_rows = [encoded]
        if beam_width:
            # Greedy is evaluated first; search is lazy, bounded and scored by
            # model probabilities without a source parser or expected labels.
            def searched():
                yield from encoder_rows
                search=backend.infer_paired_copy_continuation_beam(selected,grammar.model_input(instruction),
                    'encode',beam_width=beam_width,**options)
                report['encoder_search']=search
                report['counts']['encoder_executions']+=1
                yield from search['rows']
            candidates = searched()
        else:
            candidates = iter(encoder_rows)
        tried = set()
        for candidate in candidates:
            if not generation_usable(candidate):continue
            try: ast=grammar.sequence_to_ast(candidate['generated_text'])
            except (ValueError,TypeError):continue
            identity=sha(wire(ast))
            if identity in tried:continue
            tried.add(identity)
            if ast!=grammar.parse_instruction(instruction):continue
            sequence=grammar.ast_to_sequence(ast)
            decoded=backend.infer_paired_copy_continuation(selected,sequence,'decode',**options)
            report['counts']['decoder_executions']+=1
            inverse_rows=[decoded]
            if beam_width:
                def inverses():
                    yield from inverse_rows
                    search=backend.infer_paired_copy_continuation_beam(selected,sequence,'decode',beam_width=beam_width,**options)
                    report['decoder_searches'].append(search)
                    report['counts']['decoder_executions']+=1
                    yield from search['rows']
                possibilities=inverses()
            else:possibilities=iter(inverse_rows)
            for inverse in possibilities:
                if not generation_usable(inverse):continue
                text=grammar._unspace(inverse['generated_text'])
                # Delimiters separate whole clauses; period spacing is only
                # display normalization of the tokenizer's punctuation tokens.
                import re
                text=re.sub(r'\s+,',',',text)
                method='frozen_unspace'
                try: reconstructed=grammar.parse_instruction(text,normalized_inverse=True)
                except (ValueError,TypeError): reconstructed=None
                if reconstructed!=ast:
                    recovery=recover_generated_inverse(inverse['generated_text'])
                    if (recovery['status']!='candidate' or recovery['ast']!=ast
                            or tokenize(recovery['text'])!=tokenize(inverse['generated_text'])): continue
                    text=recovery['text']
                    if grammar.parse_instruction(text,normalized_inverse=True)!=ast:continue
                    method='token_equivalent_field_codec'
                report['inverse_decoding_method']=method
                report.update(status='source_supported_rich_candidate',source_agreement=True,
                    rich_ir={'schema':'intent-rich-ir/v1','ast':ast,'source_sha256':report['instruction_sha256']},
                    logic=project_rich_intent_logic(ast,instruction=instruction,context=context) if project else None)
                report['learned']={'encoder':candidate,'decoder':inverse,'ast':ast,'normalized_text':text}
                return finish()
        report['status']='fail_open_no_source_agreed_roundtrip'
    except Exception as exc:
        report.update(status='fail_open_checkpoint_or_inference_error',error_type=type(exc).__name__,reason=str(exc))
    return finish()


def validate_aligned_rich_intent(report, *, instruction, checkpoint_descriptor):
    replay=prepare_aligned_rich_intent(instruction,checkpoint_descriptor,context=report['context'],
        beam_width=report['beam_width'],weight_ablation=report['weight_ablation'],project=report['project'])
    if wire(replay)!=wire(report):raise ValueError('aligned rich report differs from fresh numerical replay')
    return report
