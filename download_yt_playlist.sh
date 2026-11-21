#!/bin/bash

URL="https://www.youtube.com/playlist?list=PLAYLIST_ID"

mkdir -p yt_dlp_output
cd yt_dlp_output
yt-dlp --extract-audio --audio-format vorbis -o "%(playlist_index)s - %(title)s.%(ext)s" "$URL"

for f in *.ogg; do
  ffmpeg -y -i "$f" -c:a libvorbis "tmp_$f" && mv "tmp_$f" "$f"
done