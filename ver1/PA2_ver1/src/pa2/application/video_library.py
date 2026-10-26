"""Manage only completed, project-owned videos; never exported copies."""
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
from sqlalchemy import select
from pa2.storage.database import ConfirmationRecord, Project, VideoRecord


NAME=re.compile(r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-[0-9a-f]{8})?\.mp4$',re.I)


def complete_video(path):
    """Decode a tail frame: incomplete/unfinalized containers are not latest."""
    try:
        result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error',
            '-sseof','-1','-i',str(path),'-map','0:v:0','-frames:v','1','-progress','pipe:1','-f','null','-'],
            capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        frames=[int(line.split('=',1)[1]) for line in result.stdout.splitlines() if line.startswith('frame=')]
        return result.returncode==0 and bool(frames and frames[-1]>0)
    except (OSError,subprocess.TimeoutExpired):return False


class VideoLibrary:
    def __init__(self,database,layout):self.database,self.layout=database,layout

    def completed(self,project_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',project_id):raise ValueError('잘못된 프로젝트 ID입니다.')
        root=self.layout.projects.resolve()
        requested=root/project_id/'videos'
        directory=requested.resolve()
        if directory!=requested or not directory.is_relative_to(root) or directory.parent.parent!=root:
            raise ValueError('프로젝트 영상 경로가 관리 영역 밖입니다.')
        with self.database.session() as session:
            if session.get(Project,project_id) is None:raise KeyError('프로젝트가 없습니다.')
            confirmations=set(session.scalars(select(ConfirmationRecord.id).where(ConfirmationRecord.project_id==project_id)))
        rows=[]
        for path in directory.glob('*.mp4'):
            match=NAME.fullmatch(path.name)
            if (not match or match.group(1) not in confirmations or path.is_symlink()
                    or path.resolve().parent!=directory or not path.is_file()):continue
            stat=path.stat()
            if complete_video(path):rows.append((path,stat.st_mtime_ns,stat.st_size))
        return sorted(rows,key=lambda row:(row[1],row[0].name),reverse=True)

    def keep_latest(self,project_id):
        rows=self.completed(project_id)
        if not rows:return {'kept':None,'deleted':[],'freed_bytes':0,'errors':[]}
        kept,kept_time,kept_size=rows[0]
        # Recheck the retained file immediately before any destructive operation.
        stat=kept.stat()
        if (stat.st_mtime_ns,stat.st_size)!=(kept_time,kept_size) or not complete_video(kept):
            raise ValueError('최신 영상이 변경됐습니다. 삭제하지 않았습니다.')
        deleted=[];errors=[];freed=0
        with self.database.session() as session:
            for path,mtime,size in rows[1:]:
                try:
                    stat=path.stat()
                    if path.is_symlink() or path.resolve().parent!=kept.parent or (stat.st_mtime_ns,stat.st_size)!=(mtime,size):
                        errors.append({'name':path.name,'error':'파일 변경 감지'});continue
                    path.unlink()
                    relative=path.relative_to(self.layout.root.resolve()).as_posix()
                    session.query(VideoRecord).filter(VideoRecord.relative_path==relative).delete(synchronize_session=False)
                    deleted.append(path.name);freed+=size
                except OSError as exc:errors.append({'name':path.name,'error':str(exc)})
        return {'kept':str(kept),'deleted':deleted,'freed_bytes':freed,'errors':errors}
