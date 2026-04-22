# VideoMaker V1.4

VideoMaker V1.4 is a Flask web app for creating narrated MP4 videos from a voice-over plus either uploaded images or auto-downloaded keyword images.

## V1.4 Production Fixes

- Streams animation and transition frames instead of keeping large frame lists in RAM.
- Uses a fast FFmpeg voice-over/SFX/music mix path by default, avoiding a second full MoviePy video encode.
- Adds sound effects by default, with background music and overlay selectable per render.
- Skips risky overlay processing automatically on long or high-resolution renders.
- Stores lightweight job status files so a restart reports interrupted jobs cleanly.
- Fixes frontend polling so failed or missing jobs never display `undefined%`.
- Uses per-render auto-image folders instead of one shared image cache.
- Trims deployment dependencies to the packages this Flask app actually needs.
- Ships Docker and Render settings for predictable FFmpeg support.

## Local Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

## Important Environment Variables

- `FLASK_SECRET_KEY`: required for production.
- `PORT`: server port.
- `VIDEO_MAKER_DATA_DIR`: writable folder for exports, uploads, temp files, and job records.
- `VIDEO_MAKER_WORKERS`: render workers. Keep `1` on small servers.
- `WEB_CONCURRENCY`: Gunicorn app workers. Keep `1` unless job state is moved to a real queue/database.
- `GUNICORN_THREADS`: request threads. Default `4`.
- `GUNICORN_TIMEOUT`: worker timeout. Default `600`.
- `MAX_UPLOAD_MB`: upload size limit. Default `256`.
- `VIDEO_MAKER_BG_MUSIC`: global switch for user-selected background music. Default `1`.
- `VIDEO_MAKER_SFX`: global switch for sound effects. Default `1`.
- `VIDEO_MAKER_OVERLAY`: global switch for user-selected overlay video composition. Default `1`.
- `VIDEO_MAKER_OVERLAY_PIXEL_SECOND_BUDGET`: safety budget for overlay. Lower it on small servers.

Sound effects and background music use FFmpeg audio mixing and are much lighter than overlay. Overlay still requires video composition, so V1.4 automatically skips it when the estimated workload is too risky.

## Render Deployment

Use a new Render web service with:

- Runtime: Docker
- Dockerfile path: `./Dockerfile`
- Health check path: `/healthz`
- Persistent disk mount path: `/app/data`

Do not reuse an old start command such as `gunicorn firstpro.wsgi:application`. This app starts with:

```bash
gunicorn -c gunicorn.conf.py --bind 0.0.0.0:${PORT} app:app
```

## VPS Deployment

Docker is recommended:

```bash
docker build -t videomaker-v1-4 .
docker run -d --name videomaker \
  -p 10000:10000 \
  -e FLASK_SECRET_KEY=replace-with-a-long-random-secret \
  -e VIDEO_MAKER_DATA_DIR=/app/data \
  -v videomaker-data:/app/data \
  videomaker-v1-4
```

For Nginx, proxy to `http://127.0.0.1:10000` and set upload limits high enough for your audio/image files.

## Notes

Rendering video is CPU-heavy. On small Render plans or low-RAM VPS instances, keep one render worker. Sound effects are enabled by default; background music and overlay are selected from the web form. Overlay may be skipped automatically when it would put the server at risk.
