"""Explicit reviewed native hf upload, followed by metadata-only immutable checks."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

import publication_common as c


def remote_snapshot(native, api, repository, revision=None):
    sha, private, rows = native._info(api, repository, revision)
    info = api.model_info(repository, revision=sha, files_metadata=False)
    files = {}
    for path, row in rows.items():
        lfs = native._field(row, 'lfs')
        files[path] = dict(bytes=native._field(row, 'size'),
            git_blob_oid=native._field(row, 'blob_id', 'blobId'),
            lfs_sha256=native._field(lfs, 'sha256') if lfs is not None else None,
            lfs_bytes=native._field(lfs, 'size') if lfs is not None else None)
        c.require(type(files[path]['bytes']) is int and type(files[path]['git_blob_oid']) is str,
            'full prior remote file identity required')
    return dict(repository_id=repository, revision=sha, file_identities=files,
        settings=dict(private=private, gated=getattr(info, 'gated', None), disabled=getattr(info, 'disabled', None)))


class ReadOnlyExistingApi:
    """Native publisher may only verify already uploaded exact bytes."""
    def __init__(self, api, repository, revision):
        self.api, self.repository, self.revision = api, repository, revision

    def model_info(self, repository, **kwargs):
        c.require(repository == self.repository, 'unexpected repository access')
        if kwargs.get('revision') is None:
            kwargs['revision'] = self.revision
        c.require(kwargs['revision'] == self.revision, 'immutable verification revision differs')
        return self.api.model_info(repository, **kwargs)

    def create_repo(self, *args, **kwargs):
        raise ValueError('repository creation forbidden')

    def create_commit(self, *args, **kwargs):
        raise ValueError('native verifier mutation forbidden')


def verify_prefix(native, plan, frozen, snapshot, *, prefix=c.PREFIX):
    paths = {op['path_in_repo'] for op in plan['operations']}
    remote_paths = {p for p in snapshot['file_identities'] if p.startswith(prefix + '/')}
    c.require(not remote_paths - paths, 'unexpected existing experiment-prefix files')
    c.require(not remote_paths or remote_paths == paths, 'partial existing prefix requires a separate reviewed recovery')
    if not remote_paths:
        return False
    for operation in plan['operations']:
        # Native verifier authenticates LFS SHA256 or Git blob SHA1 against these bytes.
        identity = snapshot['file_identities'][operation['path_in_repo']]
        raw = c.read(operation['file_pin'])
        expected_blob = c.hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        c.require(identity['bytes'] == len(raw) and
            (identity['lfs_sha256'] == operation['file_pin']['sha256'] if identity['lfs_sha256'] is not None
                else identity['git_blob_oid'] == expected_blob), 'existing prefix bytes differ; overwrite forbidden')
    return True


def check_preserved(before, after, expected_paths):
    c.require(before['settings'] == after['settings'], 'repository visibility/settings changed')
    c.require(all(after['file_identities'].get(p) == row for p, row in before['file_identities'].items()),
        'prior remote file identity changed')
    added = set(after['file_identities']) - set(before['file_identities'])
    c.require(added <= set(expected_paths), 'unexpected remote additions during cooperative operation')


def fence_preparation(preparation_pin, prep, native):
    c.require(c.document(preparation_pin) == prep and prep['source_pins'] == c.source_pins(), 'prepared source changed')
    auth = c.document(prep['authentication_pin'])
    c.fence(auth['protected_input_pins'] + prep['source_pins'] + prep['staged_file_pins'])
    c.historical_source_fence(auth.get('historical_shared_or_large_source_input_pins', []))
    c.require(c.load_native('ir_model_hub_publish')[1] == prep['native_publisher_owner'], 'native publisher source differs')
    contract = c.inventory_contract(prep['schema'])
    c.require(prep['release_prefix'] == contract['prefix'], 'closed inventory prefix differs')
    for plan_pin in prep['plan_pins']:
        plan = native._capture_plan(c.document(plan_pin))
        native._freeze_files(plan)
        folder = Path(plan['manifest_pin']['path']).parent
        c.exact_stage_files(folder, [op['path_in_repo'][len(contract['prefix']) + 1:] for op in plan['operations']])


def validate_review(value, preparation_pin, prep):
    c.require(value.get('schema') == 'dual-bank-publication-driver-review/v1'
        and value.get('approved') is True and value.get('findings') == [], 'approved independent publication review required')
    expected = dict(reviewed_preparation_pin=preparation_pin, reviewed_source_pins=prep['source_pins'],
        reviewed_native_publisher_owner=prep['native_publisher_owner'],
        reviewed_authentication_pin=prep['authentication_pin'], reviewed_plan_pins=prep['plan_pins'],
        reviewed_staged_file_pins=prep['staged_file_pins'])
    for key, answer in expected.items():
        c.require(c.wire(value.get(key)) == c.wire(answer), 'independent publication review bytes differ: ' + key)


def checked_cli(arguments, *, timeout=600):
    c.require(type(arguments) is list and arguments[:2] in (['hf', 'upload'], ['hf', 'download'])
        and '--token' not in arguments, 'fixed native CLI command required')
    value = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout, check=False)
    # Provider output/exception details may contain credentials: keep them off disk and stdout.
    c.require(value.returncode == 0, 'native hf CLI failed; provider output suppressed')
    return value.stdout.decode('utf-8', errors='strict').strip()


def published_revision(output, repository):
    # Quiet upload emits an immutable commit URL. A mutable branch URL is refused.
    matches = re.findall(r'https://huggingface\.co/' + re.escape(repository)
        + r'/commit/([0-9a-f]{40})(?:\s|$)', output)
    c.require(len(matches) == 1, 'CLI must return one exact immutable commit URL')
    return matches[0]


def publish_stage(preparation_pin, review_pin, output_dir, *, download=True):
    out = Path(output_dir)
    c.require(out.is_absolute() and not out.exists(), 'fresh absolute publication-attempt directory required')
    prep = c.document(preparation_pin)
    contract = c.inventory_contract(prep['schema'])
    prefix = contract['prefix']
    c.require(prep['schema'] == contract['publication_schema'] and prep['complete'] is True
        and prep['repository_ids'] == list(c.REPOSITORIES) and prep['release_prefix'] == prefix,
        'exact reviewed public experiment required')
    validate_review(c.document(review_pin), preparation_pin, prep)
    native, _ = c.load_native('ir_model_hub_publish')
    fence_preparation(preparation_pin, prep, native)
    out.mkdir(parents=True)
    from huggingface_hub import HfApi
    api = HfApi(endpoint='https://huggingface.co')
    receipt_pins = []
    phase, upload_possible = 'remote_preflight', False
    try:
        for index, plan_pin in enumerate(prep['plan_pins']):
            plan = native._capture_plan(c.document(plan_pin))
            frozen = native._freeze_files(plan)
            repository = plan['repository_id']
            c.require(repository == c.REPOSITORIES[index] and all(op['path_in_repo'].startswith(prefix + '/')
                for op in plan['operations']), 'closed repository/prefix plan differs')
            c.read(review_pin)
            fence_preparation(preparation_pin, prep, native)
            before = remote_snapshot(native, api, repository)
            c.require(before['settings']['private'] is False, 'existing public repository required')
            c.require(remote_snapshot(native, api, repository, 'main') == before,
                'existing main branch must match observed repository head before CLI upload')
            complete = verify_prefix(native, plan, frozen, before, prefix=prefix)
            c.write(out / (str(index) + '-before.json'), before)
            if complete:
                revision = before['revision']
            else:
                # hf CLI exposes no parent_commit. The exact prefix and full before/after
                # fences are cooperative; they cannot prevent a concurrent same-path race.
                c.require(remote_snapshot(native, api, repository) == before, 'remote head changed before CLI append')
                phase, upload_possible = 'native_cli_upload', True
                answer = checked_cli(['hf', 'upload', repository, str(Path(plan['manifest_pin']['path']).parent),
                    prefix, '--type', 'model', '--revision', 'main', '--commit-message',
                    'Retain experimental authored LegalIR384 wording checkpoints', '--quiet'])
                revision = published_revision(answer, repository)
            phase = 'native_idempotent_verification'
            after = remote_snapshot(native, api, repository, revision)
            check_preserved(before, after, [op['path_in_repo'] for op in plan['operations']])
            c.require(verify_prefix(native, plan, frozen, after, prefix=prefix), 'complete immutable publication required')
            receipt = native.publish_ir_model_hub_release(plan, api=ReadOnlyExistingApi(api, repository, revision))
            c.require(receipt['idempotent_reuse'] is True and not receipt['created_paths']
                and receipt['revision'] == revision, 'native publisher must verify only already present bytes')
            native_pin = c.write(out / (repository.replace('/', '--') + '-native-receipt.json'), receipt)
            downloads = []
            if download:
                phase = 'immutable_cli_byte_download'
                directory = out / 'downloads' / repository.replace('/', '--')
                for operation in plan['operations']:
                    checked_cli(['hf', 'download', repository, operation['path_in_repo'], '--repo-type', 'model',
                        '--revision', revision, '--local-dir', str(directory), '--quiet'])
                    downloaded = c.capture(directory / operation['path_in_repo'])
                    c.require((downloaded['bytes'], downloaded['sha256']) ==
                        (operation['file_pin']['bytes'], operation['file_pin']['sha256']), 'immutable download bytes differ')
                    downloads.append(downloaded)
            fence_preparation(preparation_pin, prep, native)
            c.read(review_pin)
            c.write(out / (repository.replace('/', '--') + '-verification.json'),
                dict(schema='dual-bank-cli-publication-verification/v1', complete=True, repository_id=repository,
                    revision=revision, native_publication_receipt_pin=native_pin,
                    preparation_pin=preparation_pin, review_pin=review_pin,
                    native_cli_upload_executed=not complete, immutable_download_pins=downloads,
                    all_prior_remote_file_identities_preserved=True, existing_visibility_preserved=True,
                    root_readme_or_defaults_replaced=False,
                    native_verifier_repository_creation_attempted=False,
                    cli_existing_repository_create_exist_ok_call_performed=not complete,
                    new_repository_observed=False, main_branch_observed_before_upload=True,
                    cooperative_endpoint_scope=True, atomic_parent_commit_fence_available_in_cli=False,
                    model_numerically_loaded=False, database_write_executed=False, **c.AUTHORITY))
            receipt_pins.append(native_pin)
        return c.write(out / 'publication-result.json', dict(schema='dual-bank-publication-result/v1',
            complete=True, preparation_pin=preparation_pin, review_pin=review_pin,
            native_publication_receipt_pins=receipt_pins, cross_repository_transaction_atomic=False, **c.AUTHORITY))
    except BaseException as error:
        c.write(out / 'failure.json', dict(phase=phase, failure_type=type(error).__name__,
            hub_may_have_changed=upload_possible, completed_native_receipt_pins=receipt_pins,
            provider_details_suppressed=True, no_automatic_retry_or_rollback=True))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', required=True, help='absolute file path=SHA256')
    parser.add_argument('--review-receipt', required=True, help='absolute file path=SHA256')
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--skip-download', action='store_true')
    args = parser.parse_args()
    preparation, review = c.argument_pin(args.preparation), c.argument_pin(args.review_receipt)
    if not args.publish:
        prep = c.document(preparation)
        native, _ = c.load_native('ir_model_hub_publish')
        validate_review(c.document(review), preparation, prep)
        fence_preparation(preparation, prep, native)
        print(c.wire(dict(status='offline_preflight_only', network_executed=False, database_write_executed=False)))
        return
    result = publish_stage(preparation, review, args.output_directory, download=not args.skip_download)
    print(c.wire(dict(complete=True, result_pin=result)))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(c.wire(dict(failed=True, failure_type=type(error).__name__, provider_details_suppressed=True)), file=sys.stderr)
        raise SystemExit(1)
