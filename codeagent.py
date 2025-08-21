from unittest import result
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import getpass
import os

app = FastAPI()

# GOOGLE_API_KEY="AIzaSyCy6yF6gdXlRDEaAT7sMM8t8A6dN8f_UHg"
if not os.environ.get("GOOGLE_API_KEY"):
  os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter API key for Google Gemini: ")

from langchain.chat_models import init_chat_model
llm = init_chat_model("gemini-2.5-flash", model_provider="google_genai")


from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
vector_store = InMemoryVectorStore(embeddings)

import bs4
from langchain import hub
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import START, StateGraph
from typing_extensions import List, TypedDict

# Load and chunk contents of the blog
loader = WebBaseLoader(
    web_paths=("https://peps.python.org/pep-0008/",),
    bs_kwargs=dict(
        parse_only=bs4.SoupStrainer(
            class_=("post-content", "post-title", "post-header")
        )
    ),
)
docs = loader.load()

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
all_splits = text_splitter.split_documents(docs)

# Index chunks
_ = vector_store.add_documents(documents=all_splits)

from langchain.prompts import PromptTemplate
prompt = PromptTemplate.from_template(
    """Based on the provided requirements {question} and using this as your context generate or modify according to the requirements which is a clean code with following proper guidelines which you can refer to this {context} for the code given {code}.

    NOTE: You will have to follow the same file name structure as the code has file name and its contents.

    Follow this output format:
    #file_name.py
    file contents   
    
    Do not include any other text or comments outside the code block.                             
        """) 

# Define state for application
class State(TypedDict):
    question: str
    context: str
    answer: str
    directory :str
    github_url:str
    access_token:str
    branch:str


# Define application steps
def retrieve(state: State):
    retrieved_docs = vector_store.similarity_search(state["question"])
    return {"context": retrieved_docs}

def generate(state: State):
    docs_content = state["context"]
    directory = state["directory"]
    question = state["question"]
    print(f"Processing directory: {directory}")
    answers = {}

    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".py"):  # allow only .py files
                file_path = os.path.join(root, filename)
                print(f"Reading file: {file_path}")
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                except Exception as e:
                    file_content = f"[Error reading file: {e}]"

                # ✅ Move LLM call *inside* the if-block
                messages = prompt.invoke({
                    "question": question,
                    "context": docs_content,
                    "code": f"Filename: {filename}\n\n{file_content}"
                })

                response = llm.invoke(messages)
                result = response.content
                answer = result.replace("'''python", "").replace("'''", "")

                answers[filename] = answer

                # ⚡ Overwrite the original file with the LLM's answer
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(answer)
                    print(f"Updated file: {file_path}")
                    
    github_link = state["github_url"]
    access_token = state["access_token"]
    branch = state["branch"]
    directory = state["directory"]

    print("All files processed successfully.")
    return {"status": "pass",
            "github_url": github_link,
            "access_token": access_token,
            "branch": branch,
            "directory": directory
}

# Step 3: Build the graph
graph_builder = StateGraph(State).add_sequence([retrieve, generate])
graph_builder.add_edge(START, "retrieve")
graph = graph_builder.compile()

# Request body model
class QueryRequest(BaseModel):
    question: str
    directory: str
    github_url: str
    access_token: str
    branch: str

@app.post("/code_agent")
def invoke_graph(request: QueryRequest):
    state = {
        "question": request.question,
        "directory": request.directory,
        "github_url": request.github_url,   
        "access_token": request.access_token,
        "branch": request.branch
    }
    response = graph.invoke(state)
    # Filter only generate() return
    return {
            "github_url": response.get("github_url"),
            "access_token": response.get("access_token"),
            "branch": response.get("branch"),
            "directory": response.get("directory")
    }


if __name__ == "__main__":
    uvicorn.run(app, host="192.168.208.84", port=8000)
