import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import time
import imageio_ffmpeg
import httpx
import pytest
from stream_player.media import Library, NO_WINDOW, inspect_media
from stream_player.streaming import MediaServer

@pytest.fixture(scope='session')
def samples(tmp_path_factory):
    folder = tmp_path_factory.mktemp('videos')
    options = {'mp4': ['-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-ac','2'], 'mkv': ['-c:v','libx264','-pix_fmt','yuv420p','-c:a','ac3'], 'avi': ['-c:v','mpeg4','-c:a','pcm_s16le'], 'webm': ['-c:v','libvpx-vp9','-c:a','libopus']}
    for ext,args in options.items():
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','4',*args,str(folder/f'test.{ext}')],check=True,creationflags=NO_WINDOW)
    return folder

def wait_ready(library, identity):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        item=library.items[identity]
        if item['state'] in {'ready','error'}:
            assert item['state']=='ready',item.get('error')
            return item
        time.sleep(.05)
    pytest.fail('Preparation timed out')

@pytest.mark.parametrize('ext,mode',[('mp4','Direkt abspielbar'),('mkv','Ton & Container anpassen'),('avi','Video kompatibel machen'),('webm','Video kompatibel machen')])
def test_real_formats(samples,tmp_path,ext,mode):
    library=Library(tmp_path)
    try:
        item=wait_ready(library,library.add(str(samples/f'test.{ext}'))['id'])
        assert item['mode']==mode
        info=inspect_media(item['output'])
        assert info['codec']=='h264' and info['audio_codec']=='aac' and info['direct']
        assert info['duration']>=3.9
        result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(item['output']),'-f','null','-'],capture_output=True,creationflags=NO_WINDOW)
        assert result.returncode==0,result.stderr
    finally:
        library.close()

@pytest.fixture
def service(tmp_path,samples):
    library=Library(tmp_path)
    item=wait_ready(library,library.add(str(samples/'test.mp4'))['id'])
    server=MediaServer(library,host='127.0.0.1')
    with httpx.Client(base_url=f'http://127.0.0.1:{server.server.server_port}') as client:
        yield library,item,server,client
    server.close()
    library.close()

def test_only_shared_media_accessible(service):
    library,item,server,client=service
    endpoint=f'/video/{server.token}/{item["id"]}.mp4'
    assert client.get(endpoint).status_code==404
    server.identity=item['id']
    assert client.get(endpoint).status_code==200
    assert client.get(endpoint.replace(server.token,'wrong')).status_code==404
    assert client.get('/').status_code==404
    assert client.get('/api/state').status_code==404
    server.revoke()
    assert client.get(endpoint).status_code==404

@pytest.mark.parametrize('header,kind',[('bytes=0-31','first'),('bytes=-16','last'),('bytes=16-47','middle')])
def test_byte_ranges(service,header,kind):
    library,item,server,client=service
    server.identity=item['id']
    original=item['output'].read_bytes()
    expected={'first':original[:32],'last':original[-16:],'middle':original[16:48]}[kind]
    response=client.get(f'/video/{server.token}/{item["id"]}.mp4',headers={'Range':header})
    assert response.status_code==206 and response.content==expected
    assert response.headers['accept-ranges']=='bytes'

def test_head_and_invalid_ranges(service):
    library,item,server,client=service
    server.identity=item['id']
    endpoint=f'/video/{server.token}/{item["id"]}.mp4'
    response=client.head(endpoint)
    assert response.status_code==200 and response.content==b''
    assert int(response.headers['content-length'])==item['output'].stat().st_size
    for header in ['bytes=999999999-','bytes=-0','bytes=','bytes=9-2','bytes=0-1,4-8']:
        assert client.get(endpoint,headers={'Range':header}).status_code==416

def test_bad_file_and_remove_preserves_original(tmp_path,samples):
    library=Library(tmp_path/'cache')
    try:
        with pytest.raises(ValueError):library.add(str(tmp_path/'missing.mp4'))
        original=samples/'test.mp4'
        item=wait_ready(library,library.add(str(original))['id'])
        library.remove(item['id'])
        assert original.is_file()
        corrupt=tmp_path/'bad.avi';corrupt.write_text('not a video')
        identity=library.add(str(corrupt))['id']
        for _ in range(100):
            if library.items[identity]['state']=='error':break
            time.sleep(.05)
        assert library.items[identity]['state']=='error'
    finally:library.close()

def test_native_player_decodes_and_seeks(tmp_path,samples,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QMediaPlayer
    from stream_player.desktop import PlayerWindow,STYLE
    from stream_player.casting import Casting
    monkeypatch.setattr(Casting,'discover',lambda self:None)
    app=QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window=PlayerWindow(tmp_path)
    frames=[]
    window.video.videoSink().videoFrameChanged.connect(lambda frame:frames.append(frame.isValid()))
    def until(predicate):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
        pytest.fail('Native playback condition timed out')
    try:
        window.add_files([str(samples/'test.mp4')])
        until(lambda:window.current()['state']=='ready')
        window.refresh()
        window.toggle()
        until(lambda:any(frames))
        assert window.player.error()==QMediaPlayer.Error.NoError
        window.seek(2)
        until(lambda:window.player.position()>=1900)
        window.toggle()
        assert window.player.playbackState()==QMediaPlayer.PlaybackState.PausedState
        window.change_volume(30)
        assert abs(window.audio.volume()-.3)<.01
        window.mute()
        assert window.audio.isMuted()
    finally:
        window.close()
        app.processEvents()
