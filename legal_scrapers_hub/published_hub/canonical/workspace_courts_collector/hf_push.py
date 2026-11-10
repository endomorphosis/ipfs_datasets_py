import sys;# sanitized: expects HF_TOKEN in environment (connector secret loader removed)
# sets HF_TOKEN env from existing connector secret; never printed
from huggingface_hub import HfApi
api=HfApi();R='justicedao/ipfs_us_courts'
api.create_repo(R,repo_type='dataset',exist_ok=True)
c=api.upload_folder(folder_path='/workspace/courts/hf_stage',repo_id=R,repo_type='dataset',commit_message='Initial US courts: federal courts/courthouses/judges/forms/rules + state_rules (11 states)')
print('COMMIT',c.oid);print('URL',c.commit_url)
