"""Hash-bind both completed output bundles before authored evaluation scoring.

Model states are raw-hashed only; authored reference descriptors are copied
from registration. This performs no inference, optimizer update or admission.
"""
import hashlib
import json
import os
from pathlib import Path

F = Path(__file__).resolve().parent
RUN = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def pin(path):
    require(path.resolve() == path and path.is_file() and not path.is_symlink(), 'physical ordinary input required')
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def read(path):
    require('checkpoint' not in path.name and 'reference-packet' not in path.name, 'model/reference JSON parsing forbidden')
    return json.loads(path.read_bytes())

def main():
    output = F/'two-cell-output-freeze-v01.json'
    require(not output.exists(), 'exclusive freeze required')
    registration = read(F/'registration-v01.json')
    manifest = dict(schema='permission-retention-two-cell-freeze/v1', all_two_outputs_frozen=True,
        authorizes_authored_eval_scoring=True, new_pair_outputs_scored_before_freeze=False, reference_packet_previously_scored=True,
        freeze_scope="new_two_cell_outputs_only; references previously exposed",
        independent_blinding=False, reference_builder_author_visible=True,
        runner=pin(F/'run_permission_retention.py'), registration=pin(F/'registration-v01.json'),
        training_export=pin(F/'training-export-v01.json'), reference_packet=registration['reference_packet'], cells=[])
    for cell in ("all-parameters", "span-heads-only"):
        plan_path=F/(cell+'-plan-v01.json');plan=read(plan_path)
        attempt=RUN/plan['attempt_name'];results=attempt/'results'
        summary_path=results/'summary.json';summary=read(summary_path)
        terminal_path=attempt/'guardian-exit.json';terminal=read(terminal_path)
        require(summary['status']=='completed' and summary['actual_new_updates']==32
                and summary['cell']==plan['cell'] and summary['actual_encoder_calls']==0,
                'completed32 exactcell source-only required')
        require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
                and terminal['returncode']==terminal['child_returncode']==0
                and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
                'successful durable released guardian required')
        files=list(results.iterdir())
        require(all(path.is_file() and not path.is_symlink() and path.suffix=='.json' for path in files),
                'closed ordinary JSON result inventory required')
        expected={'cell-checkpoint.json','cell-training.json','data-schedule-before-models.json','summary.json','trained-modality-retention.json'}
        for stage in ('initial','trained'):
            expected.add(stage+'-parity.json')
            expected.update(stage+'-parity-'+control+'.json' for control in
                            ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
        for state in (('baseline','trained') if cell=='all-parameters' else ('trained',)):
            for panel in ('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law'):
                expected.update(state+'-'+panel+'-'+kind+'.json' for kind in ('raw','joint'))
                if panel not in ('authored_eval','law'):expected.add(state+'-'+panel+'-score.json')
        require({path.name for path in files}==expected and len(expected)==(53 if cell=='all-parameters' else 34),
                'exact first/reuse result paths required')
        inventory={}
        for path in sorted(files):
            value=pin(path);inventory[str(path)]={key:value[key] for key in ('bytes','sha256')}
        manifest['cells'].append(dict(cell=plan['cell'],plan=pin(plan_path),summary=pin(summary_path),
            guardian_terminal=pin(terminal_path),pre_admission=pin(attempt/'pre-admission.json'),results=inventory))
    for cell in manifest['cells']:
        for name,expected in cell['results'].items():
            require({key:pin(Path(name))[key] for key in ('bytes','sha256')}==expected, 'result drift before freeze')
    with output.open('x') as stream:
        json.dump(manifest,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    output.chmod(0o444)
    fd=os.open(F,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    print(json.dumps(dict(status='two_outputs_frozen_before_eval_scoring',cells=2,updates=64,results=87,manifest=pin(output))))

if __name__=='__main__':
    main()
