"""Probe the installed encoders before starting a long render."""
import subprocess
import time
from functools import lru_cache


def encoder_arguments(name):
    if name=='h264_nvenc':return ['-c:v',name,'-preset','p4','-cq','23']
    if name=='h264_qsv':return ['-c:v',name,'-global_quality','23']
    if name=='h264_amf':return ['-c:v',name,'-quality','balanced','-rc','cqp','-qp_i','23','-qp_p','23']
    return ['-c:v','libx264','-crf','23']


@lru_cache(maxsize=32)
def _probe_encoder(ffmpeg,width,height,fps,encoder):
    started=time.perf_counter()
    try:
        result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i',
            f'testsrc2=size={width}x{height}:rate={fps}','-frames:v','30','-an',
            *encoder_arguments(encoder),'-pix_fmt','yuv420p','-f','null','-'],
            capture_output=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return {'encoder':encoder,'supported':result.returncode==0,'elapsed_sec':time.perf_counter()-started,
                'error':result.stderr.decode('utf-8',errors='replace').strip()[-2000:]}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {'encoder':encoder,'supported':False,'elapsed_sec':time.perf_counter()-started,'error':str(exc)}


def probe_encoders(ffmpeg,width,height,fps,cancel_check=lambda:False):
    rows=[]
    for encoder in ('libx264','h264_nvenc','h264_qsv','h264_amf'):
        if cancel_check():raise InterruptedError('영상 생성을 취소했습니다.')
        rows.append(_probe_encoder(ffmpeg,width,height,fps,encoder))
    if cancel_check():raise InterruptedError('영상 생성을 취소했습니다.')
    return tuple(rows)


def select_encoder(ffmpeg,width,height,fps,requested='auto',cancel_check=lambda:False):
    rows=probe_encoders(ffmpeg,width,height,fps,cancel_check)
    supported=[r for r in rows if r['supported']]
    if requested!='auto':
        match=next((r for r in supported if r['encoder']==requested),None)
        if match:return requested,rows
        return 'libx264',rows
    if not supported:raise RuntimeError('ENCODE_FAILED: 사용 가능한 H.264 인코더가 없습니다.')
    return min(supported,key=lambda r:r['elapsed_sec'])['encoder'],rows
