import subprocess
import tempfile
import os
from fastapi import HTTPException


def convert_to_wav(input_path: str) -> str:
    """Convert audio to 16kHz mono WAV through ffmpeg. Return the generated temp file path."""
    fd, output_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(
            status_code=422,
            detail=f"Failed to convert audio with ffmpeg: {result.stderr.strip()[-500:]}",
        )

    return output_path
