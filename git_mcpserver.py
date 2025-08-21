import os
import shutil
import subprocess
from fastapi import FastAPI, HTTPException, Form
from git import Repo, GitCommandError

app = FastAPI()


# def get_auth_repo_url(repo_url: str, token: str) -> str:
#     if not repo_url.startswith("https://"):
#         raise HTTPException(status_code=400, detail="Invalid repo URL. Must start with HTTPS.")
#     sam=repo_url.replace("https://", f"https://{token}@")
#     print(f"Using token for repo URL: {sam}")
#     return sam

def get_auth_repo_url(repo_url: str, token: str, username: str = None) -> str:
    """
    Return an authenticated repo URL for GitHub using either:
      - https://<token>@github.com/...
      - https://<username>:<token>@github.com/...
    """
    # Clean input
    repo_url = repo_url.strip().rstrip("/")
    if not repo_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid repo URL. Must start with HTTPS.")

    # Insert authentication
    if username:
        # username + token style (more reliable for pushing)
        auth_url = repo_url.replace("https://", f"https://{username}:{token}@")
    else:
        # token-only style
        auth_url = repo_url.replace("https://", f"https://{token}@")

    print(f"Using authenticated repo URL: {auth_url}")
    return auth_url


def list_remote_branches(repo_url: str, token: str):
    """Get list of remote branches without cloning the repo."""
    repo_url = get_auth_repo_url(repo_url, token)
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"Remote branches for {repo_url}:\n{result.stdout}")
        branches = []
        for line in result.stdout.splitlines():
            if line.strip():
                _, ref = line.split()
                branch_name = ref.replace("refs/heads/", "")
                branches.append(branch_name)
        return branches
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to list remote branches: {e.stderr}")


def generate_versioned_branch(repo_url: str, token: str, base_name: str) -> str:
    """Generate new versioned branch name without cloning."""
    existing_branches = list_remote_branches(repo_url, token)
    version = 1
    new_branch = f"{base_name}_v{version}"
    while new_branch in existing_branches:
        version += 1
        new_branch = f"{base_name}_v{version}"
    return new_branch


def push_folder_to_new_branch(folder_path, repo_url, token, base_name, commit_message):
    """Push local folder contents directly to a new versioned branch."""
    new_branch = generate_versioned_branch(repo_url, token, base_name)
    auth_repo_url = get_auth_repo_url(repo_url, token)

    # Initialize repo if not already a git repo
    if not os.path.exists(os.path.join(folder_path, ".git")):
        repo = Repo.init(folder_path)
        repo.create_remote("origin", auth_repo_url)
    else:
        repo = Repo(folder_path)
        if "origin" not in [r.name for r in repo.remotes]:
            repo.create_remote("origin", auth_repo_url)

    # Create new branch
    repo.git.checkout("-B", new_branch)

    # Add + commit
    repo.git.add(A=True)
    if repo.is_dirty(untracked_files=True):
        repo.index.commit(commit_message)

    # Push to remote
    try:
        repo.git.push("origin", new_branch, force=True)
    except GitCommandError as e:
        raise HTTPException(status_code=500, detail=f"Push failed: {e}")

    return new_branch

import requests

def create_github_pr(repo_url: str, token: str, head_branch: str, base_branch: str, title: str, body: str):
    # Cleanly extract owner/repo
    repo_url_clean = repo_url.removesuffix(".git")
    parts = repo_url_clean.split("/")
    owner, repo = parts[-2], parts[-1]

    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "title": title,
        "head": head_branch,   # if same repo
        # "head": f"{owner}:{head_branch}"  # if fork
        "base": base_branch,   # must exist (e.g., main/master/develop)
        "body": body,
    }

    response = requests.post(api_url, headers=headers, json=payload)
    if response.status_code == 201:
        pr = response.json()
        return {"url": pr["html_url"], "number": pr["number"]}
    else:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"GitHub PR failed: {response.text}"
        )
    
@app.post("/git/create-branch")
def git_create_branch(
    repo_url: str = Form(...),
    access_token: str = Form(...),
    # source_path: str = Form(...)
):
    base_name = "code-update"
    print("file ", source_path)
    if not os.path.exists(source_path):
        raise HTTPException(status_code=400, detail=f"Source folder not found at {source_path}")
    
    new_branch = push_folder_to_new_branch(
        folder_path=source_path,
        repo_url=repo_url,
        token=access_token,
        base_name=base_name,
        commit_message="updated code with the requirements given",
    )

    # pr_info = create_github_pr(
    #     repo_url=repo_url,
    #     token=access_token,
    #     head_branch=new_branch,
    #     base_branch="main",
    #     title=f"Update code in {new_branch}",
    #     body="Automated PR with updated code."
    # )

    return {"message": f"Code pushed successfully to branch {new_branch}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
