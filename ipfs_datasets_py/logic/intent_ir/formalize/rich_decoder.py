"""Learned rich Intent candidates with independent complete-source agreement.

The encoder receives only source text. The inverse receives only predicted IR.
Parsing supplies weak training labels and post-generation checks, never neural
targets at inference. Missing checkpoints and unsupported outputs fail open.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import rich_grammar as grammar

SCHEMA = "intent-rich-copy-roundtrip/v1"
CHECKPOINT_SCHEMA = "intent-rich-copy-checkpoint/v1"
AUTHORITY = {"proof_authority":False,"execution_authority":False,"completion_authority":False,
             "source_semantics_verified":False,"whole_document_formalized":False}


def wire(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def _pins():
    from . import rich_logic, instruction_scope, copy_roundtrip
    return {__name__:sha(Path(__file__).read_bytes()),
            **{m.__name__:sha(Path(m.__file__).read_bytes()) for m in (grammar,rich_logic,instruction_scope,copy_roundtrip)}}


def register_rich_intent_checkpoint(backend_descriptor, *, output, corpus_sha256):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy_continuation import load_paired_copy_continuation
    load_paired_copy_continuation(backend_descriptor)
    output = Path(output).resolve(strict=True)
    backend_path = Path(backend_descriptor['path']).resolve(strict=True)
    relative = backend_path.relative_to(output).as_posix()
    manifest = {'schema':CHECKPOINT_SCHEMA,'backend':{k:v for k,v in backend_descriptor.items() if k!='path'},
        'backend_file':relative,'corpus_sha256':corpus_sha256,'producer_pins':_pins(),
        'scope':'bounded_learned_atoms_binary_composition_and_atomic_conditional_norms',**AUTHORITY}
    path = output/'manifest.json'
    with path.open('xb') as stream:
        stream.write(wire(manifest))
    descriptor = {'schema':CHECKPOINT_SCHEMA,'path':str(path),'sha256':sha(path.read_bytes())}
    load_rich_intent_checkpoint(descriptor)
    return descriptor


def load_rich_intent_checkpoint(descriptor):
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as backend
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import _read,_json
    if type(descriptor) is not dict or set(descriptor)!={'schema','path','sha256'} or descriptor['schema']!=CHECKPOINT_SCHEMA:
        raise ValueError('closed rich checkpoint descriptor required')
    path = Path(descriptor['path'])
    raw = _read(path,65536)
    if sha(raw)!=descriptor['sha256']:
        raise ValueError('rich checkpoint manifest digest differs')
    manifest = _json(raw)
    fields = {'schema','backend','backend_file','corpus_sha256','producer_pins','scope',*AUTHORITY}
    if (type(manifest) is not dict or set(manifest)!=fields or manifest['schema']!=CHECKPOINT_SCHEMA
            or manifest['producer_pins']!=_pins() or any(manifest[k] is not False for k in AUTHORITY)):
        raise ValueError('rich checkpoint producer or authority differs')
    relative = Path(manifest['backend_file'])
    if (relative.is_absolute() or any(p in ('.','..') for p in relative.parts)
            or relative.as_posix()!=manifest['backend_file'] or not relative.parts):
        raise ValueError('child weights must remain within checkpoint package')
    child = path.parent/relative
    if child.resolve(strict=True)!=child:
        raise ValueError('canonical child weights path required')
    selected = {**manifest['backend'],'path':str(child)}
    return {'manifest':manifest,'backend_descriptor':selected,'backend':backend.load_paired_copy_continuation(selected)}


def prepare_rich_intent_instruction(instruction, checkpoint_descriptor=None, *, context=None,
                                    beam_width=8, weight_ablation=None, project=True):
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as backend
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
        'weight_ablation':weight_ablation,'context':context,'beam_width':beam_width,'project':project,**AUTHORITY}
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
        loaded = load_rich_intent_checkpoint(checkpoint_descriptor)
        selected = loaded['backend_descriptor']
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
                try: reconstructed=grammar.parse_instruction(text,normalized_inverse=True)
                except (ValueError,TypeError):continue
                if reconstructed!=ast:continue
                report.update(status='source_supported_rich_candidate',source_agreement=True,
                    rich_ir={'schema':'intent-rich-ir/v1','ast':ast,'source_sha256':report['instruction_sha256']},
                    logic=project_rich_intent_logic(ast,instruction=instruction,context=context) if project else None)
                report['learned']={'encoder':candidate,'decoder':inverse,'ast':ast,'normalized_text':text}
                return finish()
        report['status']='fail_open_no_source_agreed_roundtrip'
    except Exception as exc:
        report.update(status='fail_open_checkpoint_or_inference_error',error_type=type(exc).__name__,reason=str(exc))
    return finish()


def validate_rich_intent_report(report, *, instruction, checkpoint_descriptor=None):
    expected=prepare_rich_intent_instruction(instruction,checkpoint_descriptor,
        context=report['context'],weight_ablation=report['weight_ablation'],
        beam_width=report['beam_width'],project=report['project'])
    if wire(expected)!=wire(report):
        raise ValueError('rich candidate differs from actual learned replay')
    return report
