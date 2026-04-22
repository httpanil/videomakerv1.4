RESOLUTIONS = {
    "long": (1280, 720),
    "short": (1080, 1920),
}


def get_video_resolution(mode: str) -> tuple[int, int]:
    return RESOLUTIONS.get(mode, RESOLUTIONS["long"])
