"""Exercise the recorder on the unchanged real8 packet with zero submissions."""
import importlib.abc
from pathlib import Path
import sys
from types import ModuleType
from prepare_structured_span_pilot import pin, read, write

F=Path(__file__).resolve().parent
J=F.parent/'legal-joint-readout-20261011-01'
N=F.parent/'legal-native-cache-20261011-01'

class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','transformers','sentence_transformers','numpy'}:
            raise AssertionError('numerical import prohibited in blank recorder')
        return None

def main():
    sys.meta_path.insert(0,NoModels())
    def audit(event,values):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn')) or event=='os.system':
            raise AssertionError('network/process prohibited in blank recorder')
    sys.addaudithook(audit)
    for name in ('ipfs_datasets_py','ipfs_datasets_py.logic','ipfs_datasets_py.logic.legal_ir'):
        module=ModuleType(name);module.__path__=[str((F/'datasets').joinpath(*name.split('.')))];sys.modules[name]=module
    from ipfs_datasets_py.logic.legal_ir import statutory_review_recording as recording
    packet_path=J/'statutory-source-review-packet.json';packet_pin=pin(packet_path)
    assert packet_pin['sha256']=='bf42fb6a854d0a5b8f77e09b1bfd6e1fad4a6bf47323dd246826774b9bf6dc06'
    packet=read(packet_path);expected=recording.digest(packet)
    assert expected=='73fbfd8731ea3b11ec8a49a4f8b21ba2f80a0f34009d744c301540417d559054'
    bindings=read(N/'source-artifact-pins.json');provenance=pin(N/'source-view-provenance.json')
    bindings[provenance['sha256']]=provenance
    def resolver(ref):
        value=bindings[ref['sha256']];assert value['bytes']==ref['bytes'] and pin(value['path'])==value
        return Path(value['path'])
    guide=recording.submission_guide(packet,expected_packet_sha256=expected,artifact_resolver=resolver)
    receipt=recording.record_reviews(packet,[],expected_packet_sha256=expected,artifact_resolver=resolver)
    replay=recording.validate_recording(receipt,packet,[],expected_packet_sha256=expected,artifact_resolver=resolver)
    assert all(value==0 for value in receipt['admission_masks'].values()) and pin(packet_path)==packet_pin
    outputs=[write(F/'statutory-review-submission-guide.json',guide),
        write(F/'statutory-review-pending-recording.json',receipt),
        write(F/'statutory-review-pending-replay.json',replay)]
    write(F/'statutory-review-pending-build.json',dict(schema='real8-statutory-pending-recorder-build/v1',
        passed=True,findings=[],inputs=[packet_pin,*bindings.values()],outputs=outputs,
        packet_canonical_sha256=expected,actual_submissions=0,actual_human_labels=0,
        training_admissions=0,evaluation_admissions=0,model_execution=False,source_semantics_verified=False,
        admission_masks=receipt['admission_masks'],original_packet_byte_exact=True))
    print('Real8 remains pending: zero submissions, zero labels, zero admission masks.')

if __name__=='__main__':main()
