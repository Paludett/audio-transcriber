import ctypes
import glob
import logging
import time

from faster_whisper import WhisperModel

from . import config

logger = logging.getLogger("transcriber")

_model: WhisperModel | None = None
_active_device: str = config.DEVICE


def _preload_cuda_libs() -> None:
    """Preload cuBLAS/cuDNN installed through pip (nvidia-cublas-cu12, nvidia-cudnn-cu12).

    CTranslate2 resolves these libs through dlopen at runtime, which only sees
    LD_LIBRARY_PATH set *before* the process starts. To avoid depending on external
    shell configuration, load the .so files manually here: once mapped into the
    process, CTranslate2 dlopen-by-soname finds them without needing LD_LIBRARY_PATH.
    """
    try:
        import nvidia.cublas.lib
        import nvidia.cudnn.lib
    except ImportError:
        return

    for pkg in (nvidia.cublas.lib, nvidia.cudnn.lib):
        pkg_dir = pkg.__path__[0] if hasattr(pkg, "__path__") else None
        if not pkg_dir:
            continue
        for so_path in sorted(glob.glob(f"{pkg_dir}/*.so*")):
            try:
                ctypes.CDLL(so_path, mode=ctypes.RTLD_GLOBAL)
            except OSError as exc:
                logger.debug("Could not preload %s: %s", so_path, exc)


def load_model() -> WhisperModel:
    """Load the faster-whisper model once. Fall back to CPU if CUDA fails (for example OOM)."""
    if config.DEVICE == "cuda":
        _preload_cuda_libs()
    global _model, _active_device

    try:
        logger.info(
            "Loading model '%s' on device='%s' compute_type='%s'...",
            config.WHISPER_MODEL, config.DEVICE, config.COMPUTE_TYPE,
        )
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.DEVICE,
            compute_type=config.COMPUTE_TYPE,
        )
        _active_device = config.DEVICE
        logger.info("Model loaded successfully on '%s'.", config.DEVICE)
    except Exception as exc:
        logger.error(
            "Failed to load model on device='%s' (%s). Falling back to CPU; "
            "transcription will be slower.", config.DEVICE, exc,
        )
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )
        _active_device = "cpu"
        logger.warning("Model loaded on CPU (fallback).")

    return _model


def get_model() -> WhisperModel:
    if _model is None:
        raise RuntimeError("Model was not initialized. Call load_model() on startup.")
    return _model


def get_active_device() -> str:
    return _active_device


def transcribe_audio(wav_path: str, language: str | None = None) -> dict:
    model = get_model()
    lang = language or config.DEFAULT_LANGUAGE

    start = time.perf_counter()
    segments_iter, info = model.transcribe(wav_path, language=lang, beam_size=5)

    segments = []
    full_text_parts = []
    for seg in segments_iter:
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })
        full_text_parts.append(seg.text.strip())

    processing_time = time.perf_counter() - start

    return {
        "text": " ".join(full_text_parts).strip(),
        "segments": segments,
        "duration_seconds": info.duration,
        "processing_time_seconds": processing_time,
    }
