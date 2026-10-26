"""Same recorded assembly frames, CPU/GPU encoding timing and decoded PSNR."""
import json,time,subprocess,tempfile
from pathlib import Path
import numpy as np
import imageio_ffmpeg
from pa2.video.encoding import encoder_arguments,probe_encoders

def main():
    root=Path('runtime-data/native-validation'); folder=root/'video-encoder-v17'; folder.mkdir(exist_ok=True)
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    source=root/'video-v16-final/PA2_assembly_v16.mp4'
    raw=folder/'source.rgb'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-ss','8','-i',str(source),'-frames:v','90',
                    '-f','rawvideo','-pix_fmt','rgb24',str(raw)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    rows=[]
    for probe in probe_encoders(ffmpeg,1920,1080,30):
        if not probe['supported']:rows.append(dict(probe)); continue
        encoder=probe['encoder']; destination=folder/(encoder+'.mp4')
        started=time.perf_counter()
        result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i',str(raw),
            '-an',*encoder_arguments(encoder),'-pix_fmt','yuv420p','-movflags','+faststart',str(destination)],capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        elapsed=time.perf_counter()-started
        if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace'))
        decoded=folder/(encoder+'.rgb')
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-i',str(destination),'-f','rawvideo','-pix_fmt','rgb24',str(decoded)],check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        a=np.memmap(raw,dtype=np.uint8,mode='r'); b=np.memmap(decoded,dtype=np.uint8,mode='r')
        if a.shape!=b.shape:raise RuntimeError('Decoded frame count differs')
        squared=0.
        for start in range(0,a.size,1920*1080*3):
            diff=a[start:start+1920*1080*3].astype(np.float32)-b[start:start+1920*1080*3].astype(np.float32)
            squared+=float(np.square(diff).sum(dtype=np.float64))
        mse=squared/a.size; psnr=float(10*np.log10(255**2/mse)) if mse else None
        del a,b; decoded.unlink()
        rows.append({'encoder':encoder,'supported':True,'elapsed_sec':elapsed,'bytes':destination.stat().st_size,'psnr_db':psnr,'frames':90})
        print(json.dumps(rows[-1]),flush=True)
    raw.unlink()
    (root/'video-encoder-v17.json').write_text(json.dumps({'source':str(source),'same_frames':True,'rows':rows},indent=2),encoding='utf-8')

if __name__=='__main__':main()
