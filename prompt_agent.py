from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import getpass
import os
import requests
import subprocess
from urllib.parse import urlparse, quote

import bs4
from langchain import hub
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import START, StateGraph
from typing_extensions import List, TypedDict
from langchain.prompts import PromptTemplate
from langchain.chat_models import init_chat_model


# ---------- LLM ----------
if not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter API key for Google Gemini: ")

llm = init_chat_model("gemini-2.5-flash", model_provider="google_genai")


# ---------- FastAPI ----------
app = FastAPI()


# ---------- State ----------
class State(TypedDict):
    question: str
    github_url: str
    access_token: str
    branch: str
    directory: str


# ---------- Prompts ----------
prompt_1 = PromptTemplate.from_template(
    """Based on the provided 
    requirements {question} 
    Generate the assumptions telling summarising the requirements by analysing the code base given to you.
    Code :{code}

    Provide a detailed analysis telling what are the changes and updates needed within the code based on the requirements and context provided.
        """
)

prompt_2 = PromptTemplate.from_template(
    """Based on the provided 
    requirements {question}
    Generate the assumptions telling summarising the requirements.
    Provide a detailed analysis telling what are the changes and updates needed based on the requirements and context provided.
        """
)

prompt_3 = PromptTemplate.from_template(
    """Based on the provided 
    requirements {reqs}
    Summarise this and provide in a detail and brief manner.
        """
)

import os
import subprocess
from urllib.parse import urlparse, quote

def git_clone(state:State):
    """
    Clone a GitHub repository using a personal access token (supports encoded tokens).
    
    :param git_url: Repository URL (e.g., https://github.com/user/repo.git)
    :param access_token: Personal Access Token (encoded or plain)
    :param branch: Branch to clone (default: repo’s default branch)
    """

    # Encode token safely (only if needed)
    token = quote(state["access_token"], safe="") if any(c in state["access_token"] for c in ['@', ':', '/']) else state["access_token"]

    parsed = urlparse(state["github_url"])
    if not parsed.scheme.startswith("http"):
        raise ValueError("Only HTTPS Git URLs are supported")

    # Insert token into URL
    auth_url = f"https://{token}@{parsed.hostname}{parsed.path}"

    # Auto-generate directory name from repo
    repo_name = os.path.splitext(os.path.basename(parsed.path))[0]
    dest_dir = repo_name

    # Build git command
    cmd = ["git", "clone"]
    if state["branch"]:
        cmd.extend(["-b", state["branch"]])
    cmd.extend([auth_url, dest_dir])

    print(f"Running: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print(f"Repository cloned into {dest_dir}")
        return {"directory": dest_dir}
    except subprocess.CalledProcessError as e:
        print(f"Error cloning repo: {e}")


def generate(state: State):
    analysis = ""
    directory = state.get("directory", "")

    # Define allowed extensions
    allowed_extensions = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".html", ".css", ".md", ".json"}

    if directory:
        for root, _, files in os.walk(directory):
            # Skip hidden/system folders
            if any(skip in root for skip in [".git", "__pycache__", ".venv", "node_modules"]):
                continue  

            for filename in files:
                _, ext = os.path.splitext(filename)
                if ext.lower() not in allowed_extensions:
                    continue  

                file_path = os.path.join(root, filename)
                print(f"Reading file: {file_path}")

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                except Exception as e:
                    file_content = f"[Error reading file: {e}]"

                # Call LLM
                messages = prompt_1.invoke({
                    "question": state["question"],
                    "code": f"Filename: {filename}\n\n{file_content}"
                })

                response = llm.invoke(messages)
                analysis += response.content + "\n"
    else:
        messages = prompt_2.invoke({
            "question": state["question"],
        })
        response = llm.invoke(messages)
        return {"status": "pass", "answer": response.content}

    # Final summarisation
    final_messages = prompt_3.invoke({
        "reqs": analysis
    })

    response = llm.invoke(final_messages)
    print("final analysis completed")
    return {"status": "pass", "answer": response.content}


# ---------- Build Graph ----------
graph_builder = StateGraph(State).add_sequence([git_clone, generate])
graph_builder.add_edge(START, "git_clone")
graph = graph_builder.compile()


# # ---------- Test Run ----------
# response = graph.invoke({
#     "question": "instead of model use openai model use gemini and improve the comment structure",                
#     "github_url": "https://github.com/akshara05/github_repo.git",
#     "access_token": "LhAAfhN3eKG4vszWxOsZJA0cpJk2RacRW",
#     "branch": "main",
#     "project_structure": """test
#      test/1.RAG via CrewAI.py
#      test/2.CrewAI via Server.py """
# })


# ---------- FastAPI Endpoint ----------
class QueryRequest(BaseModel):
    question: str
    github_url: str
    access_token: str
    branch: str

@app.post("/prompt_agent")
def invoke_graph(request: QueryRequest):
    response = graph.invoke({
        "question": request.question,
        "github_url": request.github_url,   
        "access_token": request.access_token,
        "branch": request.branch,
        "directory": ""   # let clone_repo fill this
    })
    return { 
            "question": request.question,
            "github_url": response.get("github_url"),
            "access_token": response.get("access_token"),
            "branch": response.get("branch"),
            "directory": response.get("directory")
            }


if __name__ == "__main__":
    uvicorn.run("prompt_agent:app", host="192.168.208.84", port=8009, reload=False)