# Local Transcriber

Local web app for transcribing audio files (`.opus`/`.ogg` from WhatsApp, `.m4a`/`.mp3`/`.wav`) with `faster-whisper`, or a YouTube URL (via official captions, falling back to Whisper if none exist). Runs 100% on `localhost`, with no deployment, authentication, or database.

## Requirements

- Python 3.10+
- `ffmpeg` installed on the system (external dependency, not installed by pip)
- NVIDIA GPU with CUDA driver installed (optional; falls back to CPU automatically if missing/OOM)

### Install ffmpeg

```bash
# Fedora
sudo dnf install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

Verify with `ffmpeg -version`.

## Installation

```bash
git clone <repo>  # or enter the project folder
cd local-transcriber

python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
```

## Running

Single command (starts the API and opens `frontend/index.html` in your default browser):

```bash
./start.sh
```

Press `Ctrl+C` to stop; it also shuts down the background uvicorn process.

Manual alternative:

```bash
uvicorn backend.main:app --reload
```

The server runs at `http://localhost:8000`. Open `frontend/index.html` directly in your browser (double-click or `file://`), drag in an audio file, and get the transcription.

Check backend health and which device is active (`cuda` or `cpu`):

```bash
curl http://localhost:8000/health
```

## Configuration (VRAM: 4GB target)

Variables in `.env` (see `.env.example`):

| Variable | Default | Note |
|---|---|---|
| `WHISPER_MODEL` | `small` | Safe on 4GB. `medium` with int8 is the **safe limit**. `large-v3` will **probably exceed** 4GB. |
| `WHISPER_COMPUTE_TYPE` | `int8_float16` | Light VRAM quantization. |
| `WHISPER_DEVICE` | `cuda` | If loading fails (for example OOM), the backend automatically falls back to `cpu` and logs a warning. |
| `WHISPER_LANGUAGE` | `en` | Default forced language (avoids automatic detection and runs faster). Can be overridden per request. |
| `YOUTUBE_MAX_DURATION_SECONDS` | `7200` (2h) | Videos longer than this are rejected before download. Also guards against livestreams (which is checked separately). |
| `YOUTUBE_MAX_DOWNLOAD_BYTES` | `524288000` (500MB) | Backstop cap on the downloaded audio track, in case reported duration is wrong. |
| `YOUTUBE_ACCEPT_AUTO_CAPTIONS` | `true` | Whether YouTube's auto-generated (ASR) captions count as usable captions. If `false`, only human-made captions skip Whisper. |

The model is loaded **once** during FastAPI startup (`lifespan` event), not on every request.

To test `medium`:

```bash
WHISPER_MODEL=medium uvicorn backend.main:app --reload
```

Monitor VRAM with `nvidia-smi -l 1` during the test.

## Available Languages

The frontend currently exposes these transcription language options:

| Code | Language |
|---|---|
| `en` | English |
| `pt` | Portuguese |
| `es` | Spanish |
| empty value | Automatic detection |

## Endpoint

`POST /transcribe` — `multipart/form-data`:
- `file`: audio file (`.opus`, `.ogg`, `.m4a`, `.mp3`, `.wav`)
- `language` (optional): language code (`en`, `pt`, ...). If omitted, uses `WHISPER_LANGUAGE`.

Response:

```json
{
  "text": "full transcribed text",
  "segments": [{"start": 0.0, "end": 3.2, "text": "..."}],
  "duration_seconds": 12.4,
  "processing_time_seconds": 3.1
}
```

All audio is converted with `ffmpeg` to 16kHz mono WAV before being sent to Whisper. Temporary files are deleted after transcription, whether it succeeds or fails.

`POST /transcribe/youtube` — `application/json`:
- `url`: a `youtube.com`/`youtu.be` video URL
- `language` (optional): language code (`en`, `pt`, ...). If omitted, uses `WHISPER_LANGUAGE`.

Tries YouTube's own captions first (manually-created, then auto-generated if `YOUTUBE_ACCEPT_AUTO_CAPTIONS=true`); if none are available, downloads the audio track with `yt-dlp` and runs it through the same `ffmpeg` + Whisper pipeline as `/transcribe`.

Response (superset of `/transcribe`'s shape):

```json
{
  "text": "full transcribed text",
  "segments": [{"start": 0.0, "end": 3.2, "text": "..."}],
  "duration_seconds": 12.4,
  "processing_time_seconds": 3.1,
  "source": "captions",
  "video_id": "dQw4w9WgXcQ",
  "video_title": "...",
  "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
```

`source` is `"captions"` or `"whisper"`, depending on which path served the request.

Errors: `400` (not a YouTube URL / bad video ID), `404` (video private/deleted/region-blocked), `413` (exceeds `YOUTUBE_MAX_DURATION_SECONDS`), `422` (live stream in progress, or audio download/ffmpeg conversion failed), `500` (Whisper transcription failed).

This endpoint needs outbound internet access to reach YouTube, unlike the pure file-upload flow.

`yt-dlp` ships frequent releases to keep up with YouTube's changes — if YouTube requests start failing with a "signature extraction" or similar error, `pip install -U yt-dlp` is the first thing to try.

## Structure

```
local-transcriber/
├── backend/
│   ├── main.py              # FastAPI app, endpoints /transcribe and /transcribe/youtube
│   ├── transcriber.py       # faster-whisper wrapper
│   ├── audio_utils.py       # ffmpeg conversion
│   ├── youtube_utils.py     # YouTube URL validation, captions, yt-dlp download
│   └── config.py            # config via env vars
├── frontend/
│   └── index.html           # drag&drop + YouTube link tabs + fetch
├── requirements.txt
├── .env.example
└── README.md
```

## Out of scope

Authentication, multi-user support, async queue, persisted history, speaker diarization, real-time streaming, YouTube playlist/batch URLs, and caching of previously-fetched videos.
