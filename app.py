from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any
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
TOOL_NAME = "Free Video Maker"
SITE_DESCRIPTION = "Free Video Maker is an online AI video maker and faceless video maker for turning voice-overs, images, transitions, sound effects, and optional background music into finished MP4 videos."
CONTACT_EMAIL = os.getenv("SITE_CONTACT_EMAIL", "techliciousgyan@gmail.com")
BLOG_POSTS = [
    {
        "slug": "how-to-make-faceless-videos-fast",
        "title": "How To Make Faceless Videos Faster Without Losing Quality",
        "description": "A practical workflow for turning a voice-over and a few images into a clean faceless video faster.",
        "published": "April 23, 2026",
        "content": [
            "The fastest video workflow usually starts with a clean voice-over. When your narration is already trimmed and clear, the rest of the edit becomes simpler because timing decisions are easier to make.",
            "Use a small set of focused images instead of dozens of random visuals. Strong, related images produce a cleaner result and reduce the chance of awkward transitions.",
            "If you are publishing consistently, save time by standardizing your format. Pick one long-video layout and one short-video layout, then reuse those settings instead of rebuilding your process each time.",
            "Sound effects can add motion and energy, but too many layers slow down rendering and make the final mix feel busy. Use them selectively, then add background music only when it supports the voice-over."
        ]
    },
    {
        "slug": "best-images-for-voice-over-videos",
        "title": "What Images Work Best For Voice-Over Videos",
        "description": "Learn how to choose images that match your narration and improve the feel of simple slideshow-style videos.",
        "published": "April 23, 2026",
        "content": [
            "Images with one clear subject almost always work better than crowded visuals. The more obvious the subject is, the better zooms and transitions feel.",
            "Try to keep the image style consistent across the whole video. Mixing completely different color tones, illustration styles, or lighting can make even a good script feel disconnected.",
            "Keyword-based image search works best when your phrases are specific. Instead of broad keywords, use descriptive phrases that describe the exact scene you want the audience to see.",
            "If you are building content for monetization, make sure you have the right to use every image and media file. Clean asset rights matter for both trust and ad policy compliance."
        ]
    },
    {
        "slug": "before-you-apply-for-adsense-on-a-tool-site",
        "title": "Before You Apply For AdSense On A Tool Website",
        "description": "A simple checklist for turning an online tool into a more complete, AdSense-ready website.",
        "published": "April 23, 2026",
        "content": [
            "A tool alone is often not enough. Add clear navigation, an About page, a Contact page, a Privacy Policy, Terms, and a few helpful articles so the website looks complete and trustworthy.",
            "Keep the homepage focused on what the tool does, who it helps, and how to use it. Remove internal language that sounds like a development dashboard or a private project.",
            "Use a custom domain, make sure the site works well on mobile, and avoid intrusive ad placements near important action buttons like upload, create, preview, or download.",
            "If your tool works with media, be careful about copyright and source quality. Responsible usage language and transparent policies help both users and monetization review."
        ]
    },
    {
        "slug": "how-to-run-a-faceless-youtube-channel",
        "title": "How To Run A Faceless YouTube Channel In A Sustainable Way",
        "description": "A simple system for planning, producing, and publishing faceless YouTube videos without burning out.",
        "published": "April 23, 2026",
        "content": [
            "Running a faceless YouTube channel is less about hiding your face and more about building a repeatable production system. The strongest channels usually rely on a stable topic, a clear audience promise, and a publishing process that can be repeated every week.",
            "Start by choosing one video structure and one thumbnail style that you can reuse. A stable format makes scripting faster, keeps editing simpler, and helps viewers recognize your content more quickly.",
            "Your workflow should be broken into small repeatable parts: topic selection, script outline, voice-over, visuals, editing, thumbnail, and publishing. Once those parts are separated, the whole channel becomes easier to manage.",
            "A faceless channel grows faster when the viewer immediately understands the value of the video. Titles, openings, and thumbnails should be clear and specific rather than mysterious without context."
        ]
    },
    {
        "slug": "how-to-grow-a-youtube-channel-in-2026",
        "title": "How To Grow A YouTube Channel In 2026",
        "description": "A practical growth guide for creators who want better retention, stronger topic selection, and more consistent publishing in 2026.",
        "published": "April 23, 2026",
        "content": [
            "Growing on YouTube in 2026 still comes back to three things: better topic selection, stronger packaging, and more satisfying watch time. Good editing helps, but it does not save a weak topic.",
            "Choose video ideas that solve a problem, answer a question, or create a clear curiosity gap for the right viewer. Viewers click when the promise is understandable and relevant, not just because the edit looks expensive.",
            "Retention starts in the first thirty seconds. Open fast, avoid long self-introductions, and make sure the viewer instantly knows what result they will get by staying.",
            "Consistency matters, but consistency does not mean posting low-quality videos just to stay active. A smaller number of stronger uploads usually works better than many rushed videos."
        ]
    },
    {
        "slug": "how-to-get-a-youtube-silver-play-button",
        "title": "How To Reach A YouTube Silver Play Button",
        "description": "What creators should focus on if they want to reach 100,000 subscribers and qualify for a Silver Play Button.",
        "published": "April 23, 2026",
        "content": [
            "The Silver Play Button is a milestone of 100,000 subscribers, but channels reach it through repeatable value, not one lucky upload. The path is usually a mix of topic focus, packaging quality, and consistent publishing discipline.",
            "If you want to reach six figures in subscribers, build a channel around a clear theme so viewers know what to expect next. Random uploads make it harder for both viewers and the platform to understand your direction.",
            "Study the videos that already bring watch time and subscriber growth. Your best-performing topics should shape future uploads, related series, and follow-up videos.",
            "The creators who reach this milestone often improve the same basics over time: titles, thumbnails, hooks, viewer satisfaction, clarity, and consistency."
        ]
    },
    {
        "slug": "how-to-become-a-faceless-content-creator",
        "title": "How To Become A Faceless Content Creator",
        "description": "A beginner-friendly path for becoming a faceless creator using voice-over, visuals, and simple editing systems.",
        "published": "April 23, 2026",
        "content": [
            "A faceless content creator builds trust through clarity, usefulness, storytelling, and editing rather than personal on-camera presence. That means your content system matters more than personality-driven presentation.",
            "Choose a niche that gives you enough room to publish many related videos. Education, finance explainers, productivity, motivation, health tips, tech basics, and story formats all work well in faceless form when they are handled responsibly.",
            "The easiest way to start is with a voice-over plus visuals workflow. That can include screenshots, stock media, illustrations, AI voice-over, subtitle-driven edits, or simple image-based videos.",
            "To stay consistent, keep your tools lightweight. Use one script format, one editing flow, and one publishing routine so you are not rebuilding your system from zero for every upload."
        ]
    },
    {
        "slug": "how-to-make-faceless-videos",
        "title": "How To Make Faceless Videos For YouTube And Shorts",
        "description": "A clean workflow for creating faceless long-form videos and short videos using voice-over, visuals, and lightweight editing.",
        "published": "April 23, 2026",
        "content": [
            "Faceless videos usually start with a script or topic outline, then move to voice-over, visual collection, editing, music, and export. Keeping those steps separate makes the process far easier to improve.",
            "Your visuals do not need to be complicated. A strong combination of relevant images, motion, transitions, and clean pacing is often enough for educational or explainer content.",
            "If you are making Shorts, keep each line of narration tight and each visual change purposeful. For long-form videos, focus more on flow and topic structure so viewers stay with the video.",
            "Many creators overcomplicate their early videos. Start with a lighter system first, then add more effects only when they improve clarity rather than just adding noise."
        ]
    },
    {
        "slug": "how-to-make-ai-voice-over-with-google-ai-studio-or-elevenlabs",
        "title": "How To Make AI Voice Over With Google AI Studio Or ElevenLabs",
        "description": "A practical overview of creating AI voice-overs for videos using Google AI Studio or ElevenLabs.",
        "published": "April 23, 2026",
        "content": [
            "AI voice-over tools are useful when you need a faster workflow, multiple voice styles, or a cleaner narration tone without recording every script yourself. The two common paths many creators explore are Google AI Studio based workflows and ElevenLabs.",
            "Before generating the voice-over, clean the script first. Add punctuation for pauses, split long sentences, and remove hard-to-pronounce wording where possible. Better script formatting usually produces better synthetic narration.",
            "Test several short samples before generating the entire audio file. Voice choice, pacing, and sentence rhythm can change how professional the final video feels.",
            "Even with AI voice-over, editing still matters. Trim dead space, control volume, and make sure the visuals reinforce the spoken message instead of distracting from it."
        ]
    },
    {
        "slug": "how-to-use-free-video-maker-for-faceless-videos",
        "title": "How To Use Free Video Maker To Create Faceless Videos",
        "description": "A step-by-step guide to using Free Video Maker as a simple faceless video maker and AI-style video editing workflow.",
        "published": "April 23, 2026",
        "content": [
            "Free Video Maker is built for creators who want a simple path from voice-over and visuals to a finished MP4. The easiest workflow is to prepare your narration first, then upload your own images or use targeted keywords for automatic visuals.",
            "On the homepage tool form, upload one voice-over file, choose long or short format, then decide whether you want to upload images manually or let the tool fetch visuals from keywords.",
            "For a richer result, keep sound effects enabled and add background music when it supports the narration. Overlay can be turned on too, but the system may skip it automatically on heavier renders to keep the export stable.",
            "After the render begins, stay on the same page to follow progress, preview the finished video, and download the final export. This makes the tool useful for fast faceless content workflows, especially when you want to publish consistently without using a full editing suite."
        ]
    },
]


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


def _find_post(slug: str) -> dict[str, Any] | None:
    for post in BLOG_POSTS:
        if post["slug"] == slug:
            return post
    return None


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

    @app.context_processor
    def inject_site_globals():
        return {
            "tool_name": TOOL_NAME,
            "site_description": SITE_DESCRIPTION,
            "contact_email": CONTACT_EMAIL,
        }

    @app.get("/")
    def index():
        exports = sorted(paths.exports_dir.glob("video*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        return render_template(
            "index.html",
            exports=exports[:10],
            queue_workers=worker_count,
            page_title=TOOL_NAME,
            meta_description="Free Video Maker is a free AI video maker, faceless video maker, and online video editor for creating narrated MP4 videos from voice-over and images.",
        )

    @app.get("/about")
    def about():
        return render_template(
            "page.html",
            page_title=f"About {TOOL_NAME}",
            meta_description=f"Learn what {TOOL_NAME} does and who it is for.",
            heading=f"About {TOOL_NAME}",
            intro="Free Video Maker helps creators turn a voice-over and a small set of visuals into a finished MP4 without using a complicated editing workflow.",
            sections=[
                {
                    "title": "What the tool does",
                    "body": [
                        "The tool is designed for simple narrated videos, faceless content, quick explainers, slideshow-style videos, short educational clips, and promotional voice-over edits.",
                        "You can upload your own images or generate a visual set from keywords, then export a ready-to-preview video from the browser."
                    ],
                },
                {
                    "title": "Who it is for",
                    "body": [
                        "It is built for solo creators, students, marketers, educators, and small publishers who want a simpler path from script and audio to finished video.",
                        "It works best when you already know the topic you want to explain and you want the video creation step to stay light and direct."
                    ],
                },
            ],
        )

    @app.get("/contact")
    def contact():
        return render_template(
            "page.html",
            page_title=f"Contact {TOOL_NAME}",
            meta_description=f"Contact information and support details for {TOOL_NAME}.",
            heading="Contact",
            intro="For support requests, feedback, partnerships, or copyright concerns, use the contact details below.",
            sections=[
                {
                    "title": "Support email",
                    "body": [
                        f"Email: {CONTACT_EMAIL}",
                        "Please include the page URL, job issue, and a short description of the problem if you are reporting a bug."
                    ],
                },
                {
                    "title": "Response expectations",
                    "body": [
                        "General support questions usually take less time to review than media-rights or abuse reports.",
                        "If you are contacting us about a policy, media rights, or takedown issue, include enough detail for a clear review."
                    ],
                },
            ],
        )

    @app.get("/privacy")
    def privacy():
        return render_template(
            "page.html",
            page_title="Privacy Policy",
            meta_description=f"Privacy Policy for {TOOL_NAME}.",
            heading="Privacy Policy",
            intro="This page explains what information may be processed when you use the tool.",
            sections=[
                {
                    "title": "Uploaded media",
                    "body": [
                        "When you upload audio or images to generate a video, those files are processed by the server to complete your request.",
                        "Temporary files, exports, and processing data may be stored for operational reasons, including rendering, retries, and download access.",
                        "Generated exports may remain on the server for a period of time unless removed through server cleanup, deployment changes, or storage limits."
                    ],
                },
                {
                    "title": "Basic technical data",
                    "body": [
                        "Like most websites, the service may process technical information such as browser type, request timestamps, IP-related request data, and error logs for security and reliability.",
                        "Analytics, monetization, and advertising tools may also use cookies or related technologies depending on how the site is configured.",
                        "Hosting providers, reverse proxies, content delivery systems, and basic application logs may also process technical request details as part of normal website operations."
                    ],
                },
                {
                    "title": "Advertising, analytics, and cookies",
                    "body": [
                        "If advertising or analytics tools are enabled on the site, they may use cookies, local storage, or similar technologies to measure traffic, improve performance, prevent abuse, and support monetization.",
                        "Third-party services may have their own privacy terms and policies. You should review those services directly where relevant."
                    ],
                },
                {
                    "title": "Your responsibility and media rights",
                    "body": [
                        "Do not upload private, confidential, or sensitive information unless you are comfortable with server-side processing required to complete the tool workflow.",
                        "If you use third-party media, make sure you have the right to use it.",
                        "Users are responsible for the legality, ownership, and licensing of the audio, images, keywords, scripts, and other materials they submit through the service."
                    ],
                },
                {
                    "title": "Contact and requests",
                    "body": [
                        f"If you have privacy-related questions, you can contact us at {CONTACT_EMAIL}.",
                        "Operational and policy requests should include enough detail for identification and review, especially if the issue relates to uploaded or generated media."
                    ],
                },
            ],
        )

    @app.get("/terms")
    def terms():
        return render_template(
            "page.html",
            page_title="Terms of Use",
            meta_description=f"Terms of Use for {TOOL_NAME}.",
            heading="Terms of Use",
            intro="By using this website, you agree to use it lawfully and responsibly.",
            sections=[
                {
                    "title": "Acceptable use",
                    "body": [
                        "You must not use the tool to process unlawful, abusive, infringing, or harmful content.",
                        "You are responsible for the media, scripts, audio, keywords, and files you upload or request through the service.",
                        "You must not attempt to misuse the service through abusive automation, denial-of-service behavior, scraping that harms stability, or repeated malicious uploads."
                    ],
                },
                {
                    "title": "No guarantees",
                    "body": [
                        "Rendering speed, output style, optional effects, and exported results can vary based on server load, asset quality, and selected options.",
                        "The service may skip resource-heavy optional effects such as overlay processing when necessary to protect stability.",
                        "The website may be updated, paused, restricted, or changed without prior notice where necessary for technical, operational, legal, or security reasons."
                    ],
                },
                {
                    "title": "Intellectual property",
                    "body": [
                        "You must have the right to use the files and media you upload or request through the tool.",
                        "If you believe your rights have been affected by content processed through the site, contact the support email with enough detail for review.",
                        "The site name, branding, interface copy, and website materials remain protected to the extent allowed by applicable law."
                    ],
                },
                {
                    "title": "User responsibility and risk",
                    "body": [
                        "You are responsible for reviewing generated results before publication, distribution, or commercial use.",
                        "If you use the service for monetized content, client work, or commercial publishing, you should independently verify that your media rights, disclosures, and usage practices are appropriate for your platform and audience."
                    ],
                },
                {
                    "title": "Limitation of service",
                    "body": [
                        "The tool is provided as an online utility and informational service. It may occasionally be unavailable, slower than expected, or limited by hosting, storage, queue load, or provider-level restrictions.",
                        "Using the site does not create a promise of uninterrupted access, guaranteed delivery speed, or permanent storage of generated files."
                    ],
                },
            ],
        )

    @app.get("/blog")
    def blog_index():
        return render_template(
            "blog_index.html",
            page_title="Blog",
            meta_description=f"Helpful articles, tutorials, and publishing tips from {TOOL_NAME}.",
            posts=BLOG_POSTS,
        )

    @app.get("/blog/<slug>")
    def blog_post(slug: str):
        post = _find_post(slug)
        if post is None:
            return render_template(
                "page.html",
                page_title="Article not found",
                meta_description="The requested article could not be found.",
                heading="Article not found",
                intro="The article you requested is not available.",
                sections=[],
            ), 404
        return render_template(
            "blog_post.html",
            page_title=post["title"],
            meta_description=post["description"],
            post=post,
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
