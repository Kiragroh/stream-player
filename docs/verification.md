# Verification

Native desktop edition 1.1.0, Windows x64 / Python 3.12 / Qt 6.12.

- 11 automated tests pass: real MP4, MKV (H.264/AC3), AVI (MPEG-4/PCM) and WebM (VP9/Opus) inputs; complete decoding of prepared outputs.
- Native Qt multimedia test decodes video frames, seeks, pauses, changes volume and mutes.
- The media-only receiver endpoint supports byte ranges and HEAD; wrong tokens, revoked shares, invalid ranges, root and API paths are rejected.
- Corrupt files produce errors; removing a queue item preserves the original file.
- Native Windows EXE and portable packaging are checked separately from the Python development environment.

The earlier prototype was also tested against a real Chromecast HD for play, pause, seek and return-to-PC. Not every listed container/codec combination is individually tested. Apple TV, DLNA, Roku, DRM, subtitles and HDR tone mapping are not implemented.
