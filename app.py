from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from job_manager import JobManager
from video_pipeline import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    ProjectPaths,
    RenderRequest,
    ensure_project_dirs,
    resolve_ffmpeg_binary,
)

SOURCE_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.4"


def _get_int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def build_project_paths() -> ProjectPaths:
    data_root = Path(os.getenv("VIDEO_MAKER_DATA_DIR", SOURCE_DIR / "data")).resolve()
    return ProjectPaths(source_dir=SOURCE_DIR, data_dir=data_root)


def _allowed(filename: str, extensions: set[str]) -> bool:
    return Path(filename).suffix.lower() in extensions


def _save_upload(file_storage, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_storage.save(destination)
    return destination


def _resolve_export_file(exports_dir: Path, filename: str) -> Path | None:
    clean_name = Path(filename).name
    if not clean_name:
        return None

    file_path = exports_dir / clean_name
    return file_path if file_path.exists() else None


def create_app() -> Flask:
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.config["MAX_CONTENT_LENGTH"] = _get_int_env("MAX_UPLOAD_MB", 256) * 1024 * 1024
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

    paths = build_project_paths()
    ensure_project_dirs(paths)

    worker_count = _get_int_env("VIDEO_MAKER_WORKERS", 1)
    app.config["PROJECT_PATHS"] = paths
    app.config["JOB_MANAGER"] = JobManager(paths, max_workers=worker_count)

    @app.get("/")
    def index():
        exports = sorted(paths.exports_dir.glob("video*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        return render_template(
            "index.html",
            exports=exports[:10],
            queue_workers=worker_count,
        )

    @app.get("/healthz")
    def healthz():
        return jsonify(
            {
                "status": "ok",
                "version": APP_VERSION,
                "ffmpeg": resolve_ffmpeg_binary(),
            }
        )

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": "Upload is too large for the current server limit."}), 413

    @app.post("/create")
    def create_video():
        audio_file = request.files.get("audio")
        if audio_file is None or not audio_file.filename:
            return jsonify({"error": "Please upload a voice-over audio file."}), 400

        if not _allowed(audio_file.filename, ALLOWED_AUDIO_EXTENSIONS):
            return jsonify({"error": "Unsupported audio format."}), 400

        orientation = request.form.get("orientation", "long")
        image_mode = request.form.get("image_mode", "manual")
        keywords = [item.strip() for item in request.form.get("keywords", "").split(",") if item.strip()]
        include_sfx = request.form.get("include_sfx") == "1"
        include_bg_music = request.form.get("include_bg_music") == "1"
        include_overlay = request.form.get("include_overlay") == "1"

        if orientation not in {"long", "short"}:
            return jsonify({"error": "Unsupported video format."}), 400
        if image_mode not in {"manual", "auto"}:
            return jsonify({"error": "Unsupported image mode."}), 400

        job_id = uuid4().hex
        work_dir = paths.uploads_dir / job_id
        audio_name = secure_filename(audio_file.filename)
        audio_path = _save_upload(audio_file, work_dir / audio_name)

        manual_images: list[Path] = []
        if image_mode == "manual":
            uploads = request.files.getlist("images")
            for upload in uploads:
                if upload and upload.filename and _allowed(upload.filename, ALLOWED_IMAGE_EXTENSIONS):
                    image_name = secure_filename(upload.filename)
                    manual_images.append(_save_upload(upload, work_dir / "images" / image_name))

            if not manual_images:
                shutil.rmtree(work_dir, ignore_errors=True)
                return jsonify({"error": "Please upload at least one valid image for manual mode."}), 400
        elif len(keywords) < 3:
            shutil.rmtree(work_dir, ignore_errors=True)
            return jsonify({"error": "Auto mode needs at least 3 keywords."}), 400

        render_request = RenderRequest(
            audio_path=audio_path,
            orientation=orientation,
            image_mode=image_mode,
            manual_images=manual_images,
            keywords=keywords,
            include_sfx=include_sfx,
            include_bg_music=include_bg_music,
            include_overlay=include_overlay,
        )

        job = app.config["JOB_MANAGER"].create_job(render_request, work_dir)
        return jsonify(
            {
                "job_id": job.id,
                "status_url": f"/jobs/{job.id}",
                "download_url": f"/jobs/{job.id}/download",
            }
        )

    @app.get("/jobs/<job_id>")
    def get_job(job_id: str):
        payload = app.config["JOB_MANAGER"].get_public_job(job_id)
        if payload is None:
            return jsonify({"error": "Job not found."}), 404

        if payload.get("output_name"):
            payload["download_url"] = f"/jobs/{payload['id']}/download"
            payload["preview_url"] = f"/jobs/{payload['id']}/preview"
        return jsonify(payload)

    @app.get("/jobs/<job_id>/download")
    def download_job_output(job_id: str):
        job = app.config["JOB_MANAGER"].get_public_job(job_id)
        output_name = job.get("output_name") if job else None
        if output_name is None:
            return jsonify({"error": "This job has no finished export yet."}), 404

        file_path = paths.exports_dir / output_name
        if not file_path.exists():
            return jsonify({"error": "Export file could not be found."}), 404

        return send_file(file_path, as_attachment=True, download_name=file_path.name)

    @app.get("/jobs/<job_id>/preview")
    def preview_job_output(job_id: str):
        job = app.config["JOB_MANAGER"].get_public_job(job_id)
        output_name = job.get("output_name") if job else None
        if output_name is None:
            return jsonify({"error": "This job has no finished export yet."}), 404

        file_path = paths.exports_dir / output_name
        if not file_path.exists():
            return jsonify({"error": "Export file could not be found."}), 404

        return send_file(file_path, mimetype="video/mp4", conditional=True)

    @app.get("/jobs/manual-download")
    def download_existing_output():
        filename = request.args.get("file", "")
        file_path = _resolve_export_file(paths.exports_dir, filename)
        if file_path is None:
            return jsonify({"error": "Export file could not be found."}), 404

        return send_file(file_path, as_attachment=True, download_name=file_path.name)

    @app.get("/jobs/manual-preview")
    def preview_existing_output():
        filename = request.args.get("file", "")
        file_path = _resolve_export_file(paths.exports_dir, filename)
        if file_path is None:
            return jsonify({"error": "Export file could not be found."}), 404

        return send_file(file_path, mimetype="video/mp4", conditional=True)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
