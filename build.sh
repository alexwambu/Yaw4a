#!/usr/bin/env bash
set -e
python -m pip install --upgrade pip
pip install -r requirements.txt
# ensure ffmpeg available; Render's base image usually has ffmpeg,
# but if not, you must install it via apt in a custom image or use a buildpack.
