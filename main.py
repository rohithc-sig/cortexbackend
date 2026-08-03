import os
import requests
import snowflake.connector

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# ----------------------------------------------------------
# Load Environment Variables
# ----------------------------------------------------------

load_dotenv()

app = FastAPI(title="Cortex Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------
# Request Models
# ----------------------------------------------------------

class ChatRequest(BaseModel):
    question: str


# ----------------------------------------------------------
# Snowflake Connection
# ----------------------------------------------------------

def get_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        role=os.getenv("SNOWFLAKE_ROLE"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )


# ----------------------------------------------------------
# Health Check
# ----------------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "Running",
        "service": "Snowflake Cortex Backend"
    }


# ----------------------------------------------------------
# Test Snowflake Connection
# ----------------------------------------------------------

@app.get("/test-connection")
def test_connection():

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("SELECT CURRENT_VERSION()")

        version = cursor.fetchone()[0]

        return {
            "status": "Connected",
            "snowflake_version": version
        }

    finally:
        cursor.close()
        conn.close()


# ----------------------------------------------------------
# Cortex Chat Endpoint
# ----------------------------------------------------------

@app.post("/chat")
def chat(request: ChatRequest):

    url = f"{os.getenv('SNOWFLAKE_HOST')}/api/v2/cortex/analyst/message"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": request.question
                    }
                ]
            }
        ],
        "semantic_view": os.getenv("SEMANTIC_VIEW")
    }

    response = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {os.getenv('SNOWFLAKE_PAT')}",
            "Content-Type": "application/json",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"
        },
        timeout=60
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.json()
        )

    data = response.json()

    answer = ""
    sql = ""

    for item in data.get("message", {}).get("content", []):

        if item.get("type") == "text":
            answer = item.get("text", "")

        elif item.get("type") == "sql":
            sql = item.get("statement", "")

    return {
        "answer": answer,
        "sql": sql,
        "request_id": data.get("request_id"),
        "warnings": data.get("warnings", [])
    }