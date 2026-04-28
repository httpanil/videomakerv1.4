from __future__ import annotations

import os
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

import cv2
import imageio_ffmpeg
import numpy as np
from moviepy import AudioFileClip
from PIL import Image, ImageFile

from image_download import generate_images_from_audio_duration
from video_selector import get_video_resolution

FPS = 30
SECONDS_PER_IMAGE = 3
TRANSITION_FRAMES = 20
BG_MUSIC_VOLUME = 0.06
VOICE_MIX_VOLUME = 1.75
SFX_VOLUME = 0.28
OVERLAY_OPACITY = 0.5
MAX_SFX_CLIPS = 16
MIN_SECONDS_BETWEEN_SFX = 6
OVERLAY_PIXEL_SECOND_BUDGET = 90_000_000
LONG_VIDEO_MAX_SECONDS = 69
SHORT_VIDEO_MAX_SECONDS = 69
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
ImageFile.LOAD_TRUNCATED_IMAGES = True


ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class ProjectPaths:
    source_dir: Path
    data_dir: Path

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def sfx_dir(self) -> Path:
        return self.source_dir / "sfx"

    @property
    def bg_music_dir(self) -> Path:
        return self.source_dir / "bg_music"

    @property
    def overlay_dir(self) -> Path:
        return self.source_dir / "overlay"


@dataclass(slots=True)
class RenderRequest:
    audio_path: Path
    orientation: str
    image_mode: str
    manual_images: list[Path]
    keywords: list[str]
    include_sfx: bool = True
    include_bg_music: bool = False
    include_overlay: bool = False


def resolve_ffmpeg_binary() -> str:
    return shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()


def resolve_ffprobe_binary() -> str:
    if ffprobe := shutil.which("ffprobe"):
        return ffprobe

    ffmpeg_path = Path(resolve_ffmpeg_binary())
    candidate = ffmpeg_path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return str(candidate)


def ensure_runtime_requirements() -> None:
    ffmpeg_binary = resolve_ffmpeg_binary()
    if not ffmpeg_binary:
        raise RuntimeError("FFmpeg runtime is unavailable. Install FFmpeg or ensure imageio-ffmpeg is installed.")


def ensure_project_dirs(paths: ProjectPaths) -> None:
    for folder in [paths.exports_dir, paths.images_dir, paths.uploads_dir, paths.temp_dir]:
        folder.mkdir(parents=True, exist_ok=True)


def list_audio_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS)


def list_overlay_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() == ".mp4")


def validate_images(image_paths: list[Path]) -> list[Path]:
    valid_images: list[Path] = []

    for path in image_paths:
        try:
            with Image.open(path) as image:
                image.verify()
            valid_images.append(path)
        except Exception:
            continue

    if not valid_images:
        raise RuntimeError("No valid images were found.")

    return valid_images


def load_image_rgb(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            return np.array(image.convert("RGB"))
    except Exception as exc:
        raise RuntimeError(f"Could not load image '{path.name}': {exc}") from exc


def max_duration_for_orientation(orientation: str) -> int:
    return SHORT_VIDEO_MAX_SECONDS if orientation == "short" else LONG_VIDEO_MAX_SECONDS


def format_duration_limit(seconds: int) -> str:
    minutes = seconds // 60
    remainder = seconds % 60
    if remainder == 0:
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{minutes} minute {remainder} seconds"


def probe_audio_duration(audio_path: Path) -> float:
    command = [
        resolve_ffprobe_binary(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Could not read the audio duration.")

    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError("Could not parse the audio duration.") from exc


def normalize_audio_for_moviepy(audio_path: Path, temp_dir: Path) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = temp_dir / f"{audio_path.stem}_normalized.wav"

    command = [
        resolve_ffmpeg_binary(),
        "-y",
        "-i",
        str(audio_path),
        "-ar",
        "44100",
        "-ac",
        "2",
        "-vn",
        str(normalized_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio normalization failed: {result.stderr.strip()}")
    if not normalized_path.exists() or normalized_path.stat().st_size < 4096:
        raise RuntimeError("Normalized audio file looks invalid.")
    return normalized_path


def load_and_resize(path: Path, width: int, height: int) -> np.ndarray | None:
    image_rgb = load_image_rgb(path)
    image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    source_height, source_width = image.shape[:2]
    background = cv2.resize(image, (width, height))
    background = cv2.GaussianBlur(background, (51, 51), 0)

    scale = min(width / source_width, height / source_height)
    new_width = int(source_width * scale)
    new_height = int(source_height * scale)

    resized = cv2.resize(image, (new_width, new_height))
    x_offset = (width - new_width) // 2
    y_offset = (height - new_height) // 2
    background[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = resized
    return background


def crop_to_frame(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    frame_height, frame_width = frame.shape[:2]
    if frame_height == height and frame_width == width:
        return frame

    x_offset = max(0, (frame_width - width) // 2)
    y_offset = max(0, (frame_height - height) // 2)
    cropped = frame[y_offset:y_offset + height, x_offset:x_offset + width]
    return cv2.resize(cropped, (width, height))


def safe_write(writer, frame: np.ndarray | None, width: int, height: int) -> bool:
    if frame is None or not isinstance(frame, np.ndarray):
        return False

    if frame.shape[0] != height or frame.shape[1] != width:
        frame = cv2.resize(frame, (width, height))
    if frame.dtype != np.uint8:
        frame = frame.astype(np.uint8)

    writer.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    return True


def open_video_writer(temp_video: Path, width: int, height: int):
    writer = imageio_ffmpeg.write_frames(
        str(temp_video),
        (width, height),
        fps=FPS,
        codec="libx264",
        pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p",
        output_params=["-preset", "ultrafast", "-movflags", "+faststart"],
    )
    writer.send(None)
    return writer


def close_video_writer(writer) -> None:
    try:
        writer.close()
    except Exception:
        pass


def ease_in_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def zoom_animation(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    image_height, image_width = image.shape[:2]
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        progress = ease_in_out(index / max(1, total - 1))
        scale = 1 + progress * 0.08
        scaled = cv2.resize(image, (int(image_width * scale), int(image_height * scale)))
        yield crop_to_frame(scaled, width, height)


def zoom_out(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    image_height, image_width = image.shape[:2]
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        progress = ease_in_out(index / max(1, total - 1))
        scale = 1.08 - progress * 0.08
        scaled = cv2.resize(image, (int(image_width * scale), int(image_height * scale)))
        yield crop_to_frame(scaled, width, height)


def pan_left_to_right(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    scaled = cv2.resize(image, (width + 180, height))
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        max_shift = scaled.shape[1] - width
        shift = int(ease_in_out(index / max(1, total - 1)) * max_shift)
        yield scaled[:, shift:shift + width]


def pan_right_to_left(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    scaled = cv2.resize(image, (width + 180, height))
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        max_shift = scaled.shape[1] - width
        shift = int((1 - ease_in_out(index / max(1, total - 1))) * max_shift)
        yield scaled[:, shift:shift + width]


def cinematic_pan(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    scaled = cv2.resize(image, (width + 200, height + 120))
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        progress = ease_in_out(index / max(1, total - 1))
        x_shift = int(progress * (scaled.shape[1] - width))
        y_shift = int(progress * (scaled.shape[0] - height))
        yield scaled[y_shift:y_shift + height, x_shift:x_shift + width]


def diagonal_drift(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    scaled = cv2.resize(image, (width + 140, height + 140))
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        progress = ease_in_out(index / max(1, total - 1))
        x_shift = int(progress * (scaled.shape[1] - width))
        y_shift = int(progress * (scaled.shape[0] - height))
        yield scaled[y_shift:y_shift + height, x_shift:x_shift + width]


def tilt_motion(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    center = (width // 2, height // 2)
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        angle = -1.4 + ease_in_out(index / max(1, total - 1)) * 2.8
        matrix = cv2.getRotationMatrix2D(center, angle, 1.02)
        rotated = cv2.warpAffine(image, matrix, (width, height), borderMode=cv2.BORDER_REFLECT)
        yield rotated


def cinematic_zoom(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    return zoom_animation(image, width, height)


def focus_pull(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    image_height, image_width = image.shape[:2]
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        progress = ease_in_out(index / max(1, total - 1))
        scale = 1.02 + progress * 0.10
        scaled = cv2.resize(image, (int(image_width * scale), int(image_height * scale)))
        frame = crop_to_frame(scaled, width, height)
        blur_strength = max(1, int((1 - progress) * 9) | 1)
        yield cv2.GaussianBlur(frame, (blur_strength, blur_strength), 0)


def vertical_glide(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    scaled = cv2.resize(image, (width, height + 220))
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        max_shift = scaled.shape[0] - height
        shift = int(ease_in_out(index / max(1, total - 1)) * max_shift)
        yield scaled[shift:shift + height, :]


def drift_zoom(image: np.ndarray, width: int, height: int) -> Iterator[np.ndarray]:
    image_height, image_width = image.shape[:2]
    total = FPS * SECONDS_PER_IMAGE
    for index in range(total):
        progress = ease_in_out(index / max(1, total - 1))
        scale = 1.01 + progress * 0.06
        scaled = cv2.resize(image, (int(image_width * scale), int(image_height * scale)))
        x_room = max(0, scaled.shape[1] - width)
        y_room = max(0, scaled.shape[0] - height)
        x_shift = int(progress * x_room)
        y_shift = int((1 - progress) * y_room)
        frame = scaled[y_shift:y_shift + height, x_shift:x_shift + width]
        yield crop_to_frame(frame, width, height)


def fade_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    for index in range(TRANSITION_FRAMES):
        yield cv2.addWeighted(image_a, 1 - (index / TRANSITION_FRAMES), image_b, index / TRANSITION_FRAMES, 0)


def slide_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    width = image_a.shape[1]
    for index in range(TRANSITION_FRAMES):
        shift = int((index / TRANSITION_FRAMES) * width)
        frame = np.zeros_like(image_a)
        frame[:, :width - shift] = image_a[:, shift:]
        frame[:, width - shift:] = image_b[:, :shift]
        yield frame


def blur_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    for index in range(TRANSITION_FRAMES):
        alpha = index / TRANSITION_FRAMES
        blur_strength = max(1, int(alpha * 31) | 1)
        blurred_a = cv2.GaussianBlur(image_a, (blur_strength, blur_strength), 0)
        blurred_b = cv2.GaussianBlur(image_b, (blur_strength, blur_strength), 0)
        yield cv2.addWeighted(blurred_a, 1 - alpha, blurred_b, alpha, 0)


def zoom_blur_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    height, width = image_a.shape[:2]
    for index in range(TRANSITION_FRAMES):
        alpha = index / TRANSITION_FRAMES
        scale_a = 1 + alpha * 0.2
        scale_b = 1.2 - alpha * 0.2
        scaled_a = cv2.resize(image_a, (int(width * scale_a), int(height * scale_a)))
        scaled_b = cv2.resize(image_b, (int(width * scale_b), int(height * scale_b)))
        frame_a = crop_to_frame(scaled_a, width, height)
        frame_b = crop_to_frame(scaled_b, width, height)
        yield cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)


def whip_pan_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    width = image_a.shape[1]
    for index in range(TRANSITION_FRAMES):
        shift = min(width, int((index / TRANSITION_FRAMES) * width * 1.5))
        frame = np.zeros_like(image_a)
        if shift < width:
            frame[:, :width - shift] = image_a[:, shift:]
            frame[:, width - shift:] = image_b[:, :shift]
        else:
            frame = image_b.copy()
        yield cv2.GaussianBlur(frame, (9, 9), 0)


def circle_reveal_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    height, width = image_a.shape[:2]
    center = (width // 2, height // 2)
    max_radius = int(np.hypot(width, height))
    for index in range(TRANSITION_FRAMES):
        radius = int((index / TRANSITION_FRAMES) * max_radius)
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.circle(mask, center, radius, 255, -1)
        mask_3d = cv2.merge([mask, mask, mask]) / 255.0
        frame = (image_b * mask_3d + image_a * (1 - mask_3d)).astype(np.uint8)
        yield frame


def film_fade_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    white = np.full_like(image_a, 246)
    midpoint = TRANSITION_FRAMES / 2
    for index in range(TRANSITION_FRAMES):
        if index <= midpoint:
            alpha = index / midpoint
            frame = cv2.addWeighted(image_a, 1 - alpha, white, alpha, 0)
        else:
            alpha = (index - midpoint) / midpoint
            frame = cv2.addWeighted(white, 1 - alpha, image_b, alpha, 0)
        yield frame


def soft_push_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    width = image_a.shape[1]
    height = image_a.shape[0]
    for index in range(TRANSITION_FRAMES):
        alpha = index / TRANSITION_FRAMES
        shift = int(alpha * width * 0.24)
        frame_a = np.roll(image_a, -shift, axis=1)
        frame_b = np.roll(image_b, width - shift, axis=1)
        base = cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)
        vignette = np.linspace(0.92, 1.0, height, dtype=np.float32).reshape(height, 1, 1)
        yield np.clip(base * vignette, 0, 255).astype(np.uint8)


def cross_zoom_transition(image_a: np.ndarray, image_b: np.ndarray) -> Iterator[np.ndarray]:
    height, width = image_a.shape[:2]
    for index in range(TRANSITION_FRAMES):
        alpha = index / TRANSITION_FRAMES
        scale_a = 1.0 + alpha * 0.16
        scale_b = 1.16 - alpha * 0.16
        frame_a = crop_to_frame(cv2.resize(image_a, (int(width * scale_a), int(height * scale_a))), width, height)
        frame_b = crop_to_frame(cv2.resize(image_b, (int(width * scale_b), int(height * scale_b))), width, height)
        yield cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)


def choose_animation():
    return random.choice([
        cinematic_zoom,
        zoom_out,
        pan_left_to_right,
        pan_right_to_left,
        cinematic_pan,
        diagonal_drift,
        focus_pull,
        vertical_glide,
        drift_zoom,
    ])


def choose_transition():
    return random.choice([
        fade_transition,
        blur_transition,
        zoom_blur_transition,
        circle_reveal_transition,
        soft_push_transition,
        cross_zoom_transition,
        film_fade_transition,
    ])


def get_random_bg_music(bg_music_dir: Path) -> Path | None:
    tracks = list_audio_files(bg_music_dir)
    return random.choice(tracks) if tracks else None


def create_export_name(exports_dir: Path) -> Path:
    return exports_dir / f"video-{uuid4().hex[:12]}.mp4"


def emit_progress(progress_callback: ProgressCallback | None, value: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, value)), message)


def voice_filter_chain() -> str:
    return (
        "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
        "highpass=f=90,"
        "lowpass=f=12000,"
        f"volume={VOICE_MIX_VOLUME},"
        "acompressor=threshold=0.08:ratio=3.2:attack=15:release=180:makeup=4"
    )


def mux_voice_with_ffmpeg(
    temp_video: Path,
    output_video: Path,
    normalized_audio: Path,
    progress_callback: ProgressCallback | None,
    complete_progress: int = 100,
    complete_message: str = "Video is ready",
) -> None:
    emit_progress(progress_callback, 92, "Adding voice-over")
    command = [
        resolve_ffmpeg_binary(),
        "-y",
        "-i",
        str(temp_video),
        "-i",
        str(normalized_audio),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-filter_complex",
        f"[1:a]{voice_filter_chain()},alimiter=limit=0.98[aout]",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_video),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Final audio mux failed: {result.stderr.strip()}")
    if not output_video.exists() or output_video.stat().st_size < 4096:
        raise RuntimeError("Final video file looks invalid.")
    emit_progress(progress_callback, complete_progress, complete_message)


def choose_sfx_layers(sfx_times: list[float], sfx_dir: Path) -> list[tuple[Path, float]]:
    sfx_files = list_audio_files(sfx_dir)
    if not sfx_files:
        return []

    layers: list[tuple[Path, float]] = []
    last_sfx = -MIN_SECONDS_BETWEEN_SFX
    for start_time in sfx_times:
        if len(layers) >= MAX_SFX_CLIPS:
            break
        if start_time - last_sfx >= MIN_SECONDS_BETWEEN_SFX:
            layers.append((random.choice(sfx_files), start_time))
            last_sfx = start_time
    return layers


def mux_audio_with_ffmpeg(
    temp_video: Path,
    output_video: Path,
    normalized_audio: Path,
    sfx_times: list[float],
    paths: ProjectPaths,
    request: RenderRequest,
    duration: float,
    progress_callback: ProgressCallback | None,
    complete_progress: int = 100,
    complete_message: str = "Video is ready",
) -> None:
    use_bg_music = request.include_bg_music and env_flag("VIDEO_MAKER_BG_MUSIC", "1")
    use_sfx = request.include_sfx and env_flag("VIDEO_MAKER_SFX", "1")
    bg_music_path = get_random_bg_music(paths.bg_music_dir) if use_bg_music else None
    sfx_layers = choose_sfx_layers(sfx_times, paths.sfx_dir) if use_sfx else []

    if not bg_music_path and not sfx_layers:
        mux_voice_with_ffmpeg(
            temp_video,
            output_video,
            normalized_audio,
            progress_callback,
            complete_progress=complete_progress,
            complete_message=complete_message,
        )
        return

    emit_progress(progress_callback, 92, "Mixing audio effects")
    command = [
        resolve_ffmpeg_binary(),
        "-y",
        "-i",
        str(temp_video),
        "-i",
        str(normalized_audio),
    ]

    next_input = 2
    filter_parts = [f"[1:a]{voice_filter_chain()}[a0]"]
    mix_labels = ["[a0]"]

    if bg_music_path:
        command.extend(["-stream_loop", "-1", "-i", str(bg_music_path)])
        filter_parts.append(
            f"[{next_input}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"volume={BG_MUSIC_VOLUME},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[a{len(mix_labels)}]"
        )
        mix_labels.append(f"[a{len(mix_labels)}]")
        next_input += 1

    for sfx_path, start_time in sfx_layers:
        delay_ms = max(0, int(start_time * 1000))
        command.extend(["-i", str(sfx_path)])
        label = f"a{len(mix_labels)}"
        filter_parts.append(
            f"[{next_input}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"volume={SFX_VOLUME},adelay={delay_ms}|{delay_ms}[{label}]"
        )
        mix_labels.append(f"[{label}]")
        next_input += 1

    filter_parts.append(
        f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.97[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_video),
        ]
    )
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Final audio mix failed: {result.stderr.strip()}")
    if not output_video.exists() or output_video.stat().st_size < 4096:
        raise RuntimeError("Final video file looks invalid.")
    emit_progress(progress_callback, complete_progress, complete_message)


def can_apply_overlay(width: int, height: int, duration: float) -> bool:
    budget = int(os.getenv("VIDEO_MAKER_OVERLAY_PIXEL_SECOND_BUDGET", str(OVERLAY_PIXEL_SECOND_BUDGET)))
    return width * height * duration <= budget


def apply_overlay_with_moviepy(
    input_video: Path,
    output_video: Path,
    paths: ProjectPaths,
    width: int,
    height: int,
    progress_callback: ProgressCallback | None,
) -> None:
    overlay_files = list_overlay_files(paths.overlay_dir)
    if not overlay_files:
        shutil.move(str(input_video), str(output_video))
        emit_progress(progress_callback, 100, "Video is ready")
        return

    emit_progress(progress_callback, 94, "Applying overlay")
    overlay_path = overlay_files[0]
    command = [
        resolve_ffmpeg_binary(),
        "-y",
        "-i",
        str(input_video),
        "-stream_loop",
        "-1",
        "-i",
        str(overlay_path),
        "-filter_complex",
        (
            f"[1:v]scale={width}:{height},format=rgba,colorchannelmixer=aa={OVERLAY_OPACITY}[ov];"
            f"[0:v][ov]overlay=shortest=1:eof_action=pass:format=auto[vout]"
        ),
        "-map",
        "[vout]",
        "-map",
        "0:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_video),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Overlay render failed: {result.stderr.strip()}")
    if not output_video.exists() or output_video.stat().st_size < 4096:
        raise RuntimeError("Overlay output file looks invalid.")
    emit_progress(progress_callback, 100, "Video is ready")


def prepare_images(
    request: RenderRequest,
    paths: ProjectPaths,
    normalized_audio: Path,
    progress_callback: ProgressCallback | None,
    auto_image_dir: Path | None = None,
) -> list[Path]:
    if request.image_mode == "auto":
        emit_progress(progress_callback, 8, "Downloading images")
        audio_clip = AudioFileClip(str(normalized_audio))
        try:
            image_dir = auto_image_dir or paths.images_dir
            return generate_images_from_audio_duration(audio_clip, request.keywords, image_dir)
        finally:
            audio_clip.close()

    emit_progress(progress_callback, 8, "Validating uploaded images")
    return validate_images(request.manual_images)


def render_video(
    request: RenderRequest,
    paths: ProjectPaths,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    ensure_runtime_requirements()
    ensure_project_dirs(paths)

    emit_progress(progress_callback, 2, "Preparing render")
    width, height = get_video_resolution(request.orientation)
    normalized_audio = normalize_audio_for_moviepy(
        request.audio_path,
        paths.temp_dir / f"audio_{uuid4().hex}",
    )

    voice_clip = AudioFileClip(str(normalized_audio))
    try:
        voice_duration = voice_clip.duration
    finally:
        voice_clip.close()

    max_duration = max_duration_for_orientation(request.orientation)
    if voice_duration > max_duration:
        raise RuntimeError(f"Audio is too long for this format. The current limit is {format_duration_limit(max_duration)}.")

    total_frames_needed = max(1, int(voice_duration * FPS))
    auto_image_dir = paths.temp_dir / f"images_{uuid4().hex}" if request.image_mode == "auto" else None

    temp_video = paths.temp_dir / f"render_{uuid4().hex}.mp4"
    final_output = create_export_name(paths.exports_dir)
    writer = open_video_writer(temp_video, width, height)

    frame_count = 0
    image_index = 0
    previous_image = None
    sfx_times: list[float] = []
    last_percent = -1

    try:
        image_paths = prepare_images(request, paths, normalized_audio, progress_callback, auto_image_dir)
        emit_progress(progress_callback, 10, "Rendering video frames")
        while frame_count < total_frames_needed:
            image_path = image_paths[image_index % len(image_paths)]
            image = load_and_resize(image_path, width, height)
            image_index += 1
            if image is None:
                continue

            sfx_times.append(frame_count / FPS)

            if previous_image is not None:
                for frame in choose_transition()(previous_image, image):
                    if safe_write(writer, frame, width, height):
                        frame_count += 1
                    current_percent = 10 + int((frame_count / total_frames_needed) * 78)
                    if current_percent > last_percent:
                        emit_progress(progress_callback, current_percent, "Rendering video frames")
                        last_percent = current_percent
                    if frame_count >= total_frames_needed:
                        break

            for frame in choose_animation()(image, width, height):
                if safe_write(writer, frame, width, height):
                    frame_count += 1
                current_percent = 10 + int((frame_count / total_frames_needed) * 78)
                if current_percent > last_percent:
                    emit_progress(progress_callback, current_percent, "Rendering video frames")
                    last_percent = current_percent
                if frame_count >= total_frames_needed:
                    break

            previous_image = image
    finally:
        close_video_writer(writer)

    try:
        overlay_requested = request.include_overlay and env_flag("VIDEO_MAKER_OVERLAY", "1")
        overlay_allowed = overlay_requested and can_apply_overlay(width, height, voice_duration)
        if overlay_requested and not overlay_allowed:
            emit_progress(progress_callback, 91, "Skipping overlay to protect server memory")

        if overlay_allowed:
            audio_mixed_output = paths.temp_dir / f"audio_mix_{uuid4().hex}.mp4"
            mux_audio_with_ffmpeg(
                temp_video,
                audio_mixed_output,
                normalized_audio,
                sfx_times,
                paths,
                request,
                voice_duration,
                progress_callback,
                complete_progress=93,
                complete_message="Audio effects ready",
            )
            try:
                apply_overlay_with_moviepy(audio_mixed_output, final_output, paths, width, height, progress_callback)
            finally:
                if audio_mixed_output.exists():
                    audio_mixed_output.unlink()
        else:
            mux_audio_with_ffmpeg(
                temp_video,
                final_output,
                normalized_audio,
                sfx_times,
                paths,
                request,
                voice_duration,
                progress_callback,
            )
        return final_output
    finally:
        if temp_video.exists():
            temp_video.unlink()
        if auto_image_dir is not None:
            shutil.rmtree(auto_image_dir, ignore_errors=True)
        if normalized_audio.exists():
            normalized_audio.unlink()
