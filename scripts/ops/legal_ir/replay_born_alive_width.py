"""Frozen, source-bound 384D/768D engineering replay; no legal quality claim.

The source occurrences are exact complete subsections of two pinned parents.
Both native producers retain their 512-token admission/actual-forward checks.
The selected decoder's frozen residual projection is identity by construction:
its cosine/MSE are an engineering diagnostic, never learned reconstruction.
Validation independently repeats production and selected-model inference.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import hashlib
import importlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
import zipfile


SCHEMA = 'legal-ir-born-alive-selected-width-replay/v1'
RECEIPT_SCHEMA = 'legal-ir-supervisor-task-receipt/v1'
SCOPE = 'identity_by_construction_not_learned_reconstruction'
REVISION = '5016b86a273ce5e4ffd066c5ae9f5fe494dd417e'
PARQUET_SHA256 = '4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8'
PARQUET = Path('/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots') / REVISION / 'uscode_parquet/laws.parquet'
CANONICAL = Path('/home/barberb/lift_coding/external/ipfs_datasets')
SNAPSHOT384 = '/home/barberb/.cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd'
ASSETS768 = Path('/home/barberb/lift_coding/artifacts/autoformalization-alignment-20261003/richer-encoder-assets')
ASSET_MANIFEST_SHA256 = '8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166'
DONOR = Path('/home/barberb/lift_coding/artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json')
DONOR_SHA256 = '6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61'
MAX_RAW_CHECKPOINT = 5 * 1024**2
MAX_CHECKPOINT_ARCHIVE = 4 * 1024**2
FALSE = dict(training_executed=False, admitted=False, formalized=False,
             quality_qualified=False, source_semantics_verified=False,
             statutory_fidelity_qualified=False, learned_reconstruction_demonstrated=False,
             target_representability_verified=False, proof_authority=False)
PROFILES = {
    384: dict(profile_id='retained_contextual_384',
        checkpoint_sha256='0ac5c21656187d1d8040a02bcc0b4716a8093db17f05adc9a22e99d5b6b2cc00',
        checkpoint_bytes=2799098, preprocessing_bytes=1510086,
        preprocessing_sha256='de96c5f0a90a1472e346f3732ace42f0b4af4b3915026695fb705ae809663d8f'),
    768: dict(profile_id='retained_contextual_768',
        checkpoint_sha256='8892a3261c0750a6247ba5400069ed18cad3354426e2095ed1d295287e3559b4',
        checkpoint_bytes=4781613, preprocessing_bytes=2864122,
        preprocessing_sha256='f4acb7b6b20a38c226a509e331d638fa667c929bd5b8970be44048d549f072ae'),
}
SOURCES = (
    dict(id='born-alive-10-1059-n', title='10', section='1059', legal_id='usc:us:10:1059',
        parent_sha256='6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2',
        start='(n) Dependent Child Defined', end=' (Added Pub. L. 103'),
    dict(id='born-alive-1-8-b', title='1', section='8', legal_id='usc:us:1:8',
        parent_sha256='fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a',
        start='(b) As used in this section', end=' (c) Nothing in this section'),
)
_BLOBS384 = (
    ('d1514c3162bbe87b343f565fadc62e6c06f04f03',190,'4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23'),
    ('bcc565b3b20a79e17f048e97717303f26ea833e5',583,'00273cdfb3e05c7304d180270bdef8adae45023e7bdfc396338bdd815943dc59'),
    ('9a1eb90bbac323ea08aa5629b624fe6ae75db121b904799c2266a1e2c2de22d2',66746168,'9a1eb90bbac323ea08aa5629b624fe6ae75db121b904799c2266a1e2c2de22d2'),
    ('db4787d654117aedec30099876bfa6431eb39827',385,'73348a3d8f8ae4cc5f851dc6b98be3ea819390b814e83656d5eebbadf75fe43e'),
    ('4eca68d85ecd3034cf4174d8a4033a75344ea62d',57,'948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529'),
    ('a8b3208c2884c4efb86e49300fdd3dc877220cdf',125,'b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3'),
    ('c17ed520ed8438736732a54957a69306b8822215',711661,'da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0'),
    ('42046bd361a033a24264dc41de1fe6cafd68072f',394,'e1790949631401af1bfb6c9c7aeec7fcf612e274d73579d99f704faea40c8ba7'),
    ('fb140275c155a9c7c5a3b3e0e77a9e839594a938',231508,'07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'),
)
_FILES768 = (
    ('model/config.json',1429,'711bdc81365fc25d30533cf05b9fdf588e5ba01f18540fbbb1307d787597a313'),
    ('model/tokenizer_config.json',1149,'24cebbf2ef20fc317256e03e52ac7b2ca326586f946a8427ecac036332bf0933'),
    ('model/special_tokens_map.json',964,'8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835'),
    ('model/tokenizer.json',17082756,'f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af'),
    ('model/model.safetensors',610753338,'f5a35a10faa54da7717870af1517c9b41e9bd8e3880bc5a8e9363d4c3c63e9b0'),
    ('code/configuration.py',7127,'3411088045ffb8a9a0aa9936eae275896b39983a2ee5b08f091b44e6289e4fe4'),
    ('code/modeling.py',59023,'374670b416fcc82f081c9cd28b5fd61c2bd91bbe18eb4798fcc48a81f9c250a0'),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def file_pin(path, maximum=1024**3):
    path = Path(path).resolve(strict=True)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            'bounded nonempty ordinary input file required')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'input changed while hashing')
    return dict(path=str(path), bytes=before.st_size, sha256=digest)


def write_new(directory, name, payload):
    path = Path(directory) / name
    payload = payload if isinstance(payload, bytes) else wire(payload) + b'\n'
    with path.open('xb') as stream:
        stream.write(payload)
    return file_pin(path)


def dimension_for(task_id):
    require(task_id in ('LIRAE-WIDTH-384', 'LIRAE-WIDTH-768'),
            'only separately approved frozen384/768 replay is supported')
    return int(task_id.rsplit('-', 1)[1])


def required_input_file_pins(dimension):
    """Fixed trusted byte/hash expectations; no file reads, imports or writes.

    Canonical blob locators are literal retained identities, rather than
    resolving mutable snapshot symlinks or trusting hashes of current bytes.
    """
    require(type(dimension) is int and dimension in PROFILES, 'only native384/768 pins exist')
    profile = PROFILES[dimension]
    selected = CANONICAL / ('workspace/test-logs/decoder-selected-continuation-20261004/'
        f'training-r1/results/{dimension}-selected-followup-lr0001-1729/selected-state.json')
    preprocessing = CANONICAL / ('workspace/test-logs/decoder-four-width-20261004/'
        f'training-r1/results/{dimension}/preprocessing.json')
    entries = [(selected,profile['checkpoint_bytes'],profile['checkpoint_sha256']),
        (preprocessing,profile['preprocessing_bytes'],profile['preprocessing_sha256']),
        (DONOR,614534,DONOR_SHA256),
        (Path('/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/blobs')/PARQUET_SHA256,
         374277662,PARQUET_SHA256)]
    if dimension == 384:
        blob_root=Path('/home/barberb/.cache/huggingface/hub/models--thenlper--gte-small/blobs')
        entries.extend((blob_root/name,count,digest) for name,count,digest in _BLOBS384)
    else:
        entries.extend((ASSETS768/name,count,digest) for name,count,digest in _FILES768)
        entries.append((CANONICAL/'configs/autoencoders/gte_multilingual_local_assets_v1.json',
                        1470,ASSET_MANIFEST_SHA256))
    return [dict(path=str(path),bytes=count,sha256=digest) for path,count,digest
            in sorted(entries,key=lambda item:str(item[0]))]


def checkpoint_archive(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_RAW_CHECKPOINT,
            'bounded actual checkpoint bytes required')
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=False) as archive:
        item = zipfile.ZipInfo('checkpoint.json', date_time=(1980, 1, 1, 0, 0, 0))
        item.create_system = 3
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = (stat.S_IFREG | 0o600) << 16
        archive.writestr(item, raw, compresslevel=9)
    payload = target.getvalue()
    require(len(payload) <= MAX_CHECKPOINT_ARCHIVE, 'checkpoint archive exceeds bound')
    return payload


def unpack_checkpoint(payload, dimension):
    require(type(payload) is bytes and 0 < len(payload) <= MAX_CHECKPOINT_ARCHIVE,
            'bounded checkpoint ZIP required')
    # Reject multi-entry/trailing/ZIP64-directory tricks before ZipFile builds
    # an attacker-controlled central-directory object inventory.
    end = payload.rfind(b'PK\x05\x06', max(0,len(payload)-65557))
    require(end >= 0 and len(payload)-end >= 22, 'ordinary ZIP end record required')
    signature,disk,central_disk,on_disk,total,central_bytes,central_start,comment = struct.unpack(
        '<4s4H2IH',payload[end:end+22])
    require(disk == central_disk == 0 and on_disk == total == 1 and comment == 0
        and end+22 == len(payload) and central_start+central_bytes == end
        and central_bytes <= 4096, 'single bounded ordinary ZIP directory required')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        items = archive.infolist()
        require(len(items) == 1 and not archive.comment, 'exactly one checkpoint member required')
        item = items[0]
        require(item.filename == 'checkpoint.json' and not item.is_dir()
            and not item.flag_bits & 1 and item.compress_type == zipfile.ZIP_DEFLATED
            and stat.S_ISREG(item.external_attr >> 16)
            and 0 < item.file_size <= MAX_RAW_CHECKPOINT
            and item.file_size == PROFILES[dimension]['checkpoint_bytes'],
            'exact bounded checkpoint.json member required')
        with archive.open(item) as stream:
            raw = stream.read(MAX_RAW_CHECKPOINT + 1)
        require(len(raw) == item.file_size and sha(raw) == PROFILES[dimension]['checkpoint_sha256'],
                'actual selected checkpoint bytes differ')
    require(payload == checkpoint_archive(raw), 'deterministic checkpoint archive required')
    return raw


def independent_metrics(left, right):
    require(type(left) is list and type(right) is list and len(left) == len(right) > 0,
            'matching finite coordinate vectors required')
    require(all(type(value) is float and math.isfinite(value) for value in left + right),
            'ordinary finite floating coordinates required')
    with localcontext() as context:
        context.prec = 80
        a, b = [[Decimal.from_float(value) for value in row] for row in (left, right)]
        dot = sum(x*y for x, y in zip(a, b))
        norm = sum(x*x for x in a).sqrt() * sum(y*y for y in b).sqrt()
        require(norm > 0, 'cosine undefined for zero vector')
        return dict(cosine_similarity=float(dot / norm),
                    reconstruction_loss=float(sum((x-y)**2 for x, y in zip(a, b)) / len(a)))


def load_file_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure(root):
    root = Path(root).resolve(strict=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1', CUDA_VISIBLE_DEVICES='', TOKENIZERS_PARALLELISM='false',
        PYTHONDONTWRITEBYTECODE='1', IPFS_DATASETS_PY_MINIMAL_IMPORTS='1')
    sys.path.insert(0, str(root))
    return root


def preflight(root, task_id):
    """Authenticate dependencies/assets before any encoder/model execution."""
    dimension = dimension_for(task_id)
    root = configure(root)
    for name in ('torch', 'transformers', 'huggingface_hub', 'tokenizers',
                 'sentence_transformers', 'safetensors', 'pyarrow'):
        require(importlib.util.find_spec(name) is not None, 'missing numerical dependency: '+name)
    profile = PROFILES[dimension]
    checkpoint = CANONICAL / ('workspace/test-logs/decoder-selected-continuation-20261004/'
        f'training-r1/results/{dimension}-selected-followup-lr0001-1729/selected-state.json')
    preprocessing = CANONICAL / ('workspace/test-logs/decoder-four-width-20261004/'
        f'training-r1/results/{dimension}/preprocessing.json')
    pins = dict(checkpoint=file_pin(checkpoint, MAX_RAW_CHECKPOINT),
                preprocessing=file_pin(preprocessing, MAX_RAW_CHECKPOINT),
                donor_checkpoint=file_pin(DONOR, MAX_RAW_CHECKPOINT),
                source_parquet=file_pin(PARQUET))
    require(pins['checkpoint']['sha256'] == profile['checkpoint_sha256']
        and pins['checkpoint']['bytes'] == profile['checkpoint_bytes'], 'selected checkpoint unavailable or changed')
    require(pins['preprocessing']['sha256'] == profile['preprocessing_sha256']
        and pins['preprocessing']['bytes'] == profile['preprocessing_bytes'], 'selected preprocessing changed')
    require(pins['donor_checkpoint']['sha256'] == DONOR_SHA256
        and pins['source_parquet']['sha256'] == PARQUET_SHA256, 'donor or pinned parent corpus changed')
    if dimension == 384:
        owner = load_file_module('_born_alive384_asset_owner', root/
            'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py')
        snapshot, assets = owner._snapshot_assets(SNAPSHOT384)
        asset_receipt = dict(snapshot=str(snapshot), files=assets)
    else:
        owner = load_file_module('_born_alive768_asset_owner', root/
            'ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py')
        asset_receipt = owner.inspect_local_assets(root/'configs/autoencoders/gte_multilingual_local_assets_v1.json',
            expected_sha256=ASSET_MANIFEST_SHA256, model_directory=ASSETS768/'model', code_directory=ASSETS768/'code')
        require(asset_receipt['status'] == 'available', 'complete native768 local assets unavailable')
    return dict(dimension=dimension, pins=pins, assets=asset_receipt,
                encoder_executed=False, model_loaded=False, **FALSE)


def physical_sources(directory):
    import pyarrow.parquet as pq
    keys = {(source['title'],source['section']) for source in SOURCES}
    rows = []
    # Stream the already-authenticated corpus so full-parent uniqueness does
    # not require retaining the corpus text column in memory.
    for batch in pq.ParquetFile(PARQUET).iter_batches(batch_size=256,
            columns=['title_number','section_number','text'],use_threads=False):
        rows.extend(row for row in batch.to_pylist()
                    if (row['title_number'],row['section_number']) in keys)
    requests, artifacts, spans = [], {}, []
    for source in SOURCES:
        selected = [row for row in rows if row['title_number'] == source['title']
                    and row['section_number'] == source['section']]
        require(len(selected) == 1 and type(selected[0]['text']) is str, 'unique exact parent row required')
        text = selected[0]['text']
        raw = text.encode()
        require(sha(raw) == source['parent_sha256'], 'parent plaintext identity differs')
        require(text.count(source['start']) == 1, 'unambiguous literal subsection start required')
        start = text.index(source['start'])
        end = text.index(source['end'], start)
        piece = text[start:end]
        begin_byte, end_byte = len(text[:start].encode()), len(text[:end].encode())
        require(raw[begin_byte:end_byte] == piece.encode() and 'born alive' in piece.casefold(),
                'exact born-alive physical subsection required')
        parent = write_new(directory, 'parent-'+source['title']+'-'+source['section']+'.txt', raw)
        artifacts[parent['sha256']] = parent
        origin = dict(artifact={key:parent[key] for key in ('sha256', 'bytes')},
            source_kind='us_code', release_id=REVISION, document_id=source['legal_id'],
            language='en', citation=source['legal_id'], byte_start=begin_byte,
            byte_end=end_byte, normalization='identity')
        requests.append(dict(id=source['id'], source_text=piece, source=origin))
        spans.append(dict(id=source['id'], legal_id=source['legal_id'],
            parent_sha256=source['parent_sha256'], parent_bytes=len(raw),
            byte_start=begin_byte, byte_end=end_byte, char_start=start, char_end=end,
            span_sha256=sha(piece.encode()), span_bytes=len(piece.encode()),
            coverage='complete_literal_subsection', full_parent_coverage=False))
    return requests, artifacts, spans


def run_selected_profile(root, task_id, *, output_directory, checkpoint_bytes=None):
    """Frozen producer+selected decoder execution; outputs remain unqualified."""
    admitted = preflight(root, task_id)
    root, dimension = Path(root).resolve(), admitted['dimension']
    output_directory = Path(output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='native-replay-', dir=output_directory))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    import torch
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        require(torch.get_num_interop_threads() == 1, 'single interop thread required')
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        arbitrary_native_source_cache as cache, arbitrary_native_legal_ir_runtime as arbitrary,
        contextual_legal_ir_runtime as contextual, contextual_legal_ir_output as output,
        decoder_distillation_experiment as numeric_core)
    prep = load_file_module('_born_alive_preparation', root/'scripts/ops/legal_ir/prepare_arbitrary_native_legal_sources.py')
    requests, artifacts, spans = physical_sources(directory)
    requests_pin = write_new(directory, 'source-requests.json', requests)
    resolver = prep.source_resolver(artifacts)
    cache._requests(requests, resolver)
    write_new(directory, 'start.json', dict(pid=os.getpid(),
        start_ticks=Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
        dimension=dimension, probe=admitted, script=file_pin(__file__), **FALSE))
    if dimension == 384:
        config = dict(schema=prep.CONFIG_SCHEMA, mode='produce384', dimension=384,
            source_requests_pin=requests_pin, source_artifact_pins=artifacts,
            native384_receipt_refs=[], native768_report_refs=[], snapshot_path=SNAPSHOT384, batch_size=2)
        production = prep.prepare(config, output_directory=directory/'production')
        source_cache = production['source_cache']
        native384, native768 = production['native_receipt_refs'], []
    else:
        from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs as fresh
        native_rows = [dict(id='source:'+sha(row['source_text'].encode()),
                           source_text=row['source_text']) for row in requests]
        config = dict(manifest_path=str(root/'configs/autoencoders/gte_multilingual_local_assets_v1.json'),
            expected_manifest_sha256=ASSET_MANIFEST_SHA256,
            model_directory=str(ASSETS768/'model'), code_directory=str(ASSETS768/'code'))
        # The private primitive is explicitly used for two occurrences; the
        # unrelated public 48-row authored-assay plan is never fabricated.
        production = fresh._produce768(dict(source_inputs=native_rows), config, None, 2,
                                       time.monotonic()+240)
        native768 = [write_new(directory, 'native768-production.json', production['native_production'])]
        native384 = []
        checked = cache.plan_arbitrary_native_source_cache(requests, dimension=768,
            native768_report_refs=native768, source_resolver=resolver)
        source_cache = write_new(directory, 'source-cache.json', checked)
    write_new(directory, 'producer-records.json', production)
    profile = PROFILES[dimension]
    checkpoint = admitted['pins']['checkpoint']
    if checkpoint_bytes is not None:
        require(type(checkpoint_bytes) is bytes and sha(checkpoint_bytes) == profile['checkpoint_sha256']
            and len(checkpoint_bytes) == profile['checkpoint_bytes'], 'received actual checkpoint differs')
        checkpoint = write_new(directory, 'received-checkpoint.json', checkpoint_bytes)
    selection = dict(ir_family_id='legal_ir', dimension=dimension, dimension_role='input_embedding',
        task_id='semantic_IR_reconstruction', checkpoint_sha256=profile['checkpoint_sha256'])
    paths = arbitrary.source_owner_paths()
    owner_pins = {name:file_pin(path, 512*1024) for name,path in paths.items()}
    captured = contextual._capture(selection, checkpoint, admitted['pins']['preprocessing'],
        admitted['pins']['donor_checkpoint'], source_cache, source_cache,
        {name:owner_pins[name] for name in contextual.SOURCE_OWNER_NAMES},
        [row['id'] for row in requests], 120, contextual.MAX_REFERENCE_BYTES)
    for name, owner_pin in owner_pins.items():
        require(owner_pin['path'] == paths[name], 'fixed current numerical owner required')
        captured['pins']['source:'+name] = contextual._pin(owner_pin, 512*1024)
    captured['pins']['source_requests'] = requests_pin
    for name,refs in (('native384',native384),('native768',native768)):
        captured[name+'_refs'] = refs
        for index,ref in enumerate(refs):
            captured['pins'][name+':'+str(index)] = ref
    captured['source_artifact_pins'] = artifacts
    for digest,ref in artifacts.items():
        captured['pins']['source:artifact:'+digest] = ref
    require(sum(ref['bytes'] for ref in captured['pins'].values()) <= contextual.MAX_TOTAL_BYTES,
            'combined source/native custody exceeds existing bound')
    script_pin = file_pin(__file__)

    def prepare(options):
        require(file_pin(__file__) == script_pin, 'trusted replay owner changed')
        arbitrary._verify_origins(options)
        plan, prepared, witnesses = contextual._prepare(options, _source_packet=arbitrary._source_packet)
        plan.update(extension_contract_id=SCHEMA, physical_source_binding_verified=True,
                    source_native_records_verified=True, legal_quality_qualified=False)
        contextual._fence(options['pins'], witnesses)
        arbitrary._verify_origins(options)
        return plan, prepared, witnesses

    plan, prepared, witnesses = prepare(captured)
    write_new(directory, 'runtime-plan.json', plan)
    owner = contextual._numeric_owner(plan)
    restored = owner.restore_contextual_legal_model(prepared)
    handle = contextual._ContextualLegalAutoencoder(owner, restored, captured, plan, witnesses,
                                                   _prepare_plan=prepare)
    inference = handle.infer_cached()
    inspection = output.inspect_contextual_legal_predictions(
        inference['raw_candidate_report']['predictions'], codec=plan['codec'], output_limit=512)
    write_new(directory, 'decoder-inference.json', inference)
    write_new(directory, 'decoder-inspection.json', inspection)
    before = numeric_core.tensor_digest(restored.model)
    rows = plan['source_inputs']['rows']
    with torch.inference_mode():
        values = (torch.tensor([row['input'] for row in rows], dtype=torch.float32)
            -torch.tensor(restored.input_transform['mean'], dtype=torch.float32))/restored.input_transform['scale']
        projected = restored.model.project(values)
        framework_cos = torch.nn.functional.cosine_similarity(values, projected, dim=1).tolist()
        framework_mse = ((values-projected)**2).mean(dim=1).tolist()
    require(numeric_core.tensor_digest(restored.model) == before == restored.tensor_sha256,
            'frozen selected state changed')
    source_data = json.loads(Path(source_cache['path']).read_text())
    records = []
    for index,row in enumerate(rows):
        left, right = values[index].tolist(), projected[index].tolist()
        measured = independent_metrics(left, right)
        require(left == right, 'selected frozen identity projection changed')
        require(abs(measured['cosine_similarity']-framework_cos[index]) <= 2e-6
            and abs(measured['reconstruction_loss']-framework_mse[index]) <= 1e-12,
            'independent metrics disagree with numerical owner')
        # The source cache's occurrence receipt contains actual producer tokens.
        native = source_data['input_origins'][row['id']][0]['native']
        tokens = native['tokens']
        require(1 <= len(tokens['input_ids']) <= 512
            and all(value == 1 for value in tokens['attention_mask']), 'actual native512 tokens required')
        records.append(dict(id=row['id'], native_embedding=row['input'],
            actual_source_tokens=tokens, actual_token_count=len(tokens['input_ids']),
            transformed_decoder_input=left, selected_projection_output=right,
            metrics=measured, raw_prediction=inference['raw_candidate_report']['predictions'][index]))
    raw = Path(checkpoint['path']).read_bytes()
    archive = checkpoint_archive(raw)
    observation = dict(schema=SCHEMA, dimension=dimension, status='observed',
        source_hashes=sorted(source['parent_sha256'] for source in SOURCES),
        source_spans=spans, source_access='literal_complete_subsections_only',
        profile_id=profile['profile_id'], checkpoint_sha256=sha(raw),
        checkpoint_archive_sha256=sha(archive), checkpoint_raw_bytes=len(raw),
        checkpoint_transport='deterministic_zip_single_checkpoint_json',
        measurement_scope=SCOPE,
        coordinate_domain='saved_TRAIN_center_rms_transformed_native_source_embedding_float32',
        reconstruction_loss_definition='coordinate_mean_squared_error(input,selected_model_project(input))',
        output_scope='normative32_candidate_language_not_statutory_reconstruction',
        output_vocabulary_size=32, native_ir_schema_version=None,
        decoder_profile_id=None, decoder_format_id=None,
        token_ceiling=512, truncation_used=False, encoder_executed=True, decoder_executed=True,
        corpus_default=dimension==384, rows=records,
        metrics={key:math.fsum(row['metrics'][key] for row in records)/len(records)
                 for key in ('cosine_similarity','reconstruction_loss')}, **FALSE)
    require(file_pin(PARQUET)['sha256'] == PARQUET_SHA256, 'parent corpus changed during replay')
    resolver.fence()
    prepare(captured)
    write_new(directory, 'stable-observation.json', observation)
    return dict(observation=observation, checkpoint_archive=archive, replay_directory=str(directory))


def compare_stable(expected, actual, location='observation'):
    """Compare semantic stable content; timing/private paths are excluded."""
    require(type(expected) is type(actual), location+': scalar/container type differs')
    if isinstance(expected, dict):
        require(set(expected) == set(actual), location+': fields differ')
        for key in expected:
            compare_stable(expected[key], actual[key], location+'.'+key)
    elif isinstance(expected, list):
        require(len(expected) == len(actual), location+': coverage differs')
        for index,(left,right) in enumerate(zip(expected, actual)):
            compare_stable(left,right,location+'['+str(index)+']')
    elif type(expected) is float:
        require(math.isfinite(actual) and abs(expected-actual) <= 1e-10,
                location+': independently replayed numerical observation differs')
    else:
        require(expected == actual, location+': independently replayed content differs')


def verify_observation(root, task_id, observation, checkpoint_archive_bytes, *, output_directory):
    """Rerun trusted frozen production/decoder and independently check claims."""
    dimension = dimension_for(task_id)
    require(type(observation) is dict and observation.get('schema') == SCHEMA
        and type(observation.get('dimension')) is int and observation['dimension'] == dimension,
        'exact source-bound selected replay observation required')
    require(observation.get('measurement_scope') == SCOPE and all(
        observation.get(key) is value for key,value in FALSE.items()),
        'identity diagnostic and explicit nonquality authority flags required')
    require(observation.get('checkpoint_sha256') == PROFILES[dimension]['checkpoint_sha256']
        and observation.get('checkpoint_archive_sha256') == sha(checkpoint_archive_bytes),
        'separate actual raw/archive checkpoint identities required')
    raw = unpack_checkpoint(checkpoint_archive_bytes, dimension)
    repeated = run_selected_profile(root, task_id, output_directory=output_directory,
                                    checkpoint_bytes=raw)
    compare_stable(repeated['observation'], observation)
    return dict(verified=True, dimension=dimension, measurement_scope=SCOPE,
                source_count=2, independent_frozen_reexecution=True,
                replay_directory=repeated['replay_directory'], **FALSE)


OUTPUT_NAMES = ('observation.json','checkpoint.zip','receipt.json')


def _open_directory(path):
    """Open every absolute path component without following symlinks."""
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts,'canonical absolute directory required')
    descriptor=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor)
            descriptor=following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def output_directory(root,task_id,requested, *, engineering=False):
    """Check exact task location and all existing destinations before replay."""
    dimension=engineering_profile(task_id)['dimension'] if engineering else dimension_for(task_id)
    root=Path(root).absolute()
    require(root==root.resolve(strict=True),'repository root must be canonical')
    expected=root/'docs/implementation/reports/evidence/legal_ir_autoencoder'/('lirae-width-'+str(dimension))
    names=OUTPUT_NAMES
    if engineering:
        expected=root/'docs/implementation/reports/evidence/legal_ir_autoencoder'/task_id.lower()/'successor-v2'
        names=('observation.json','capture.zip','receipt.json')
    candidate=Path(requested)
    candidate=candidate if candidate.is_absolute() else root/candidate
    require(candidate==expected,'output must be the exact width task directory')
    current=_open_directory(root)
    try:
        for part in expected.relative_to(root).parts:
            try:
                following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current)
            except FileNotFoundError:
                return expected
            os.close(current)
            current=following
        _check_output_entries(current,names=names)
    finally:
        os.close(current)
    return expected


def _check_output_entries(descriptor, *, names=OUTPUT_NAMES):
    require(set(os.listdir(descriptor))<=set(names),'unexpected existing task output')
    for name in names:
        try:
            info=os.stat(name,dir_fd=descriptor,follow_symlinks=False)
        except FileNotFoundError:
            continue
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,
                'task output must be an ordinary single-link file')


def publish_outputs(root,task_id,directory,payloads, *, engineering=False):
    """All-file conflict precheck, exclusive no-follow writes, receipt last."""
    expected=output_directory(root,task_id,directory,engineering=engineering)
    names=('observation.json','capture.zip','receipt.json') if engineering else OUTPUT_NAMES
    require(set(payloads)==set(names) and all(type(v) is bytes for v in payloads.values()),
            'exact three output byte payloads required')
    descriptor=_open_directory(Path(root).absolute())
    try:
        for part in expected.relative_to(Path(root).absolute()).parts:
            try:
                following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part,0o700,dir_fd=descriptor)
                following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor)
            descriptor=following
        _check_output_entries(descriptor,names=names)
        present=set()
        for name in names:
            try:
                existing=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=descriptor)
            except FileNotFoundError:
                continue
            try:
                info=os.fstat(existing)
                require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'existing task output custody differs')
                with os.fdopen(existing,'rb',closefd=False) as stream:
                    require(stream.read(len(payloads[name])+1)==payloads[name],
                            'conflicting existing task output: '+name)
                present.add(name)
            finally:
                os.close(existing)
        for name in names:
            if name in present:
                continue
            target=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=descriptor)
            with os.fdopen(target,'wb') as stream:
                stream.write(payloads[name])
                stream.flush()
                os.fsync(stream.fileno())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


ENGINEERING_CONTRACT = 'legal-ir-genuine-source-width/v2'
ENGINEERING_CAPTURE_SCHEMA = 'legal-ir-genuine-width-capture/v2'
ENGINEERING_REVIEW_SCHEMA = 'legal-ir-genuine-width-capture-review/v2'
ENGINEERING_SELECTION_SCHEMA = 'legal-ir-genuine-width-selection/v2'
ENGINEERING_SCHEMA = 'legal-ir-born-alive-genuine-width-observation/v2'
ENGINEERING_MAX_BYTES = 8_000_000
ENGINEERING_TASKS = {
    'LIRAE-WIDTH-08': dict(dimension=8,
        profile_id='spacy_linguistic8_frozen_feature_reconstruction/v2',
        measurement_scope='target_aware_linguistic_feature_reconstruction_not_formula_fidelity',
        right_vector='reconstructed_vector', loss='reconstruction_loss'),
    'LIRAE-WIDTH-4096': dict(dimension=4096,
        profile_id='leanstral4096_native_source_repeatability/v2',
        measurement_scope='independent_full_forward_source_embedding_repeatability_not_learned_reconstruction',
        right_vector='repeat_vector', loss='repeatability_mean_squared_error'),
}


def engineering_profile(task_id):
    require(type(task_id) is str and task_id in ENGINEERING_TASKS,
            'genuine v2 replay supports only exact08/4096 task IDs')
    return dict(ENGINEERING_TASKS[task_id])


def _engineering_closed(value, keys, message):
    require(type(value) is dict and set(value) == set(keys), message)


def _engineering_pin(pin):
    _engineering_closed(pin, ('path', 'bytes', 'sha256'), 'closed engineering input pin required')
    path = Path(pin['path']) if type(pin['path']) is str else Path('.')
    require(type(pin['path']) is str and path.is_absolute() and '..' not in path.parts
            and path.as_posix() == pin['path'], 'canonical absolute engineering input path required')
    require(type(pin['bytes']) is int and 0 < pin['bytes'] <= ENGINEERING_MAX_BYTES
            and type(pin['sha256']) is str and len(pin['sha256']) == 64
            and all(c in '0123456789abcdef' for c in pin['sha256']),
            'bounded independently selected engineering input identity required')
    return dict(pin)


def _engineering_read(pin):
    """Read exact selected bytes; no symlink, FIFO, hardlink or rewrite admission."""
    pin = _engineering_pin(pin)
    path = Path(pin['path'])
    parent = _open_directory(path.parent)
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_size == pin['bytes'], 'selected engineering input custody/size differs')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(pin['bytes'] + 1)
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(identity(before) == identity(after) == identity(named)
                and stat.S_ISREG(after.st_mode) and stat.S_ISREG(named.st_mode)
                and after.st_nlink == named.st_nlink == 1
                and len(raw) == pin['bytes'] and sha(raw) == pin['sha256'],
                'selected engineering input changed or hash differs')
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def _engineering_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate engineering JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite engineering JSON')))


def engineering_required_input_file_pins(task_id, selection):
    """Only small independently selected captures/reviews, never the67GB model."""
    engineering_profile(task_id)
    _engineering_closed(selection, ('schema', 'capture', 'review'), 'closed engineering selection required')
    require(selection['schema'] == ENGINEERING_SELECTION_SCHEMA, 'engineering selection schema differs')
    pins = [_engineering_pin(selection[key]) for key in ('capture', 'review')]
    require(pins[0]['path'] != pins[1]['path'], 'capture and independent review must be distinct inputs')
    for pin in pins:
        require('docs/implementation/reports/evidence/legal_ir_autoencoder' not in pin['path'],
                'trusted engineering capture must remain outside provider task outputs')
    return pins


def _engineering_sources(capture):
    """Recompute exact source geometry from retained complete parent plaintext."""
    require(type(capture.get('parents')) is list and len(capture['parents']) == len(SOURCES),
            'two complete source parents required')
    requests, spans = [], []
    for expected, parent in zip(SOURCES, capture['parents'], strict=True):
        _engineering_closed(parent, ('id', 'text'), 'closed retained source parent required')
        require(parent['id'] == expected['id'] and type(parent['text']) is str,
                'retained source parent identity differs')
        text = parent['text']
        raw = text.encode('utf-8')
        require(sha(raw) == expected['parent_sha256'] and text.count(expected['start']) == 1,
                'retained source parent SHA or literal start differs')
        start = text.index(expected['start'])
        end = text.index(expected['end'], start)
        piece = text[start:end]
        begin_byte, end_byte = len(text[:start].encode('utf-8')), len(text[:end].encode('utf-8'))
        require(raw[begin_byte:end_byte] == piece.encode('utf-8') and 'born alive' in piece.casefold(),
                'complete source subsection differs')
        origin = dict(artifact=dict(sha256=sha(raw), bytes=len(raw)), source_kind='us_code',
            release_id=REVISION, document_id=expected['legal_id'], language='en', citation=expected['legal_id'],
            byte_start=begin_byte, byte_end=end_byte, normalization='identity')
        requests.append(dict(id=expected['id'], source_text=piece, source=origin))
        spans.append(dict(id=expected['id'], legal_id=expected['legal_id'], parent_sha256=sha(raw),
            parent_bytes=len(raw), byte_start=begin_byte, byte_end=end_byte, char_start=start, char_end=end,
            span_sha256=sha(piece.encode('utf-8')), span_bytes=len(piece.encode('utf-8')),
            coverage='complete_literal_subsection', full_parent_coverage=False))
    compare_stable(requests, capture.get('source_requests'), 'source_requests')
    compare_stable(spans, capture.get('source_spans'), 'source_spans')
    return requests, spans


def _engineering_vector(value, dimension):
    require(type(value) is list and len(value) == dimension
            and all(type(number) is float and math.isfinite(number) for number in value),
            'complete ordinary finite engineering vector required')
    return value


def _engineering_measurements(task_id, result):
    profile = engineering_profile(task_id)
    require(type(result) is dict and result.get('profile_id') == profile['profile_id']
            and result.get('measurement_scope') == profile['measurement_scope'],
            'engineering producer profile/scope differs')
    rows = result.get('rows')
    require(type(rows) is list and len(rows) == 2 and all(type(row) is dict for row in rows)
            and [row.get('id') for row in rows] == [source['id'] for source in SOURCES],
            'complete ordered engineering source rows required')
    measurements = []
    for row in rows:
        left = _engineering_vector(row.get('input_vector'), profile['dimension'])
        right = _engineering_vector(row.get(profile['right_vector']), profile['dimension'])
        measured = independent_metrics(left, right)
        measured[profile['loss']] = measured.pop('reconstruction_loss')
        compare_stable(measured, row.get('metrics'), 'independently_computed_row_metrics')
        measurements.append(measured)
    average = {key: math.fsum(row[key] for row in measurements) / len(measurements)
               for key in ('cosine_similarity', profile['loss'])}
    compare_stable(average, result.get('metrics'), 'independently_computed_mean_metrics')
    require(all(result.get(key) is value for key, value in FALSE.items()),
            'engineering result cannot claim training or quality authority')
    return average


def _engineering_native_evidence(capture):
    """Check retained numerical/receipt consistency; issue no live capability."""
    result = capture['result']
    evidence = result.get('producer_evidence')
    require(type(evidence) is dict and type(evidence.get('expected_producer')) is dict,
            'retained original native producer declaration required')
    producer, operations = evidence['expected_producer'], evidence.get('operations')
    require(type(operations) is list and len(operations) == 2,
            'both independently received original native records required')
    native_wire = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=True, allow_nan=False).encode('utf-8')
    nonces, children, token_panels = [], [], []
    authored = [dict(id=row['id'], source_text=row['source_text']) for row in capture['source_requests']]
    for operation in operations:
        require(type(operation) is dict
                and operation.get('schema') == 'leanstral-completed-source4096-embedding-production/v1'
                and operation.get('expected_producer') == producer
                and operation.get('ordinary_receipt_is_capability') is False,
                'retained completed native record identity differs')
        receipt, provenance = operation.get('native_operation_receipt'), operation.get('native_provenance')
        require(type(receipt) is dict and type(provenance) is dict
                and provenance.get('receipt_sha256') == sha(native_wire(receipt) + b'\n')
                and receipt.get('complete') is True and receipt.get('full_forward_executed') is True
                and receipt.get('model_content_hash_verified') is True
                and type(receipt.get('sample_count')) is int and receipt['sample_count'] == 2
                and type(receipt.get('vectors_produced')) is int and receipt['vectors_produced'] == 2,
                'complete original native full-forward receipt required')
        for key in ('qualified', 'admitted', 'proof_authority', 'source_semantics_verified',
                    'training_executed', 'persisted_receipt_is_execution_authority'):
            require(receipt.get(key) is False, 'ordinary native receipt cannot grant authority')
        for key, expected in producer.items():
            if key != 'library_sha256':
                require(receipt.get(key) == expected, 'retained native producer identity differs')
        nonce = receipt.get('operation_nonce')
        require(type(nonce) is str and len(nonce) == 64
                and all(c in '0123456789abcdef' for c in nonce)
                and receipt.get('request_sha256') == sha(native_wire(dict(
                    schema='native-source4096-worker-request/v1', nonce=nonce, rows=authored)) + b'\n'),
                'retained original native request differs from complete source rows')
        cleanup, cgroup = receipt.get('cleanup'), receipt.get('resource_cgroup')
        require(type(cleanup) is dict and cleanup.get('leader_reaped') is True
                and type(cleanup.get('returncode')) is int and cleanup['returncode'] == 0
                and type(cleanup.get('live_group_processes')) is int and cleanup['live_group_processes'] == 0
                and type(cgroup) is dict and cgroup.get('only_owner_after_exit') is True,
                'original native child cleanup evidence required')
        require(type(receipt.get('child')) is dict and type(receipt['child'].get('pid')) is int,
                'original native child birth identity required')
        nonces.append(nonce)
        children.append(wire(receipt['child']))
        rows = operation.get('rows')
        require(type(rows) is list and len(rows) == 2, 'both original source4096 rows required')
        panel = []
        for source, row in zip(authored, rows, strict=True):
            require(type(row) is dict and row.get('id') == source['id']
                    and row.get('source_text') == source['source_text']
                    and row.get('source_sha256') == sha(source['source_text'].encode('utf-8')),
                    'native source occurrence identity differs')
            tokens, vector, geometry = row.get('token_ids'), row.get('embedding'), row.get('geometry')
            require(type(tokens) is list and 1 <= len(tokens) <= 512
                    and all(type(token) is int and token >= 0 for token in tokens)
                    and type(row.get('token_count')) is int and row['token_count'] == len(tokens)
                    and type(row.get('native_tokens_evaluated')) is int and row['native_tokens_evaluated'] == len(tokens),
                    'complete untruncated evaluated source tokens required')
            require(type(vector) is list and len(vector) == 4096
                    and all(type(value) in (int, float) and math.isfinite(value) for value in vector)
                    and abs(math.sqrt(math.fsum(value * value for value in vector)) - 1.0) <= 2e-6,
                    'full genuine native4096 normalized source coordinates required')
            require(type(geometry) is dict and geometry.get('actual_pooling') == 'last'
                    and all(type(geometry.get(key)) is int and geometry[key] == expected for key, expected in
                        (('native_input_dimension', 4096), ('native_output_dimension', 4096),
                         ('actual_context', 512), ('actual_batch', 512), ('actual_ubatch', 512), ('actual_sequences', 1))),
                    'original single-sequence native4096 geometry differs')
            require(row.get('token_input_sha256') == sha(native_wire(tokens))
                    and row.get('embedding_sha256') == sha(native_wire(vector)),
                    'retained native token/vector bytes differ')
            panel.append(tokens)
        token_panels.append(panel)
    require(len(set(nonces)) == len(set(children)) == 2 and token_panels[0] == token_panels[1],
            'independent native operation/child identities and identical token inputs required')
    for index, row in enumerate(result['rows']):
        for operation, key in zip(operations, ('input_vector', 'repeat_vector'), strict=True):
            compare_stable([float(value) for value in operation['rows'][index]['embedding']], row[key],
                           'original_native_result_coordinates')
        require(row.get('actual_source_tokens') == token_panels[0][index]
                and type(row.get('actual_token_count')) is int
                and row['actual_token_count'] == len(token_panels[0][index]),
                'reported native repeatability token population differs')


def _engineering_observation(capture, capture_pin):
    task_id = capture.get('task_id')
    profile = engineering_profile(task_id)
    require(capture.get('schema') == ENGINEERING_CAPTURE_SCHEMA
            and capture.get('contract_id') == ENGINEERING_CONTRACT
            and capture.get('source_repository') == 'justicedao/ipfs_uscode'
            and capture.get('source_revision') == REVISION
            and capture.get('source_parquet_sha256') == PARQUET_SHA256
            and type(capture.get('replay_owner_sha256')) is str
            and len(capture['replay_owner_sha256']) == 64
            and all(c in '0123456789abcdef' for c in capture['replay_owner_sha256']),
            'exact genuine engineering capture required')
    _engineering_sources(capture)
    result = capture.get('result')
    metrics = _engineering_measurements(task_id, result)
    require(all(capture.get(key) is value for key, value in FALSE.items()),
            'capture cannot claim training or legal/numerical quality authority')
    native = task_id == 'LIRAE-WIDTH-4096'
    require(type(capture.get('native_operations')) is int
            and type(capture.get('actual_source_forwards')) is int
            and capture['native_operations'] == (2 if native else 0)
            and capture['actual_source_forwards'] == (4 if native else 0),
            'finite original native operation population differs')
    if native:
        _engineering_native_evidence(capture)
    else:
        require(result.get('checkpoint_identity') == {
            name: dict(bytes=count, sha256=digest) for name, count, digest in _SPACY8_BUNDLE_FILES},
            'original selected frozen linguistic checkpoint identity differs')
        producer = result.get('producer_evidence')
        require(type(producer) is dict and producer.get('producer_profile_id') == SPACY8_PROFILE_ID
                and producer.get('linguistic_identity_sha256') == SPACY8_IDENTITY_SHA256
                and producer.get('formula_head_attached') is False
                and producer.get('target_aware_reconstruction') is True
                and producer.get('source_text_truncated') is False
                and producer.get('weights_state_unchanged') is True
                and producer.get('source_model_checkpoint_closing_pins_matched') is True,
                'genuine frozen spaCy producer/source scope differs')
    return dict(schema=ENGINEERING_SCHEMA, contract_id=ENGINEERING_CONTRACT,
        task_id=task_id, dimension=profile['dimension'], profile_id=profile['profile_id'], status='observed',
        source_hashes=sorted(source['parent_sha256'] for source in SOURCES),
        source_spans=capture['source_spans'], source_access='literal_complete_subsections_only',
        measurement_scope=profile['measurement_scope'], capture_sha256=capture_pin['sha256'],
        capture_bytes=capture_pin['bytes'], metrics=metrics, result=result,
        encoder_executed=True, acquisition_encoder_executed=True,
        acquisition_source_feature_rows=0 if native else 2,
        acquisition_build_sample_calls=0 if native else 2,
        acquisition_linguistic_observation_calls=0 if native else 2,
        acquisition_feature_encode_calls=0 if native else 2,
        acquisition_feature_decode_calls=0 if native else 2,
        feature_call_count_scope='explicit_public_autoencoder_API_calls_not_internal_tokenizer_invocations',
        historical_development_result={'successful': 0, 'total': 12} if native else None,
        historical_contract_retained=True, corpus_default=False,
        live_capability_reconstructed_from_receipt=False,
        native_operations=2 if native else 0, actual_source_forwards=4 if native else 0,
        validation_encoder_executions=0, **FALSE)


def _engineering_selected_capture(task_id, selection):
    capture_pin, review_pin = engineering_required_input_file_pins(task_id, selection)
    capture_raw, review_raw = _engineering_read(capture_pin), _engineering_read(review_pin)
    capture, review = _engineering_json(capture_raw), _engineering_json(review_raw)
    require(type(capture) is dict and capture.get('task_id') == task_id,
            'selected engineering capture task differs')
    require(type(review) is dict and review.get('schema') == ENGINEERING_REVIEW_SCHEMA
            and review.get('task_id') == task_id and review.get('capture') == capture_pin,
            'independent engineering review/capture identity differs')
    for field in ('independently_reviewed', 'original_source_READ_closed', 'original_native_and_storage_released'):
        require(review.get(field) is True, 'independent capture review or original resource closure missing: ' + field)
    require(review.get('completion_authority') is False and review.get('training_executed') is False,
            'capture review cannot grant completion or training authority')
    for field in ('native_operations', 'actual_source_forwards'):
        require(type(review.get(field)) is int and review[field] == capture.get(field),
                'reviewed original operation population differs')
    observation = _engineering_observation(capture, capture_pin)
    require(capture_raw == wire(capture) + b'\n', 'canonical retained engineering capture bytes required')
    return capture_raw, observation


def engineering_capture_archive(raw):
    require(type(raw) is bytes and 0 < len(raw) <= ENGINEERING_MAX_BYTES,
            'bounded actual engineering capture bytes required')
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=False) as archive:
        item = zipfile.ZipInfo('capture.json', date_time=(1980, 1, 1, 0, 0, 0))
        item.create_system, item.compress_type = 3, zipfile.ZIP_DEFLATED
        item.external_attr = (stat.S_IFREG | 0o600) << 16
        archive.writestr(item, raw, compresslevel=9)
    payload = target.getvalue()
    require(len(payload) <= ENGINEERING_MAX_BYTES, 'engineering capture archive exceeds bound')
    return payload


def verify_engineering_observation(root, task_id, observation, capture_archive_bytes, *, selection, output_directory):
    """Offline engineering replay of an independently selected genuine capture.

    Native ownership was established during the original protected capture and
    independently reviewed after cleanup. Ordinary serialized records grant no
    live native capability, decoder authority, training or legal qualification.
    Validation never executes an encoder or invokes a model provider.
    """
    raw, expected = _engineering_selected_capture(task_id, selection)
    require(type(capture_archive_bytes) is bytes
            and capture_archive_bytes == engineering_capture_archive(raw),
            'exact independently selected engineering capture archive required')
    compare_stable(expected, observation, 'engineering_observation')
    return dict(verified=True, task_id=task_id, contract_id=ENGINEERING_CONTRACT,
        source_count=2, independent_measurement_recomputation=True,
        original_native_execution_independently_reviewed=True,
        validation_encoder_executions=0, live_capability_reconstructed_from_receipt=False, **FALSE)


def _engineering_plan_selection(root, task_id):
    engineering_profile(task_id)
    plan = _engineering_json((Path(root) / 'ipfs_datasets_py/logic/autoformal/legal_ir_autoencoder_supervisor_plan.json').read_bytes())
    tasks = [task for task in plan['tasks'] if task['task_id'] == task_id]
    require(len(tasks) == 1 and tasks[0].get('engineering_width_replay') == ENGINEERING_CONTRACT,
            'exact protected plan must select the genuine v2 engineering route')
    selection = tasks[0].get('engineering_width_capture')
    engineering_required_input_file_pins(task_id, selection)
    return selection


def _publish_engineering_task(root, task_id, requested):
    selection = _engineering_plan_selection(root, task_id)
    directory = output_directory(root, task_id, requested, engineering=True)
    raw, observation = _engineering_selected_capture(task_id, selection)
    archive = engineering_capture_archive(raw)
    payloads = {'observation.json': wire(observation) + b'\n', 'capture.zip': archive}
    artifacts = [dict(kind=kind, path=str((directory / name).relative_to(Path(root).resolve())),
                      sha256=sha(payloads[name]))
                 for kind, name in (('observation', 'observation.json'), ('capture', 'capture.zip'))]
    receipt = dict(schema=RECEIPT_SCHEMA, task_id=task_id, task_kind='width', status='inventory',
        authority=dict(admitted=False, formalized=False), artifacts=artifacts,
        evidence=dict(dimension=engineering_profile(task_id)['dimension'],
                      replay_contract=ENGINEERING_CONTRACT,
                      measurement_scope=observation['measurement_scope']))
    payloads['receipt.json'] = wire(receipt) + b'\n'
    publish_outputs(root, task_id, directory, payloads, engineering=True)
    return dict(task_id=task_id, status='observed', contract_id=ENGINEERING_CONTRACT,
                validation_encoder_executions=0, completion_allowed=False, **FALSE)


def _run_leanstral4096_repeatability(root, requests, spans, *, config, resource_cgroup, output_directory):
    """Exactly two genuine native operations, only in an explicitly admitted capture."""
    fields = ('schema', 'worker_path', 'worker_sha256', 'worker_source_path', 'worker_source_sha256',
              'model_path', 'expected_model_sha256', 'expected_library_sha256', 'expected_producer',
              'deadline_seconds', 'max_rss_bytes', 'reclaim_model_mappings')
    _engineering_closed(config, fields, 'closed genuine4096 capture configuration required')
    require(config['schema'] == 'legal-ir-leanstral4096-capture-config/v2'
            and type(config['deadline_seconds']) is int and config['deadline_seconds'] == 900
            and type(config['max_rss_bytes']) is int and config['max_rss_bytes'] == 8 * 1024**3
            and config['reclaim_model_mappings'] is True,
            'original bounded genuine4096 capture policy required')
    require(type(resource_cgroup) is str and resource_cgroup.startswith('/sys/fs/cgroup/'),
            'explicit fresh delegated capture cgroup required')
    configure(root)
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        source_embeddings_4096_full_owner as native, source_embeddings_4096_verified as verified)
    config_wire = wire(config)
    producer = config['expected_producer']
    _engineering_closed(producer, ('profile', 'model_sha256', 'worker_sha256', 'worker_source_sha256',
        'owner_source_sha256', 'vocabulary_owner_source_sha256', 'library_sha256'),
        'closed original genuine4096 producer required')
    require(producer.get('owner_source_sha256') == file_pin(native.__file__)['sha256']
            and producer.get('vocabulary_owner_source_sha256') == file_pin(native.vocab.__file__)['sha256'],
            'original native owner/vocabulary source pins differ before forward')
    require(producer.get('profile') == native.RECLAIM_PROFILE
            and producer.get('model_sha256') == config['expected_model_sha256']
            == '4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da'
            and producer.get('worker_sha256') == config['worker_sha256']
            and producer.get('worker_source_sha256') == config['worker_source_sha256']
            and producer.get('library_sha256') == config['expected_library_sha256'],
            'selected original genuine4096 producer identity differs')
    source_rows = [dict(id=row['id'], source_text=row['source_text']) for row in requests]
    operations = []
    for index in range(2):
        directory = Path(output_directory) / ('native-operation-' + str(index + 1))
        native_result = native.run_full_forward(source_rows,
            **{key: config[key] for key in fields if key not in ('schema', 'expected_producer')},
            resource_cgroup=resource_cgroup, output_directory=directory)
        handle = verified.receive_verified_source_embeddings(native_result, rows=source_rows, expected_producer=producer)
        record = verified.read_verified_source_embeddings(handle)
        write_new(directory.parent, 'verified-operation-' + str(index + 1) + '.json', record)
        operations.append(record)
        require(wire(config) == config_wire, 'capture producer configuration changed during native execution')
    nonces = [operation['native_operation_receipt']['operation_nonce'] for operation in operations]
    require(len(set(nonces)) == 2, 'two independent original native operations required')
    rows = []
    for authored, first, repeated in zip(source_rows, operations[0]['rows'], operations[1]['rows'], strict=True):
        require(first['id'] == repeated['id'] == authored['id']
                and first['source_text'] == repeated['source_text'] == authored['source_text']
                and first['token_ids'] == repeated['token_ids'],
                'independent native source/token inputs differ')
        left = [float(value) for value in first['embedding']]
        right = [float(value) for value in repeated['embedding']]
        measured = independent_metrics(left, right)
        measured['repeatability_mean_squared_error'] = measured.pop('reconstruction_loss')
        rows.append(dict(id=authored['id'], input_vector=left, repeat_vector=right, metrics=measured,
            actual_source_tokens=first['token_ids'], actual_token_count=first['token_count']))
    return dict(profile_id=ENGINEERING_TASKS['LIRAE-WIDTH-4096']['profile_id'],
        measurement_scope=ENGINEERING_TASKS['LIRAE-WIDTH-4096']['measurement_scope'],
        coordinate_domain='complete_untruncated_native4096_last_pooled_l2_source_embedding',
        repeatability_loss_definition='coordinate_mean_squared_error(independent_native_forward_1,independent_native_forward_2)',
        producer_evidence=dict(expected_producer=producer, operations=operations), rows=rows,
        metrics={key: math.fsum(row['metrics'][key] for row in rows) / len(rows)
                 for key in ('cosine_similarity', 'repeatability_mean_squared_error')},
        decoder_executed=False, decoder_status='not_selected_no_compatible_bound_head_asserted',
        neural_source_encoder_executed=True, historical_development_result={'successful': 0, 'total': 12}, **FALSE)


def capture_engineering_width_profile(root, task_id, *, output_directory, native4096_config=None, resource_cgroup=None):
    """Operator-only acquisition; selecting/reviewing the capture is a later step."""
    profile = engineering_profile(task_id)
    root = Path(root).resolve(strict=True)
    directory = Path(output_directory).absolute()
    require(directory == directory.resolve(strict=False) and not directory.exists(),
            'fresh ordinary operator capture directory required')
    require(not directory.is_relative_to(root / 'docs/implementation/reports/evidence/legal_ir_autoencoder'),
            'operator capture must remain outside provider task output authority')
    require(file_pin(PARQUET)['sha256'] == PARQUET_SHA256, 'original corpus identity differs')
    directory.mkdir(parents=True, exist_ok=False)
    script_sha = file_pin(__file__)['sha256']
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        os.environ[variable]='1'
    configure(root)
    requests, artifacts, spans = physical_sources(directory)
    if profile['dimension'] == 8:
        require(native4096_config is None and resource_cgroup is None,
                'spaCy8 capture cannot select a native4096 operation')
        result = _run_spacy8_reconstruction(root, requests, spans)
    else:
        require(type(native4096_config) is dict and resource_cgroup is not None,
                'genuine4096 capture requires explicit protected configuration and delegated execution context')
        result = _run_leanstral4096_repeatability(root, requests, spans, config=native4096_config,
            resource_cgroup=resource_cgroup, output_directory=directory)
    runtime_packages={}
    for name in ('spacy','en_core_web_sm','numpy','thinc','torch'):
        module=sys.modules.get(name)
        if module is not None:
            runtime_packages[name]=dict(version=str(getattr(module,'__version__','not_declared')), origin=str(getattr(module,'__file__','not_declared')))
    parents = [dict(id=source['id'], text=Path(artifacts[source['parent_sha256']]['path']).read_bytes().decode('utf-8'))
               for source in SOURCES]
    capture = dict(schema=ENGINEERING_CAPTURE_SCHEMA, contract_id=ENGINEERING_CONTRACT, task_id=task_id,
        replay_owner_sha256=script_sha, source_repository='justicedao/ipfs_uscode', source_revision=REVISION,
        source_parquet_sha256=PARQUET_SHA256, parents=parents, source_requests=requests, source_spans=spans,
        runtime_context=dict(python_executable=sys.executable,python_version=sys.version,packages=runtime_packages),
        result=result, native_operations=2 if profile['dimension'] == 4096 else 0,
        actual_source_forwards=4 if profile['dimension'] == 4096 else 0, **FALSE)
    _engineering_observation(capture, dict(bytes=1, sha256='0' * 64))
    require(file_pin(__file__)['sha256'] == script_sha
            and file_pin(PARQUET)['sha256'] == PARQUET_SHA256, 'capture source/corpus changed')
    raw = wire(capture) + b'\n'
    require(len(raw) <= ENGINEERING_MAX_BYTES, 'genuine engineering capture exceeds fixed bound')
    pin = write_new(directory, 'capture.json', raw)
    return dict(capture=pin, task_id=task_id, independently_reviewed=False,
        native_operations=capture['native_operations'], actual_source_forwards=capture['actual_source_forwards'],
        completion_allowed=False, **FALSE)


# Private merger fragment for scripts/ops/legal_ir/replay_born_alive_width.py only.
# Not an independent product owner or executable launch path.

SPACY8_MEASUREMENT_SCOPE = 'target_aware_linguistic_feature_reconstruction_not_formula_fidelity'
SPACY8_SUCCESSOR_PROFILE_ID = 'spacy_linguistic8_frozen_feature_reconstruction/v2'
SPACY8_PROFILE_ID = 'legacy-linguistic-features-8d/v1'
SPACY8_BUNDLE = CANONICAL / 'workspace/test-logs/legacy-linguistic-20261001/release-e2e/local_en_core_web_sm/checkpoint-after-two-epochs'
SPACY8_MODEL_DIRECTORY = Path('/home/barberb/.local/lib/python3.12/site-packages/en_core_web_sm')
SPACY8_MODEL_FILES_SHA256 = '8dcaf7d0276e5e0adf7aba9daeb16042f69d962d9fa7f51c5e01822c17c47e10'
SPACY8_IDENTITY_SHA256 = '54a6867209ed68230035571dc80a6a01c3f18905a9b43ab42c7e8474c74462d5'
_SPACY8_PREFIX = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/'
_SPACY8_SOURCE_FILES = (
    ('_contract.py', 16164, 'ad9603c7b4dd80736aa9bb32dc4ffc537149f1d111b265c95b6dbedc5dbfe8aa'),
    ('legacy_v1/__init__.py', 1994, 'bdbe2843741514298d49ce2c5ed8aab1c1aeb447b8cae515c81aaa7e0f02dae6'),
    ('legacy_v1/linguistic.py', 21063, 'baca84b44f7eda33466ffdc75170d904f480aafb47a779131337d90ed9a7bca3'),
    ('legacy_v1/_snapshot/MANIFEST.json', 22117, '58935518a2114e361855f8832ab4c38af5671296fde657053e15a9139baaa314'),
    ('legacy_v1/_linguistic_snapshot/__init__.py', 751, '209d89df0ac32061a5237d87d19e42bbd0ddd60b0ad8ac939b44cc18c5156b36'),
    ('legacy_v1/_linguistic_snapshot/MANIFEST.json', 1178, 'f44966d10d21f6f97ef89d967f411f5d86fe7195a0aa212269e3c785e27ddfa3'),
)
_SPACY8_SHARED_SOURCE_FILES = (
    ('ipfs_datasets_py/logic/autoformal/tree_pin.py', 2052,
     'ec43fd9379f3c9198451e8d62d98db53826dcf115e6858039a73c3da7d72a1c2'),
    ('ipfs_datasets_py/logic/legal_ir/canonical_compiler.py', 37034,
     'daa148e076ebfd0e61f5a06a915bb924023873bcad5b41923976a33e2693ebdd'),
    ('ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py', 13437,
     '79eeb9072e74e68dc5fab7640b5ad49e82131d0f35232ff473c7f2dfbe232c64'),
    ('ipfs_datasets_py/logic/deontic/utils/deontic_parser.py', 337171,
     '980e214b068184823cdb318024c3eef9e8b03852c79d3cf58396cc1dca8d6eec'),
)
_SPACY8_MODEL_FILES = (
    ('__init__.py', 237, 'c8eb57079c03fc4157c227f641781fbcb3e9d11439abe1bf0b72e4c0fa78a38d'),
    ('en_core_web_sm-3.8.0/LICENSE', 1056, '3933c176979b68bc6d0bcc902c7d6c130f1d127f476f17ba5cdba8d99cfd0012'),
    ('en_core_web_sm-3.8.0/LICENSES_SOURCES', 2347, '20d9dfacd215112251f15341edd1a47b1f98bf393a212f10f194ffdc7ee98a90'),
    ('en_core_web_sm-3.8.0/README.md', 2587, '91b0ed1742ea0803034b4d769c4536e88d9d4da7808d833f2a804b6c54aae220'),
    ('en_core_web_sm-3.8.0/accuracy.json', 6341, 'e7572d7f2f3c18e9921471f9d0b3424f8cf7f1a909ae484fa10b780a13f4c676'),
    ('en_core_web_sm-3.8.0/attribute_ruler/patterns', 14735, 'f8b97f7ebef9b8536bba5f0fc1e73af6183563e96e2325bcbb021b8c6dbc6683'),
    ('en_core_web_sm-3.8.0/config.cfg', 5527, '65c545ca2da5bd4b87b22d4917318605360b37dee6ed6b18516a036f87319f79'),
    ('en_core_web_sm-3.8.0/lemmatizer/lookups/lookups.bin', 972893, 'eb64f40c0f8396d1762730c0ddf4dad2a52d138f5a389f71a1a1d088173b7737'),
    ('en_core_web_sm-3.8.0/meta.json', 10106, '7456349002fa8cf31111051bd37fdbea67a1b7f7a0a60ce235466f98a6758125'),
    ('en_core_web_sm-3.8.0/ner/cfg', 221, 'a7172edadafba9f472e9ac0f2660eec04b6405e471be9e20267b79c67288d22d'),
    ('en_core_web_sm-3.8.0/ner/model', 6154601, 'cd93e9ca9126c69f1d10a1039ef67c3d9ec1223b44d079856705970f0f19ff4e'),
    ('en_core_web_sm-3.8.0/ner/moves', 1064, 'd82b13473ebd33e0396004dd22f00c71fe3c1251742bf1f7c4554f23fd3b0af4'),
    ('en_core_web_sm-3.8.0/parser/cfg', 222, 'e2a240ef01f95e58f5dd4c9d6e90d61f597b8d998966570d3009dd81e8879780'),
    ('en_core_web_sm-3.8.0/parser/model', 319909, 'e0098910535a863d430082ece57455d5fa071cd4ca3a0054e80582076c752b1e'),
    ('en_core_web_sm-3.8.0/parser/moves', 1571, 'ec41318c32eb7f9e4d8f050b2e8466ee67954d2d3455c1aec73abf46c82dd67f'),
    ('en_core_web_sm-3.8.0/senter/cfg', 23, '2a4db4a729b6469da1f87d71cc7cd3ed2a73360cc85326821e850836c4671103'),
    ('en_core_web_sm-3.8.0/senter/model', 197089, 'b69e7174a0b6307739adec3c8053ac45fdbad7171c4d3d8bfcd9713ecbc01f8c'),
    ('en_core_web_sm-3.8.0/tagger/cfg', 615, 'd484c3d9391f37bf9c727aa2eb4c477a24cb103020f95e52dc37842818b50118'),
    ('en_core_web_sm-3.8.0/tagger/model', 19829, '1ec3d93f38cebe172f2b5c89d84be72856ce42c8f1a64f1699f1d98a771f36b7'),
    ('en_core_web_sm-3.8.0/tok2vec/cfg', 4, 'f8a5a26e3056eb6fb06deeb3dbccfd88ae74900200c98c70b5966bbb7ec9d4de'),
    ('en_core_web_sm-3.8.0/tok2vec/model', 6269370, 'e84fc06eb319c94d28e460fc334e292120b01f18baa5dc8b50c977459820a090'),
    ('en_core_web_sm-3.8.0/tokenizer', 77066, 'b014e8bba4958b120af2d0c1c63eabb7c00379f2bacaf10df7c5325efd2ea467'),
    ('en_core_web_sm-3.8.0/vocab/key2row', 1, '76be8b528d0075f7aae98d6fa57a6d3c83ae480a8469e668d7b0af968995ac71'),
    ('en_core_web_sm-3.8.0/vocab/lookups.bin', 70040, 'fce9c883c56165f29573cc938c2a1c9d417ac61bd8f56b671dd5f7996de70682'),
    ('en_core_web_sm-3.8.0/vocab/strings.json', 1103983, 'b1966d1f07a05b68576df07f43f40203b4e11124ad82cc839e8312ad8d7fdae7'),
    ('en_core_web_sm-3.8.0/vocab/vectors', 128, '14772b683e726436d5948ad3fff2b43d036ef2ebbe3458aafed6004e05a40706'),
    ('en_core_web_sm-3.8.0/vocab/vectors.cfg', 22, 'ff4359091952c8cd16f1f0482f5770fb82d1707368d5cca3c46aa501f552e3c5'),
    ('meta.json', 10106, '7456349002fa8cf31111051bd37fdbea67a1b7f7a0a60ce235466f98a6758125'),
)
_SPACY8_BUNDLE_FILES = (
    ('manifest.json', 5241, 'd0657114967d2019889d8b39b2581107bd4a3affcd07f2555fe8f73fbe5e9a39'),
    ('core.state.json', 453998, '498fa1029c349903a38ca58ef20115a45c3248d2258aaae8a013f69ce2a5ef94'),
)
_SPACY8_SOURCE_SPANS = (
    {'id': 'born-alive-10-1059-n', 'legal_id': 'usc:us:10:1059', 'parent_sha256': '6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2', 'parent_bytes': 30787, 'byte_start': 14849, 'byte_end': 16175, 'char_start': 14806, 'char_end': 16128, 'span_sha256': 'bfdabce62b4c822fa39aaa517ab55815501c68b6fb10ee292accb3015e7c9faf', 'span_bytes': 1326, 'coverage': 'complete_literal_subsection', 'full_parent_coverage': False},
    {'id': 'born-alive-1-8-b', 'legal_id': 'usc:us:1:8', 'parent_sha256': 'fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a', 'parent_bytes': 1584, 'byte_start': 722, 'byte_end': 1282, 'char_start': 721, 'char_end': 1281, 'span_sha256': 'e9b539bd922e3196c8bef902808393b47ce74601d64353fb505625fa0e006851', 'span_bytes': 560, 'coverage': 'complete_literal_subsection', 'full_parent_coverage': False},
)


def _spacy8_fixed_file(path, count, digest):
    """Authenticate one original ordinary file without a model import."""
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(strict=True),
            'spaCy input path must be canonical and nonsymlink')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_size == count and 0 < count <= 16 * 1024**2,
            'spaCy input file identity/size differs')
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(count + 1)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    require(identity(before) == identity(opened) == identity(closed)
            == identity(path.lstat()) and len(raw) == count and sha(raw) == digest,
            'spaCy input changed or authentication failed')
    return raw


def _spacy8_validate_sources(requests, spans):
    """Only the two complete pinned occurrences may enter this successor."""
    require(type(requests) is list and type(spans) is list
            and len(requests) == len(spans) == 2,
            'spaCy replay requires both exact complete source occurrences')
    require(wire(spans) == wire(list(_SPACY8_SOURCE_SPANS)),
            'spaCy full source span coordinates/hash differ')
    for row, span, source in zip(requests, spans, SOURCES, strict=True):
        require(type(row) is dict and set(row) == {'id', 'source_text', 'source'}
                and row['id'] == source['id'], 'spaCy source occurrence identity differs')
        text = row['source_text']
        require(type(text) is str and 0 < len(text.encode('utf-8')) == span['span_bytes']
                and sha(text.encode('utf-8')) == span['span_sha256'],
                'spaCy source text must be the complete exact UTF8 span')
        expected = dict(artifact=dict(sha256=span['parent_sha256'], bytes=span['parent_bytes']),
            source_kind='us_code', release_id=REVISION, document_id=span['legal_id'],
            language='en', citation=span['legal_id'], byte_start=span['byte_start'],
            byte_end=span['byte_end'], normalization='identity')
        require(type(row['source']) is dict and wire(row['source']) == wire(expected),
                'spaCy original source custody differs')
    return sha(wire(dict(requests=requests, spans=spans)))


def _spacy8_vector(vector):
    require(type(vector) is list and len(vector) == 8 and all(
        type(value) is float and math.isfinite(value) for value in vector),
        'spaCy output must contain exactly eight ordinary finite float coordinates')
    require(math.hypot(*vector) > 0, 'spaCy cosine is undefined for a zero feature vector')
    return list(vector)


def _spacy8_metrics(metrics):
    require(type(metrics) is dict and set(metrics) == {'cosine_similarity', 'reconstruction_loss'}
            and all(type(value) is float and math.isfinite(value) for value in metrics.values())
            and -1 <= metrics['cosine_similarity'] <= 1 and metrics['reconstruction_loss'] >= 0,
            'spaCy independent reconstruction metrics must be finite and bounded')
    return dict(metrics)


def _spacy8_unchanged(before, after, label):
    require(type(before) is bytes and before == wire(after),
            'spaCy ' + label + ' changed during frozen replay')


def _spacy8_preflight(root):
    """Authenticate original bundle, numerical/codec closure and installed model."""
    root = Path(root).resolve(strict=True)
    source_pins, source_bytes = {}, {}
    for relative, count, digest in _SPACY8_SOURCE_FILES:
        raw = _spacy8_fixed_file(root / _SPACY8_PREFIX / relative, count, digest)
        source_pins[relative] = dict(bytes=len(raw), sha256=digest)
        source_bytes[relative] = raw
    for relative, count, digest in _SPACY8_SHARED_SOURCE_FILES:
        raw = _spacy8_fixed_file(root / relative, count, digest)
        source_pins['shared/' + relative] = dict(bytes=len(raw), sha256=digest)
    numerical = json.loads(source_bytes['legacy_v1/_snapshot/MANIFEST.json'])
    require(type(numerical.get('files')) is list and 1 <= len(numerical['files']) <= 64,
            'spaCy numerical source population differs')
    directory = root / _SPACY8_PREFIX / 'legacy_v1/_snapshot'
    for entry in numerical['files']:
        name = entry['vendored_path']
        require(type(name) is str and Path(name).name == name,
                'spaCy numerical source path differs')
        raw = _spacy8_fixed_file(directory / name, entry['vendored_bytes'], entry['vendored_sha256'])
        source_pins['legacy_v1/_snapshot/' + name] = dict(bytes=len(raw), sha256=entry['vendored_sha256'])
    init = directory / '__init__.py'
    raw = _spacy8_fixed_file(init, init.stat().st_size, numerical['snapshot_init_sha256'])
    source_pins['legacy_v1/_snapshot/__init__.py'] = dict(bytes=len(raw), sha256=numerical['snapshot_init_sha256'])
    codec = root / _SPACY8_PREFIX / 'legacy_v1/_linguistic_snapshot/spacy_modal_codec.py'
    raw = _spacy8_fixed_file(codec, 306403, '16ec4e141d5cb2f9d37cd4db42733921bc046e17fee12afc43ab31ca7a60cd59')
    source_pins['legacy_v1/_linguistic_snapshot/spacy_modal_codec.py'] = dict(bytes=len(raw), sha256=sha(raw))
    bundle = {}
    for name, count, digest in _SPACY8_BUNDLE_FILES:
        bundle[name] = _spacy8_fixed_file(SPACY8_BUNDLE / name, count, digest)
    # The full package closure has a fixed allowlist; bytecode is never a producer input.
    observed = []
    for path in SPACY8_MODEL_DIRECTORY.rglob('*'):
        require(not path.is_symlink(), 'spaCy model package may not contain aliases')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            observed.append(path.relative_to(SPACY8_MODEL_DIRECTORY).as_posix())
    require(sorted(observed) == [item[0] for item in _SPACY8_MODEL_FILES],
            'spaCy model package population differs')
    model_pins, model_digest = {}, hashlib.sha256()
    for name, count, digest in _SPACY8_MODEL_FILES:
        raw = _spacy8_fixed_file(SPACY8_MODEL_DIRECTORY / name, count, digest)
        relative = name.encode()
        model_digest.update(len(relative).to_bytes(8, 'big'))
        model_digest.update(relative)
        model_digest.update(count.to_bytes(8, 'big'))
        model_digest.update(raw)
        model_pins[name] = dict(bytes=count, sha256=digest)
    require(model_digest.hexdigest() == SPACY8_MODEL_FILES_SHA256,
            'spaCy installed model original identity differs')
    return dict(source_pins=source_pins, model_pins=model_pins,
                manifest=json.loads(bundle['manifest.json']), core=json.loads(bundle['core.state.json']),
                checkpoint_identity={name: dict(bytes=count, sha256=digest)
                                     for name, count, digest in _SPACY8_BUNDLE_FILES})


def _spacy8_model_contract(description, manifest):
    require(type(description) is dict and description.get('training_profile') == SPACY8_PROFILE_ID
            and description.get('linguistic_identity') == manifest['linguistic_identity']
            and description.get('linguistic_identity_sha256') == SPACY8_IDENTITY_SHA256
            and description.get('effective_configuration') == manifest['effective_configuration'],
            'spaCy restored profile/backend/producer configuration differs')
    require(description.get('reconstruction_objective') == 'historical_target_aware_safe_projection'
            and description.get('reconstruction_is_fidelity_evidence') is False
            and description.get('formula_training_executed') is False
            and all(description.get(key) is False for key in
                ('admitted', 'formalized', 'semantic_qualification', 'independent_formula_generation')),
            'spaCy target-aware feature-only scope differs')
    identity = description['linguistic_identity']
    require(identity.get('backend') == 'local_en_core_web_sm'
            and identity.get('used_fallback_model') is False
            and identity.get('spacy_version') == '3.8.14'
            and identity.get('model_version') == '3.8.0'
            and identity.get('model_files_sha256') == SPACY8_MODEL_FILES_SHA256,
            'spaCy actual trained model is required; fallback is forbidden')


def _spacy8_runtime():
    """Bind actual imported packages, separately from the conserved model bytes."""
    versions = dict(spacy='3.8.14', en_core_web_sm='3.8.0', numpy='1.26.4', thinc='8.3.13')
    package_root = SPACY8_MODEL_DIRECTORY.parent
    observed = {}
    for name, expected_version in versions.items():
        module = importlib.import_module(name)
        expected_path = package_root / name / '__init__.py'
        require(type(getattr(module, '__file__', None)) is str
                and module.__file__ == str(expected_path)
                and getattr(module, '__version__', None) == expected_version,
                'genuine spaCy runtime version/origin differs: ' + name)
        pin = file_pin(module.__file__, 16 * 1024**2)
        require(pin['path'] == str(expected_path), 'genuine spaCy runtime source resolves elsewhere: ' + name)
        observed[name] = dict(version=expected_version, origin=pin)
    return observed


def _run_spacy8_reconstruction(root, requests, spans):
    """Frozen spaCy eight-feature reconstruction, with the original target-aware readout.

    The deterministic source hash is the target. This restores trained sparse
    categorical heads but does not claim a learned compressed embedding or any
    source-text/formula reconstruction. Only the original replayer calls this
    helper after source/native admission and exact physical source capture.
    """
    root = Path(root).resolve(strict=True)
    source_fingerprint = _spacy8_validate_sources(requests, spans)
    admitted = _spacy8_preflight(root)
    runtime = _spacy8_runtime()
    module_name = ('ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
                   'autoencoder_lineages.legacy_v1.linguistic')
    module = importlib.import_module(module_name)
    require(Path(module.__file__).resolve() == root / _SPACY8_PREFIX / 'legacy_v1/linguistic.py',
            'spaCy linguistic owner import origin differs')
    loader = module.load_training_checkpoint
    model = loader(SPACY8_BUNDLE)
    require(type(model) is module.LinguisticAutoencoder,
            'spaCy replay requires the genuine retained linguistic autoencoder')
    description = model.describe()
    _spacy8_model_contract(description, admitted['manifest'])
    require(model.formula_checkpoint is None and model.formula_decoder_description().get('attached') is False,
            'spaCy linguistic profile may not attach a formula head')
    require(wire(model.state.to_dict()) == wire(admitted['core']),
            'spaCy restored sparse state differs from retained core')
    state_before = wire(model.state.to_dict())
    description_before = wire(description)
    methods = tuple(getattr(type(model), name) for name in
                    ('build_sample', 'encode', 'decode', 'linguistic_observation', 'describe'))
    rows = []
    for request, span, source in zip(requests, spans, SOURCES, strict=True):
        sample = model.build_sample(title=source['title'], section=source['section'],
                                    text=request['source_text'], citation=source['legal_id'])
        require(sample.text == request['source_text'], 'spaCy sample source text changed')
        target = _spacy8_vector(sample.embedding_vector)
        diagnostic = model.linguistic_observation(sample)
        require(diagnostic.get('source_sha256') == span['span_sha256']
                and diagnostic.get('linguistic_identity_sha256') == SPACY8_IDENTITY_SHA256
                and diagnostic.get('vector_origin') == 'deterministic_linguistic_feature_hash'
                and diagnostic.get('decoded_feature_vector') == target,
                'spaCy feature source/producer identity differs')
        encoding = diagnostic['encoding']
        normalized = ' '.join(request['source_text'].split())
        require(encoding.get('text') == request['source_text']
                and encoding.get('normalized_text') == normalized
                and encoding.get('model_name') == 'en_core_web_sm'
                and encoding.get('used_fallback_model') is False
                and type(encoding.get('tokens')) is list and len(encoding['tokens']) > 0,
                'spaCy actual full-source tokenization evidence differs')
        encoded = model.encode(sample, use_sample_memory=False)
        reconstructed = _spacy8_vector(model.decode(encoded))
        measured = _spacy8_metrics(independent_metrics(target, reconstructed))
        rows.append(dict(id=request['id'], input_vector=target, reconstructed_vector=reconstructed,
            metrics=measured, source_sha256=span['span_sha256'], actual_token_count=len(encoding['tokens']),
            normalized_source_sha256=sha(normalized.encode()), raw_encoding=encoding,
            encoded_diagnostic=encoded, linguistic_ir=diagnostic['modal_ir'],
            token_offsets_domain='whitespace_collapsed_source_characters_not_original_UTF8_offsets',
            sample_memory_used=False, formula_head_attached=False))
        _spacy8_unchanged(state_before, model.state.to_dict(), 'weights/state')
        require(_spacy8_validate_sources(requests, spans) == source_fingerprint,
                'spaCy source inputs changed during frozen replay')
    _spacy8_unchanged(description_before, model.describe(), 'producer/configuration')
    require(module.load_training_checkpoint is loader and methods == tuple(
        getattr(type(model), name) for name in
        ('build_sample', 'encode', 'decode', 'linguistic_observation', 'describe')),
        'spaCy original producer callable changed during replay')
    closing = _spacy8_preflight(root)
    compare_stable(runtime, _spacy8_runtime(), 'genuine_spacy_runtime_closing_identity')
    _spacy8_unchanged(wire(admitted), closing, 'source/model/checkpoint bytes')
    _spacy8_unchanged(state_before, model.state.to_dict(), 'weights/state')
    require(_spacy8_validate_sources(requests, spans) == source_fingerprint,
            'spaCy closing source inputs changed during frozen replay')
    return dict(profile_id=SPACY8_SUCCESSOR_PROFILE_ID, measurement_scope=SPACY8_MEASUREMENT_SCOPE,
        coordinate_domain='deterministic_spacy_lexical_pos_dependency_modal_feature_hash8d',
        reconstruction_loss_definition='coordinate_mean_squared_error(spacy_feature_target,historical_target_aware_decode_encode)',
        rows=rows, metrics={key: math.fsum(row['metrics'][key] for row in rows) / 2
                           for key in ('cosine_similarity', 'reconstruction_loss')},
        producer_evidence=dict(producer_profile_id=SPACY8_PROFILE_ID,
            runtime_packages=runtime,
            linguistic_identity=description['linguistic_identity'],
            linguistic_identity_sha256=SPACY8_IDENTITY_SHA256,
            effective_configuration=description['effective_configuration'],
            source_pins=admitted['source_pins'], model_files=admitted['model_pins'],
            feature_preprocessing='collapse_whitespace_then_strip', source_text_truncated=False,
            token_ceiling=None, max_codec_feature_keys=64, sample_memory_used=False,
            target_aware_reconstruction=True, deterministic_feature_target=True,
            vector_weight_table_rows={key: len(value) for key, value in admitted['core'].items()
                                     if key.endswith('_embedding_weights')},
            weights_state_unchanged=True, source_model_checkpoint_closing_pins_matched=True,
            formula_head_attached=False, formula_origin='frozen_linguistic_IR_compiler_not_neural_generation'),
        checkpoint_identity=admitted['checkpoint_identity'], **FALSE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--output-directory', type=Path)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--probe', action='store_true')
    modes.add_argument('--engineering-width-v2', action='store_true', help='Replay a separately selected and independently reviewed genuine producer capture offline')
    modes.add_argument('--capture-engineering-width-v2', action='store_true', help='Operator acquisition under existing source/native/resource admission; never used by board validation')
    parser.add_argument('--native4096-config', type=Path)
    parser.add_argument('--resource-cgroup')
    args = parser.parse_args()
    if args.capture_engineering_width_v2:
        require(args.output_directory is not None, 'explicit fresh operator capture directory required')
        config=None
        if args.native4096_config is not None:
            require(stat.S_ISREG(args.native4096_config.lstat().st_mode), 'ordinary capture configuration required')
            config=_engineering_json(_engineering_read(file_pin(args.native4096_config)))
        result=capture_engineering_width_profile(args.root,args.task_id,output_directory=args.output_directory,
            native4096_config=config,resource_cgroup=args.resource_cgroup)
        print(json.dumps(result,sort_keys=True))
        return
    require(args.native4096_config is None and args.resource_cgroup is None, 'capture context cannot be supplied to ordinary replay')
    if args.engineering_width_v2:
        require(args.output_directory is not None, 'explicit successor task output directory required')
        print(json.dumps(_publish_engineering_task(args.root,args.task_id,args.output_directory),sort_keys=True))
        return
    if args.probe:
        result = preflight(args.root,args.task_id)
        print(json.dumps(dict(status='available',dimension=result['dimension'],
            capability='legal-ir-born-alive-width-'+str(result['dimension'])+'-replay-v1',
            encoder_executed=False,model_loaded=False)))
        return
    require(args.output_directory is not None, 'explicit task output directory required')
    directory = output_directory(args.root,args.task_id,args.output_directory)
    # Product task directories contain exactly the three reviewed outputs.
    # Raw producer/cache/model replay records use a private temporary tree.
    with tempfile.TemporaryDirectory(prefix='born-alive-width-replay-') as private:
        result = run_selected_profile(args.root,args.task_id,output_directory=private)
    artifacts,payloads = [],{}
    for kind,name,payload in (('observation','observation.json',wire(result['observation'])+b'\n'),
                              ('checkpoint','checkpoint.zip',result['checkpoint_archive'])):
        destination = directory/name
        payloads[name]=payload
        artifacts.append(dict(kind=kind,path=str(destination.relative_to(args.root.resolve())),sha256=sha(payload)))
    receipt = dict(schema=RECEIPT_SCHEMA,task_id=args.task_id,task_kind='width',status='inventory',
        authority=dict(admitted=False,formalized=False),artifacts=artifacts,
        evidence=dict(dimension=dimension_for(args.task_id),measurement_scope=SCOPE))
    payloads['receipt.json']=wire(receipt)+b'\n'
    publish_outputs(args.root,args.task_id,directory,payloads)
    print(json.dumps(dict(task_id=args.task_id,status='observed',measurement_scope=SCOPE,
        replay_directory=result['replay_directory'],quality_qualified=False)))


if __name__ == '__main__':
    main()
