import os
import json
import uuid
import datetime
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


# ==========================================================
# TEMPORARY USAGE TRACKING - START
# ==========================================================
#
# PURPOSE:
#
#   Temporary investigation only.
#
#   This section tracks:
#
#       1. Snowi temporary request ID
#       2. Snowflake query IDs
#       3. QUERY_TAG used for correlation
#       4. Cortex AI Function credits/tokens
#       5. Warehouse query credits
#       6. Cortex Analyst hourly usage
#
#   IMPORTANT:
#
#   This is NOT part of the permanent Snowi architecture.
#
#   Everything between:
#
#       TEMPORARY USAGE TRACKING - START
#
#   and:
#
#       TEMPORARY USAGE TRACKING - END
#
#   can later be removed.
#
# ==========================================================

TEMP_USAGE_TAG_PREFIX = "SNOWI_TEMP_USAGE"

# ==========================================================
# PERSISTENT USAGE HISTORY TABLE
# ==========================================================
#
# Historical token / credit usage is stored here.
#
# The table name is intentionally hardcoded as requested.
#
# ==========================================================

USAGE_HISTORY_TABLE = "CPG.IBP_SEMANTIC.CORTEX_USAGE_HISTORY"
# ==========================================================
# IST TIMESTAMP HELPER
# ==========================================================
#
# India does not observe daylight saving time, so a fixed
# UTC+5:30 offset is correct year-round and does not require
# a timezone database lookup.
#
# ==========================================================

IST_OFFSET = datetime.timezone(
    datetime.timedelta(
        hours=5,
        minutes=30
    )
)


def to_ist_iso(ts):
    """
    Convert a Snowflake-returned timestamp (timezone-aware
    datetime) into an ISO-8601 string in Indian Standard Time.

    Returns None if the timestamp is missing or cannot be
    converted (e.g. naive datetime with no tzinfo).
    """

    if ts is None:

        return None

    try:

        return ts.astimezone(
            IST_OFFSET
        ).isoformat()

    except Exception:

        return None


def create_temporary_usage_id():
    """
    Create a unique identifier for one /chat request.

    Example:

        SNOWI_TEMP_USAGE_8f3b1c...
    """

    return (
        f"{TEMP_USAGE_TAG_PREFIX}_"
        f"{uuid.uuid4().hex}"
    )


def set_temporary_query_tag(
    cursor,
    usage_id: str
):
    """
    Set a temporary QUERY_TAG on the Snowflake session.

    All subsequent Snowflake SQL statements executed through
    this cursor/session will carry this tag.
    """

    safe_usage_id = usage_id.replace(
        "'",
        "''"
    )

    cursor.execute(

        f"ALTER SESSION SET QUERY_TAG = "
        f"'SNOWI_TEMP:{safe_usage_id}'"

    )


def get_snowflake_query_id(cursor):

    """
    Return the Snowflake query ID generated by the last
    cursor.execute() call.

    Snowflake Connector exposes this as sfqid.
    """

    try:

        return getattr(
            cursor,
            "sfqid",
            None
        )

    except Exception:

        return None


def execute_with_temporary_tracking(
    cursor,
    sql,
    params=None,
    usage_tracker=None,
    usage_label="sql"
):
    """
    Execute a Snowflake statement while recording its
    Snowflake query ID.

    This is temporary diagnostic instrumentation only.
    """

    if params is None:

        cursor.execute(
            sql
        )

    else:

        cursor.execute(
            sql,
            params
        )


    query_id = get_snowflake_query_id(
        cursor
    )


    if (
        usage_tracker is not None
        and query_id
    ):

        usage_tracker.append({

            "label":
                usage_label,

            "query_id":
                query_id

        })


    print(
        "TEMP USAGE TRACKING | "
        f"{usage_label} | "
        f"query_id={query_id}"
    )


    return query_id


def _extract_cortex_metrics(metrics):

    """
    Extract token metrics from the METRICS field returned by
    CORTEX_AI_FUNCTIONS_USAGE_HISTORY.

    IMPORTANT:

    Snowflake returns METRICS as a JSON-encoded STRING, not a
    parsed array/list. If this string is iterated directly
    (as if it were already a list of dicts), Python iterates
    over individual characters instead of metric objects, and
    every metric silently resolves to 0. This is corrected
    here by explicitly parsing the string with json.loads()
    before iterating.

    Snowflake can return metrics such as:

        input tokens
        output tokens

    or:

        total tokens

    The exact structure can vary by function/model.
    """

    if not metrics:

        return {

            "input_tokens":
                0,

            "output_tokens":
                0,

            "total_tokens":
                0

        }


    # ------------------------------------------------------
    # METRICS is typically a JSON string. Parse it before
    # attempting to iterate.
    # ------------------------------------------------------

    if isinstance(
        metrics,
        str
    ):

        try:

            metrics = json.loads(
                metrics
            )

        except Exception as parse_error:

            print(
                "TEMP USAGE: failed to parse "
                f"METRICS JSON string: {parse_error}"
            )

            return {

                "input_tokens":
                    0,

                "output_tokens":
                    0,

                "total_tokens":
                    0

            }


    if not isinstance(
        metrics,
        list
    ):

        return {

            "input_tokens":
                0,

            "output_tokens":
                0,

            "total_tokens":
                0

        }


    input_tokens = 0

    output_tokens = 0

    total_tokens = 0


    try:

        for metric_item in metrics:

            if not isinstance(
                metric_item,
                dict
            ):

                continue


            key = metric_item.get(
                "key",
                {}
            )


            value = metric_item.get(
                "value",
                0
            )


            if not isinstance(
                key,
                dict
            ):

                continue


            metric_name = str(

                key.get(
                    "metric",
                    ""
                )

            ).lower()


            try:

                numeric_value = int(
                    value
                )

            except Exception:

                numeric_value = 0


            if metric_name == "input":

                input_tokens += (
                    numeric_value
                )


            elif metric_name == "output":

                output_tokens += (
                    numeric_value
                )


            elif metric_name == "total":

                total_tokens += (
                    numeric_value
                )


    except Exception:

        pass


    # If Snowflake reports input/output separately,
    # calculate total ourselves.

    if (
        total_tokens == 0
        and
        (
            input_tokens > 0
            or
            output_tokens > 0
        )
    ):

        total_tokens = (

            input_tokens

            +

            output_tokens

        )


    return {

        "input_tokens":
            input_tokens,

        "output_tokens":
            output_tokens,

        "total_tokens":
            total_tokens

    }


def query_temporary_usage(
    usage_id: str
):
    """
    Query Snowflake ACCOUNT_USAGE views for the temporary
    usage identifier.

    IMPORTANT:

    Snowflake usage history is asynchronous.

    Therefore:

        /chat
            ↓
        wait for usage records
            ↓
        /temporary-usage/{usage_id}

    may be necessary.

    This endpoint deliberately does NOT return zero as proof
    that no credits were consumed. It reports whether usage
    records have appeared yet.

    ADDITIONALLY:

    Because QUERY_ATTRIBUTION_HISTORY / QUERY_METERING_HISTORY
    (ACCOUNT_USAGE views) can lag by up to a few hours before a
    query is attributed, this function also queries
    INFORMATION_SCHEMA.QUERY_HISTORY(), which reflects recent
    query activity almost immediately (no per-query credit
    figure, but confirms the tagged query actually ran). This
    lets us distinguish "tag never reached Snowflake" from
    "tag reached Snowflake, credit attribution just hasn't
    landed yet."
    """

    conn = None

    cursor = None


    result = {

        "usage_id":
            usage_id,

        "status":
            "checking",

        "cortex_analyst": {

            "credits":
                None,

            "request_count":
                None,

            "recent_hourly_records":
                []

        },

        "cortex_ai_functions": {

            "credits":
                0.0,

            "input_tokens":
                0,

            "output_tokens":
                0,

            "total_tokens":
                0,

            "query_count":
                0

        },

        "warehouse": {

            "credits":
                0.0,

            "query_count":
                0,

            "source":
                None,

            "immediate_confirmation":
                []

        },

        "total_identifiable_credits":
            0.0,

        "details": {

            "cortex_ai_function_rows":
                [],

            "warehouse_query_rows":
                []

        }

    }


    try:

        conn = get_connection()

        cursor = conn.cursor()


        # ==================================================
        # 1. Cortex AI Function Usage
        # ==================================================
        #
        # AI_COMPLETE usage is recorded in:
        #
        #   CORTEX_AI_FUNCTIONS_USAGE_HISTORY
        #
        # The QUERY_TAG allows us to identify the exact
        # AI_COMPLETE statements belonging to this temporary
        # /chat request.
        #
        # ==================================================

        cortex_sql = """

        SELECT

            START_TIME,

            END_TIME,

            FUNCTION_NAME,

            MODEL_NAME,

            QUERY_ID,

            WAREHOUSE_ID,

            QUERY_TAG,

            METRICS,

            CREDITS,

            IS_COMPLETED

        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY

        WHERE QUERY_TAG = %s

        ORDER BY START_TIME

        """


        cortex_rows = []


        try:

            cursor.execute(

                cortex_sql,

                (
                    f"SNOWI_TEMP:{usage_id}",
                )

            )


            cortex_rows = (
                cursor.fetchall()
            )


            cortex_columns = [

                desc[0]

                for desc
                in cursor.description

            ]


        except Exception as cortex_error:

            print(
                "TEMP USAGE: "
                "CORTEX_AI_FUNCTIONS_USAGE_HISTORY "
                f"lookup failed: {cortex_error}"
            )

            result[
                "cortex_ai_functions"
            ][
                "error"
            ] = str(
                cortex_error
            )

            cortex_columns = []


        cortex_details = []


        cortex_credits = 0.0

        input_tokens = 0

        output_tokens = 0

        total_tokens = 0


        for row in cortex_rows:

            item = dict(

                zip(
                    cortex_columns,
                    row
                )

            )


            metrics = item.get(
                "METRICS"
            )


            metric_values = (
                _extract_cortex_metrics(
                    metrics
                )
            )


            input_tokens += (

                metric_values[
                    "input_tokens"
                ]

            )


            output_tokens += (

                metric_values[
                    "output_tokens"
                ]

            )


            total_tokens += (

                metric_values[
                    "total_tokens"
                ]

            )


            if item.get(
                "CREDITS"
            ) is not None:

                cortex_credits += float(

                    item.get(
                        "CREDITS"
                    )

                )


            cortex_details.append({

                "start_time":
                    item.get(
                        "START_TIME"
                    ),

                "end_time":
                    item.get(
                        "END_TIME"
                    ),

                # ------------------------------------------
                # IST TIMESTAMPS
                # ------------------------------------------

                "start_time_ist":
                    to_ist_iso(
                        item.get(
                            "START_TIME"
                        )
                    ),

                "end_time_ist":
                    to_ist_iso(
                        item.get(
                            "END_TIME"
                        )
                    ),

                "function_name":
                    item.get(
                        "FUNCTION_NAME"
                    ),

                "model_name":
                    item.get(
                        "MODEL_NAME"
                    ),

                "query_id":
                    item.get(
                        "QUERY_ID"
                    ),

                "warehouse_id":
                    item.get(
                        "WAREHOUSE_ID"
                    ),

                "query_tag":
                    item.get(
                        "QUERY_TAG"
                    ),

                "metrics":
                    item.get(
                        "METRICS"
                    ),

                "credits":
                    item.get(
                        "CREDITS"
                    ),

                "is_completed":
                    item.get(
                        "IS_COMPLETED"
                    ),

                "input_tokens":
                    metric_values[
                        "input_tokens"
                    ],

                "output_tokens":
                    metric_values[
                        "output_tokens"
                    ],

                "total_tokens":
                    metric_values[
                        "total_tokens"
                    ]

            })


        result[
            "cortex_ai_functions"
        ] = {

            "credits":
                cortex_credits,

            "input_tokens":
                input_tokens,

            "output_tokens":
                output_tokens,

            "total_tokens":
                total_tokens,

            "query_count":
                len(
                    cortex_rows
                )

        }


        result[
            "details"
        ][
            "cortex_ai_function_rows"
        ] = cortex_details


        # ==================================================
        # 2. Standard Warehouse Query Attribution
        # ==================================================
        #
        # QUERY_ATTRIBUTION_HISTORY provides per-query
        # warehouse compute attribution for standard
        # warehouses.
        #
        # It does NOT include warehouse idle time.
        #
        # NOTE: This ACCOUNT_USAGE view can lag by up to a
        # few hours before a given query is attributed. See
        # the "immediate_confirmation" section below for a
        # near-real-time check.
        #
        # ==================================================

        warehouse_sql = """

        SELECT

            QUERY_ID,

            QUERY_TAG,

            WAREHOUSE_NAME,

            START_TIME,

            END_TIME,

            CREDITS_ATTRIBUTED_COMPUTE,

            CREDITS_USED_QUERY_ACCELERATION

        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY

        WHERE QUERY_TAG = %s

        ORDER BY START_TIME

        """


        warehouse_rows = []


        try:

            cursor.execute(

                warehouse_sql,

                (
                    f"SNOWI_TEMP:{usage_id}",
                )

            )


            attribution_rows = (
                cursor.fetchall()
            )


            attribution_columns = [

                desc[0]

                for desc
                in cursor.description

            ]


            for row in attribution_rows:

                item = dict(

                    zip(
                        attribution_columns,
                        row
                    )

                )


                normalized = {

                    key.lower():
                        value

                    for key, value
                    in item.items()

                }


                normalized[
                    "start_time_ist"
                ] = to_ist_iso(

                    normalized.get(
                        "start_time"
                    )

                )


                normalized[
                    "end_time_ist"
                ] = to_ist_iso(

                    normalized.get(
                        "end_time"
                    )

                )


                warehouse_rows.append(
                    normalized
                )


        except Exception as attribution_error:

            print(
                "TEMP USAGE: "
                "QUERY_ATTRIBUTION_HISTORY "
                f"lookup failed: {attribution_error}"
            )


        warehouse_credits = 0.0


        for item in warehouse_rows:

            compute_credits = (

                item.get(
                    "credits_attributed_compute"
                )

                or 0

            )


            qas_credits = (

                item.get(
                    "credits_used_query_acceleration"
                )

                or 0

            )


            warehouse_credits += (

                float(
                    compute_credits
                )

                +

                float(
                    qas_credits
                )

            )


        if warehouse_rows:

            result[
                "warehouse"
            ][
                "source"
            ] = (
                "QUERY_ATTRIBUTION_HISTORY"
            )


        # ==================================================
        # 3. Adaptive Warehouse Fallback
        # ==================================================
        #
        # QUERY_ATTRIBUTION_HISTORY does not contain
        # Adaptive Warehouse queries.
        #
        # QUERY_METERING_HISTORY is the per-query source
        # for Adaptive Warehouses.
        #
        # ==================================================

        if not warehouse_rows:

            adaptive_sql = """

            SELECT

                QUERY_ID,

                QUERY_TAG,

                WAREHOUSE_NAME,

                QUERY_METERING_HOUR,

                QUERY_START_TIME,

                QUERY_END_TIME,

                CREDITS_USED_COMPUTE,

                CREDITS_USED_CLOUD_SERVICES,

                CREDITS_USED

            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_METERING_HISTORY

            WHERE QUERY_TAG = %s

            ORDER BY QUERY_START_TIME

            """


            try:

                cursor.execute(

                    adaptive_sql,

                    (
                        f"SNOWI_TEMP:{usage_id}",
                    )

                )


                adaptive_rows = (
                    cursor.fetchall()
                )


                adaptive_columns = [

                    desc[0]

                    for desc
                    in cursor.description

                ]


                adaptive_details = []


                warehouse_credits = 0.0


                for row in adaptive_rows:

                    item = dict(

                        zip(
                            adaptive_columns,
                            row
                        )

                    )


                    normalized = {

                        key.lower():
                            value

                        for key, value
                        in item.items()

                    }


                    normalized[
                        "query_start_time_ist"
                    ] = to_ist_iso(

                        normalized.get(
                            "query_start_time"
                        )

                    )


                    normalized[
                        "query_end_time_ist"
                    ] = to_ist_iso(

                        normalized.get(
                            "query_end_time"
                        )

                    )


                    adaptive_details.append(
                        normalized
                    )


                    # For Adaptive Warehouses we use
                    # CREDITS_USED because this is the
                    # per-query credit usage value.
                    #
                    # This includes compute and cloud
                    # services for the query.

                    warehouse_credits += float(

                        normalized.get(
                            "credits_used",
                            0
                        )

                        or 0

                    )


                if adaptive_details:

                    warehouse_rows = (
                        adaptive_details
                    )

                    result[
                        "warehouse"
                    ][
                        "source"
                    ] = (
                        "QUERY_METERING_HISTORY"
                    )


            except Exception as adaptive_error:

                print(
                    "TEMP USAGE: "
                    "QUERY_METERING_HISTORY "
                    f"lookup failed: {adaptive_error}"
                )


        result[
            "warehouse"
        ][
            "credits"
        ] = warehouse_credits


        result[
            "warehouse"
        ][
            "query_count"
        ] = len(
            warehouse_rows
        )


        result[
            "details"
        ][
            "warehouse_query_rows"
        ] = warehouse_rows


        # ==================================================
        # 3b. Immediate Confirmation (near real-time)
        # ==================================================
        #
        # INFORMATION_SCHEMA.QUERY_HISTORY() is a table
        # function backed by near-real-time metadata (unlike
        # the ACCOUNT_USAGE views above, which can lag by
        # hours). It does NOT report per-query credits, but
        # it confirms whether the tagged query actually ran
        # on Snowflake.
        #
        # This lets us distinguish two very different
        # situations when warehouse credits show as 0/empty:
        #
        #   a) The tagged query hasn't been picked up by
        #      ACCOUNT_USAGE yet (attribution lag) -- the
        #      query DOES show up here.
        #
        #   b) The tag never reached Snowflake at all (a
        #      tagging/session bug) -- the query does NOT
        #      show up here either.
        #
        # ==================================================

        confirmation_sql = """

        SELECT

            QUERY_ID,

            QUERY_TAG,

            WAREHOUSE_NAME,

            EXECUTION_STATUS,

            START_TIME,

            END_TIME,

            TOTAL_ELAPSED_TIME,

            BYTES_SCANNED,

            ROWS_PRODUCED

        FROM TABLE(

            INFORMATION_SCHEMA.QUERY_HISTORY(

                RESULT_LIMIT => 100

            )

        )

        WHERE QUERY_TAG = %s

        ORDER BY START_TIME DESC

        """


        try:

            cursor.execute(

                confirmation_sql,

                (
                    f"SNOWI_TEMP:{usage_id}",
                )

            )


            confirmation_rows = (
                cursor.fetchall()
            )


            confirmation_columns = [

                desc[0]

                for desc
                in cursor.description

            ]


            confirmation_details = []


            for row in confirmation_rows:

                item = dict(

                    zip(
                        confirmation_columns,
                        row
                    )

                )


                normalized = {

                    key.lower():
                        value

                    for key, value
                    in item.items()

                }


                normalized[
                    "start_time_ist"
                ] = to_ist_iso(

                    normalized.get(
                        "start_time"
                    )

                )


                normalized[
                    "end_time_ist"
                ] = to_ist_iso(

                    normalized.get(
                        "end_time"
                    )

                )


                confirmation_details.append(
                    normalized
                )


            result[
                "warehouse"
            ][
                "immediate_confirmation"
            ] = confirmation_details


        except Exception as confirmation_error:

            print(
                "TEMP USAGE: "
                "INFORMATION_SCHEMA.QUERY_HISTORY "
                f"lookup failed: {confirmation_error}"
            )

            result[
                "warehouse"
            ][
                "immediate_confirmation_error"
            ] = str(
                confirmation_error
            )


        # ==================================================
        # 4. Cortex Analyst Usage
        # ==================================================
        #
        # IMPORTANT:
        #
        # Cortex Analyst usage is reported in hourly
        # aggregates rather than per-request records.
        #
        # Therefore it cannot be perfectly attributed to
        # one request when multiple Analyst requests happen
        # in the same aggregation window.
        #
        # For our temporary single-query test:
        #
        #   - run one Analyst request
        #   - make sure there are no competing requests
        #   - inspect the corresponding hourly record
        #
        # ==================================================

        analyst_sql = """

        SELECT

            START_TIME,

            END_TIME,

            REQUEST_COUNT,

            CREDITS,

            USERNAME

        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY

        WHERE START_TIME >= DATEADD(

            hour,

            -2,

            CURRENT_TIMESTAMP()

        )

        ORDER BY START_TIME DESC

        LIMIT 10

        """


        try:

            cursor.execute(
                analyst_sql
            )


            analyst_rows = (
                cursor.fetchall()
            )


            analyst_columns = [

                desc[0]

                for desc
                in cursor.description

            ]


            analyst_details = []


            for row in analyst_rows:

                item = dict(

                    zip(
                        analyst_columns,
                        row
                    )

                )


                normalized = {

                    key.lower():
                        value

                    for key, value
                    in item.items()

                }


                normalized[
                    "start_time_ist"
                ] = to_ist_iso(

                    normalized.get(
                        "start_time"
                    )

                )


                normalized[
                    "end_time_ist"
                ] = to_ist_iso(

                    normalized.get(
                        "end_time"
                    )

                )


                analyst_details.append(
                    normalized
                )


            result[
                "cortex_analyst"
            ][
                "recent_hourly_records"
            ] = analyst_details


        except Exception as analyst_error:

            print(
                "TEMP USAGE: "
                "CORTEX_ANALYST_USAGE_HISTORY "
                f"lookup failed: {analyst_error}"
            )

            result[
                "cortex_analyst"
            ][
                "error"
            ] = str(
                analyst_error
            )


        # ==================================================
        # 5. Calculate identifiable total
        # ==================================================
        #
        # This currently includes:
        #
        #   Cortex AI Function credits
        #
        #       +
        #
        #   Warehouse query credits
        #
        # Cortex Analyst is intentionally NOT automatically
        # added here because its usage view is hourly
        # aggregated and cannot safely be mapped to one
        # request when other Analyst traffic exists.
        #
        # ==================================================

        identifiable_total = (

            cortex_credits

            +

            warehouse_credits

        )


        result[
            "total_identifiable_credits"
        ] = identifiable_total


        # --------------------------------------------------
        # Determine status
        # --------------------------------------------------

        if (

            cortex_rows

            or

            warehouse_rows

        ):

            result[
                "status"
            ] = (
                "usage_found"
            )

        elif (

            result[
                "warehouse"
            ][
                "immediate_confirmation"
            ]

        ):

            # The query ran (confirmed via QUERY_HISTORY)
            # but ACCOUNT_USAGE attribution has not landed
            # yet. This is expected latency, not a failure.

            result[
                "status"
            ] = (
                "query_ran_awaiting_credit_attribution"
            )

        else:

            result[
                "status"
            ] = (
                "usage_not_available_yet"
            )


        return result


    except Exception as usage_error:

        result[
            "status"
        ] = (
            "usage_lookup_failed"
        )

        result[
            "error"
        ] = str(
            usage_error
        )

        return result


    finally:

        if cursor is not None:

            cursor.close()


        if conn is not None:

            conn.close()




#####aaaddd
# ==========================================================
# PERSISTENT USAGE HISTORY LOGGER
# ==========================================================

def log_usage_history(
    usage_result,
    question,
    usage_id
):
    """
    Persist token / credit usage for a /chat request.

    Only historical usage information is stored.

    The user's original question is stored exactly as received
    from request.question.

    The generated answer is intentionally NOT stored.

    CREATED_AT is generated in Indian Standard Time (IST).
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()

        cursor = conn.cursor()

        # --------------------------------------------------
        # Extract usage information
        # --------------------------------------------------

        cortex_ai = usage_result.get(
            "cortex_ai_functions",
            {}
        )

        warehouse = usage_result.get(
            "warehouse",
            {}
        )

        cortex_analyst = usage_result.get(
            "cortex_analyst",
            {}
        )

        # --------------------------------------------------
        # Values to persist
        # --------------------------------------------------

        input_tokens = cortex_ai.get(
            "input_tokens",
            0
        ) or 0

        output_tokens = cortex_ai.get(
            "output_tokens",
            0
        ) or 0

        total_tokens = cortex_ai.get(
            "total_tokens",
            0
        ) or 0

        cortex_ai_credits = cortex_ai.get(
            "credits",
            0.0
        ) or 0.0

        warehouse_credits = warehouse.get(
            "credits",
            0.0
        ) or 0.0

        total_identifiable_credits = (
            usage_result.get(
                "total_identifiable_credits",
                0.0
            )
            or 0.0
        )

        cortex_analyst_credits = (
            cortex_analyst.get(
                "credits"
            )
        )

        request_count = (
            cortex_analyst.get(
                "request_count"
            )
        )

        status = usage_result.get(
            "status"
        )

        # --------------------------------------------------
        # CREATED_AT
        #
        # Store the timestamp as timezone-aware IST.
        # --------------------------------------------------

        created_at = datetime.datetime.now(
            IST_OFFSET
        )

        # --------------------------------------------------
        # Insert historical usage record
        #
        # IMPORTANT:
        #
        # No answer is stored.
        #
        # --------------------------------------------------

        insert_sql = f"""

            INSERT INTO {USAGE_HISTORY_TABLE} (

                USAGE_ID,
                QUESTION,

                INPUT_TOKENS,
                OUTPUT_TOKENS,
                TOTAL_TOKENS,

                CORTEX_AI_CREDITS,
                WAREHOUSE_CREDITS,
                TOTAL_IDENTIFIABLE_CREDITS,

                STATUS,
                CREATED_AT

            )

            SELECT

                %s,
                %s,

                %s,
                %s,
                %s,

                %s,
                %s,
                %s,

                %s,
                %s

            """

        cursor.execute(
            insert_sql,
            (
                usage_id,
                question,

                int(input_tokens),
                int(output_tokens),
                int(total_tokens),

                float(cortex_ai_credits),
                float(warehouse_credits),
                float(total_identifiable_credits),

                status,
                created_at
            )
        )

        conn.commit()

        print(
            "========================================"
        )

        print(
            "USAGE HISTORY LOGGED SUCCESSFULLY"
        )

        print(
            "========================================"
        )

        print(
            f"Usage ID: {usage_id}"
        )

        print(
            f"Question: {question}"
        )

        print(
            f"Input tokens: {input_tokens}"
        )

        print(
            f"Output tokens: {output_tokens}"
        )

        print(
            f"Total tokens: {total_tokens}"
        )

        print(
            f"Cortex AI credits: {cortex_ai_credits}"
        )

        print(
            f"Warehouse credits: {warehouse_credits}"
        )

        print(
            f"Total identifiable credits: "
            f"{total_identifiable_credits}"
        )

        print(
            f"Created at IST: "
            f"{created_at.isoformat()}"
        )

        print(
            "========================================"
        )

        return True

    except Exception as usage_log_error:

        print(
            "========================================"
        )

        print(
            "USAGE HISTORY LOGGING FAILED"
        )

        print(
            "========================================"
        )

        print(
            f"Error type: "
            f"{type(usage_log_error).__name__}"
        )

        print(
            f"Error message: "
            f"{str(usage_log_error)}"
        )

        import traceback

        traceback.print_exc()

        print(
            "========================================"
        )

        # --------------------------------------------------
        # IMPORTANT:
        #
        # Usage logging must never break /chat.
        # --------------------------------------------------

        return False

    finally:

        if cursor is not None:

            cursor.close()

        if conn is not None:

            conn.close()
            
    
# ==========================================================
# USAGE HISTORY POLLING
# ==========================================================

def wait_for_usage_history(
    usage_id,
    max_wait_seconds=30,
    poll_interval_seconds=5
):
    """
    Poll Snowflake usage history for a short period so that
    ACCOUNT_USAGE attribution has time to appear.

    This prevents us from immediately logging zero credits/tokens
    simply because Snowflake usage history has not updated yet.

    The function returns the latest usage result available.

    If usage is still unavailable after the polling window,
    the final result is returned with its current status.
    """

    start_time = datetime.datetime.now(
        datetime.timezone.utc
    )

    latest_result = None

    while True:

        try:

            latest_result = query_temporary_usage(
                usage_id
            )

        except Exception as usage_error:

            print(
                "========================================"
            )

            print(
                "USAGE HISTORY POLLING ERROR"
            )

            print(
                f"Error type: "
                f"{type(usage_error).__name__}"
            )

            print(
                f"Error message: "
                f"{str(usage_error)}"
            )

            print(
                "========================================"
            )

            latest_result = None


        # --------------------------------------------------
        # Check whether actual usage has appeared.
        #
        # Cortex AI function usage or warehouse attribution
        # means we have identifiable usage.
        # --------------------------------------------------

        if latest_result:

            cortex_ai = latest_result.get(
                "cortex_ai_functions",
                {}
            )

            warehouse = latest_result.get(
                "warehouse",
                {}
            )

            cortex_rows = (
                latest_result.get(
                    "details",
                    {}
                ).get(
                    "cortex_ai_function_rows",
                    []
                )
            )

            warehouse_rows = (
                latest_result.get(
                    "details",
                    {}
                ).get(
                    "warehouse_query_rows",
                    []
                )
            )

            has_cortex_usage = bool(
                cortex_rows
            )

            has_warehouse_usage = bool(
                warehouse_rows
            )

            has_identifiable_credits = (

                float(
                    cortex_ai.get(
                        "credits",
                        0
                    )
                    or 0
                )

                > 0

                or

                float(
                    warehouse.get(
                        "credits",
                        0
                    )
                    or 0
                )

                > 0

            )

            has_tokens = (

                int(
                    cortex_ai.get(
                        "total_tokens",
                        0
                    )
                    or 0
                )

                > 0

            )


            if (

                has_cortex_usage

                or

                has_warehouse_usage

                or

                has_identifiable_credits

                or

                has_tokens

            ):

                print(
                    "========================================"
                )

                print(
                    "USAGE HISTORY FOUND"
                )

                print(
                    f"Usage ID: {usage_id}"
                )

                print(
                    f"Status: "
                    f"{latest_result.get('status')}"
                )

                print(
                    "========================================"
                )

                return latest_result


        # --------------------------------------------------
        # Check polling timeout
        # --------------------------------------------------

        elapsed_seconds = (

            datetime.datetime.now(
                datetime.timezone.utc
            )

            -

            start_time

        ).total_seconds()


        if elapsed_seconds >= max_wait_seconds:

            print(
                "========================================"
            )

            print(
                "USAGE HISTORY POLLING TIMEOUT"
            )

            print(
                f"Usage ID: {usage_id}"
            )

            print(
                f"Waited approximately "
                f"{int(elapsed_seconds)} seconds."
            )

            print(
                "Returning latest available usage result."
            )

            print(
                "========================================"
            )

            return latest_result


        print(
            "Usage history not available yet. "
            f"Retrying in {poll_interval_seconds} seconds..."
        )


        import time

        time.sleep(
            poll_interval_seconds
        )          
            
# ==========================================================
# TEMPORARY USAGE TRACKING - END
# ==========================================================


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
    table_schema: list,
    usage_tracker=None,
    usage_id=None
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

        # ==================================================
        # TEMPORARY USAGE TRACKING
        # ==================================================

        if usage_id:

            set_temporary_query_tag(

                cursor,

                usage_id

            )


        sql = """

        SELECT AI_COMPLETE(

            %s,

            %s,

            {'temperature': 0, 'top_p': 0},

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


        # ==================================================
        # TEMPORARY USAGE TRACKING
        # ==================================================

        execute_with_temporary_tracking(

            cursor,

            sql,

            (
                model,
                prompt
            ),

            usage_tracker=usage_tracker,

            usage_label="AI_COMPLETE_NORMAL"

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
    rows: list,
    usage_tracker=None,
    usage_id=None
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

        # ==================================================
        # TEMPORARY USAGE TRACKING
        # ==================================================

        if usage_id:

            set_temporary_query_tag(

                cursor,

                usage_id

            )


        sql = """

        SELECT AI_COMPLETE(

            %s,

            %s,

            {'temperature': 0, 'top_p': 0},

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


        # ==================================================
        # TEMPORARY USAGE TRACKING
        # ==================================================

        execute_with_temporary_tracking(

            cursor,

            sql,

            (
                model,
                prompt
            ),

            usage_tracker=usage_tracker,

            usage_label="AI_COMPLETE_RCA"

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
    # TEMPORARY USAGE TRACKING - START
    # ======================================================
    #
    # This ID exists only for the temporary usage test.
    #
    # It allows us to correlate:
    #
    #   generated SQL
    #   AI_COMPLETE
    #   RCA AI_COMPLETE
    #
    # using Snowflake QUERY_TAG.
    #
    # ======================================================

    temporary_usage_id = (
        create_temporary_usage_id()
    )

    temporary_usage_tracker = []


    print("========================================")
    print("TEMPORARY USAGE TRACKING")
    print("========================================")

    print(
        f"Temporary usage ID: "
        f"{temporary_usage_id}"
    )

    # ======================================================
    # TEMPORARY USAGE TRACKING - END
    # ======================================================


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

        conn = None

        cursor = None


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


            # ==================================================
            # TEMPORARY USAGE TRACKING
            # ==================================================
            #
            # The generated Cortex Analyst SQL is tagged so
            # warehouse usage can later be attributed to this
            # exact /chat request.
            #
            # ==================================================

            set_temporary_query_tag(

                cursor,

                temporary_usage_id

            )


            execute_with_temporary_tracking(

                cursor,

                generated_sql,

                usage_tracker=
                    temporary_usage_tracker,

                usage_label=
                    "CORTEX_GENERATED_SQL"

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

            if cursor is not None:

                cursor.close()


            if conn is not None:

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

                table_schema=table_schema,

                # ==========================================
                # TEMPORARY USAGE TRACKING
                # ==========================================

                usage_tracker=
                    temporary_usage_tracker,

                usage_id=
                    temporary_usage_id

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
    # We only execute RCA for diagnostic questions.
    #
    # rca_status distinguishes the four possible outcomes so
    # the frontend can render the correct state instead of
    # silently showing nothing:
    #
    #   "not_diagnostic"        -> question wasn't diagnostic
    #   "insufficient_evidence" -> diagnostic, but not enough
    #                               rows/columns for RCA
    #   "success"                -> RCA generated
    #   "failed"                 -> RCA was attempted but the
    #                               AI_COMPLETE call errored
    #
    # ======================================================

    diagnostic = is_diagnostic_question(
        request.question
    )

    rca_result = None

    rca_status = "not_diagnostic"

    rca_error = None

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

                        rows=rows,

                        usage_tracker=
                            temporary_usage_tracker,

                        usage_id=
                            temporary_usage_id

                    )

                    rca_status = "success"

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

                rca_result = None

                rca_status = "failed"

                rca_error = (

                    f"{type(rca_err).__name__}: "
                    f"{str(rca_err)}"

                )


        else:

            rca_status = "insufficient_evidence"

            print(
                "RCA skipped because evidence is insufficient."
            )


    else:

        print(
            "RCA skipped because question is not diagnostic."
        )


    # ======================================================
    # 8. PERSIST USAGE HISTORY
    # ======================================================
    #
    # Poll Snowflake usage history before writing the
    # historical record.
    #
    # This gives ACCOUNT_USAGE time to expose the
    # Cortex / warehouse usage generated by this request.
    #
    # The original user question is stored.
    #
    # The AI answer is NOT stored.
    #
    # ======================================================

    try:

        usage_result = wait_for_usage_history(
            temporary_usage_id
        )


        if usage_result is None:

            print(
                "No usage result available for "
                f"{temporary_usage_id}"
            )

        else:

            log_usage_history(

                usage_result=usage_result,

                question=request.question,

                usage_id=temporary_usage_id

            )


    except Exception as usage_history_error:

        print(
            "========================================"
        )

        print(
            "PERSISTENT USAGE HISTORY FAILED"
        )

        print(
            "========================================"
        )

        print(
            f"Error type: "
            f"{type(usage_history_error).__name__}"
        )

        print(
            f"Error message: "
            f"{str(usage_history_error)}"
        )

        import traceback

        traceback.print_exc()

        print(
            "========================================"
        )


    # ======================================================
    # 9. FINAL RESPONSE TO POWER BI
    # ======================================================

    return {
        
        # ==================================================
        # TEMPORARY USAGE TRACKING
        # ==================================================
        #
        # This does NOT change the existing Power BI behavior.
        #
        # It simply adds temporary diagnostic information.
        #
        # ==================================================

        "temporary_usage": {

            "usage_id":
                temporary_usage_id,

            "query_ids":
                temporary_usage_tracker,

            "message":
                (
                    "Temporary diagnostic tracking only. "
                    "Use GET /temporary-usage/{usage_id} "
                    "after Snowflake usage history has "
                    "updated."
                )

        },


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
            rca_result,

        "rca_status":
            rca_status,

        "rca_error":
            rca_error

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


# ==========================================================
# TEMPORARY USAGE INSPECTION ENDPOINT - START
# ==========================================================
#
# Call:
#
#   GET /temporary-usage/{usage_id}
#
# Example:
#
#   GET /temporary-usage/SNOWI_TEMP_USAGE_xxxxx
#
# This endpoint is temporary and can later be removed
# together with the other TEMPORARY USAGE sections.
#
# ==========================================================

@app.get("/temporary-usage/{usage_id}")
def temporary_usage(usage_id: str):

    if not usage_id.startswith(
        f"{TEMP_USAGE_TAG_PREFIX}_"
    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "Invalid temporary usage ID."
            )

        )


    print("========================================")
    print("TEMPORARY USAGE LOOKUP")
    print("========================================")

    print(
        f"Usage ID: {usage_id}"
    )


    result = query_temporary_usage(
        usage_id
    )


    print(
        json.dumps(
            result,
            default=str,
            indent=2
        )
    )


    # ======================================================
    # UPDATE PERSISTENT USAGE HISTORY
    # ======================================================

    try:

        cortex_ai = result.get(
            "cortex_ai_functions",
            {}
        )

        warehouse = result.get(
            "warehouse",
            {}
        )

        input_tokens = int(
            cortex_ai.get(
                "input_tokens",
                0
            ) or 0
        )

        output_tokens = int(
            cortex_ai.get(
                "output_tokens",
                0
            ) or 0
        )

        total_tokens = int(
            cortex_ai.get(
                "total_tokens",
                0
            ) or 0
        )

        cortex_ai_credits = float(
            cortex_ai.get(
                "credits",
                0
            ) or 0
        )

        warehouse_credits = float(
            warehouse.get(
                "credits",
                0
            ) or 0
        )

        total_identifiable_credits = float(
            result.get(
                "total_identifiable_credits",
                0
            ) or 0
        )

        status = result.get(
            "status"
        )


        conn = None
        cursor = None

        try:

            conn = get_connection()

            cursor = conn.cursor()


            update_sql = """
            UPDATE CPG.IBP_SEMANTIC.CORTEX_USAGE_HISTORY
            SET
                INPUT_TOKENS = %s,
                OUTPUT_TOKENS = %s,
                TOTAL_TOKENS = %s,
                CORTEX_AI_CREDITS = %s,
                WAREHOUSE_CREDITS = %s,
                TOTAL_IDENTIFIABLE_CREDITS = %s,
                STATUS = %s
            WHERE USAGE_ID = %s
            """


            cursor.execute(
                update_sql,
                (
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    cortex_ai_credits,
                    warehouse_credits,
                    total_identifiable_credits,
                    status,
                    usage_id
                )
            )


            conn.commit()


            print(
                "Usage history table updated successfully."
            )


        finally:

            if cursor is not None:
                cursor.close()

            if conn is not None:
                conn.close()


    except Exception as usage_update_error:

        print("========================================")
        print("USAGE HISTORY TABLE UPDATE FAILED")
        print("========================================")

        print(
            f"Error type: "
            f"{type(usage_update_error).__name__}"
        )

        print(
            f"Error message: "
            f"{str(usage_update_error)}"
        )

        import traceback
        traceback.print_exc()

        print("========================================")

        # IMPORTANT:
        # Do not fail the existing API because the
        # historical usage update failed.


    print("========================================")


    return result


# ==========================================================
# TEMPORARY USAGE INSPECTION ENDPOINT - END
# ==========================================================