# Sankar Group – AI Voice Sales Bot

A beginner-friendly Streamlit demo that supports turn-based voice conversation, live transcript, call controls, recording consent, WAV playback/download, AI-generated summary, sales status, and SQLite call history.

## Features
- Actual microphone recording from the browser (record a turn, stop, and send it).
- Gemini interprets the audio and generates the next sales response.
- Spoken AI response via Gemini TTS, with Google Text-to-Speech fallback.
- Operator consent checkbox before a call starts.
- Conversation transcript shown in the UI.
- Call summary, customer requirements, objections, next steps, and one of six statuses.
- WAV recording assembled from the customer's recorded turns and the bot's spoken replies.
- SQLite history for completed calls.

## Important scope note
This is a browser-based, turn-by-turn voice demo, not a telephone/PSTN dialer or low-latency streaming voice agent. The browser captures a customer utterance, sends it to the backend, and the bot responds. Test microphone permission and audio output in the target browser. Local SQLite files and recordings on Streamlit Community Cloud may be ephemeral across app rebuilds/restarts; use managed storage for production persistence.

## 1. Requirements
- Python 3.11 recommended
- VS Code
- A Gemini API key from Google AI Studio
- Chrome or Edge with microphone permission
- Internet connection

## 2. Setup in VS Code (Windows PowerShell)
Open this folder in VS Code, then run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run this once in the current terminal:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Create `.streamlit/secrets.toml` (copy from `.streamlit/secrets.toml.example`) and replace the placeholder with your key:

```toml
GEMINI_API_KEY = "your-real-key"
```

Do not commit the real key to GitHub. The `.gitignore` excludes this file.

Start the app:
```powershell
streamlit run app.py
```

## 3. Test flow
1. Open the app in Chrome/Edge and allow microphone permission.
2. In the sidebar, edit the product description if you want.
3. Check the consent box only after informing the test participant and getting their consent.
4. Click **Start Call**.
5. Click **Start recording**, speak a sentence, and click **Stop recording**.
6. Wait for the bot's response; the transcript should update and the response should be playable.
7. Try asking about product benefits, pricing, integrations, or requesting a demo. The bot must not invent facts that are not in the product description.
8. Click **End Call**. Confirm the summary and sales status appear.
9. Expand the call in **Call history** and test transcript, playback, and download.

## 4. Deploy to Streamlit Community Cloud
1. Create a GitHub repository and upload `app.py`, `requirements.txt`, `packages.txt`, `.gitignore`, and README. Do not upload `.streamlit/secrets.toml`.
2. Open Streamlit Community Cloud and create an app from the repository.
3. Set the main file path to `app.py`.
4. In the app's **Settings → Secrets**, add:
   ```toml
   GEMINI_API_KEY = "your-real-key"
   ```
5. Deploy and wait for dependencies to install. `packages.txt` installs FFmpeg for audio conversion.
6. Open the public app URL, test microphone permissions, make a short test call, end it, and check call history.

## 5. Troubleshooting
- **API key missing:** local `.streamlit/secrets.toml` or deployed app Secrets must contain `GEMINI_API_KEY`.
- **Quota/model error:** verify your API key, quota, and available models in Google AI Studio. If the TTS model is unavailable, the app attempts a gTTS fallback.
- **Microphone not available:** use HTTPS in deployment, allow microphone access in the browser, and refresh the page.
- **No recording in history:** ensure at least one successful turn was recorded and that FFmpeg installed successfully.
- **Timer:** the app refreshes the displayed duration once per second while a call is active.
- **Cloud persistence:** Streamlit's local disk is not a durable database/storage service. For a production submission with persistent history across rebuilds, connect a managed database and object storage.

## 6. Demo video outline (60–90 seconds)
1. Show the deployed website and product configuration.
2. Mention recording consent and click Start Call.
3. Record yourself asking what the product does.
4. Show the customer transcript and play the AI spoken reply.
5. Ask for a demo or say you need time to decide.
6. Click End Call and show summary/status.
7. Expand Call History and play/download the recording.
