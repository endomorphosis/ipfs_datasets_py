"""Shared frozen replay preparation for exposed Legal decoder experiments.

This is a script helper, not a checkpoint loader or production qualification API.
It authenticates the complete paragraph/token/component and import-tree bindings
before returning private numerical models. It never starts training or writes.
"""
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'


def load_context(args, *, validate_plan=None):
    args.dependency_root = args.dependency_root.resolve()
    args.extension_root = args.extension_root.resolve()
    manifest = json.loads(args.manifest.read_bytes())
    helper_relative = 'scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py'
    path = args.extension_root/helper_relative
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['extensions'].get(helper_relative):
        raise ValueError('frozen replay helper differs')
    name = '_decoder_fidelity_replay_helpers'
    if name in sys.modules:
        raise ValueError('replay helper must be loaded exactly once')
    spec = importlib.util.spec_from_file_location(name, path)
    helpers = importlib.util.module_from_spec(spec)
    sys.modules[name] = helpers
    spec.loader.exec_module(helpers)
    require, sha, inventory, extension = helpers.require, helpers.sha, helpers.inventory, helpers.extension
    pins = manifest['extensions']
    require(not args.output.exists(), 'fresh immutable experiment directory required')
    require(sha(args.plan)==manifest['plan_sha256'], 'experiment plan changed')
    plan = json.loads(args.plan.read_bytes())
    (validate_plan or helpers.validate_plan)(plan)
    helpers.validate_manifest_inputs(manifest)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.dependency_root))
    importlib.import_module(PREFIX.rstrip('.'))
    core = extension(args.extension_root, AUTO+'decoder_distillation_experiment.py', PREFIX+'decoder_distillation_experiment', pins)
    adapter = extension(args.extension_root, AUTO+'decoder_distillation_experiment_v2.py', PREFIX+'decoder_distillation_experiment_v2', pins)
    scorer = extension(args.extension_root, AUTO+'decoder_source_fidelity.py', PREFIX+'decoder_source_fidelity', pins)
    trainer = extension(args.extension_root, AUTO+'long_span_decoder_training.py', PREFIX+'long_span_decoder_training', pins)
    curriculum_owner = extension(args.extension_root, AUTO+'source_length_curriculum.py', PREFIX+'source_length_curriculum', pins)
    prior = extension(args.extension_root, 'scripts/ops/autoencoder/benchmark_long_span_decoder.py', 'prior_source_benchmark', pins)
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree = require_workspace_logic_tree()
    before_sources = inventory(args.dependency_root, args.extension_root, pins)
    donor_path = Path(manifest['donor'])
    donor = json.loads(donor_path.read_bytes())
    corpus = json.loads(Path(manifest['paragraphs']).read_bytes())
    embeddings = json.loads(Path(manifest['embeddings']).read_bytes())
    source_plan = json.loads(Path(manifest['curriculum']).read_bytes())
    require(corpus['status'] == 'prepared' and source_plan['ready'], 'original full length panel unavailable')
    require(embeddings['producer']['actual_forward_tokens_checked'] and embeddings['producer']['encoder_context_tokens']==512,
            'complete original native inputs required')
    by_id = {row['input_id']: row for row in embeddings['rows']}
    original_rows = corpus['train']+corpus['validation']
    require(len(by_id)==len(embeddings['rows'])==96 and len({r['id'] for r in original_rows})==96
        and set(by_id)=={r['id'] for r in original_rows}, 'complete unique paragraph/embedding IDs required')
    require(core.digest(donor['codec'])==corpus['codec_sha256']==source_plan['codec_sha256'], 'paragraph codec differs')
    plan_rows = curriculum_owner.paragraph_rows([{**r, 'embedding_result': by_id[r['id']]} for r in original_rows],
        tokenizer_sha256=embeddings['producer']['tokenizer_sha256'],
        tokenizer_profile_id='gte-small:'+embeddings['producer']['revision'], encoder_context_tokens=512,
        codec_sha256=core.digest(donor['codec']))
    require(plan_rows==json.loads(Path(manifest['curriculum_inputs']).read_bytes()), 'source input replay differs')
    curriculum_owner.validate_curriculum(source_plan, plan_rows, tokenizer=source_plan['tokenizer'],
        output_limit=512, expected_codec_sha256=core.digest(donor['codec']),
        expected_rows_sha256=curriculum_owner.digest(plan_rows))
    rows, references = {}, {}
    for split in ('train', 'validation'):
        references[split] = [dict(id=row['id'], source_text=row['source_text'], source_sha256=row['source_sha256'],
            target=row['target'], clause_count=row['clause_count']) for row in corpus[split]]
        rows[split] = [dict(id=row['id'], source_text=row['source_text'], target_ids=row['target_ids'],
            input=by_id[row['id']]['vector']) for row in corpus[split]]
        require(len(rows[split]) == 48 and all(by_id[row['id']]['status']=='embedded' for row in rows[split]), 'complete48row panel required')
    require(not {core.digest(r['input']) for r in rows['train']} & {core.digest(r['input']) for r in rows['validation']}, 'input-vector split leakage')
    stages, previous = [], set()
    for stage in source_plan['stages']:
        if stage['training_ids'] and set(stage['training_ids']) != previous:
            stages.append(dict(name=stage['stage_id'], training_ids=stage['training_ids'], epochs=plan['epochs_per_source_stage']))
            previous = set(stage['training_ids'])
    require(previous == {row['id'] for row in rows['train']}, 'curriculum dropped training rows')
    validator_id = 'canonical-single-rule-sha256:'+sha(legal_formula_codec.__file__)
    def validate_rule(target):
        legal_formula_codec._rule(target)
        return dict(valid=True, canonical_ir=target)
    base_model = prior.private_teacher(donor, numerical, core)
    lineage = dict(teacher_checkpoint_sha256=sha(donor_path), teacher_codec_sha256=core.digest(donor['codec']),
        input_provenance_sha256=sha(manifest['embeddings']), domain='legal_ir',
        teacher_lineage='private_original_source384_numerical_replay', student_lineage='long_source_fidelity_v1',
        teacher_output_limit=512, student_role='source_conditioned_decoder')
    return locals()
