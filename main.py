import os
import requests
import snowflake.connector
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
import os
import requests
import snowflake.connector
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any

# ----------------------------------------------------------
# Load Environment Variables
# ----------------------------------------------------------
load_dotenv()

app = FastAPI(title="Cortex Backend")
# ----------------------------------------------------------
# Load Environment Variables
# ----------------------------------------------------------
load_dotenv()

app = FastAPI(title="Cortex Backend")

# Enable CORS for Power BI Service Iframe
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
# ----------------------------------------------------------
# Request Models
# ----------------------------------------------------------
class ChatRequest(BaseModel):
    question: str
    pbi_context: Optional[Dict[str, Any]] = None

# ----------------------------------------------------------
# Snowflake Connection Utility
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
# Health Check & Test Endpoints
# ----------------------------------------------------------
# ----------------------------------------------------------
# Snowflake Connection Utility
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
# Health Check & Test Endpoints
# ----------------------------------------------------------
@app.get("/")
def home():
    return {
        "status": "Running",
        "service": "Snowflake Cortex Backend"
    }

@app.get("/test-connection")
def test_connection():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT CURRENT_VERSION()")
        version = cursor.fetchone()[0]
        return {
            "status": "Connected",
            "snowflake_version": version
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
        "status": "Running",
        "service": "Snowflake Cortex Backend"
    }

@app.get("/test-connection")
def test_connection():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT CURRENT_VERSION()")
        version = cursor.fetchone()[0]
        return {
            "status": "Connected",
            "snowflake_version": version
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

# Explicit preflight handler to prevent CORS errors on OPTIONS requests
# Explicit preflight handler to prevent CORS errors on OPTIONS requests
@app.options("/chat")
def options_chat():
    return {}

# ----------------------------------------------------------
# Live Cortex Chat Endpoint
# ----------------------------------------------------------
# ----------------------------------------------------------
# Live Cortex Chat Endpoint
# ----------------------------------------------------------
@app.post("/chat")
def chat(request: ChatRequest):
    # 1. Append Power BI context/slicers if available
    # 1. Append Power BI context/slicers if available
    user_query = request.question
    if request.pbi_context and request.pbi_context.get("categories"):
        filters = []
        for cat in request.pbi_context["categories"]:
            col = cat.get("columnName") or cat.get("column")
            vals = cat.get("values") or cat.get("activeValues", [])
            if col and vals:
                formatted_vals = ", ".join([f"'{v}'" for v in vals])
                filters.append(f"{col} IN ({formatted_vals})")
                formatted_vals = ", ".join([f"'{v}'" for v in vals])
                filters.append(f"{col} IN ({formatted_vals})")
        if filters:
            user_query += f" (Context filters: {'; '.join(filters)})"

    # 2. Construct Cortex Analyst REST Payload
    account = os.getenv("SNOWFLAKE_ACCOUNT")
    # Clean host URL if user provides account identifier or full host
    if "snowflakecomputing.com" in account:
        host_url = f"https://{account}"
    else:
        host_url = f"https://{account}.snowflakecomputing.com"

    url = f"{host_url}/api/v2/cortex/analyst/message"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_query
                    }
                ]
            }
        ],
        "semantic_model_file": os.getenv("SNOWFLAKE_SEMANTIC_MODEL","CPG.PUBLIC.SALES_SEMANTIC")
    }

    headers = {
        "Authorization": f"Bearer {os.getenv('SNOWFLAKE_PAT')}",
        "Content-Type": "application/json",
        "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"
    }

    # 3. Call Snowflake Cortex Analyst REST API
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reach Cortex API: {str(e)}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.json()
        )

    data = response.json()

    answer_text = ""
    generated_sql = ""

    # Parse Cortex Analyst Response Content Blocks
    for item in data.get("message", {}).get("content", []):
        if item.get("type") == "text":
            answer_text += item.get("text", "") + "\n"
        elif item.get("type") == "sql":
            generated_sql = item.get("statement", "")

    # 4. Execute the Generated SQL against Snowflake to fetch real rows
    columns = []
    rows = []

    if generated_sql:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(generated_sql)
            
            # Extract column headers
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                
                # Fetch row records and map to list of dicts
                raw_rows = cursor.fetchall()
                for row in raw_rows:
                    row_dict = {}
                    for idx, col_name in enumerate(columns):
                        row_dict[col_name] = str(row[idx]) if row[idx] is not None else ""
                    rows.append(row_dict)
        except Exception as sql_err:
            answer_text += f"\n\n*(Note: Generated SQL failed to execute: {str(sql_err)})*"
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    # 5. Return JSON payload matching Power BI Visual expects
    return {
        "answer": answer_text.strip(),
        "sql": generated_sql,
        "answer": answer_text.strip(),
        "sql": generated_sql,
        "columns": columns,
        "rows": rows,
        "request_id": data.get("request_id"),
        "warnings": data.get("warnings", [])
    }








