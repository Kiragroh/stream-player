"""Local file inspection and interruptible, cached FFmpeg preparation."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg

EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.m4v', '.webm', '.wmv', '.flv', '.mpg', '.mpeg', '.ts', '.m2ts', '.mts', '.ogv', '.vob', '.3gp'}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def inspect_media(path):
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-i', str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, creationflags=NO_WINDOW)
    text = result.stderr
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
    video = re.search(r'Stream #0:(\d+)[^\n]*?: Video: ([^\n]+)', text)
    if not video:
        raise ValueError('Keine lesbare Videospur gefunden. Die Datei ist beschädigt oder das Format wird nicht unterstützt.')
    description = video.group(2)
    dimensions = re.search(r'\b(\d{2,5})x(\d{2,5})\b', description)
    fps = re.search(r'([\d.]+) fps', description)
    width, height = (int(dimensions[1]), int(dimensions[2])) if dimensions else (0, 0)
    codec = description.split(' ')[0].split(',')[0]
    copy_video = codec == 'h264' and bool(re.search(r'\byuv420p[,(]', description))
    copy_video = copy_video and 0 < width <= 1920 and 0 < height <= 1080 and float(fps[1] if fps else 999) <= 30
    audio = re.search(r'Stream #0:(\d+)[^\n]*?: Audio: ([^\n]+)', text)
    audio_description = audio.group(2) if audio else ''
    audio_codec = audio_description.split(' ')[0].split(',')[0]
    direct_audio = not audio or audio_codec == 'aac' and ('stereo' in audio_description or 'mono' in audio_description)
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3]) if duration else 0
    return {'duration': seconds, 'width': width, 'height': height, 'codec': codec, 'audio_codec': audio_codec, 'copy_video': bool(copy_video), 'direct': bool(copy_video and direct_audio and path.suffix.lower() in {'.mp4', '.m4v'}), 'video_index': int(video[1]), 'audio_index': int(audio[1]) if audio else None}


class Library:
    def __init__(self, cache):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.items = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='prepare')
        self.processes = {}
        self.closed = False

    def add(self, raw_path):
        path = Path(raw_path.strip().strip('"')).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError('Bitte eine vorhandene Videodatei auswählen (z. B. MP4, MKV oder AVI).')
        stat = path.stat()
        identity = hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}:v1'.encode()).hexdigest()[:24]
        with self.lock:
            if identity in self.items and self.items[identity]['state'] != 'error':
                return self.public(self.items[identity])
            item = {'id': identity, 'name': path.name, 'format': path.suffix[1:].upper(), 'size': stat.st_size, 'state': 'queued', 'progress': 0, 'duration': 0, 'path': path, 'output': None, 'error': None, 'mode': 'Prüfen'}
            self.items[identity] = item
        self.executor.submit(self.prepare, identity)
        return self.public(item)

    def public(self, item):
        return {k: v for k, v in item.items() if k not in {'path', 'output'}}

    def list(self):
        with self.lock:
            return [self.public(x) for x in self.items.values()]

    def ready(self, identity):
        with self.lock:
            item = self.items.get(identity)
            if not item or item['state'] != 'ready':
                raise ValueError('Das Video ist noch nicht bereit.')
            return item.copy()

    def prepare(self, identity):
        with self.lock:
            item = self.items.get(identity)
            if item is None or self.closed:
                return
            item['state'] = 'preparing'
        partial = self.cache / f'{identity}.partial.mp4'
        process = None
        try:
            info = inspect_media(item['path'])
            with self.lock:
                item.update({k: info[k] for k in ('duration', 'width', 'height', 'codec', 'audio_codec')})
            target = self.cache / f'{identity}.mp4'
            if info['direct']:
                target = item['path']
                item['mode'] = 'Direkt abspielbar'
            elif target.is_file() and target.stat().st_size > 0:
                item['mode'] = 'Bereits vorbereitet'
            else:
                item['mode'] = 'Ton & Container anpassen' if info['copy_video'] else 'Video kompatibel machen'
                args = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-y', '-i', str(item['path']), '-map', f'0:{info["video_index"]}']
                if info['audio_index'] is not None:
                    args += ['-map', f'0:{info["audio_index"]}']
                args += ['-map_metadata', '-1', '-sn']
                if info['copy_video']:
                    args += ['-c:v', 'copy']
                else:
                    args += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-vf', "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2", '-r', '30', '-profile:v', 'high', '-level:v', '4.1']
                args += ['-c:a', 'aac', '-ac', '2', '-b:a', '192k', '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(partial)]
                with open(self.cache / f'{identity}.log', 'w', encoding='utf-8') as log:
                    with self.lock:
                        if self.closed or identity not in self.items:
                            return
                        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log, text=True, creationflags=NO_WINDOW)
                        self.processes[identity] = process
                    for line in process.stdout:
                        if line.startswith('out_time_us=') and info['duration']:
                            try:
                                item['progress'] = min(99, round(int(line.split('=')[1]) / (info['duration'] * 10000)))
                            except ValueError:
                                pass
                    if process.wait() != 0:
                        raise ValueError('Vorbereitung fehlgeschlagen. Prüfe die Datei und freien Speicherplatz; Details stehen im lokalen Cache-Log.')
                partial.replace(target)
            with self.lock:
                item.update(output=target, state='ready', progress=100)
        except Exception as exc:
            with self.lock:
                item.update(state='error', error=str(exc))
            partial.unlink(missing_ok=True)
        finally:
            if process and process.poll() is None:
                process.terminate()
            with self.lock:
                self.processes.pop(identity, None)

    def remove(self, identity):
        with self.lock:
            item = self.items.pop(identity, None)
            process = self.processes.get(identity)
            if process and process.poll() is None:
                process.terminate()
            return item is not None

    def close(self):
        with self.lock:
            self.closed = True
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
        self.executor.shutdown(wait=True, cancel_futures=True)
