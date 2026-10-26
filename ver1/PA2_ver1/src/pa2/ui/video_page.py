"""Native local MP4 preview and render progress."""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, Signal, QEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                              QComboBox,QSlider,QProgressBar,QFileDialog)
from .transport import configure_transport, update_play_button


class VideoPage(QWidget):
    render_requested=Signal()
    cleanup_requested=Signal()
    export_requested=Signal(object)

    def __init__(self):
        super().__init__(); root=QVBoxLayout(self)
        self.confirmation_id=None
        self.info=QLabel('확정된 순서가 없습니다.'); self.info.setWordWrap(True); root.addWidget(self.info)
        actions=QHBoxLayout(); self.generate=QPushButton('영상 생성'); self.generate.setProperty('primary',True)
        self.cleanup=QPushButton('최신 버전만 남기기'); self.cleanup.setToolTip('현재 프로젝트의 정상 생성된 최신 영상 1개를 유지하고 이전 영상 삭제')
        self.export=QPushButton('파일 내보내기')
        self.generate.setEnabled(False); self.cleanup.setEnabled(False); self.export.setEnabled(False)
        self.generate.clicked.connect(self.render_requested); self.cleanup.clicked.connect(self.cleanup_requested); self.export.clicked.connect(self._export)
        for w in (self.generate,self.cleanup,self.export):actions.addWidget(w)
        actions.addStretch(); root.addLayout(actions)
        self.progress_bar=QProgressBar(); self.progress_bar.setRange(0,100); self.progress_bar.setValue(0)
        self.progress_label=QLabel('영상 생성 대기'); root.addWidget(self.progress_bar); root.addWidget(self.progress_label)
        self.video=QVideoWidget(); self.video.setMinimumHeight(260); self.video.installEventFilter(self); root.addWidget(self.video,1)
        self.player=QMediaPlayer(self); self.audio=QAudioOutput(self); self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio); self.player.setVideoOutput(self.video)
        playback_widget=QWidget();playback_widget.setObjectName('playbackBar')
        controls=QHBoxLayout(playback_widget);controls.setContentsMargins(8,4,8,4);controls.setSpacing(4)
        self.first_button=QPushButton();self.previous_button=QPushButton()
        self.play=QPushButton();self.next_button=QPushButton();self.last_button=QPushButton()
        for button,name,title in ((self.first_button,'first','처음으로'),(self.previous_button,'previous','5초 뒤로'),
                                  (self.next_button,'next','5초 앞으로'),(self.last_button,'last','끝으로')):
            configure_transport(button,name,title)
        self.first_button.clicked.connect(lambda:self._seek_to(0))
        self.previous_button.clicked.connect(lambda:self._skip(-5000))
        self.next_button.clicked.connect(lambda:self._skip(5000))
        self.last_button.clicked.connect(lambda:self._seek_to(self.player.duration()))
        self.play.clicked.connect(self._toggle_play);update_play_button(self.play,False)
        self.seek=QSlider(Qt.Horizontal); self.seek.setRange(0,0); self.seek.sliderMoved.connect(self._seek_to)
        self.time_label=QLabel('00:00 / 00:00');self.time_label.setProperty('muted',True);self.time_label.setMinimumWidth(100)
        self.rate=QComboBox(); self.rate.addItems(['0.25×','0.5×','1×','1.5×','2×','3×','4×']); self.rate.setCurrentText('1×')
        self.rate.setToolTip('재생 배속');self.rate.setFixedWidth(75)
        self.rate.currentTextChanged.connect(lambda s:self.player.setPlaybackRate(float(s.rstrip('×'))))
        self.fullscreen=QPushButton('전체화면'); self.fullscreen.clicked.connect(self._toggle_fullscreen)
        self.video.fullScreenChanged.connect(lambda full:self.fullscreen.setText('전체화면 해제' if full else '전체화면'))
        for w in (self.first_button,self.previous_button,self.play,self.next_button,self.last_button,self.time_label,self.rate):controls.addWidget(w)
        controls.addStretch();controls.addWidget(self.fullscreen)
        root.addWidget(playback_widget);root.addWidget(self.seek)
        self.result=QLabel(''); self.result.setWordWrap(True); root.addWidget(self.result)
        self.player.positionChanged.connect(self._position); self.player.durationChanged.connect(self._duration)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.mediaStatusChanged.connect(lambda _:self._sync_controls())
        self.player.sourceChanged.connect(lambda _:self._sync_controls())
        self.player.errorOccurred.connect(lambda _error,message:self.result.setText('미리보기 오류: '+message))
        self.decoded_preview_frames=0
        self.video.videoSink().videoFrameChanged.connect(self._frame)
        self._sync_controls()

    def _sync_controls(self):
        ready=not self.player.source().isEmpty() and self.player.duration()>0
        for widget in (self.first_button,self.previous_button,self.play,self.next_button,self.last_button,
                       self.seek,self.rate,self.fullscreen):widget.setEnabled(ready)

    def _playback_state(self,state):
        update_play_button(self.play,state==QMediaPlayer.PlayingState)

    def _duration(self,milliseconds):
        self.seek.setRange(0,max(0,milliseconds));self._position(self.player.position());self._sync_controls()

    def _seek_to(self,milliseconds):
        self.player.setPosition(max(0,min(int(milliseconds),self.player.duration())))

    def _skip(self,milliseconds):
        self._seek_to(self.player.position()+milliseconds)

    def _toggle_fullscreen(self):
        self.video.setFullScreen(not self.video.isFullScreen())
        if self.video.isFullScreen():self.video.setFocus(Qt.OtherFocusReason)

    def _frame(self,frame):
        if frame.isValid():self.decoded_preview_frames+=1

    def eventFilter(self,obj,event):
        if obj is self.video and event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:
            self.video.setFullScreen(False); return True
        return super().eventFilter(obj,event)

    def _toggle_play(self):
        if self.player.source().isEmpty() or self.player.duration()<=0:return
        if self.player.playbackState()==QMediaPlayer.PlayingState:self.player.pause()
        else:
            if self.player.position()>=self.player.duration():self.player.setPosition(0)
            self.player.play()

    def _position(self,milliseconds):
        if not self.seek.isSliderDown():self.seek.setValue(milliseconds)
        def stamp(ms):return f'{ms//60000:02d}:{ms//1000%60:02d}'
        self.time_label.setText(stamp(milliseconds)+' / '+stamp(self.player.duration()))

    def confirmed(self,cid,partial=False):
        self.reset()
        self.confirmation_id=cid
        self.info.setText(f"{'검토용 부분 순서' if partial else '확정본'} {cid}")
        self.progress_label.setText('현재 확정본의 영상 생성 필요')
        self.generate.setEnabled(True)

    def require_confirmation(self,pending=False):
        self.generate.setEnabled(False)
        self.progress_label.setText('작업 속성의 수정값을 선택 단계에 적용한 뒤 순서를 확정하세요.' if pending else '수정된 순서를 다시 확정한 뒤 영상을 생성하세요.')

    def reset(self):
        self.video.setFullScreen(False)
        self.player.stop(); self.player.setSource(QUrl())
        self.video_path=None
        self.confirmation_id=None
        self.seek.setRange(0,0); self.time_label.setText('00:00 / 00:00')
        self.generate.setEnabled(False); self.export.setEnabled(False)
        self.info.setText('확정된 순서가 없습니다.'); self.result.setText('')
        self.progress_bar.setRange(0,100); self.progress_bar.setValue(0); self.progress_label.setText('영상 생성 대기')
        self._sync_controls()

    def started(self):
        self.player.pause(); self.generate.setEnabled(False); self.cleanup.setEnabled(False)
        self.progress_bar.setRange(0,0); self.progress_label.setText('장면 준비 중')

    def progress(self,done,total):
        self.progress_bar.setRange(0,max(1,total)); self.progress_bar.setValue(done)
        self.progress_label.setText(f'영상 생성 {done/total*100:.1f}% · {done:,}/{total:,}프레임' if total else '장면 준비 중')

    def stopped(self,message):
        self.generate.setEnabled(bool(self.confirmation_id)); self.cleanup.setEnabled(True)
        self.progress_bar.setRange(0,100); self.progress_bar.setValue(0); self.progress_label.setText(message)

    def rendered(self,path):
        self.video_path=Path(path); self.result.setText(f'생성 완료: {path}')
        self.generate.setEnabled(True); self.cleanup.setEnabled(True); self.export.setEnabled(True)
        self.progress_bar.setRange(0,100); self.progress_bar.setValue(100); self.progress_label.setText('영상 생성 완료')
        self.player.setSource(QUrl.fromLocalFile(str(self.video_path.resolve())))

    def _export(self):
        path,_=QFileDialog.getSaveFileName(self,'MP4 내보내기','PA2_assembly.mp4','MP4 (*.mp4)')
        if path:self.export_requested.emit(Path(path))
