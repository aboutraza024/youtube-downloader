#!/usr/bin/env python3
"""
YouTube Video Downloader API
Downloads full videos or segments based on mode, serves them to frontend, then deletes from server.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
import subprocess
import uvicorn
from urllib.parse import urlparse
import asyncio

app = FastAPI(title="YouTube Downloader API")


# --- Dependency Check ---
def check_dependencies():
    try:
        subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("yt-dlp is not installed. Install with: pip install yt-dlp")

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("ffmpeg is not installed. Install from https://ffmpeg.org/")


# --- URL Validation ---
def _is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if not parsed.scheme or not parsed.netloc:
        return False
    hostname = parsed.netloc.lower()
    return hostname.endswith("youtube.com") or hostname.endswith("youtu.be")


def validate_youtube_url_downloadable(url: str) -> None:
    if not _is_youtube_url(url):
        raise ValueError("Provided URL is not a valid YouTube link.")
    check_dependencies()
    cmd = [
        'yt-dlp',
        '--simulate',  # do not download
        '--skip-download',
        '--quiet',
        '--no-warnings',
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or '').strip()
        raise ValueError(f"The provided YouTube URL is not downloadable. {stderr}")


# --- Video Download Functions ---
def download_full_video(url, quality=720, output_filename=None):
    validate_youtube_url_downloadable(url)
    output_dir = Path("downloads")
    output_dir.mkdir(exist_ok=True)
    if not output_filename:
        output_filename = "full_video.mp4"
    output_path = output_dir / output_filename
    cmd = [
        'yt-dlp',
        '--format', f'best[height<={quality}]',
        '--output', str(output_path),
        url
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error downloading video: {e.stderr}")


def download_video_segment(url, start_time, end_time, quality=720, output_filename=None):
    validate_youtube_url_downloadable(url)
    duration = end_time - start_time
    output_dir = Path("downloads")
    output_dir.mkdir(exist_ok=True)
    if not output_filename:
        output_filename = f"video_segment_{start_time}s_to_{end_time}s.mp4"
    output_path = output_dir / output_filename
    cmd = [
        'yt-dlp',
        '--format', f'best[height<={quality}]',
        '--external-downloader', 'ffmpeg',
        '--external-downloader-args', f'ffmpeg:-ss {start_time} -t {duration}',
        '--output', str(output_path),
        url
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error downloading video segment: {e.stderr}")


# --- Request Model ---
class VideoRequest(BaseModel):
    url: str
    quality: int = 720
    mode: str = Field(default="full", description="Download mode: 'full' or 'segment'")
    start_time: int | None = Field(default=None, description="Segment start time in seconds")
    end_time: int | None = Field(default=None, description="Segment end time in seconds")


# --- Unified API Endpoint ---
@app.post("/download")
async def api_download(request: VideoRequest, background: BackgroundTasks):
    try:
        if request.mode.lower() == "segment":
            if request.start_time is None or request.end_time is None:
                raise HTTPException(
                    status_code=400,
                    detail="For segment mode, start_time and end_time must be provided"
                )
            file_path = await asyncio.to_thread(
                download_video_segment,
                request.url,
                request.start_time,
                request.end_time,
                request.quality
            )
        else:
            file_path = await asyncio.to_thread(
                download_full_video,
                request.url,
                request.quality
            )

        response = FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type='video/mp4'
        )
        background.add_task(file_path.unlink, True)  # delete after sending
        return response

    except Exception as e:
        if isinstance(e, ValueError):
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# --- Run Server ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=1000)
