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


def output_directory(root,task_id,requested):
    """Check exact task location and all existing destinations before replay."""
    dimension=dimension_for(task_id)
    root=Path(root).absolute()
    require(root==root.resolve(strict=True),'repository root must be canonical')
    expected=root/'docs/implementation/reports/evidence/legal_ir_autoencoder'/('lirae-width-'+str(dimension))
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
        _check_output_entries(current)
    finally:
        os.close(current)
    return expected


def _check_output_entries(descriptor):
    require(set(os.listdir(descriptor))<=set(OUTPUT_NAMES),'unexpected existing task output')
    for name in OUTPUT_NAMES:
        try:
            info=os.stat(name,dir_fd=descriptor,follow_symlinks=False)
        except FileNotFoundError:
            continue
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,
                'task output must be an ordinary single-link file')


def publish_outputs(root,task_id,directory,payloads):
    """All-file conflict precheck, exclusive no-follow writes, receipt last."""
    expected=output_directory(root,task_id,directory)
    require(set(payloads)==set(OUTPUT_NAMES) and all(type(v) is bytes for v in payloads.values()),
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
        _check_output_entries(descriptor)
        present=set()
        for name in OUTPUT_NAMES:
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
        for name in OUTPUT_NAMES:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--output-directory', type=Path)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
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
