# main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional
import uvicorn
import os
from video_pipeline import (
    generate_movie_from_script,
    generate_character_clip_from_image,
)

app = FastAPI(title="AI Movie Creator Backend")

# CORS - allow everything for development; restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change to your frontend origin in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "Video Creator API is running!"}


@app.post("/generate_movie")
async def generate_movie(
    script: str = Form(...),
    title: Optional[str] = Form("movie"),
    target_fps: Optional[int] = Form(24),
    target_resolution: Optional[str] = Form("1920x1080"),  # e.g., "1280x720" or "3840x2160"
    # Clients can upload multiple images and clips to be used as characters or b-roll
    images: Optional[List[UploadFile]] = File(None),
    clips: Optional[List[UploadFile]] = File(None),
    voice: Optional[str] = Form("default"),  # voice profile name (map to TTS API)
    realtime_character: Optional[bool] = Form(False),
):
    """
    Main entry: create a movie from a script, optional images/clips.
    Returns JSON with output path (URL when served).
    """
    os.makedirs("uploads", exist_ok=True)
    saved_images = []
    saved_clips = []

    try:
        # Save uploads
        if images:
            for img in images:
                path = os.path.join("uploads", img.filename)
                with open(path, "wb") as f:
                    f.write(await img.read())
                saved_images.append(path)

        if clips:
            for c in clips:
                path = os.path.join("uploads", c.filename)
                with open(path, "wb") as f:
                    f.write(await c.read())
                saved_clips.append(path)

        # Generate movie (this is the main worker - may take long)
        output_filename = f"{title.replace(' ', '_')}.mp4"
        output_path = os.path.abspath(output_filename)

        generate_movie_from_script(
            script=script,
            output_path=output_path,
            images=saved_images,
            clips=saved_clips,
            voice_profile=voice,
            fps=int(target_fps),
            resolution=target_resolution,
            realtime_character=bool(realtime_character),
        )

        # Return path (in production you should return a public URL or upload to S3/R2)
        return {"status": "done", "file": output_filename}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/character_from_image")
async def character_from_image(file: UploadFile = File(...), name: str = Form("character")):
    """
    Generate a short animated character clip from a single image.
    This uses a Ken-Burns / pan-zoom + optional basic face motion approach.
    For production, integrate a character generator / animator model.
    """
    os.makedirs("uploads", exist_ok=True)
    path = os.path.join("uploads", file.filename)
    with open(path, "wb") as f:
        f.write(await file.read())

    out_path = generate_character_clip_from_image(path, name=name, duration=8, resolution="1280x720")
    return {"status": "done", "file": out_path}


@app.get("/download/{filename}")
async def download_file(filename: str):
    if not os.path.exists(filename):
        return JSONResponse(status_code=404, content={"error": "file not found"})
    return FileResponse(filename, media_type="video/mp4", filename=filename)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
