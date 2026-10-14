"""Pure rejection fixtures; never call the publisher main, SDK or network."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

F = Path(__file__).resolve().parent
SOURCE = F / 'resume_actor_refinement_hf_v01.py'
spec = importlib.util.spec_from_file_location('_resume_fixture_only', SOURCE)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
CASES = []


def raw_identity(raw, lfs=False):
    return dict(size=len(raw), blob_id=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                lfs=None if not lfs else dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), pointer_size=128))


def fixture():
    names = [m.PREFIX + '/fixture/' + str(i) + '.txt' for i in range(198)]
    names[19] = m.CHECKPOINT_NAME
    sizes = [18, 8, 12, 23, 48, 48, 41]; groups = []; start = 0
    for n in sizes: groups.append(names[start:start+n]); start += n
    payload = {name: ('opaque fixture ' + str(i)).encode() for i, name in enumerate(names)}
    original = {'original/' + str(i): raw_identity(('prior ' + str(i)).encode()) for i in range(5447)}
    original['.gitattributes'] = copy.deepcopy(m.OLD_ATTRIBUTES)
    first = dict(parent_revision=m.BASELINE_REVISION, revision=m.FIRST_REVISION, names=groups[0])
    second = dict(parent_revision=m.FIRST_REVISION, revision=m.PARTIAL_REVISION, names=groups[1])
    verified = dict(parent_revision=m.BASELINE_REVISION, revision=m.FIRST_REVISION,
                    new_files=18, old_identities_exact=True, new_byte_identities_exact=True)
    current = copy.deepcopy(original); current['.gitattributes'] = copy.deepcopy(m.PARTIAL_ATTRIBUTES)
    current.update({name: raw_identity(payload[name], name == m.CHECKPOINT_NAME) for group in groups[:2] for name in group})
    snapshot = dict(schema='actor-refinement-Hub-partial-immutable-snapshot/v1', repository=m.REPO,
        requested_revision=m.PARTIAL_REVISION, returned_revision=m.PARTIAL_REVISION, metadata_queries=1, files=current)
    return [original, snapshot, payload, groups, first, second, verified]


def good(label, call):
    call(); CASES.append(dict(name=label, passed=True, expected='accepted'))


def reject(label, call):
    try: call()
    except (ValueError, KeyError, TypeError):
        CASES.append(dict(name=label, passed=True, expected='refused')); return
    raise AssertionError(label + ': mutation was accepted')


def mutate_partial(label, change):
    values = fixture(); change(values)
    reject(label, lambda: m.qualify_partial(*values))


def main():
    values = fixture()
    good('exact5474partial_including_opaque_LFS_payload', lambda: m.qualify_partial(*values))
    mutate_partial('unexpected_remote_path', lambda v: v[1]['files'].update({'unexpected': raw_identity(b'x')}))
    mutate_partial('missing_original_path', lambda v: v[1]['files'].pop('original/0'))
    mutate_partial('changed_other_original', lambda v: v[1]['files']['original/0'].update(size=999))
    mutate_partial('wrong_partial_attributes', lambda v: v[1]['files']['.gitattributes'].update(size=999))
    mutate_partial('missing_created_payload', lambda v: v[1]['files'].pop(v[3][0][0]))
    mutate_partial('wrong_created_raw_Git_hash', lambda v: v[1]['files'][v[3][0][0]].update(blob_id='0'*40))
    mutate_partial('wrong_created_LFS_sha256', lambda v: v[1]['files'][m.CHECKPOINT_NAME]['lfs'].update(sha256='0'*64))
    mutate_partial('wrong_created_LFS_size', lambda v: v[1]['files'][m.CHECKPOINT_NAME]['lfs'].update(size=0))
    mutate_partial('wrong_partial_revision', lambda v: v[1].update(returned_revision='0'*40))
    mutate_partial('boolean_metadata_query_count', lambda v: v[1].update(metadata_queries=True))
    mutate_partial('wrong_second_parent', lambda v: v[5].update(parent_revision=m.BASELINE_REVISION))
    mutate_partial('wrong_second_names', lambda v: v[5].update(names=v[3][0]))
    mutate_partial('original_chunk1_failure_not_success', lambda v: v[6].update(old_identities_exact=False))
    mutate_partial('duplicate_original_chunk_name', lambda v: v[3][2].__setitem__(0, v[3][0][0]))
    mutate_partial('different_original_group_geometry', lambda v: v[3][0].pop())
    mutate_partial('missing_original_attributes', lambda v: v[0].pop('.gitattributes'))
    values = fixture(); original, snapshot, payload, groups = values[:4]
    additions = m.qualify_partial(*values); restored = {**original, **additions}
    good('strict_all5448plus26_restored_identity_equality', lambda: m.qualify_restored(restored, original, additions))
    wrong = copy.deepcopy(restored); wrong['.gitattributes'] = copy.deepcopy(m.PARTIAL_ATTRIBUTES)
    reject('automatic_attributes_delta_reappears_after_correction', lambda: m.qualify_restored(wrong, original, additions))
    wrong = copy.deepcopy(restored); wrong[groups[0][0]]['blob_id'] = '0'*40
    reject('created_payload_identity_changes_in_correction', lambda: m.qualify_restored(wrong, original, additions))
    wrong = copy.deepcopy(restored); wrong['unexpected'] = raw_identity(b'x')
    reject('correction_adds_unapproved_path', lambda: m.qualify_restored(wrong, original, additions))
    names = groups[2]; after = {**restored, **{name: raw_identity(payload[name]) for name in names}}
    good('next_original_chunk_only', lambda: m.qualify_chunk(after, restored, names, payload))
    wrong = copy.deepcopy(after); wrong['.gitattributes'] = copy.deepcopy(m.PARTIAL_ATTRIBUTES)
    reject('automatic_attributes_delta_reappears_during_resume', lambda: m.qualify_chunk(wrong, restored, names, payload))
    reject('previously_created_chunk_cannot_repeat', lambda: m.qualify_chunk(after, restored, groups[0], payload))
    reject('duplicate_new_names', lambda: m.qualify_chunk(after, restored, names + names[:1], payload))
    wrong = copy.deepcopy(after); wrong[names[0]]['blob_id'] = '0'*40
    reject('new_chunk_bytes_differ', lambda: m.qualify_chunk(wrong, restored, names, payload))
    wrong = copy.deepcopy(after); wrong.pop('original/0')
    reject('old_path_removed_by_resume', lambda: m.qualify_chunk(wrong, restored, names, payload))
    wrong = copy.deepcopy(after); wrong['unapproved'] = raw_identity(b'x')
    reject('extra_path_added_by_resume', lambda: m.qualify_chunk(wrong, restored, names, payload))
    attrs = json.loads((F / 'hf-attributes-immutable-readback-independent-v01.json').read_text())
    baseline_raw = Path(attrs['files']['baseline']['path']).read_bytes()
    partial_raw = Path(attrs['files']['chunk02']['path']).read_bytes()
    good('actual_public_attributes_2230plus129_exact', lambda: m.qualify_attributes(attrs, baseline_raw, partial_raw, original, snapshot['files']))
    reject('baseline_attributes_raw_byte_drift', lambda: m.qualify_attributes(attrs, baseline_raw + b'x', partial_raw, original, snapshot['files']))
    reject('partial_attributes_raw_byte_drift', lambda: m.qualify_attributes(attrs, baseline_raw, partial_raw + b'x', original, snapshot['files']))
    wrong = copy.deepcopy(attrs); wrong['removed_lines'] = ['removed']
    reject('attributes_line_removal_disallowed', lambda: m.qualify_attributes(wrong, baseline_raw, partial_raw, original, snapshot['files']))
    wrong = copy.deepcopy(attrs); wrong['files']['baseline']['immutable_download_byte_identity_matches'] = False
    reject('unverified_baseline_attributes_disallowed', lambda: m.qualify_attributes(wrong, baseline_raw, partial_raw, original, snapshot['files']))
    reject('malformed_returned_revision', lambda: m.revision('not-a-revision'))
    tree = ast.parse(SOURCE.read_text()); main_ast = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    text = ast.unparse(main_ast)
    assert "'--force-download'" in text and "'hf-verified-download-v02'" in text
    assert "groups[2:]" in text and "'.gitattributes'" in text and "parent_commit=current" in text
    assert 'CommitOperationDelete' not in text and 'automatic_retry_performed=False' in text
    assert "discrepancy['passed'] is False" in text and "discrepancy['reconciliation_completed'] is True" in text
    assert 'checkpoint_JSON_parses=0' in text and 'Git_clone_LFS_automatic_materialization_qualified=False' in text
    assert [n for n in ast.walk(main_ast) if isinstance(n, ast.ImportFrom) and n.module == 'huggingface_hub']
    CASES.append(dict(name='main_static_recovery_limits_force_download_and_failed_discrepancy', passed=True, expected='source_only'))
    def pin(path):
        raw=path.read_bytes();return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    result = dict(schema='actor-refinement-Hub-resume-author-controls/v1', passed=True, findings=[],
        source=pin(SOURCE), tests=pin(Path(__file__).resolve()), controls=CASES, count=len(CASES),
        scope='Pure synthetic5474identity and chunk fixtures plus exact public attributes byte fixtures and static main limits only.',
        publisher_main_calls=0, SDK_imports=0, network_calls=0, uploads=0, checkpoint_JSON_parses=0, model_calls=0,
        private_body_reads=0, public_raw_attributes_reads=2)
    output = F / 'actor-refinement-hf-resume-author-controls-v01.json'
    raw=(json.dumps(result, indent=2, sort_keys=True)+'\n').encode()
    with output.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    output.chmod(0o444);print(json.dumps(pin(output)))


if __name__ == '__main__':
    main()
