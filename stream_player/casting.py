"""Discovery and real Google Cast playback, without browser Cast extensions."""
import ipaddress
import socket
import threading
import time
import uuid

import pychromecast
from pychromecast.models import CastInfo, HostServiceInfo
from zeroconf import Zeroconf


def lan_address(target):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((target, 8009))
        return sock.getsockname()[0]


class Casting:
    def __init__(self):
        self.lock = threading.RLock()
        self.zeroconf = None
        self.browser = None
        self.cast = None
        self.item_id = None
        self.scanning = False
        self.error = None
        self.manual = {}

    def discover(self):
        with self.lock:
            if self.scanning:
                return
            self.scanning = True
        def run():
            try:
                if self.browser is None:
                    self.zeroconf = Zeroconf()
                    self.browser = pychromecast.CastBrowser(pychromecast.SimpleCastListener(), self.zeroconf)
                    self.browser.start_discovery()
                time.sleep(12)
                self.error = None
            except Exception:
                self.error = 'Gerätesuche fehlgeschlagen. WLAN prüfen oder die TV-IP manuell eingeben.'
            finally:
                self.scanning = False
        threading.Thread(target=run, daemon=True).start()

    def devices(self):
        devices = dict(self.manual)
        if self.browser:
            for identity, info in list(self.browser.devices.items()):
                if info.cast_type != 'audio' and info.model_name != 'Google Cast Group':
                    devices[str(identity)] = {'id': str(identity), 'name': info.friendly_name, 'model': info.model_name, 'host': info.host}
        return list(devices.values())

    def add_host(self, host):
        address = ipaddress.ip_address(host)
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            raise ValueError('Bitte die lokale IPv4-Adresse des Fernsehers eingeben.')
        with socket.create_connection((str(address), 8009), timeout=3):
            pass
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f'cast:{address}'))
        self.manual[identity] = {'id': identity, 'name': f'Google TV · {address}', 'model': 'Google Cast', 'host': str(address)}
        return self.manual[identity]

    def play(self, device_id, item, make_url, position=0):
        with self.lock:
            device = next((x for x in self.devices() if x['id'] == device_id), None)
            if not device:
                raise ValueError('Gerät nicht mehr verfügbar. Bitte erneut suchen.')
            if self.cast:
                self.cast.disconnect()
            # Video receiver type is already known from discovery/manual TV selection.
            # Avoid an extra HTTP device-info probe: some Google TVs block port 8008.
            info = CastInfo({HostServiceInfo(device['host'], 8009)}, uuid.UUID(device['id']), device['model'], device['name'], device['host'], 8009, 'cast', None)
            cast = pychromecast.Chromecast(info, timeout=10, tries=2, retry_wait=1)
            try:
                cast.wait(timeout=15)
                cast.media_controller.play_media(make_url(device['host']), 'video/mp4', title=item['name'], current_time=max(0, position), stream_type='BUFFERED')
                cast.media_controller.block_until_active(timeout=20)
            except Exception:
                cast.disconnect()
                raise
            self.cast = cast
            self.item_id = item['id']
            return self.status()

    def status(self):
        if not self.cast:
            return {'connected': False}
        status = self.cast.media_controller.status
        return {'connected': True, 'device': self.cast.name, 'device_id': str(self.cast.uuid), 'item_id': self.item_id, 'state': status.player_state, 'position': status.adjusted_current_time or 0, 'duration': status.duration or 0, 'volume': self.cast.status.volume_level, 'muted': self.cast.status.volume_muted, 'idle_reason': status.idle_reason}

    def control(self, action, value=None):
        with self.lock:
            if not self.cast:
                raise ValueError('Kein Fernseher verbunden.')
            controller = self.cast.media_controller
            if action == 'play':
                controller.play()
            elif action == 'pause':
                controller.pause()
            elif action == 'seek':
                controller.seek(max(0, float(value)))
            elif action == 'volume':
                self.cast.set_volume(max(0, min(1, float(value))))
            elif action == 'mute':
                self.cast.set_volume_muted(bool(value))
            elif action == 'stop':
                controller.stop()
                self.cast.disconnect()
                self.cast = None
                self.item_id = None
            else:
                raise ValueError('Unbekannter Befehl.')
            return self.status()

    def close(self):
        if self.cast:
            self.cast.disconnect()
        if self.browser:
            self.browser.stop_discovery()
        if self.zeroconf:
            self.zeroconf.close()
