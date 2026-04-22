from __future__ import annotations

import json
import shutil
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from video_pipeline import ProjectPaths, RenderRequest, render_video


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class JobState:
    id: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    request: RenderRequest
    work_dir: Path
    output_name: str | None = None
    error: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "output_name": self.output_name,
            "error": self.error,
        }


class JobManager:
    def __init__(self, paths: ProjectPaths, max_workers: int = 1):
        self.paths = paths
        self.jobs_dir = paths.data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="videomaker")
        self.jobs: dict[str, JobState] = {}
        self.lock = threading.Lock()

    def _job_record_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _write_job_record(self, job: JobState) -> None:
        payload = job.to_public_dict()
        record_path = self._job_record_path(job.id)
        temp_path = record_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(record_path)

    def get_public_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if job is not None:
            return job.to_public_dict()

        record_path = self._job_record_path(job_id)
        if not record_path.exists():
            return None

        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        if payload.get("status") in {"queued", "running"}:
            payload["status"] = "failed"
            payload["progress"] = 100
            payload["message"] = "Render interrupted"
            payload["error"] = "The server restarted before this render finished. Please start a new render."
            payload["updated_at"] = utc_now_iso()
            record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def create_job(self, render_request: RenderRequest, work_dir: Path) -> JobState:
        job_id = uuid4().hex
        timestamp = utc_now_iso()
        job = JobState(
            id=job_id,
            status="queued",
            progress=0,
            message="Waiting for a worker",
            created_at=timestamp,
            updated_at=timestamp,
            request=render_request,
            work_dir=work_dir,
        )
        with self.lock:
            self.jobs[job_id] = job
            self._write_job_record(job)

        self.executor.submit(self._run_job, job_id)
        return job

    def get_job(self, job_id: str) -> JobState | None:
        with self.lock:
            return self.jobs.get(job_id)

    def _update_job(self, job_id: str, **changes) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return

            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = utc_now_iso()
            self._write_job_record(job)

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            return

        self._update_job(job_id, status="running", progress=1, message="Starting render")

        try:
            output_path = render_video(
                job.request,
                self.paths,
                progress_callback=lambda progress, message: self._update_job(
                    job_id,
                    progress=progress,
                    message=message,
                    status="running",
                ),
            )
        except Exception as exc:
            error_message = "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
            self._update_job(
                job_id,
                status="failed",
                progress=100,
                message="Render failed",
                error=error_message,
            )
            shutil.rmtree(job.work_dir, ignore_errors=True)
            return

        self._update_job(
            job_id,
            status="completed",
            progress=100,
            message="Video is ready",
            output_name=output_path.name,
        )
        shutil.rmtree(job.work_dir, ignore_errors=True)
