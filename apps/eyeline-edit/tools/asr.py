"""Local speech recognition adapter. Models download on first use."""
import platform, shutil, subprocess
_model = None


def audio16k(path):
    """Decode any audio file to 16 kHz mono float32 with Eyeline's bundled ffmpeg.
    mlx-whisper would otherwise call a system `ffmpeg`, which most Macs do not have."""
    import numpy as np
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg") or "ffmpeg"
    out = subprocess.run([exe, "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0

def transcribe(path, **options):
    global _model
    options.pop("path_or_hf_repo", None)
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        import mlx_whisper
        return mlx_whisper.transcribe(audio16k(path), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", **options)
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(path, **options)
    rows = [{"start": s.start, "end": s.end, "text": s.text, "no_speech_prob": s.no_speech_prob,
             "words": [{"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                       for w in (s.words or [])]} for s in segments]
    return {"segments": rows, "text": " ".join(s["text"] for s in rows)}
