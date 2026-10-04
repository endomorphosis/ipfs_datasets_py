"""Write reviewed supplemental publication evidence; never alter the completed archive."""
from pathlib import Path
import json
from publication_descendant_support_v3 import P,R,E,TESTED_PARENT,PUBLICATION_PARENT,info,read,validate_descendant
from publication_descendant_support import validate_supplement as validate_prior_supplement

if __name__=='__main__':
    advance=validate_descendant(PUBLICATION_PARENT)
    prior_info=validate_prior_supplement();prior=read(E/'publication-supplement.json')
    review_path=R/'publication-descendant-script-review-v3.json'
    review=read(review_path)
    assert review['passed'] is True and review['findings']==[]
    for name,expected in review['artifacts'].items():assert info(Path(name).read_bytes())==expected,name
    scripts=['publication_descendant_support_v3.py','prepare_publication_support_v3.py',
             'prepare_publication_review_v3.py','publish_v3.py','final_verify_v3.py']
    for name in scripts+['publication-source-advance-review-v3.json']:
        assert review['artifacts'][str(R/name)]==info((R/name).read_bytes()),name
    manifest=read(E/'manifest.json')
    immutable_names=['manifest.json','results.json','README.md','publication-supplement.json']+[p['filename'] for p in manifest['archive_parts']]+list(prior['files'])
    immutable={name:info((E/name).read_bytes()) for name in immutable_names}
    original=set(manifest['original_artifact_archive_paths'])|set(manifest['referenced_artifacts'])
    original|={str(E/name) for name in immutable_names}|set(prior['source_paths'].values())
    needed={str(R/name) for name in scripts}|{str(review_path),str(R/'publication-source-advance-review-v3.json')}
    for receipt in (review,read(R/'publication-source-advance-review-v3.json')):needed.update(receipt['artifacts'])
    needed.difference_update(original)
    contents={};source_paths={}
    for index,source in enumerate(sorted(needed)):
        path=Path(source);assert path.is_file() and not path.is_symlink() and path.is_relative_to(R),source
        raw=path.read_bytes();assert len(raw)<=2_000_000,source
        name=path.name if path.parent==R else 'descendant-v3-'+info(source.encode())['sha256'][:12]+'-'+path.name
        assert name not in contents and not (E/name).exists(),name
        contents[name]=raw;source_paths[name]=source
    assert sum(map(len,contents.values()))<=30_000_000
    value=dict(schema='source-modality-publication-supplement/v1',tested_parent=TESTED_PARENT,
        publication_parent=PUBLICATION_PARENT,source_advance=advance,prior_supplement=prior_info,immutable_evidence=immutable,
        files={name:info(raw) for name,raw in contents.items()},source_paths=source_paths,
        original_artifact_publication_paths={source:str((E/name).relative_to(P)) for name,source in source_paths.items()},
        archive_rebuilt=False,tests_reexecuted=False,frozen_six_fit_reexecuted=False,
        qualified=False,admitted=False,lake_executed=False)
    owned=read(R/'owned-files-v2.json')+[str((E/name).relative_to(P)) for name in sorted(contents)]+[str((E/'publication-supplement-v3.json').relative_to(P))]
    assert len(owned)==len(set(owned)) and not (R/'owned-files-v3.json').exists()
    assert not (E/'publication-supplement-v3.json').exists()
    for name,raw in contents.items():
        with (E/name).open('xb') as stream:stream.write(raw)
    with (E/'publication-supplement-v3.json').open('x') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')
    with (R/'owned-files-v3.json').open('x') as stream:stream.write(json.dumps(owned,indent=2)+'\n')
    assert all(info((E/name).read_bytes())==expected for name,expected in immutable.items())
    print(json.dumps(dict(supplemental_files=len(contents)+1,owned_files=len(owned),archive_unchanged=True)))
