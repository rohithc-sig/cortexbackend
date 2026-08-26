import os
import json
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
# Enable CORS for Power BI Service Iframe
# ----------------------------------------------------------

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
    pbi_context: Optional[Dict[str, Any]] = None
    user_email: Optional[str] = None
    user_region: Optional[str] = None
    user_identity: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------
# Snowflake Connection Utility
# ----------------------------------------------------------

def get_connection():

    return snowflake.connector.connect(

        account=os.getenv(
            "SNOWFLAKE_ACCOUNT"
        ),

        user=os.getenv(
            "SNOWFLAKE_USER"
        ),

        password=os.getenv(
            "SNOWFLAKE_PAT"
        ),

        role=os.getenv(
            "SNOWFLAKE_ROLE"
        ),

        warehouse=os.getenv(
            "SNOWFLAKE_WAREHOUSE"
        ),

        database=os.getenv(
            "SNOWFLAKE_DATABASE"
        ),

        schema=os.getenv(
            "SNOWFLAKE_SCHEMA"
        ),
    )


# ==========================================================
# SNOWFLAKE AI_COMPLETE RESPONSE GENERATOR
# ==========================================================

def generate_ai_response(
    conn,
    user_question: str,
    analyst_answer: str,
    table_schema: list
):

    model = os.getenv(
        "SNOWFLAKE_AI_COMPLETE_MODEL",
        "llama3.1-8b"
    )

    if model.strip().lower() == "mistral-large2":
        model = "llama3.1-8b"


    # ------------------------------------------------------
    # Prompt
    # ------------------------------------------------------

    prompt = f"""
You are a business analytics assistant inside a Power BI report.

The user asked:

{user_question}

Cortex Analyst interpreted the request as:

{analyst_answer}

The generated SQL returned a table with the following schema:

{json.dumps(table_schema, indent=2)}

Actual result rows are not available.

Important restrictions:

- Do NOT invent numbers.
- Do NOT invent rankings.
- Do NOT invent brands.
- Do NOT invent companies.
- Do NOT invent dates.
- Do NOT invent metrics.
- Base your answer only on the information provided.
- Generate exactly 3 useful analytical follow-up questions.
- Follow-up questions must be relevant to the user's original question
  and the available table schema.
- Prefer analytical follow-ups involving comparisons, trends, rankings,
  year-over-year analysis, filtering, or breakdowns where appropriate.
- Do not ask generic questions.
- Do not include SQL.

Return a concise answer and exactly three useful follow-up questions.
"""


    cursor = conn.cursor()


    try:

        # --------------------------------------------------
        # AI_COMPLETE
        # --------------------------------------------------

        sql = """

        SELECT AI_COMPLETE(

            %s,

            %s,

            {},

            {

                'type': 'json',

                'schema': {

                    'type': 'object',

                    'properties': {

                        'answer': {

                            'type': 'string'

                        },

                        'follow_up_questions': {

                            'type': 'array',

                            'items': {

                                'type': 'string'

                            }

                        }

                    },

                    'required': [

                        'answer',

                        'follow_up_questions'

                    ]

                }

            }

        )

        """


        print("========================================")
        print("AI_COMPLETE STARTED")
        print("========================================")

        print(
            f"AI_COMPLETE model: {model}"
        )

        print(
            "Calling Snowflake AI_COMPLETE..."
        )


        cursor.execute(

            sql,

            (
                model,
                prompt
            )

        )


        result = cursor.fetchone()[0]


        print(
            "AI_COMPLETE returned successfully."
        )


        print(
            "AI_COMPLETE raw result:"
        )

        print(result)


        # --------------------------------------------------
        # Validate response
        # --------------------------------------------------

        if result is None:

            raise ValueError(
                "AI_COMPLETE returned NULL"
            )


        # --------------------------------------------------
        # Parse structured response
        # --------------------------------------------------

        if isinstance(
            result,
            str
        ):

            result = json.loads(
                result
            )


        if not isinstance(
            result,
            dict
        ):

            raise ValueError(

                "Unexpected AI_COMPLETE "
                "result type: "

                f"{type(result).__name__}"

            )


        # --------------------------------------------------
        # Extract answer
        # --------------------------------------------------

        answer = result.get(

            "answer",

            ""

        )


        # --------------------------------------------------
        # Extract follow-up questions
        # --------------------------------------------------

        follow_up_questions = result.get(

            "follow_up_questions",

            []

        )


        if not isinstance(

            follow_up_questions,

            list

        ):

            follow_up_questions = []


        # --------------------------------------------------
        # Maximum 3 questions
        # --------------------------------------------------

        follow_up_questions = [

            str(question)

            for question
            in follow_up_questions[:3]

            if question

        ]


        return {

            "answer":

                answer,

            "follow_up_questions":

                follow_up_questions

        }


    finally:

        cursor.close()


# ----------------------------------------------------------
# Health Check
# ----------------------------------------------------------

@app.get("/")
def home():

    return {

        "status":
            "Running",

        "service":
            "Snowflake Cortex Backend"

    }


# ----------------------------------------------------------
# Snowflake Connection Test
# ----------------------------------------------------------

@app.get("/test-connection")
def test_connection():

    try:

        conn = get_connection()

        cursor = conn.cursor()


        cursor.execute(
            "SELECT CURRENT_VERSION()"
        )


        version = cursor.fetchone()[0]


        return {

            "status":
                "Connected",

            "snowflake_version":
                version

        }


    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=str(e)

        )


    finally:

        if "cursor" in locals():

            cursor.close()


        if "conn" in locals():

            conn.close()


# ----------------------------------------------------------
# Explicit preflight handler
# ----------------------------------------------------------

@app.options("/chat")
def options_chat():

    return {}


# ----------------------------------------------------------
# Live Cortex Chat Endpoint
# ----------------------------------------------------------

@app.post("/chat")
def chat(request: ChatRequest):

    # ======================================================
    # EXISTING CORTEX ANALYST LOGIC
    # ======================================================


    # ------------------------------------------------------
    # 1. Append Power BI context/slicers if available
    # ------------------------------------------------------

    user_query = request.question


    # Temporary POC: Power BI evaluated this region under dataset RLS.

    if request.user_region:

        safe_region = request.user_region.replace(
            "'",
            "''"
        )

        user_query += (

            f" (User region filter: "
            f"REGION = '{safe_region}')"

        )


    if (

        request.pbi_context

        and

        request.pbi_context.get(
            "categories"
        )

    ):

        filters = []


        for cat in request.pbi_context["categories"]:

            col = (

                cat.get(
                    "columnName"
                )

                or

                cat.get(
                    "column"
                )

            )


            vals = (

                cat.get(
                    "values"
                )

                or

                cat.get(
                    "activeValues",
                    []
                )

            )


            if col and vals:

                formatted_vals = ", ".join(

                    [

                        f"'{v}'"

                        for v in vals

                    ]

                )


                filters.append(

                    f"{col} IN ({formatted_vals})"

                )


        if filters:

            user_query += (

                f" (Context filters: "

                f"{'; '.join(filters)})"

            )


    # ------------------------------------------------------
    # 2. Construct Cortex Analyst REST Payload
    # ------------------------------------------------------

    account = os.getenv(
        "SNOWFLAKE_ACCOUNT"
    )


    # Clean host URL if user provides account identifier
    # or full host.

    if "snowflakecomputing.com" in account:

        host_url = (

            f"https://{account}"

        )

    else:

        host_url = (

            f"https://"
            f"{account}"
            f".snowflakecomputing.com"

        )


    url = (

        f"{host_url}"
        f"/api/v2/cortex/analyst/message"

    )


    # ======================================================
    # UPDATED: NATIVE SNOWFLAKE SEMANTIC VIEW
    # ======================================================

    semantic_view = os.getenv(

        "SNOWFLAKE_SEMANTIC_VIEW"

    )


    if not semantic_view:

        raise HTTPException(

            status_code=400,

            detail=(

                "Snowflake semantic view "
                "is not configured. "

                "Set SNOWFLAKE_SEMANTIC_VIEW "
                "to a fully qualified semantic "
                "view name like "
                "'DB.SCHEMA.SEMANTIC_VIEW'."

            )

        )


    payload = {

        "messages": [

            {

                "role":
                    "user",

                "content": [

                    {

                        "type":
                            "text",

                        "text":
                            user_query

                    }

                ]

            }

        ],

        "semantic_view":
            semantic_view

    }


    headers = {

        "Authorization":

            f"Bearer "
            f"{os.getenv('SNOWFLAKE_PAT')}",

        "Content-Type":
            "application/json",

        "X-Snowflake-Authorization-Token-Type":

            "PROGRAMMATIC_ACCESS_TOKEN"

    }


    # ------------------------------------------------------
    # 3. Call Snowflake Cortex Analyst REST API
    # ------------------------------------------------------

    try:

        response = requests.post(

            url,

            json=payload,

            headers=headers,

            timeout=60

        )


    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=(

                "Failed to reach Cortex API: "

                f"{str(e)}"

            )

        )


    if response.status_code != 200:

        try:

            error_detail = response.json()

        except Exception:

            error_detail = response.text


        raise HTTPException(

            status_code=response.status_code,

            detail=error_detail

        )


    data = response.json()


    # ------------------------------------------------------
    # Parse Cortex Analyst response
    # ------------------------------------------------------

    answer_text = ""

    generated_sql = ""


    for item in data.get(

        "message",

        {}

    ).get(

        "content",

        []

    ):

        if item.get(
            "type"
        ) == "text":

            answer_text += (

                item.get(
                    "text",
                    ""
                )

                + "\n"

            )


        elif item.get(
            "type"
        ) == "sql":

            generated_sql = (

                item.get(
                    "statement",
                    ""
                )

            )


    # ------------------------------------------------------
    # 4. Execute Generated SQL
    # ------------------------------------------------------

    columns = []

    rows = []


    # ======================================================
    # TABLE SCHEMA FOR AI_COMPLETE
    # ======================================================

    table_schema = []


    # ======================================================
    # END TABLE SCHEMA FOR AI_COMPLETE
    # ======================================================


    if generated_sql:

        try:

            conn = get_connection()

            cursor = conn.cursor()


            # ------------------------------------------------
            # Extract column headers
            # ------------------------------------------------

            cursor.execute(
                generated_sql
            )


            if cursor.description:

                columns = [

                    desc[0]

                    for desc
                    in cursor.description

                ]


                # ------------------------------------------------
                # Extract table schema
                # ------------------------------------------------

                for desc in cursor.description:

                    column_name = desc[0]


                    column_type = (

                        str(desc[1])

                        if desc[1] is not None

                        else "UNKNOWN"

                    )


                    table_schema.append(

                        {

                            "name":
                                column_name,

                            "type":
                                column_type

                        }

                    )


                # ------------------------------------------------
                # Fetch rows
                # ------------------------------------------------

                raw_rows = (
                    cursor.fetchall()
                )


                for row in raw_rows:

                    row_dict = {}


                    for idx, col_name in enumerate(
                        columns
                    ):

                        row_dict[col_name] = (

                            str(row[idx])

                            if row[idx] is not None

                            else ""

                        )


                    rows.append(
                        row_dict
                    )


        except Exception as sql_err:

            answer_text += (

                "\n\n"

                f"*(Note: Generated SQL failed "
                f"to execute: {str(sql_err)})*"

            )


        finally:

            if "cursor" in locals():

                cursor.close()


            if "conn" in locals():

                conn.close()


    # ======================================================
    # SNOWFLAKE AI_COMPLETE RESPONSE GENERATION
    # ======================================================

    ai_answer = answer_text.strip()

    follow_up_questions = []


    try:

        ai_conn = get_connection()

        try:

            ai_result = generate_ai_response(

                conn=ai_conn,

                user_question=request.question,

                analyst_answer=answer_text.strip(),

                table_schema=table_schema

            )

        finally:

            ai_conn.close()


        ai_answer = ai_result.get(

            "answer",

            answer_text.strip()

        )


        follow_up_questions = (

            ai_result.get(

                "follow_up_questions",

                []

            )

        )


        # Safety check:
        # maximum 3 questions.

        follow_up_questions = (

            follow_up_questions[:3]

        )


    except Exception as llm_err:

        print(
            "========================================"
        )

        print(
            "SNOWFLAKE AI_COMPLETE FAILED"
        )

        print(
            "========================================"
        )

        print(
            f"Error type: "
            f"{type(llm_err).__name__}"
        )

        print(
            f"Error message: "
            f"{str(llm_err)}"
        )

        import traceback

        traceback.print_exc()

        print(
            "========================================"
        )


        raise HTTPException(

            status_code=500,

            detail={

                "message":
                    "Snowflake AI_COMPLETE failed",

                "error_type":
                    type(llm_err).__name__,

                "error":
                    str(llm_err)

            }

        )


    # ======================================================
    # END SNOWFLAKE AI_COMPLETE RESPONSE GENERATION
    # ======================================================


    # ======================================================
    # FINAL RESPONSE TO POWER BI
    # ======================================================

    return {

        "answer":
            ai_answer,

        "follow_up_questions":
            follow_up_questions,

        "sql":
            generated_sql,

        "columns":
            columns,

        "rows":
            rows,

        "request_id":
            data.get(
                "request_id"
            ),

        "user_identity":
            request.user_identity,

        "warnings":
            data.get(
                "warnings",
                []
            )

    }