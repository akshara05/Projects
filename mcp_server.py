from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from git import Repo, GitCommandError
import subprocess, requests
from urllib.parse import urlparse, quote

app = FastAPI(title="Git MCP REST Server")

# Input schemas
class PushPayload(BaseModel):
    repo_url: str
    access_token: str
    folder_path: str
    base_name: str = "code-update"
    commit_message: str = "Automated update"

class PRPayload(BaseModel):
    repo_url: str
    access_token: str
    head_branch: str
    base_branch: str = "dev"
    pr_title: str = "Automated PR"
    pr_body: str = "This PR was created automatically"

# ---------- Data Models ----------
class ClonePayload(BaseModel):
    github_link: str
    access_token: str
    branch: str = None


# ---- Helpers (same as before) ----


# ---------- Core Git Tool ----------
def git_clone(github_link: str, access_token: str, branch: str = None):
    """
    Clone a GitHub repository using a personal access token (supports encoded tokens).
    """
    # Encode token safely
    token = quote(access_token, safe="") if any(c in access_token for c in ['@', ':', '/']) else access_token

    parsed = urlparse(github_link)
    if not parsed.scheme.startswith("http"):
        raise ValueError("Only HTTPS Git URLs are supported")

    # Insert token into URL
    auth_url = f"https://{token}@{parsed.hostname}{parsed.path}"

    # Auto-generate directory name from repo
    repo_name = os.path.splitext(os.path.basename(parsed.path))[0]
    dest_dir = repo_name

    # Build git command
    cmd = ["git", "clone"]
    if branch:
        cmd.extend(["-b", branch])
    cmd.extend([auth_url, dest_dir])

    print(f"Running: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print(f"Repository cloned into {dest_dir}")
        return dest_dir
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Error cloning repo: {e}")
    



def get_auth_repo_url(repo_url: str, token: str) -> str:
    if repo_url.startswith("git@github.com:"):
        repo_url = repo_url.replace("git@github.com:", "https://github.com/")
    if not repo_url.startswith("https://"):
        raise HTTPException(400, "Invalid repo URL")
    return repo_url.replace("https://", f"https://{token}@")

def list_remote_branches(repo_url: str, token: str):
    repo_url = get_auth_repo_url(repo_url, token)
    result = subprocess.run(
        ["git", "ls-remote", "--heads", repo_url],
        capture_output=True, text=True, check=True,
    )
    return [line.split()[1].replace("refs/heads/", "") for line in result.stdout.splitlines() if line.strip()]

def generate_versioned_branch(repo_url, token, base_name):
    existing = list_remote_branches(repo_url, token)
    v = 1
    branch = f"{base_name}_v{v}"
    while branch in existing:
        v += 1
        branch = f"{base_name}_v{v}"
    return branch

def push_folder_to_new_branch(folder_path, repo_url, token, base_name, commit_message):
    new_branch = generate_versioned_branch(repo_url, token, base_name)
    auth_repo_url = get_auth_repo_url(repo_url, token)

    if not os.path.exists(os.path.join(folder_path, ".git")):
        repo = Repo.init(folder_path)
        repo.create_remote("origin", auth_repo_url)
    else:
        repo = Repo(folder_path)
        if "origin" in [r.name for r in repo.remotes]:
            repo.delete_remote("origin")
        repo.create_remote("origin", auth_repo_url)

    repo.git.checkout("-B", new_branch)
    repo.git.add(A=True)

    if repo.is_dirty(untracked_files=True):
        repo.index.commit(commit_message)

    repo.git.push("origin", new_branch, force=True)
    return new_branch

# def create_github_pr(repo_url, token, head_branch, base_branch, title, body):
#     repo_url_clean = repo_url.removesuffix(".git")
#     parts = repo_url_clean.split("/")
#     owner, repo = parts[-2], parts[-1]

#     api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
#     headers = {"Authorization": f"Bearer {token}"}
#     payload = {"title": title, "head": head_branch, "base": base_branch, "body": body}

#     response = requests.post(api_url, headers=headers, json=payload)
#     if response.status_code == 201:
#         pr = response.json()
#         return {"url": pr["html_url"], "number": pr["number"]}
#     else:
#         raise HTTPException(response.status_code, response.text)
import base64

def create_github_pr(repo_url, token, head_branch, base_branch, title, body):
    repo_url_clean = repo_url.removesuffix(".git")
    parts = repo_url_clean.strip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"

    # 🔧 Encode username:token in Basic Auth
    username = owner  # or your GitHub username
    auth_string = f"{username}:{token}"
    b64_auth = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",   # ✅ alternative to `token <pat>`
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "title": title,
        "head": head_branch,
        "base": base_branch,
        "body": body
    }

    print("➡️ Creating PR with payload:", payload)
    print("➡️ API URL:", api_url)

    response = requests.post(api_url, headers=headers, json=payload)

    print("⬅️ GitHub status:", response.status_code)
    print("⬅️ GitHub response:", response.text)

    if response.status_code == 201:
        pr = response.json()
        return {"url": pr["html_url"], "number": pr["number"]}
    else:
        raise HTTPException(response.status_code, response.text)


# ---- REST Endpoints ----
@app.post("/git_clone")
def clone_repo(request: ClonePayload):
    try:
        result = git_clone(
            github_link=request.github_link,
            access_token=request.access_token,
            branch=request.branch,
        )
        return {"directory": result}   # ✅ wrap in JSON
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    
@app.post("/push_code")
def push_code_api(payload: PushPayload):
    branch = push_folder_to_new_branch(
        folder_path=payload.folder_path,
        repo_url=payload.repo_url,
        token=payload.access_token,
        base_name=payload.base_name,
        commit_message=payload.commit_message
    )
    print(f"Code pushed to branch: {branch}")
    return {"message": "Code pushed", "branch": branch}

@app.post("/create_pr")
def create_pr_api(payload: PRPayload):
    pr_info = create_github_pr(
        repo_url=payload.repo_url,
        token=payload.access_token,
        head_branch=payload.head_branch,
        base_branch=payload.base_branch,
        title=payload.pr_title,
        body=payload.pr_body
    )
    print(f"PR created: {pr_info}")
    return {"message": "PR created", "pull_request": pr_info}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mcp_server:app", host="192.168.208.84", port=9000, reload=False)