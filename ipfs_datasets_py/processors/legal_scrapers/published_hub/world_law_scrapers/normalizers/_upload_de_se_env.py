import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from huggingface_hub import HfApi, create_repo

token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
if not token:
    raise SystemExit("HF_TOKEN missing")
api = HfApi(token=token)
PT = timezone(timedelta(hours=-7))

jobs = [
  dict(slug="germany", laws=6127, arts=129983, fl=6124, fa=129926, prior="ab9708b5c7cc",
       msg="EXPAND Germany GII Bundesrecht 6127 laws / 129983 arts (above floor 6124/129926 tip ab9708b5c7cc); official source prevails; not legal advice"),
  dict(slug="sweden", laws=9982, arts=16690, fl=9973, fa=16526, prior="eeb006dd12d7",
       msg="EXPAND Sweden SFS/Riksdagen 9982 laws / 16690 arts (above floor 9973/16526 tip eeb006dd12d7); official source prevails; not legal advice"),
]

results = []
for j in jobs:
    slug = j["slug"]; laws = j["laws"]; arts = j["arts"]
    repo_id = "endomorphosis/ipfs_%s_laws" % slug
    local = Path("/workspace/legal-corpora-releases/%s" % slug)
    print("UPLOAD_START", repo_id, "laws=%d arts=%d" % (laws, arts), flush=True)
    try:
        create_repo(repo_id, repo_type="dataset", exist_ok=True, token=token, private=False)
        api.upload_folder(folder_path=str(local), repo_id=repo_id, repo_type="dataset", token=token, commit_message=j["msg"], ignore_patterns=[".git/**", "PUBLISH_STATUS.md"])
        info = api.repo_info(repo_id, repo_type="dataset")
        sha_full = info.sha or ""
        sha = sha_full[:12]
        man = local / "MANIFEST.md"
        if man.exists():
            man.write_text(man.read_text(encoding="utf-8").replace("uploaded: false", "uploaded: true"), encoding="utf-8")
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        utc_s = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        pt_s = now_utc.astimezone(PT).strftime("%Y-%m-%d %H:%M PT")
        lines = [
            "# %s Hub PUBLISH_STATUS" % slug.title(),
            "",
            "- status: PUBLISHED",
            "- repo: https://huggingface.co/datasets/%s" % repo_id,
            "- tip_sha: %s" % sha,
            "- tip_sha_full: %s" % sha_full,
            "- laws: %d" % laws,
            "- arts: %d" % arts,
            "- prior_floor: laws>=%d arts>=%d (tip %s)" % (j["fl"], j["fa"], j["prior"]),
            "- new_floor: laws>=%d arts>=%d" % (laws, arts),
            "- commit_message: %s" % j["msg"],
            "- upload_errors: none",
            "- published_utc: %s" % utc_s,
            "- published_pt: %s" % pt_s,
            "- notes: soft never-thin CLEAR; local exceeded both floors; EXPAND publish",
        ]
        body = "\n".join(lines).replace("laws>=", "laws\u2265").replace("arts>=", "arts\u2265") + "\n"
        (local / "PUBLISH_STATUS.md").write_text(body, encoding="utf-8")
        print("UPLOAD_OK", repo_id, sha, "laws=%d arts=%d" % (laws, arts), flush=True)
        results.append({"slug": slug, "sha": sha, "laws": laws, "arts": arts, "error": None})
    except Exception as e:
        print("UPLOAD_FAIL", repo_id, type(e).__name__ + ":", e, flush=True)
        results.append({"slug": slug, "sha": None, "laws": laws, "arts": arts, "error": "%s: %s" % (type(e).__name__, e)})

print(json.dumps(results, indent=2), flush=True)
