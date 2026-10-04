"""Finalize the exact already-built archive as ordered Git-sized byte chunks.

This publication-only adapter preserves the reviewed builder and its original
archive. It changes the physical delivery format, not any experimental bytes.
All original member, source, input, test, audit and resource checks still run.
"""
from pathlib import Path
import hashlib,json
E=Path(__file__).resolve().parent
P=E.parents[4]
R=P/'workspace/test-logs/decoder-action-binding-20261003'
BUILDER_SHA='560a707241fe5547bcb52e77b268aa2cb23cb1540bb2bd533aee309fed17987c'
# Exact original tar stream, retained locally; only parts are added to Git.
EXACT=dict(bytes=106911344,sha256='1830569d1c79cfdd897531655ba3283799edf9da0f5891347cf8bbb82f487ec6')
PART_BYTES=48_000_000
SUPPORT=('README.md','finalize_chunked_evidence.py','publish_chunked.py')

def info(path):
 h=hashlib.sha256();size=0
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b);size+=len(b)
 return dict(bytes=size,sha256=h.hexdigest())

def chunk_archive(path):
 assert info(path)==EXACT
 parts=[];offset=0;whole=hashlib.sha256()
 with path.open('rb') as stream:
  while content:=stream.read(PART_BYTES):
   name='evidence.tar.xz.part-'+str(len(parts)+1).zfill(3);target=E/name
   if target.exists():assert target.read_bytes()==content
   else:target.write_bytes(content)
   digest=info(target);assert 0<digest['bytes']<=PART_BYTES
   parts.append(dict(filename=name,offset_bytes=offset,**digest));offset+=len(content);whole.update(content)
 assert offset==EXACT['bytes'] and whole.hexdigest()==EXACT['sha256']
 return parts

def main():
 source=(R/'build_evidence.py').read_text()
 assert hashlib.sha256(source.encode()).hexdigest()==BUILDER_SHA
 def replace(old,new):
  nonlocal source
  assert source.count(old)==1,old
  source=source.replace(old,new)
 replace(" require(not E.exists(),'new immutable evidence directory required')", " require(E.is_dir() and not (E/'manifest.json').exists() and not (E/'results.json').exists(),'fresh final metadata required')")
 start=source.index(' E.mkdir(parents=True)\n archive=E/\'evidence.tar.xz\'')
 end=source.index(" with tarfile.open(archive,'r:xz') as bundle:",start)
 source=source[:start]+" archive=E/'evidence.tar.xz'\n require(info(archive)==EXACT,'exact retained archive required')\n"+source[end:]
 replace(' archive_info=info(archive)', ' archive_info=info(archive)\n parts=chunk_archive(archive)\n support={name:info(E/name) for name in SUPPORT}')
 replace(" write(E/'manifest.json',m)", " m.update(archive_parts=parts,part_maximum_bytes=PART_BYTES,publication_support=support,logical_archive_available_after_reassembly=True,delivery='Concatenate ordered parts; verify archive SHA-256/bytes before tar extraction.')\n write(E/'manifest.json',m)")
 replace("for n in ('evidence.tar.xz','manifest.json','results.json')", "for n in ([p['filename'] for p in parts]+['manifest.json','results.json']+list(SUPPORT))")
 replace(" write(E/'results.json',result);write(R/'owned-files.json',owned)", " result.update(archive_parts=parts,logical_archive_available_after_reassembly=True)\n write(E/'results.json',result);write(R/'owned-files.json',owned)")
 replace("if __name__=='__main__':main()",'')
 scope=dict(__name__='_sealed_chunk_publication',__file__=str(R/'build_evidence.py'),EXACT=EXACT,
  chunk_archive=chunk_archive,PART_BYTES=PART_BYTES,SUPPORT=SUPPORT)
 exec(compile(source,str(R/'build_evidence.py')+'[chunk_delivery_only]','exec'),scope)
 scope['main']()

if __name__=='__main__':main()
