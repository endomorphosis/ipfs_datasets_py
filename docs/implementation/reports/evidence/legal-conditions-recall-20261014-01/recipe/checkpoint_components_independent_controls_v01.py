"""Independent lossless-codec probes on synthetic canonical JSON only."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_checkpoint_components.py'
spec=importlib.util.spec_from_file_location('independent_inert_components',SOURCE)
codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)

def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)
def pin(path):
    value=path.read_bytes();return dict(path=str(path),bytes=len(value),sha256=sha(value))
def main():
    vector=[-0.0,0.0,1,1.0,9007199254740993,9007199254740992.0,5e-324,1e308]
    original=dict(schema='synthetic-only/v1',model_state=dict(mixed_numeric=vector),implementation=dict(source='synthetic'),
        metadata=dict(non_tensor=[True,False,True,False,True,False,True,False],text='\\literal\n\u03b1'),parents=[dict(model_state=dict(mixed_numeric=vector))])
    original_bytes=raw(original)
    expected=dict(expected_checkpoint_sha256=sha(original_bytes),expected_model_state_sha256=sha(raw(original['model_state'])),expected_implementation_sha256=sha(raw(original['implementation'])))
    archive=codec.pack_checkpoint(original_bytes,**expected)
    require(codec.unpack_checkpoint(archive,expected_archive_sha256=sha(archive),**expected)==original_bytes,'Extreme finite numbers/int precision/signed zero and metadata changed')
    first=json.loads(archive);require(first['manifest']['component_count']==1 and first['manifest']['component_references']==2,'Exact duplicated typed array not deduplicated')
    names=['lossless exact bytes for signed-zero/int-vs-float/beyond2^53/subnormal/largefinite/escapedUnicode and bool metadata']
    matrices=dict(schema='synthetic-only/v1',model_state=dict(ints=list(range(8)),floats=list(map(float,range(8))),matrix=[list(range(4)),list(range(4,8))]),implementation={})
    matrix_bytes=raw(matrices);matrix_expected=dict(expected_checkpoint_sha256=sha(matrix_bytes),expected_model_state_sha256=sha(raw(matrices['model_state'])),expected_implementation_sha256=sha(raw(matrices['implementation'])))
    matrix_archive=codec.pack_checkpoint(matrix_bytes,**matrix_expected)
    require(json.loads(matrix_archive)['manifest']['component_count']==3,'Scalar JSON types or rectangular shape were conflated')
    require(codec.unpack_checkpoint(matrix_archive,expected_archive_sha256=sha(matrix_archive),**matrix_expected)==matrix_bytes,'Distinct shape/type roundtrip changed bytes')
    names.append('Equal flattened numbers retain distinct int/float and vector/matrix component identities')
    first['manifest']['checkpoint_bytes']+=1;false_budget=raw(first);original_raw=codec._raw;serialized_original=[]
    def watch(value):
        if isinstance(value,dict) and value.get('schema')=='synthetic-only/v1':serialized_original.append(True)
        return original_raw(value)
    codec._raw=watch
    try:
        try:codec.unpack_checkpoint(false_budget,expected_archive_sha256=sha(false_budget),**expected)
        except ValueError as error:require('decoded byte budget differs' in str(error),'Expected size-budget failure')
        else:raise AssertionError('False expanded-size metadata accepted')
    finally:codec._raw=original_raw
    require(not serialized_original,'False expanded-size archive serialized decoded checkpoint before rejection')
    names.append('False declared expanded size rejects before reconstructed checkpoint serialization')
    return dict(schema='checkpoint-components-independent-synthetic-controls/v1',passed=True,findings=[],case_count=3,cases=names,source=pin(SOURCE),controls=pin(Path(__file__).resolve()),actual_checkpoint_JSON_parses=0,actual_model_or_encoder_calls=0,numerical_package_imports=0,full_production_package_imports=0,actual_size_savings_claimed=False)

if __name__=='__main__':
    result=main();path=ROOT/'checkpoint-components-independent-controls-v01.json'
    with path.open('x') as stream:json.dump(result,stream,sort_keys=True,separators=(',',':'),allow_nan=False)
    path.chmod(0o444);print(pin(path))
