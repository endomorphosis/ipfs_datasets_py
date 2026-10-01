"""Joint opt-in Intent sequence alignment and native-family v2 training.

The objectives retain separate weights and inference APIs. Family reconstruction
cannot fill a missing source interpretation. Native targets and split quarantine
are prepared before either fit; a failed family phase preserves the source child
and returns an explicit partial receipt. Existing default routes remain intact.
"""
from pathlib import Path
import os
from .alignment_curriculum import prepare_alignment_training_data
from .coverage_training import _legal_lineage, select_family_training_rows
from .rich_decoder import sha, wire

SCHEMA='intent-aligned-joint-training/v2'
SOURCE_OPTIONS={'epochs','max_seconds','copy_dropout','learning_rate','seed','alignment_weight','coverage_weight'}
FAMILY_OPTIONS={'epochs','latent_width','learning_rate','minibatch_size','denoising','ridge','patience','seed','max_seconds'}


def _save(path,value,replace=False):
    target=path.with_suffix('.pending')if replace else path
    with target.open('xb')as stream:stream.write(wire(value));stream.flush();os.fsync(stream.fileno())
    if replace:os.replace(target,path)


def train_aligned_intent(corpus, *, parent_backend_descriptor, expected_legal_initializer_sha256,
                         output, source_training_options=None, train_family_projection=True,
                         family_training_options=None, family_parent_descriptor=None,
                         family_target_limits=None):
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_aligned as source
    from ....optimizers.logic_theorem_optimizer import autoencoder_family_training_v2 as numerical
    from ...formalization.autoencoder.family_training_v2 import prepare_family_training_targets_v2
    if type(train_family_projection)is not bool:raise ValueError('explicit family phase mode required')
    for opts,allowed in ((source_training_options,SOURCE_OPTIONS),(family_training_options,FAMILY_OPTIONS)):
        if opts is not None and(type(opts)is not dict or set(opts)-allowed):raise ValueError('known bounded training options required')
    if not train_family_projection and(family_training_options is not None or family_parent_descriptor is not None):
        raise ValueError('family settings require enabled family phase')
    parent=source._load_parent(parent_backend_descriptor)
    lineage=_legal_lineage(parent['training'],expected_legal_initializer_sha256)
    parent_path=Path(parent_backend_descriptor['path']);parent_digest=sha(parent_path.read_bytes())
    prepared=prepare_alignment_training_data(corpus)
    if any(not 1<=len(rows)<=8192 for rows in prepared['pairs'].values()):raise ValueError('bounded nonempty paired training sets required')
    family_reports=None
    if train_family_projection:
        selected=select_family_training_rows(corpus,{'corpus_sha256':sha(wire(corpus)),
            'selected_row_ids':{'train':prepared['selected_train_ids'],'validation':prepared['selected_validation_ids']}},limits=family_target_limits)
        family_reports={split:[prepare_family_training_targets_v2('intent_ir',document=row['ast'],source_text=row['instruction'])
                               for row in rows]for split,rows in selected.items()}
        if family_parent_descriptor is not None:numerical._read(family_parent_descriptor)
    output=Path(output).absolute()
    if output.resolve()!=output or output.exists()or not output.parent.is_dir():raise ValueError('fresh canonical output directory required')
    output.mkdir()
    _save(output/'corpus.json',corpus);_save(output/'prepared.json',prepared)
    if family_reports is not None:_save(output/'family-inputs.json',family_reports)
    options={'epochs':48,'max_seconds':330,'copy_dropout':.35,'learning_rate':.0005,'alignment_weight':.1,'coverage_weight':.05}
    options.update(source_training_options or {})
    descriptor=source.train_paired_copy_continuation(prepared['pairs']['train'],prepared['pairs']['validation'],
        parent_descriptor=parent_backend_descriptor,output_dir=output/'source-model',**options)
    child=source.load_paired_copy_continuation(descriptor)
    if _legal_lineage(child['training'],expected_legal_initializer_sha256)!=lineage or sha(parent_path.read_bytes())!=parent_digest:
        raise ValueError('parent or legal lexical initializer changed')
    receipt={'schema':SCHEMA,'status':'partial'if train_family_projection else'complete',
        'source_descriptor':descriptor,'family_descriptor':None,'parent_source_descriptor':parent_backend_descriptor,
        'family_parent_descriptor':family_parent_descriptor,'source_options':options,'legal_initializer_lineage':lineage,
        'parent_bytes_unchanged':True,'corpus_sha256':sha(wire(corpus)),'source_training_sha256':sha(wire(child['training'])),
        'pair_counts':{s:len(rows)for s,rows in prepared['pairs'].items()},'quarantined':prepared['quarantined'],
        'new_holdouts_count':len(prepared['new_holdouts']),'family_stage':'pending'if train_family_projection else'not_requested',
        'family_error':None,'family_report':None,'inference_api':'ipfs_datasets_py.logic.intent_ir.formalize.rich_aligned_decoder.prepare_aligned_rich_intent',
        'family_inference_api':'ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_v2.infer_family_projection_autoencoder_v2',
        'default_supervisor_dispatch_changed':False,'source_accuracy_inferred_from_family_loss':False,
        'test_used_for_fit_or_selection':False,'proof_authority':False,'source_semantics_verified':False}
    _save(output/'receipt.json',receipt)
    if train_family_projection:
        try:
            result=numerical.train_family_projection_autoencoder_v2(family_reports['train'],family_reports['validation'],
                output_dir=output/'family-model',parent_descriptor=family_parent_descriptor,**(family_training_options or {}))
            receipt.update(status='complete',family_stage='complete',family_descriptor=result['descriptor'],family_report=result['report'])
        except Exception as exc:
            receipt.update(status='partial',family_stage='failed',family_error={'type':type(exc).__name__,'message':str(exc)[:2000]})
        _save(output/'receipt.json',receipt,replace=True)
    return receipt
