"""Build a relocatable native Windows x64 release with bundled dependencies."""
import hashlib
import os
from importlib import metadata
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stream_player import __version__


def build():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    icon = ROOT / 'build' / 'stream.ico'
    icon.parent.mkdir(exist_ok=True)
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(ROOT / 'stream_player/assets/icon.svg')).render(painter)
    painter.end()
    if not image.save(str(icon)):
        raise RuntimeError('ICO generation failed')
    # Bundling must resolve Windows ICU, not a conflicting DLL from unrelated
    # applications (e.g. Poppler/Conda) inherited through the developer's PATH.
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join([str(Path(sys.base_prefix)), str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])
    for relative in ['build/Stream', 'dist/Stream']:
        if not (ROOT / relative).resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError('Build path escaped workspace')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--windowed', '--name', 'Stream', '--icon', str(icon),
        '--add-data', f'{ROOT / "stream_player/assets"};stream_player/assets',
        '--collect-all', 'imageio_ffmpeg',
        '--exclude-module', 'tkinter', '--exclude-module', 'fastapi',
        '--exclude-module', 'PySide6.QtWebEngineCore',
        '--exclude-module', 'PySide6.QtWebEngineWidgets',
        '--exclude-module', 'PySide6.QtWebEngineQuick',
        str(ROOT / 'run_player.py'),
    ], cwd=ROOT, env=env, check=True)
    package = ROOT / 'dist/Stream'
    for name in ['README.md', 'THIRD_PARTY_NOTICES.md']:
        shutil.copy2(ROOT / name, package / name)
    licenses = package / 'licenses'
    licenses.mkdir(exist_ok=True)
    for name in ['PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'imageio-ffmpeg', 'pychromecast', 'zeroconf', 'protobuf', 'requests', 'casttube']:
        dist = metadata.distribution(name)
        for item in dist.files or []:
            if any(word in str(item).lower() for word in ['license', 'copying', 'copyright']) and dist.locate_file(item).is_file():
                target = licenses / name / str(item).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(item), target)
    # Python redistributors must preserve the interpreter license as well.
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists():
        shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
    archive = ROOT / f'dist/Stream-{__version__}-Windows-x64-portable.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(package.rglob('*')):
            if path.is_file() and 'data' not in path.relative_to(package).parts:
                output.write(path, Path('Stream') / path.relative_to(package))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT / 'dist/SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Portable release: {archive}\nSHA256: {digest}')


if __name__ == '__main__':
    build()
