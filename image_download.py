from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Iterable

import cv2
from icrawler.builtin import BingImageCrawler

IMAGE_DURATION = 3
MAX_IMAGES = 70
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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


def download_images_for_keyword(keyword: str, amount: int, image_folder: Path, start_index: int) -> int:
    temp_folder = image_folder / "temp"
    temp_folder.mkdir(parents=True, exist_ok=True)

    crawler = BingImageCrawler(
        downloader_threads=4,
        parser_threads=2,
        storage={"root_dir": str(temp_folder)},
    )
    crawler.crawl(keyword=keyword, max_num=amount)

    saved = 0

    for file_path in _valid_downloads(temp_folder):
        destination = image_folder / f"img_{start_index + saved}{file_path.suffix.lower()}"
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

    image_paths = sorted(
        path for path in image_folder.iterdir() if path.suffix.lower() in ALLOWED_EXTENSIONS
    )
    if not image_paths:
        raise RuntimeError("No images could be downloaded for the provided keywords.")

    return image_paths
