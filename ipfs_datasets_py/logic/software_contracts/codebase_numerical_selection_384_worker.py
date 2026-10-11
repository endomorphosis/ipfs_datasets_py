"""Bounded isolated CPU embedding and the unchanged experimental CALL decoder."""
from __future__ import annotations

from contextlib import redirect_stdout
from importlib.metadata import version as package_version
import json
import os
import sys


def execute(request):
    from . import codebase_numerical_selection_384 as owner
    from ..formalization.autoencoder import numerical_selection_384 as profile
    import torch

    owner.require(type(request) is dict and set(request) == {'schema', 'key', 'checkpoint', 'rows'}
        and request['schema'] == owner.WORKER_SCHEMA, 'closed numerical worker request required')
    key, rows = request['key'], request['rows']
    owner.require(key['python'] == sys.version and key['runtime_versions'] == {
        n: package_version(n) for n in ('torch', 'numpy', 'transformers', 'sentence-transformers', 'tokenizers')},
        'numerical native runtime versions differ')
    owner.require(key['producer'] == owner.pins() and key['device'] == 'cpu'
        and os.environ.get('CUDA_VISIBLE_DEVICES') == '' and not torch.cuda.is_available(),
        'exact numerical producer and explicit CPU profile required')
    owner.require(key['release'] == owner.RELEASE and key['checkpoint_file_sha256'] == owner.RELEASE['checkpoint_file_sha256']
        and profile._digest(request['checkpoint']) == key['checkpoint_canonical_sha256'],
        'explicit numerical release checkpoint differs')
    runtime = profile.NumericalSelectionRuntime384(request['checkpoint'])
    owner.require(type(rows) is list and len(rows) <= owner.MAX_SELECTED
        and all(type(r) is dict and set(r) == {'path', 'unit_id', 'source_text'}
            and type(r['source_text']) is str and 0 < len(r['source_text']) <= 16384 for r in rows)
        and len({r['unit_id'] for r in rows}) == len(rows), 'bounded original-module source rows required')
    for row in rows:
        profile.prepare_selection_unit(source_bytes=row['source_text'].encode(), path=row['path'], unit_id=row['unit_id'])
    snapshot, assets = owner.embeddings._snapshot_assets(key['embedding_snapshot'])
    owner.require(assets == key['embedding_assets'], 'numerical embedding assets differ')
    receipt = None
    if rows:
        with owner._embedding_inputs(rows) as (inputs, resolver):
            receipt = owner.embeddings.produce_native_embedding_receipt(
                inputs, resolver=resolver, snapshot_path=snapshot, batch_size=16).to_dict()
    by_source = owner._embedding_rows(receipt, rows, key)
    result, selected = [], []
    for row in rows:
        digest = owner.sha(row['source_text'].encode())
        embedded = by_source[digest]
        item = dict(path=row['path'], unit_id=row['unit_id'], source_sha256=digest,
            embedding_input_id=embedded['input_id'], candidate=None, status='deferred_gte_token_limit',
            tokens=(len(embedded['tokens']['input_ids']) if embedded['status'] == 'embedded'
                else embedded['tokens']['token_count']))
        result.append(item)
        if embedded['status'] == 'embedded':
            selected.append((dict(**row, embedding=list(owner.codec._decode_vector(embedded['vector']))), item))
    inference = runtime.infer([r for r, _ in selected]) if selected else None
    if inference is not None:
        owner.require(len(inference['rows']) == len(selected), 'numerical decoder omitted predictions')
        for (_, item), candidate in zip(selected, inference['rows']):
            item.update(candidate=candidate, status=candidate['status'])
    owner.require(owner.embeddings._snapshot_assets(snapshot)[1] == assets and key['producer'] == owner.pins(),
        'numerical embedding assets or producer changed')
    return dict(schema=owner.WORKER_SCHEMA, key=key, rows=result, embedding_receipt=receipt,
        inference=inference, model_loads=int(bool(rows)), **owner.FALSE)


def main():
    sys.path[:0] = json.loads(sys.argv[1])
    with redirect_stdout(sys.stderr):
        from ipfs_datasets_py.logic.software_contracts import codebase_numerical_selection_384 as owner
        from ipfs_datasets_py.logic.software_contracts.codebase_numerical_selection_384_worker import execute as run
        data = sys.stdin.buffer.read(owner.MAX_BYTES + 1)
        owner.require(len(data) <= owner.MAX_BYTES, 'numerical worker input exceeds bound')
        output = owner.raw(run(owner.codec._parse(data)))
        owner.require(len(output) <= owner.MAX_BYTES, 'numerical worker output exceeds bound')
    sys.stdout.buffer.write(output)


if __name__ == '__main__':
    main()
