from __future__ import annotations

import math
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import cv2
from icrawler.builtin import BingImageCrawler

IMAGE_DURATION = 3
MAX_IMAGES = 70
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PROXY_ENV_NAMES = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


def get_audio_duration(audio_clip) -> int:
    duration = getattr(audio_clip, "duration", 0) or 0
    return max(1, math.ceil(duration))


def clear_images(image_folder: Path) -> None:
    image_folder.mkdir(parents=True, exist_ok=True)

    for child in image_folder.iterdir():
        if child.is_file():
            child.unlink()


def _valid_downloads(temp_folder: Path) -> Iterable[Path]:
    for file_path in temp_folder.iterdir():
        if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        image = cv2.imread(str(file_path))
        if image is None:
            continue

        yield file_path


def _query_variants(keyword: str) -> list[str]:
    base = " ".join(keyword.split()).strip()
    variants = [base]
    if "," in base:
        variants.append(base.replace(",", " "))
    if len(base.split()) == 1:
        variants.append(f"{base} concept")
        variants.append(f"{base} background")
    return [item for item in variants if item]


@contextmanager
def _disabled_proxy_env():
    stored = {name: os.environ.get(name) for name in PROXY_ENV_NAMES}
    try:
        for name in PROXY_ENV_NAMES:
            os.environ.pop(name, None)
        yield
    finally:
        for name, value in stored.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def download_images_for_keyword(keyword: str, amount: int, image_folder: Path, start_index: int) -> int:
    temp_folder = image_folder / "temp"
    temp_folder.mkdir(parents=True, exist_ok=True)

    saved = 0
    for query in _query_variants(keyword):
        if saved >= amount:
            break

        with _disabled_proxy_env():
            crawler = BingImageCrawler(
                downloader_threads=4,
                parser_threads=2,
                storage={"root_dir": str(temp_folder)},
            )
            crawler.crawl(keyword=query, max_num=max(amount * 2, 4))

        for file_path in _valid_downloads(temp_folder):
            destination = image_folder / f"img_{start_index + saved}{file_path.suffix.lower()}"
            if destination.exists():
                file_path.unlink(missing_ok=True)
                continue
            shutil.move(str(file_path), str(destination))
            saved += 1

            if saved >= amount:
                break

    shutil.rmtree(temp_folder, ignore_errors=True)
    return saved


def generate_images_from_audio_duration(
    audio_clip,
    keywords: list[str],
    image_folder: Path,
) -> list[Path]:
    if len(keywords) < 3:
        raise ValueError("Please provide at least 3 keywords for auto mode.")

    clear_images(image_folder)

    duration = get_audio_duration(audio_clip)
    images_needed = min(MAX_IMAGES, math.ceil(duration / IMAGE_DURATION))
    images_per_keyword = images_needed // len(keywords)
    extra = images_needed % len(keywords)

    index = 0
    for keyword_index, keyword in enumerate(keywords):
        amount = images_per_keyword + (1 if keyword_index < extra else 0)
        if amount <= 0:
            continue
        saved = download_images_for_keyword(keyword, amount, image_folder, index)
        index += saved

    image_paths = sorted(path for path in image_folder.iterdir() if path.suffix.lower() in ALLOWED_EXTENSIONS)

    allow_fallback = os.getenv("VIDEO_MAKER_KEYWORD_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
    if allow_fallback and len(image_paths) < images_needed:
        from PIL import Image, ImageDraw, ImageFont
        import hashlib
        import textwrap

        def keyword_palette(text: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            color_a = (70 + digest[0] % 120, 60 + digest[1] % 120, 90 + digest[2] % 120)
            color_b = (130 + digest[3] % 90, 110 + digest[4] % 90, 80 + digest[5] % 90)
            return color_a, color_b

        def create_fallback(keyword: str, destination: Path, index: int) -> None:
            width, height = 1280, 720
            color_a, color_b = keyword_palette(f"{keyword}-{index}")
            image = Image.new("RGB", (width, height), color_a)
            draw = ImageDraw.Draw(image)
            for y in range(height):
                blend = y / max(1, height - 1)
                row_color = tuple(int(color_a[i] * (1 - blend) + color_b[i] * blend) for i in range(3))
                draw.line((0, y, width, y), fill=row_color)
            wrapped = textwrap.wrap(keyword.strip().title() or "Keyword Visual", width=18) or ["Keyword Visual"]
            font = ImageFont.load_default()
            top = height // 2 - (len(wrapped) * 24) // 2
            for line in wrapped:
                draw.text((128, top), line, fill=(255, 248, 240), font=font)
                top += 24
            image.save(destination, format="PNG")

        missing = images_needed - len(image_paths)
        for offset in range(missing):
            keyword = keywords[offset % len(keywords)]
            create_fallback(keyword, image_folder / f"img_{len(image_paths) + offset}.png", len(image_paths) + offset)
        image_paths = sorted(path for path in image_folder.iterdir() if path.suffix.lower() in ALLOWED_EXTENSIONS)

    if not image_paths:
        raise RuntimeError("No images could be downloaded for the provided keywords.")

    return image_paths
