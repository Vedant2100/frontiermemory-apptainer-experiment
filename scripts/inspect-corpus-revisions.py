from __future__ import annotations

import hashlib
import os
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download


REPO = "letta-ai/frontier-memory-corpus"
EXPECTED = "c7d31214ed20af4f14f46c4b9a838ebc9aa35a9491dfbce0fa50f7aa456eedd1"
TOKEN = os.environ["HF_TOKEN"]

api = HfApi(token=TOKEN)
commits = api.list_repo_commits(REPO, repo_type="dataset")
print(f"repo={REPO} commits_returned={len(commits)} expected_SHA256SUMS_sha256={EXPECTED}")
for commit in commits:
    try:
        sums = Path(hf_hub_download(
            REPO,
            "SHA256SUMS",
            repo_type="dataset",
            revision=commit.commit_id,
            token=TOKEN,
        ))
        digest = hashlib.sha256(sums.read_bytes()).hexdigest()
        marker = " MATCH" if digest == EXPECTED else ""
        print(f"{commit.commit_id} {commit.created_at} {digest}{marker} {commit.title}")
        if digest == EXPECTED:
            break
    except Exception as error:
        print(f"{commit.commit_id} ERROR {type(error).__name__}")
