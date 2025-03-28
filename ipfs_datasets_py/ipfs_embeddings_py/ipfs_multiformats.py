import hashlib
from multiformats import CID, multihash

class ipfs_multiformats_py:
    def __init__(self, resources, metadata): 
        self.multihash = multihash
        return None
    
    # Step 1: Hash the file content with SHA-256
    def get_file_sha256(self, file_path):
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.digest()

    # Step 2: Wrap the hash in Multihash format
    def get_multihash_sha256(self, file_content_hash):
        mh = self.multihash.wrap(file_content_hash, 'sha2-256')
        return mh

    # Step 3: Generate CID from Multihash (CIDv1)
    def get_cid(self, file_path):
        file_content_hash = self.get_file_sha256(file_path)
        mh = self.get_multihash_sha256(file_content_hash)
        cid = CID('base32', 'raw', mh)
        return str(cid)
    

if __name__ == '__main__':
    ipfs_multiformats = ipfs_multiformats_py()
    file_path = 'path_to_your_file'
    cid = ipfs_multiformats.get_cid(file_path)
    print(f"CID: {cid}")