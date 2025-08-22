import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Agent 3 API")

class Payload(BaseModel):
    github_url: str
    access_token: str
    branch: str          # base branch where PR will merge
    directory: str       # folder path with code to push


def run_agent3(repo_url: str, access_token: str, base_branch: str, directory: str):
    """Runs Agent 3 workflow via REST MCP server."""
    try:
        # 1. Push code to new branch
        print("Pushing code to new branch...")
        push_resp = requests.post("http://192.168.208.84:9000/push_code", json={
            "repo_url": repo_url,
            "access_token": access_token,
            "folder_path": directory,
            "base_name": "code-update",
            "commit_message": "Automated commit from Agent 3"
        })
        push_resp.raise_for_status()
        push_result = push_resp.json()
        print("Push result:", push_result)

        branch_name = push_result.get("branch")
        if not branch_name:
            raise Exception("No branch returned from push_code")

        # 2. Create PR for that branch
        print("Creating PR for new branch...")
        print({
            "repo_url": repo_url,
            "access_token": access_token,
            "head_branch": branch_name,
            "base_branch": base_branch,   # ✅ fixed naming
            "pr_title": f"Update code in {branch_name}",
            "pr_body": "Automated PR with updated code."
        })
        # pr_resp = requests.post("http://192.168.208.84:9000/create_pr", json={
        #     "repo_url": repo_url,
        #     "access_token": access_token,
        #     "head_branch": branch_name,
        #     "base_branch": base_branch,   # ✅ fixed naming
        #     "pr_title": f"Update code in {branch_name}",
        #     "pr_body": "Automated PR with updated code."
        # })
        # pr_resp.raise_for_status()
        # pr_result = pr_resp.json()
        # print("PR result:", pr_result)

        # return {"status": "pass", "push_result": push_result, "pr_result": pr_result}
        return {"status": "pass", "push_result": push_result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent3/run")
def run_agent3_api(request: Payload):
    """API endpoint to run Agent 3"""
    print("Received request:", request)
    result = run_agent3(
        repo_url=request.github_url,
        access_token=request.access_token,
        base_branch=request.branch,
        directory=request.directory
    )
    return {"status": "success", "result": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("git_agent:app", host="192.168.208.84", port=8005, reload=False)
