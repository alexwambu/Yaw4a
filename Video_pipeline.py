# video_pipeline.py
"""
Core pipeline to create a movie from a script and assets.

Design notes:
- This is a prototype pipeline using MoviePy for assembly.
- For production-quality visuals/characters/lip-sync, integrate model APIs:
    * Visuals: Stable Diffusion (SDXL), Runway, Make-A-Video, Imagen-Video
    * TTS: ElevenLabs, Azure TTS, Google TTS
    * Lip-sync: Wav2Lip or similar
- The pipeline:
    1. Parse script -> scenes
    2. For each scene, produce a visual clip:
        - If image provided for a character -> create a character clip (pan/zoom + subtle face move)
        - If short clip provided -> use as b-roll
        - Else -> generate scene image (placeholder)
    3. Synthesize voice for narration/dialogue
    4. Compose clip with VFX (fade, color grade), background music
    5. Export in chunks and concatenate to support long duration
"""

import os
import tempfile
from typing import List, Optional
from moviepy.editor import (
    ColorClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
    AudioFileClip,
)
from gtts import gTTS
from PIL import Image
import math
import time

# Basic helpers
def parse_script_to_scenes(script: str):
    """
    Very simple parser: split on double newlines or scene markers (---).
    Returns list of scene dicts: {text, duration_seconds (est), effects}
    """
    raw = [s.strip() for s in script.split("\n\n") if s.strip()]
    scenes = []
    for part in raw:
        # estimate duration by words (150 wpm ~ 2.5 wps)
        words = len(part.split())
        estimated_seconds = max(4, int(words / 2.5))  # crude estimate
        scenes.append({"text": part, "duration": estimated_seconds})
    return scenes


def synthesize_voice(text: str, lang="en", voice_profile: str = "default", out_path="tts.mp3"):
    """
    Quick TTS. gTTS used as default (requires network). Replace with ElevenLabs / local TTS for
    higher quality / character voices.
    """
    tts = gTTS(text=text, lang=lang)
    tts.save(out_path)
    return out_path


def generate_ken_burns_clip_from_image(image_path: str, duration: int = 8, resolution: str = "1920x1080"):
    """
    Create a panning/zooming clip from a static image (Ken Burns effect).
    """
    w, h = map(int, resolution.split("x"))
    img = Image.open(image_path)
    # create ImageClip and resize to cover resolution
    clip = ImageClip(image_path).resize(height=h)
    # If width less than required, resize by width
    if clip.w < w:
        clip = clip.resize(width=w)
    # center crop if needed
    clip = clip.set_duration(duration).fx(lambda c: c)  # placeholder
    # MoviePy supports .set_position and .resize; for pan/zoom use crop with moving window
    # Use simple cross zoom by resizing gradually
    return clip.resize(newsize=(w, h)).set_duration(duration)


def generate_character_clip_from_image(image_path: str, name: str = "char", duration: int = 6, resolution: str = "1280x720"):
    """
    Create a short character clip. For prototyping uses Ken Burns + simple mouth overlay.
    Return path to saved video file.
    """
    out = f"{name}_char_{int(time.time())}.mp4"
    clip = generate_ken_burns_clip_from_image(image_path, duration=duration, resolution=resolution)

    # Add a tiny ambient background (fade-in)
    bg = ColorClip(size=clip.size, color=(0, 0, 0), duration=duration)
    composed = clip.set_position(("center", "center"))
    final = composed.set_start(0).crossfadein(0.3)
    final.write_videofile(out, fps=24, codec="libx264", audio=False, verbose=False, logger=None)
    return out


def apply_scene_effects(video_clip: VideoFileClip, effect_name: Optional[str] = None):
    """
    Placeholder for color grading / VFX
    """
    # MoviePy can apply fx: fadein, fadeout, speedx, resize, etc.
    if effect_name == "cinematic":
        return video_clip.fx(lambda c: c).fx  # placeholder
    return video_clip


def render_scene(scene_text: str, scene_assets: List[str], voice_profile: str, duration_override: Optional[int] = None, resolution: str = "1920x1080", fps: int = 24):
    """
    Create a single scene clip:
    - If asset is an image -> create ken-burns character clip
    - If asset is a short video -> use it (trim/pad)
    - Otherwise create a background color clip with TTS audio
    """
    duration = duration_override or max(4, int(len(scene_text.split()) / 2.5))
    w, h = map(int, resolution.split("x"))
    audio_path = f"tts_{int(time.time())}.mp3"
    synthesize_voice(scene_text, out_path=audio_path)

    # prefer image assets
    clip = None
    for a in scene_assets:
        ext = os.path.splitext(a)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            clip = generate_ken_burns_clip_from_image(a, duration=duration, resolution=resolution)
            break
        elif ext in [".mp4", ".mov", ".webm", ".mkv", ".avi"]:
            v = VideoFileClip(a)
            # trim or loop to duration
            if v.duration >= duration:
                clip = v.subclip(0, duration)
            else:
                # loop to fill
                times = math.ceil(duration / max(0.1, v.duration))
                clip = concatenate_videoclips([v] * times).subclip(0, duration)
            break

    if clip is None:
        # placeholder background
        clip = ColorClip(size=(w, h), color=(10, 10, 30), duration=duration)

    # attach audio
    audio_clip = AudioFileClip(audio_path)
    clip = clip.set_audio(audio_clip).set_duration(duration)

    # apply scene effects if needed
    clip = apply_scene_effects(clip)
    return clip


def chunked_export_and_concatenate(clips, output_path, tmp_dir=None, chunk_seconds=900):
    """
    Exports clips in chunks (to avoid huge memory), then concatenates.
    chunk_seconds: target max duration per temp file (e.g., 15 min = 900s).
    """
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp(prefix="movie_chunks_")
    current = []
    current_duration = 0.0
    temp_paths = []
    idx = 0

    for c in clips:
        dur = c.duration
        if current_duration + dur > chunk_seconds and current:
            # flush current
            tmp_file = os.path.join(tmp_dir, f"part_{idx}.mp4")
            concatenate_videoclips(current).write_videofile(tmp_file, codec="libx264", fps=24, audio_codec="aac", verbose=False, logger=None)
            temp_paths.append(tmp_file)
            idx += 1
            # cleanup clips in current
            for cc in current:
                try:
                    cc.close()
                except:
                    pass
            current = []
            current_duration = 0.0
        current.append(c)
        current_duration += dur

    # flush final
    if current:
        tmp_file = os.path.join(tmp_dir, f"part_{idx}.mp4")
        concatenate_videoclips(current).write_videofile(tmp_file, codec="libx264", fps=24, audio_codec="aac", verbose=False, logger=None)
        temp_paths.append(tmp_file)

    # load temp parts and concatenate
    part_clips = [VideoFileClip(p) for p in temp_paths]
    final = concatenate_videoclips(part_clips)
    final.write_videofile(output_path, codec="libx264", fps=24, audio_codec="aac")
    # cleanup temp files
    for p in temp_paths:
        try:
            os.remove(p)
        except:
            pass
    for pc in part_clips:
        try:
            pc.close()
        except:
            pass
    return output_path


def generate_movie_from_script(
    script: str,
    output_path: str = "movie_out.mp4",
    images: Optional[List[str]] = None,
    clips: Optional[List[str]] = None,
    voice_profile: str = "default",
    fps: int = 24,
    resolution: str = "1920x1080",
    realtime_character: bool = False,
):
    """
    High-level orchestrator. Produces an HD movie from script & assets.
    """
    images = images or []
    clips = clips or []
    scenes = parse_script_to_scenes(script)

    scene_clips = []
    for idx, s in enumerate(scenes):
        assets_for_scene = []
        # simple round-robin assign user assets to scenes if available
        if images:
            assets_for_scene.append(images[idx % len(images)])
        if clips:
            assets_for_scene.append(clips[idx % len(clips)])

        clip = render_scene(
            scene_text=s["text"],
            scene_assets=assets_for_scene,
            voice_profile=voice_profile,
            duration_override=s["duration"],
            resolution=resolution,
            fps=fps,
        )
        scene_clips.append(clip)

    # Export in chunks for long movies and join
    final = chunked_export_and_concatenate(scene_clips, output_path)
    # close clips
    for sc in scene_clips:
        try:
            sc.close()
        except:
            pass
    return final
