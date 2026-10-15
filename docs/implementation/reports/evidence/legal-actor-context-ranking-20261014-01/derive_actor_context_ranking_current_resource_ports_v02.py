"""Harden unexecuted V02 resource drafts; retain every original byte.

No production imports, private reads, observations, clients or model work.
"""
import ast
import hashlib
import os
from pathlib import Path

F=Path(__file__).resolve().parent
PINS={
    'actor_context_ranking_resource_protocol_v02.py':(21063,'8838ec6f4d2f8a91da1fbba3b56b2b50de955e1eea88ee72b6b2a0e202f3390f'),
    'collect_actor_context_ranking_opening_v02.py':(9690,'afc7afe0dbba1e82e9f4c72f9dd3a1343d3776f6f3b40c951635f09c0c555b47'),
    'review_actor_context_ranking_resource_baseline_v02.py':(7532,'c3f68782666e9c71596c7a3d5cc8215ada32c6b9cf702ecba816c753d2affc6a'),
}


def read(name):
    raw=(F/name).read_bytes()
    if (len(raw),hashlib.sha256(raw).hexdigest())!=PINS[name]:raise ValueError('Retained source drift')
    return raw.decode()


def once(source,old,new):
    if source.count(old)!=1:raise ValueError('Unique source anchor required: '+old[:80])
    return source.replace(old,new)


def main():
    protocol=read('actor_context_ranking_resource_protocol_v02.py')
    protocol=once(protocol,"type(receipt['index']) is int and 1<=receipt['index']<=99",
        "type(receipt['index']) is int and receipt['index'] in (3,4,5)")
    protocol=once(protocol,"Path(receipt['path']).parent.name.startswith('opening-v')",
        "Path(receipt['path']).parent.name in ('opening-v03','opening-v04','opening-v05')")
    protocol=protocol.replace('review_actor_context_ranking_resource_baseline_v02.py','review_actor_context_ranking_resource_baseline_v03.py')
    protocol=protocol.replace('resource-observer-source-independent-review-v02.json','resource-observer-source-independent-review-v03.json')
    protocol_raw=protocol.encode();protocol_sha=hashlib.sha256(protocol_raw).hexdigest()
    collector=read('collect_actor_context_ranking_opening_v02.py')
    collector=collector.replace('resource-collection-source-independent-review-v02.json','resource-collection-source-independent-review-v03.json')
    collector=once(collector,'import sys\n','import sys\nimport types\n')
    collector=once(collector,"_spec=importlib.util.spec_from_file_location('qualified_opening_sampler_helpers',SAMPLER)\ns=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(s)",
        "s=types.ModuleType('qualified_opening_sampler_helpers')\ns.__file__=str(SAMPLER);s.__package__=''\nexec(compile(_raw,str(SAMPLER),'exec',dont_inherit=True),s.__dict__)")
    observer=read('review_actor_context_ranking_resource_baseline_v02.py')
    observer=observer.replace('resource-observer-source-independent-review-v02.json','resource-observer-source-independent-review-v03.json')
    observer=once(observer,'import importlib.util\n','import hashlib\nimport types\n')
    observer=once(observer,"spec=importlib.util.spec_from_file_location('actor_context_ranking_resource_protocol',F/'actor_context_ranking_resource_protocol_v02.py')\np=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)",
        "_protocol_path=F/'actor_context_ranking_resource_protocol_v03.py'\n_protocol_raw=_protocol_path.read_bytes()\n"
        +"if len(_protocol_raw)!="+str(len(protocol_raw))+" or hashlib.sha256(_protocol_raw).hexdigest()!="+repr(protocol_sha)+":\n"
        +"    raise ValueError('Exact current resource protocol source required before helper execution')\n"
        +"p=types.ModuleType('actor_context_ranking_resource_protocol');p.__file__=str(_protocol_path);p.__package__=''\n"
        +"exec(compile(_protocol_raw,str(_protocol_path),'exec',dont_inherit=True),p.__dict__)")
    observer=observer.replace("m.pin(F/'actor_context_ranking_resource_protocol_v02.py')","m.pin(F/'actor_context_ranking_resource_protocol_v03.py')")
    outputs={'actor_context_ranking_resource_protocol_v03.py':protocol_raw,
        'collect_actor_context_ranking_opening_v03.py':collector.encode(),
        'review_actor_context_ranking_resource_baseline_v03.py':observer.encode()}
    for name,raw in outputs.items():
        ast.parse(raw,filename=name)
        if (F/name).exists():raise ValueError('Never overwrite a draft: '+name)
    for name,raw in outputs.items():
        p=F/name
        with p.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        p.chmod(0o444)
        print(name,len(raw),hashlib.sha256(raw).hexdigest())


if __name__=='__main__':main()
