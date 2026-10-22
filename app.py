
import os
import io
import time
import sqlite3
import wave
from datetime import datetime

import streamlit as st
from streamlit_mic_recorder import mic_recorder
from google import genai
from google.genai import types


# =========================================================
# 1. CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Sankar AI Voice Sales Bot",
    page_icon="🎙️",
    layout="wide",
)

# Use the model you configured for your Gemini API.
MODEL_NAME = "gemini-3.6-flash"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sales_bot.db")


# =========================================================
# 2. DATABASE
# =========================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT DEFAULT '',
            transcript TEXT DEFAULT '',
            ai_response TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            status TEXT DEFAULT 'New',
            created_at TEXT DEFAULT ''
        )
    """)

    existing_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(calls)"
        ).fetchall()
    }

    migrations = {
        "customer_name": "TEXT DEFAULT ''",
        "transcript": "TEXT DEFAULT ''",
        "ai_response": "TEXT DEFAULT ''",
        "summary": "TEXT DEFAULT ''",
        "status": "TEXT DEFAULT 'New'",
        "created_at": "TEXT DEFAULT ''",
    }

    for column, column_type in migrations.items():
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE calls ADD COLUMN "
                f"{column} {column_type}"
            )

    conn.commit()
    conn.close()


def save_call(customer, transcript, reply, summary, status):
    conn = get_connection()

    conn.execute(
        """
        INSERT INTO calls
        (
            customer_name,
            transcript,
            ai_response,
            summary,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            customer,
            transcript,
            reply,
            summary,
            status,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )

    conn.commit()
    conn.close()


def get_call_history():
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT rowid AS _rowid, *
        FROM calls
        ORDER BY rowid DESC
        """
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def delete_call(row_id):
    conn = get_connection()

    conn.execute(
        "DELETE FROM calls WHERE rowid = ?",
        (row_id,),
    )

    conn.commit()
    conn.close()


# =========================================================
# 3. SESSION STATE
# =========================================================

def initialize_session():
    defaults = {
        "transcript": "",
        "ai_response": "",
        "summary": "",
        "customer_name": "",
        "call_status": "New",
        "error_message": "",
        "success_message": "",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# =========================================================
# 4. GEMINI API
# =========================================================

def get_api_key():
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")

        if key:
            return str(key).strip()

    except Exception:
        pass

    return os.environ.get("GEMINI_API_KEY", "").strip()


def get_client():
    api_key = get_api_key()

    if not api_key:
        raise RuntimeError(
            "Gemini API key not found. Add GEMINI_API_KEY "
            "to .streamlit/secrets.toml."
        )

    return genai.Client(api_key=api_key)


def is_temporary_error(exc):
    message = str(exc).lower()

    markers = (
        "503",
        "500",
        "429",
        "502",
        "504",
        "unavailable",
        "resource_exhausted",
        "too many requests",
        "internal server error",
        "service unavailable",
        "high demand",
    )

    return any(marker in message for marker in markers)


def generate_content_with_retry(client, contents):
    """
    Retry temporary Gemini failures up to three times.
    Wait 2 seconds and then 4 seconds between retries.
    """

    last_error = None

    for attempt in range(3):
        try:
            return client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
            )

        except Exception as exc:
            last_error = exc

            if not is_temporary_error(exc):
                raise

            if attempt < 2:
                time.sleep(2 ** (attempt + 1))

    raise RuntimeError(
        "Gemini is still unavailable after three attempts. "
        "Check your model access and API quota, then try again. "
        f"Details: {last_error}"
    )


def generate_text(prompt):
    client = get_client()

    response = generate_content_with_retry(
        client,
        prompt,
    )

    result = response.text

    if not result or not result.strip():
        raise RuntimeError(
            "Gemini returned an empty response. Please try again."
        )

    return result.strip()


# =========================================================
# 5. AUDIO VALIDATION
# =========================================================

def validate_audio(audio_bytes):
    if not audio_bytes:
        raise ValueError("No audio data was received.")

    if (
        len(audio_bytes) < 12
        or audio_bytes[:4] != b"RIFF"
        or audio_bytes[8:12] != b"WAVE"
    ):
        raise ValueError(
            "Invalid WAV recording. Please record again."
        )

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            if wav_file.getnframes() <= 0:
                raise ValueError(
                    "The recording contains no audio frames."
                )

    except wave.Error as exc:
        raise ValueError(
            f"Unable to read the WAV recording: {exc}"
        ) from exc

    return audio_bytes


# =========================================================
# 6. TRANSCRIBE AND TRANSLATE TO ENGLISH
# =========================================================

def transcribe_audio(audio_bytes):
    audio_bytes = validate_audio(audio_bytes)
    client = get_client()

    prompt = """
You are an accurate speech recognition and translation assistant.

Listen to the attached customer audio.

STRICT REQUIREMENTS:
1. Return the customer's message in ENGLISH ONLY.
2. Translate Hindi, Telugu, or any other spoken language into English.
3. If the customer speaks English, transcribe it accurately.
4. Preserve names, numbers, amounts, and important details.
5. Do not invent words or add information.
6. If a phrase is unclear, mark it as [unclear].
7. Do not summarize the message.
8. Do not answer the customer.
9. Return only the English transcript.
"""

    audio_part = types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/wav",
    )

    response = generate_content_with_retry(
        client,
        [prompt, audio_part],
    )

    transcript = response.text

    if not transcript or not transcript.strip():
        raise RuntimeError(
            "No transcript was returned. Please record again."
        )

    return transcript.strip()


# =========================================================
# 7. GENERATE A RELEVANT SALES REPLY
# =========================================================

def generate_sales_reply(transcript, product, goal):
    if not transcript.strip():
        raise ValueError(
            "Please enter a customer transcript first."
        )

    prompt = f"""
You are a professional, helpful customer support and sales assistant.

You MUST respond in ENGLISH ONLY.

Product or service: {product}
Sales objective: {goal}

CUSTOMER'S TRANSCRIPT:
"{transcript}"

FOLLOW THESE RULES:

1. Answer the customer's actual question first.
2. Never replace the question with a different question.
3. Do not assume the customer is asking about CRM unless their message
   mentions CRM or the context clearly establishes it.
4. Do not assume they are asking about a loan, bank, or Kisan Vikas Patra
   unless their message actually asks about that subject.
5. Do not claim the customer has contacted a CRM provider.
6. If the customer asks what CRM does, explain that CRM helps businesses
   manage customer details, track leads and sales opportunities, record
   interactions, and schedule follow-ups.
7. If the customer asks an unrelated question, answer it appropriately
   without forcing a CRM sales pitch.
8. If the message is unclear, ask one short clarifying question.
9. Never invent product features, prices, discounts, loan rules, or
   eligibility information.
10. Be friendly, concise, and natural for a phone conversation.
11. Usually respond in 2-5 sentences.
12. Return only the words the sales representative should say.

EXAMPLE:

Customer: What does a CRM system do?

Response:
"A CRM system helps businesses manage customer information, track sales
leads, record customer interactions, and schedule follow-ups in one
place. This helps teams stay organized and build stronger customer
relationships. Would you like to know how it could help your business?"

Now answer the customer's actual message.
"""

    return generate_text(prompt)


# =========================================================
# 8. GENERATE CALL SUMMARY
# =========================================================

def create_summary(transcript, reply):
    if not transcript.strip():
        raise ValueError(
            "Please enter a customer transcript first."
        )

    prompt = f"""
Create a concise, professional sales call report in ENGLISH ONLY.

Customer transcript:
{transcript}

Sales response:
{reply if reply.strip() else "No response generated yet."}

Use these headings:

1. Conversation Summary
2. Customer Needs
3. Questions or Concerns
4. Suggested Follow-up
5. Call Outcome

Requirements:
- Use only facts supported by the conversation.
- Do not invent customer information.
- Write "Not specified" if details are unavailable.
- Return only the report.
"""

    return generate_text(prompt)


# =========================================================
# 9. STREAMLIT CALLBACKS
# =========================================================

def generate_reply_callback(product, goal):
    """
    Called before Streamlit recreates the widgets.
    It is safe to update the ai_response widget value here.
    """

    transcript = st.session_state.get(
        "transcript", ""
    ).strip()

    st.session_state["error_message"] = ""
    st.session_state["success_message"] = ""

    if not transcript:
        st.session_state["error_message"] = (
            "Please enter the customer transcript first."
        )
        return

    try:
        reply = generate_sales_reply(
            transcript,
            product,
            goal,
        )

        st.session_state["ai_response"] = reply
        st.session_state["success_message"] = (
            "Sales reply generated successfully in English."
        )

    except Exception as exc:
        st.session_state["error_message"] = (
            f"Sales reply failed: {exc}"
        )


def generate_summary_callback():
    transcript = st.session_state.get(
        "transcript", ""
    ).strip()

    reply = st.session_state.get(
        "ai_response", ""
    ).strip()

    st.session_state["error_message"] = ""
    st.session_state["success_message"] = ""

    if not transcript:
        st.session_state["error_message"] = (
            "Please enter the customer transcript first."
        )
        return

    try:
        st.session_state["summary"] = create_summary(
            transcript,
            reply,
        )

        st.session_state["success_message"] = (
            "Call summary generated successfully."
        )

    except Exception as exc:
        st.session_state["error_message"] = (
            f"Summary generation failed: {exc}"
        )


def clear_current_call():
    st.session_state["transcript"] = ""
    st.session_state["ai_response"] = ""
    st.session_state["summary"] = ""
    st.session_state["error_message"] = ""
    st.session_state["success_message"] = ""


# =========================================================
# 10. INITIALIZE APPLICATION
# =========================================================

init_db()
initialize_session()

st.title("🎙️ Sankar AI Voice Sales Bot")

st.write(
    "Record customer conversations, get English transcripts, "
    "generate relevant sales responses, and save call records."
)

api_key = get_api_key()

if api_key:
    st.success("Gemini API key detected.")
else:
    st.error(
        "Gemini API key not found. Check "
        ".streamlit/secrets.toml."
    )


# =========================================================
# 11. SIDEBAR
# =========================================================

with st.sidebar:
    st.header("⚙️ Sales Settings")

    st.text_input(
        "Customer name",
        key="customer_name",
        placeholder="Enter customer name",
    )

    product_name = st.text_input(
        "Product or service",
        value="CRM Software",
        key="product_name",
    )

    sales_goal = st.selectbox(
        "Sales objective",
        [
            "Answer customer questions",
            "Understand customer needs",
            "Explain product benefits",
            "Handle customer objections",
            "Schedule a follow-up",
            "Close a sale",
        ],
        key="sales_goal",
    )

    st.caption(f"Gemini model: {MODEL_NAME}")
    st.caption("Transcripts, replies, and summaries use English.")


# =========================================================
# 12. TABS
# =========================================================

call_tab, history_tab = st.tabs(
    ["🎙️ Voice Sales Call", "📋 Call History"]
)


# =========================================================
# 13. VOICE SALES CALL
# =========================================================

with call_tab:

    st.header("1. Record Customer Audio")

    st.write(
        "Click Start Recording, speak clearly, click Stop Recording, "
        "and then click Process Recording."
    )

    audio = mic_recorder(
        start_prompt="🔴 Start Recording",
        stop_prompt="⏹️ Stop Recording",
        just_once=False,
        use_container_width=True,
        format="wav",
        key="customer_mic_recorder",
    )

    audio_bytes = None

    if isinstance(audio, dict):
        audio_bytes = audio.get("bytes")

    with st.expander("Recorder diagnostic"):
        st.write(
            "Audio object received:",
            audio is not None,
        )

        st.write(
            "Returned keys:",
            list(audio.keys()) if isinstance(audio, dict) else [],
        )

        st.write(
            "Audio bytes received:",
            len(audio_bytes) if audio_bytes else 0,
        )

    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")
        st.success("Audio received successfully.")

    process_col, clear_col = st.columns(2)

    with process_col:
        process_clicked = st.button(
            "✨ Process Recording",
            type="primary",
            use_container_width=True,
            disabled=not bool(api_key),
            key="process_recording_button",
        )

    with clear_col:
        st.button(
            "🧹 Clear Current Call",
            use_container_width=True,
            key="clear_call_button",
            on_click=clear_current_call,
        )

    # -----------------------------------------------------
    # PROCESS AUDIO
    # This runs before transcript and reply widgets are created.
    # -----------------------------------------------------

    if process_clicked:

        st.session_state["error_message"] = ""
        st.session_state["success_message"] = ""

        if not audio_bytes:
            st.session_state["error_message"] = (
                "No audio received. Record your voice and try again."
            )

        else:
            try:
                with st.spinner(
                    "Transcribing and translating to English..."
                ):
                    transcript = transcribe_audio(audio_bytes)

                # These assignments occur before the text widgets
                # are created on this rerun.
                st.session_state["transcript"] = transcript
                st.session_state["ai_response"] = ""
                st.session_state["summary"] = ""

                st.session_state["success_message"] = (
                    "English transcription completed."
                )

            except Exception as exc:
                st.session_state["error_message"] = (
                    f"Transcription failed: {exc}"
                )

            if st.session_state["transcript"].strip():
                try:
                    with st.spinner(
                        "Generating a relevant English sales reply..."
                    ):
                        reply = generate_sales_reply(
                            st.session_state["transcript"],
                            product_name,
                            sales_goal,
                        )

                    # The reply widget has not been created yet.
                    st.session_state["ai_response"] = reply

                    st.session_state["success_message"] += (
                        " Sales reply generated."
                    )

                except Exception as exc:
                    st.session_state["error_message"] += (
                        f"\nSales reply failed: {exc}"
                    )

    # Show messages from processing or callbacks.
    if st.session_state.get("success_message"):
        st.success(st.session_state["success_message"])

    if st.session_state.get("error_message"):
        st.error(st.session_state["error_message"])

    st.divider()

    # -----------------------------------------------------
    # TRANSCRIPT WIDGET
    # -----------------------------------------------------

    st.header("2. Customer Transcript")

    st.caption(
        "Speech is transcribed or translated into English. "
        "You can edit the transcript manually."
    )

    st.text_area(
        "Customer transcript (English)",
        key="transcript",
        height=160,
        placeholder="Example: What does a CRM system do?",
    )

    # -----------------------------------------------------
    # SALES REPLY WIDGET
    # -----------------------------------------------------

    st.header("3. AI-Generated Sales Reply")

    st.caption(
        "The reply should answer the customer's actual question "
        "before introducing a relevant product."
    )

    st.text_area(
        "Suggested sales response (English)",
        key="ai_response",
        height=160,
        placeholder="The suggested English response will appear here.",
    )

    reply_col, summary_col = st.columns(2)

    with reply_col:
        st.button(
            "🔄 Generate Sales Reply",
            use_container_width=True,
            disabled=not bool(api_key),
            key="generate_sales_reply_button",
            on_click=generate_reply_callback,
            args=(product_name, sales_goal),
        )

    with summary_col:
        st.button(
            "📝 Generate Call Summary",
            use_container_width=True,
            disabled=not bool(api_key),
            key="generate_call_summary_button",
            on_click=generate_summary_callback,
        )

    # Display callback feedback after the buttons.
    if st.session_state.get("success_message"):
        st.success(st.session_state["success_message"])

    if st.session_state.get("error_message"):
        st.error(st.session_state["error_message"])

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    if st.session_state.get("summary"):
        st.header("4. Call Summary")

        st.markdown(st.session_state["summary"])

        st.download_button(
            "⬇️ Download Summary",
            data=st.session_state["summary"],
            file_name="sales_call_summary.txt",
            mime="text/plain",
            key="current_summary_download",
        )

    st.divider()

    # -----------------------------------------------------
    # SAVE CALL
    # -----------------------------------------------------

    st.header("5. Save Call Record")

    st.selectbox(
        "Call status",
        [
            "New",
            "Interested",
            "Follow-up",
            "Converted",
            "Lost",
        ],
        key="call_status",
    )

    if st.button(
        "💾 Save Call to History",
        type="primary",
        use_container_width=True,
        key="save_call_button",
    ):
        transcript_to_save = st.session_state[
            "transcript"
        ].strip()

        reply_to_save = st.session_state[
            "ai_response"
        ].strip()

        summary_to_save = st.session_state[
            "summary"
        ].strip()

        if not transcript_to_save:
            st.error(
                "No transcript to save. Process a recording or "
                "enter the customer's message manually."
            )

        else:
            if not summary_to_save and api_key:
                try:
                    with st.spinner("Creating call summary..."):
                        summary_to_save = create_summary(
                            transcript_to_save,
                            reply_to_save,
                        )

                    st.session_state["summary"] = summary_to_save

                except Exception as exc:
                    st.warning(
                        "The call will still be saved, but the "
                        f"summary could not be generated: {exc}"
                    )

            try:
                save_call(
                    customer=st.session_state[
                        "customer_name"
                    ].strip(),
                    transcript=transcript_to_save,
                    reply=reply_to_save,
                    summary=summary_to_save,
                    status=st.session_state["call_status"],
                )

                st.success(
                    "Call saved successfully! Open the Call History tab."
                )

            except Exception as exc:
                st.error(f"Unable to save call: {exc}")


# =========================================================
# 14. CALL HISTORY
# =========================================================

with history_tab:

    st.header("📋 Saved Customer Calls")

    history = get_call_history()

    if not history:
        st.info("No saved calls yet.")

    else:
        st.write(f"**Total saved calls:** {len(history)}")

        for index, call in enumerate(history):

            customer = (
                call.get("customer_name") or "Unnamed Customer"
            )

            created = (
                call.get("created_at") or "Date unavailable"
            )

            status = call.get("status") or "New"
            row_id = call["_rowid"]

            unique_key = f"history_{row_id}_{index}"

            with st.expander(
                f"📞 {customer} | {created} | {status} "
                f"| Record {index + 1}"
            ):

                st.markdown("**Customer Transcript**")
                st.write(
                    call.get("transcript") or "No transcript saved."
                )

                st.markdown("**AI Sales Reply**")
                st.write(
                    call.get("ai_response") or "No reply saved."
                )

                st.markdown("**Call Summary**")
                summary_text = call.get("summary") or ""

                st.write(
                    summary_text or "No summary saved."
                )

                if summary_text:
                    st.download_button(
                        "⬇️ Download Summary",
                        data=summary_text,
                        file_name=f"call_{row_id}_summary.txt",
                        mime="text/plain",
                        key=f"{unique_key}_download",
                    )

                if st.button(
                    "🗑️ Delete This Call",
                    key=f"{unique_key}_delete",
                ):
                    delete_call(row_id)
                    st.success("Call deleted.")
                    st.rerun()


# =========================================================
# 15. FOOTER
# =========================================================

st.divider()

st.caption(
    "Sankar AI Voice Sales Bot | Streamlit • Gemini • SQLite"
)
