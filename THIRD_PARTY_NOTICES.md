# Third-party components

Stream's portable archive contains independently licensed components. The original
license texts supplied by the installed distributions are included in `licenses/`.
Shared libraries remain separate and can be replaced; there is no one-file packing,
encryption, obfuscation or restriction on reverse engineering for debugging changes
to LGPL libraries.

| Component | License / upstream source |
| --- | --- |
| Python | PSF license, https://www.python.org/ |
| Qt / PySide6 / Shiboken 6.12.0 | LGPLv3 / GPLv3 / Qt exceptions as applicable; https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/ |
| Qt multimedia FFmpeg libraries | FFmpeg LGPL/GPL notices distributed with Qt; https://ffmpeg.org/ |
| imageio-ffmpeg 0.6.0 | BSD-2-Clause wrapper; https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0 |
| FFmpeg executable | Upstream licenses/configuration apply to the bundled executable; https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0 and https://github.com/BtbN/FFmpeg-Builds |
| PyChromecast | MIT; https://github.com/home-assistant-libs/pychromecast |
| zeroconf | LGPL-2.1-or-later; https://github.com/python-zeroconf/python-zeroconf |
| protobuf | BSD-3-Clause; https://github.com/protocolbuffers/protobuf |
| requests / casttube | Apache-2.0 / MIT; respective package notices |
| PyInstaller bootloader | GPL with distribution exception; https://pyinstaller.org/ |

No Google software or proprietary codecs are represented as authored by this project.
The original generated banner is included as an app asset. User videos are never
distributed. FFmpeg build information is obtainable with the bundled executable's
`-version`, `-buildconf`, and `-L` commands.
