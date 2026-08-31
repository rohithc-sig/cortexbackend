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


# ==========================================================
# RCA REQUEST MODEL
# ==========================================================

class RCARequest(BaseModel):
    question: str
    sql: Optional[str] = None
    columns: Optional[list] = None
    rows: Optional[list] = None
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
# SQL SAFETY / EXECUTION SETTINGS
# ==========================================================

MAX_RESULT_ROWS = 500

STATEMENT_TIMEOUT_SECONDS = 60


def enforce_sql_limit(sql_text: str) -> str:

    """
    Enforce a hard maximum of 500 rows on Cortex-generated SQL.

    The original Cortex Analyst SQL is wrapped as a subquery so
    the backend controls the maximum number of rows returned.
    """

    if not sql_text:

        return sql_text


    cleaned_sql = sql_text.strip().rstrip(";").strip()


    if not cleaned_sql:

        return cleaned_sql


    return (

        "SELECT *\n"

        "FROM (\n"

        f"{cleaned_sql}\n"

        ") AS CORTEX_RESULT\n"

        f"LIMIT {MAX_RESULT_ROWS}"

    )


def configure_statement_timeout(cursor):

    """
    Configure the Snowflake session so individual SQL statements
    cannot execute longer than 60 seconds.
    """

    cursor.execute(

        f"ALTER SESSION SET "
        f"STATEMENT_TIMEOUT_IN_SECONDS = "
        f"{STATEMENT_TIMEOUT_SECONDS}"

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


        if result is None:

            raise ValueError(
                "AI_COMPLETE returned NULL"
            )


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


        answer = result.get(
            "answer",
            ""
        )


        follow_up_questions = result.get(
            "follow_up_questions",
            []
        )


        if not isinstance(
            follow_up_questions,
            list
        ):

            follow_up_questions = []


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


# ==========================================================
# >>> RCA AUTO-FLOW
# ==========================================================
#
# These functions are used automatically from /chat.
#
# Flow:
#
# User question
#      ↓
# Detect diagnostic intent
#      ↓
# Check SQL evidence
#      ↓
# Sufficient?
#      ↓
# RCA AI_COMPLETE
#
# ==========================================================


def is_diagnostic_question(
    user_question: str
) -> bool:

    """
    Lightweight deterministic check for RCA-style questions.

    This avoids running the expensive RCA AI_COMPLETE call for
    ordinary analytical questions.

    The check is intentionally broad enough to catch common
    business diagnostic wording.
    """

    if not user_question:

        return False


    question = user_question.lower().strip()


    diagnostic_patterns = [

        "why",

        "root cause",

        "reason for",

        "reason behind",

        "what caused",

        "what is causing",

        "driver",

        "drivers",

        "decline",

        "decrease",

        "drop",

        "dropped",

        "fall",

        "fell",

        "increase",

        "increased",

        "grew",

        "growth",

        "spike",

        "spiked",

        "change",

        "changed",

        "underperform",

        "underperformed",

        "underperformance",

        "overperform",

        "overperformed",

        "variance",

        "anomaly",

        "anomalies",

        "explain",

        "explanation",

        "investigate",

        "investigation",

        "diagnose",

        "diagnostic",

        "cause",

        "causes"

    ]


    return any(

        pattern in question

        for pattern
        in diagnostic_patterns

    )


def check_rca_evidence(
    columns: list,
    rows: list
) -> Dict[str, Any]:

    """
    Determine whether the SQL result contains enough evidence
    for a meaningful RCA.

    This is deliberately deterministic.

    We do not ask AI_COMPLETE to decide whether evidence exists.

    Minimum requirements:

    - At least 2 rows
    - At least 2 columns

    Additional signals are detected for time/dimension/value
    based analysis.
    """

    if not rows:

        return {

            "sufficient": False,

            "reason":
                "The query returned no rows.",

            "row_count":
                0,

            "column_count":
                len(columns or [])

        }


    if len(rows) < 2:

        return {

            "sufficient": False,

            "reason":
                "The query returned fewer than two rows.",

            "row_count":
                len(rows),

            "column_count":
                len(columns or [])

        }


    if len(columns or []) < 2:

        return {

            "sufficient": False,

            "reason":
                "The query does not contain enough dimensions or metrics.",

            "row_count":
                len(rows),

            "column_count":
                len(columns or [])

        }


    lower_columns = [

        str(column).lower()

        for column
        in columns

    ]


    time_keywords = [

        "date",
        "year",
        "month",
        "quarter",
        "week",
        "day",
        "period",
        "time"

    ]


    metric_keywords = [

        "sales",
        "revenue",
        "profit",
        "quantity",
        "units",
        "margin",
        "amount",
        "cost",
        "price",
        "value",
        "count",
        "volume"

    ]


    dimension_keywords = [

        "region",
        "country",
        "state",
        "city",
        "store",
        "product",
        "category",
        "subcategory",
        "brand",
        "customer",
        "segment",
        "department",
        "channel"

    ]


    has_time = any(

        any(
            keyword in column
            for keyword in time_keywords
        )

        for column
        in lower_columns

    )


    has_metric = any(

        any(
            keyword in column
            for keyword in metric_keywords
        )

        for column
        in lower_columns

    )


    has_dimension = any(

        any(
            keyword in column
            for keyword in dimension_keywords
        )

        for column
        in lower_columns

    )


    # A result containing multiple rows and some meaningful
    # dimensional/metric information is considered sufficient.

    sufficient = (

        len(rows) >= 2

        and

        (

            has_metric

            or

            has_dimension

            or

            has_time

        )

    )


    if sufficient:

        reason = (
            "The result contains multiple rows and "
            "analytical dimensions or metrics."
        )

    else:

        reason = (
            "The result does not contain enough "
            "analytical evidence for RCA."
        )


    return {

        "sufficient":
            sufficient,

        "reason":
            reason,

        "row_count":
            len(rows),

        "column_count":
            len(columns or []),

        "has_time":
            has_time,

        "has_metric":
            has_metric,

        "has_dimension":
            has_dimension

    }


# ==========================================================
# RCA AI_COMPLETE RESPONSE GENERATOR
# ==========================================================

def generate_rca_ai_response(
    conn,
    user_question: str,
    user_region: Optional[str],
    sql_text: str,
    columns: list,
    rows: list
):

    model = os.getenv(
        "SNOWFLAKE_RCA_AI_MODEL",
        "llama3.3-70b"
    )


    # ------------------------------------------------------
    # Security / Region Context
    # ------------------------------------------------------

    region_context = "Not provided"

    if user_region:

        safe_region = user_region.replace(
            "'",
            "''"
        )

        region_context = safe_region


    # ------------------------------------------------------
    # Limit evidence sent to AI_COMPLETE
    # ------------------------------------------------------

    max_rows = 500

    evidence_rows = rows[:max_rows]


    # ------------------------------------------------------
    # RCA Prompt
    # ------------------------------------------------------

    prompt = f"""
You are an expert business analytics root-cause-analysis assistant
inside a Power BI report.

The user asked:

{user_question}

The authorized user region is:

{region_context}

The SQL below was generated by Cortex Analyst and executed against
the Snowflake semantic model:

{sql_text}

The SQL result contains these columns:

{json.dumps(columns, indent=2)}

The SQL result rows are:

{json.dumps(evidence_rows, indent=2)}

Your task is to explain the likely analytical drivers behind the
user's question using ONLY the supplied SQL result evidence.

IMPORTANT SECURITY REQUIREMENTS:

- The user region is an authorized security boundary.
- Do not suggest or infer information outside the authorized region.
- Do not request or assume data from another region.
- The supplied SQL already contains the authorized region filtering.
- Treat the supplied result as the security-filtered evidence.

IMPORTANT ANALYTICAL REQUIREMENTS:

- Do NOT invent numbers.
- Do NOT invent percentages.
- Do NOT invent rankings.
- Do NOT invent brands.
- Do NOT invent products.
- Do NOT invent stores.
- Do NOT invent dates.
- Do NOT invent metrics.
- Do NOT claim causation when the evidence only shows correlation
  or association.
- Clearly distinguish observed drivers from possible explanations.
- If the evidence is insufficient, explicitly say so.
- Do not create drivers that are not present in the supplied evidence.
- Use the actual values present in the result when describing impact.
- Prefer quantitative evidence whenever available.
- Focus on the dimensions present in the result, such as time,
  category, store, quantity, revenue, or profit.
- Recommendations must logically follow from the observed evidence.
- Do not include SQL in the answer.

Return JSON with exactly this structure:

{{
    "summary": "Concise explanation of what changed and why.",
    "primary_drivers": [
        {{
            "dimension": "Dimension name",
            "driver": "Specific driver",
            "evidence": "Evidence from the supplied result",
            "impact": "Observed impact",
            "confidence": "High|Medium|Low"
        }}
    ],
    "secondary_drivers": [
        {{
            "dimension": "Dimension name",
            "driver": "Specific driver",
            "evidence": "Evidence from the supplied result",
            "impact": "Observed impact",
            "confidence": "High|Medium|Low"
        }}
    ],
    "recommendations": [
        "Actionable recommendation based on the evidence"
    ],
    "confidence_caveats": [
        "Important limitation or caveat"
    ]
}}

If there is not enough evidence to identify a driver:

- Keep primary_drivers empty or include only drivers directly supported
  by the evidence.
- Explain the limitation in confidence_caveats.
- Do not guess.

Keep the response concise and business-friendly.
"""


    cursor = conn.cursor()


    try:

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

                        'summary': {

                            'type': 'string'

                        },

                        'primary_drivers': {

                            'type': 'array',

                            'items': {

                                'type': 'object',

                                'properties': {

                                    'dimension': {

                                        'type': 'string'

                                    },

                                    'driver': {

                                        'type': 'string'

                                    },

                                    'evidence': {

                                        'type': 'string'

                                    },

                                    'impact': {

                                        'type': 'string'

                                    },

                                    'confidence': {

                                        'type': 'string'

                                    }

                                },

                                'required': [

                                    'dimension',

                                    'driver',

                                    'evidence',

                                    'impact',

                                    'confidence'

                                ]

                            }

                        },

                        'secondary_drivers': {

                            'type': 'array',

                            'items': {

                                'type': 'object',

                                'properties': {

                                    'dimension': {

                                        'type': 'string'

                                    },

                                    'driver': {

                                        'type': 'string'

                                    },

                                    'evidence': {

                                        'type': 'string'

                                    },

                                    'impact': {

                                        'type': 'string'

                                    },

                                    'confidence': {

                                        'type': 'string'

                                    }

                                },

                                'required': [

                                    'dimension',

                                    'driver',

                                    'evidence',

                                    'impact',

                                    'confidence'

                                ]

                            }

                        },

                        'recommendations': {

                            'type': 'array',

                            'items': {

                                'type': 'string'

                            }

                        },

                        'confidence_caveats': {

                            'type': 'array',

                            'items': {

                                'type': 'string'

                            }

                        }

                    },

                    'required': [

                        'summary',

                        'primary_drivers',

                        'secondary_drivers',

                        'recommendations',

                        'confidence_caveats'

                    ]

                }

            }

        )

        """


        print("========================================")
        print("RCA AI_COMPLETE STARTED")
        print("========================================")

        print(
            f"RCA AI_COMPLETE model: {model}"
        )

        print(
            f"RCA evidence rows: {len(evidence_rows)}"
        )

        print(
            f"RCA authorized region: {region_context}"
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
            "RCA AI_COMPLETE returned successfully."
        )


        print(
            "RCA AI_COMPLETE raw result:"
        )

        print(result)


        if result is None:

            raise ValueError(
                "RCA AI_COMPLETE returned NULL"
            )


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

                "Unexpected RCA AI_COMPLETE "
                "result type: "

                f"{type(result).__name__}"

            )


        summary = result.get(
            "summary",
            ""
        )


        primary_drivers = result.get(
            "primary_drivers",
            []
        )


        secondary_drivers = result.get(
            "secondary_drivers",
            []
        )


        recommendations = result.get(
            "recommendations",
            []
        )


        confidence_caveats = result.get(
            "confidence_caveats",
            []
        )


        if not isinstance(
            primary_drivers,
            list
        ):

            primary_drivers = []


        if not isinstance(
            secondary_drivers,
            list
        ):

            secondary_drivers = []


        if not isinstance(
            recommendations,
            list
        ):

            recommendations = []


        if not isinstance(
            confidence_caveats,
            list
        ):

            confidence_caveats = []


        return {

            "summary":
                str(summary),

            "primary_drivers":
                primary_drivers,

            "secondary_drivers":
                secondary_drivers,

            "recommendations":
                [
                    str(item)
                    for item in recommendations
                    if item
                ],

            "confidence_caveats":
                [
                    str(item)
                    for item in confidence_caveats
                    if item
                ]

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


# ==========================================================
# RCA PREFLIGHT
# ==========================================================

@app.options("/rca")
def options_rca():

    return {}


# ----------------------------------------------------------
# Live Cortex Chat Endpoint
# ----------------------------------------------------------

@app.post("/chat")
def chat(request: ChatRequest):

    # ======================================================
    # EXISTING CORTEX ANALYST LOGIC
    # ======================================================

    user_query = request.question


    # ------------------------------------------------------
    # Temporary POC: Power BI evaluated this region under
    # dataset RLS.
    # ------------------------------------------------------

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
    # NATIVE SNOWFLAKE SEMANTIC VIEW
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


    # ======================================================
    # 4. MANDATORY 500-ROW SQL ENFORCEMENT
    # ======================================================

    if generated_sql:

        original_generated_sql = generated_sql

        generated_sql = enforce_sql_limit(
            generated_sql
        )

        print("========================================")
        print("CORTEX SQL ROW LIMIT ENFORCEMENT")
        print("========================================")

        print(
            f"Maximum result rows: {MAX_RESULT_ROWS}"
        )

        print(
            "Original Cortex SQL:"
        )

        print(
            original_generated_sql
        )

        print(
            "SQL executed after backend enforcement:"
        )

        print(
            generated_sql
        )


    # ------------------------------------------------------
    # 5. Execute Generated SQL
    # ------------------------------------------------------

    columns = []

    rows = []

    table_schema = []


    if generated_sql:

        try:

            conn = get_connection()

            cursor = conn.cursor()


            configure_statement_timeout(
                cursor
            )


            print("========================================")
            print("SNOWFLAKE STATEMENT TIMEOUT")
            print("========================================")

            print(
                f"Statement timeout: "
                f"{STATEMENT_TIMEOUT_SECONDS} seconds"
            )


            cursor.execute(
                generated_sql
            )


            if cursor.description:

                columns = [

                    desc[0]

                    for desc
                    in cursor.description

                ]


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
    # 6. NORMAL AI_COMPLETE RESPONSE
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
    # 7. RCA AUTO-FLOW
    # ======================================================
    #
    # This is the new part.
    #
    # We only execute RCA for diagnostic questions.
    #
    # Normal questions do NOT incur the RCA AI_COMPLETE call.
    #
    # ======================================================

    diagnostic = is_diagnostic_question(
        request.question
    )


    rca_result = None

    rca_evidence = {

        "sufficient":
            False,

        "reason":
            "RCA was not requested."

    }


    print("========================================")
    print("RCA AUTO-FLOW")
    print("========================================")

    print(
        f"Diagnostic question: {diagnostic}"
    )


    if diagnostic:

        # --------------------------------------------------
        # Check evidence
        # --------------------------------------------------

        rca_evidence = check_rca_evidence(

            columns=columns,

            rows=rows

        )


        print(
            f"RCA evidence sufficient: "
            f"{rca_evidence.get('sufficient')}"
        )

        print(
            f"RCA evidence reason: "
            f"{rca_evidence.get('reason')}"
        )


        # --------------------------------------------------
        # Evidence is sufficient
        # --------------------------------------------------

        if rca_evidence.get(
            "sufficient"
        ):

            try:

                rca_conn = get_connection()

                try:

                    rca_result = generate_rca_ai_response(

                        conn=rca_conn,

                        user_question=request.question,

                        user_region=request.user_region,

                        sql_text=generated_sql,

                        columns=columns,

                        rows=rows

                    )

                finally:

                    rca_conn.close()


                print(
                    "RCA completed automatically."
                )


            except Exception as rca_err:

                print(
                    "========================================"
                )

                print(
                    "AUTOMATIC RCA FAILED"
                )

                print(
                    "========================================"
                )

                print(
                    f"Error type: "
                    f"{type(rca_err).__name__}"
                )

                print(
                    f"Error message: "
                    f"{str(rca_err)}"
                )

                import traceback

                traceback.print_exc()

                print(
                    "========================================"
                )

                # --------------------------------------------------
                # Important:
                #
                # RCA failure should NOT fail the user's normal
                # analytical response.
                # --------------------------------------------------

                rca_result = None


        else:

            print(
                "RCA skipped because evidence is insufficient."
            )


    else:

        print(
            "RCA skipped because question is not diagnostic."
        )


    # ======================================================
    # 8. FINAL RESPONSE TO POWER BI
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
            ),

        # ==================================================
        # RCA AUTO-FLOW RESPONSE
        # ==================================================

        "diagnostic":
            diagnostic,

        "rca_evidence":
            rca_evidence,

        "rca":
            rca_result

    }


# ==========================================================
# ROOT CAUSE ANALYSIS ENDPOINT
# ==========================================================
#
# Kept for backward compatibility.
#
# The new automatic flow does NOT need to call this endpoint.
#
# ==========================================================

@app.post("/rca")
def rca(request: RCARequest):

    print("========================================")
    print("RCA REQUEST STARTED")
    print("========================================")


    # ------------------------------------------------------
    # Basic validation
    # ------------------------------------------------------

    if not request.question:

        raise HTTPException(

            status_code=400,

            detail="RCA question is required."

        )


    if not request.rows:

        raise HTTPException(

            status_code=400,

            detail={

                "message":
                    "Insufficient evidence for RCA.",

                "reason":
                    "The original query returned no rows."

            }

        )


    columns = request.columns or []

    rows = request.rows or []


    # ------------------------------------------------------
    # Evidence validation
    # ------------------------------------------------------

    evidence = check_rca_evidence(

        columns=columns,

        rows=rows

    )


    if not evidence.get(
        "sufficient"
    ):

        return {

            "type":
                "root_cause_analysis",

            "question":
                request.question,

            "user_region":
                request.user_region,

            "status":
                "insufficient_evidence",

            "summary":
                "There is not enough evidence in the query result "
                "to perform a meaningful root cause analysis.",

            "primary_drivers":
                [],

            "secondary_drivers":
                [],

            "recommendations":
                [],

            "confidence_caveats":
                [
                    evidence.get(
                        "reason",
                        "Insufficient evidence."
                    )
                ]

        }


    sql_text = request.sql or ""


    # ------------------------------------------------------
    # Call AI_COMPLETE
    # ------------------------------------------------------

    try:

        conn = get_connection()

        try:

            rca_result = generate_rca_ai_response(

                conn=conn,

                user_question=request.question,

                user_region=request.user_region,

                sql_text=sql_text,

                columns=columns,

                rows=rows

            )

        finally:

            conn.close()


    except Exception as rca_err:

        print(
            "========================================"
        )

        print(
            "RCA AI_COMPLETE FAILED"
        )

        print(
            "========================================"
        )

        print(
            f"Error type: "
            f"{type(rca_err).__name__}"
        )

        print(
            f"Error message: "
            f"{str(rca_err)}"
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
                    "Root cause analysis failed",

                "error_type":
                    type(rca_err).__name__,

                "error":
                    str(rca_err)

            }

        )


    # ------------------------------------------------------
    # Final RCA Response
    # ------------------------------------------------------

    response = {

        "type":
            "root_cause_analysis",

        "question":
            request.question,

        "user_region":
            request.user_region,

        "summary":
            rca_result.get(
                "summary",
                ""
            ),

        "primary_drivers":
            rca_result.get(
                "primary_drivers",
                []
            ),

        "secondary_drivers":
            rca_result.get(
                "secondary_drivers",
                []
            ),

        "recommendations":
            rca_result.get(
                "recommendations",
                []
            ),

        "confidence_caveats":
            rca_result.get(
                "confidence_caveats",
                []
            )

    }


    print(
        "RCA completed successfully."
    )


    print(
        "========================================"
    )


    return response