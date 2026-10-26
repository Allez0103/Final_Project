from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
import uuid
import tempfile
from functools import lru_cache
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pa2.cad.importer import CadScene
from pa2.domain.models import AssemblyGroup, Plan
from pa2.rendering.scene import build_timeline, scene_at
from pa2.rendering.vtk_scene import VtkScene
from pa2.settings.config import AppSettings
from pa2.storage.assets import sha256_file
from .encoding import select_encoder, encoder_arguments


@dataclass(frozen=True, slots=True)
class VideoResult:
    path: Path
    checksum: str
    duration_sec: float
    frame_count: int
    encoder: str
    encoder_benchmarks: tuple = ()
    encoder_fallback: str | None = None


class VideoRenderer:
    TEMPLATE_VERSION = "corporate-v5-first-step-landscape"

    def __init__(self, settings: AppSettings, template_path: Path, logo_path: Path | None = None) -> None:
        self.settings = settings
        self.template = json.loads(template_path.read_text(encoding="utf-8"))
        self.logo = Image.open(logo_path).convert("RGBA") if logo_path and logo_path.exists() else None
        self._overlays = {}

    def render(self,plan,scene,groups,output_path,**kwargs):
        deadline=time.monotonic()+self.settings.video_timeout_sec
        try:
            return self._render_once(plan,scene,groups,output_path,_deadline=deadline,**kwargs)
        except (BrokenPipeError,RuntimeError) as exc:
            used=getattr(self,'_last_encoder','libx264')
            if used=='libx264' or (kwargs.get('cancel_event') and kwargs['cancel_event'].is_set()):raise
            if isinstance(exc,RuntimeError) and not str(exc).startswith('ENCODE_FAILED:'):raise
            # Reuse validated template resources; only the encoder setting differs.
            previous=self.settings
            try:
                self.settings=replace(previous,video_encoder='libx264')
                result=self._render_once(plan,scene,groups,output_path,_deadline=deadline,**kwargs)
                return replace(result,encoder_fallback=f'{used}: {exc}')
            finally:self.settings=previous

    def _render_once(
        self,
        plan: Plan,
        scene: CadScene,
        groups: list[AssemblyGroup],
        output_path: Path,
        *,
        vehicle_name: str,
        product_name: str,
        project_name: str,
        progress: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
        _deadline: float | None = None,
    ) -> VideoResult:
        plan.validate(allow_partial=True)
        partial = len(plan.steps) < len(set(plan.group_ids)-{plan.base_group_id})
        if partial and not plan.steps:
            raise ValueError("영상으로 만들 수 있는 단계가 없습니다.")
        deadline = _deadline or time.monotonic()+self.settings.video_timeout_sec
        if cancel_event and cancel_event.is_set():raise InterruptedError('영상 생성을 취소했습니다.')
        if time.monotonic()>=deadline:raise TimeoutError('영상 생성 제한 시간을 초과했습니다.')
        width, height, fps = self.settings.video_width, self.settings.video_height, self.settings.video_fps
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise FileExistsError("기존 출력 파일을 자동으로 덮어쓰지 않습니다.")
        temporary = output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.tmp.mp4")
        timeline = build_timeline(plan, self.settings,scene.bounds)
        names={group.id:group.display_name for group in groups}
        frame_count = max(1, round(timeline.duration * fps))
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        encoder, benchmarks=select_encoder(ffmpeg,width,height,fps,self.settings.video_encoder,
                                           cancel_check=cancel_event.is_set if cancel_event else lambda:False)
        self._last_encoder=encoder
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            "-an", *encoder_arguments(encoder), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary),
        ]
        error_log=tempfile.TemporaryFile()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=error_log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finished=threading.Event(); finalizing=[None]
        def watchdog():
            while not finished.wait(.1):
                expired=time.monotonic()>=deadline or (finalizing[0] is not None and time.monotonic()-finalizing[0]>30)
                if (cancel_event and cancel_event.is_set()) or expired:
                    if process.poll() is None:process.kill()
                    return
        watcher=threading.Thread(target=watchdog,daemon=True); watcher.start()
        vtk_scene = VtkScene(offscreen=True)
        try:
            vtk_scene.load(scene, groups, self.settings.resolved_for_diagonal(scene.bounds.diagonal)["display_mesh_deflection_mm"])
            region=self.template['regions']['scene']
            scene_width=int((region[0]+region[2])*width)-int(region[0]*width)
            scene_height=int((region[1]+region[3])*height)-int(region[1]*height)
            vtk_scene.render_window.SetSize(scene_width,scene_height)
            assert process.stdin is not None
            for frame_index in range(frame_count):
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("영상 생성을 취소했습니다.")
                if time.monotonic() >= deadline:
                    raise TimeoutError("영상 생성 제한 시간을 초과했습니다.")
                t = frame_index / fps
                state = scene_at(plan, t, self.settings,timeline)
                if not state.material_text.strip():
                    gid=state.active_group_id or (plan.steps[state.step_index-1].group_id if state.step_index else plan.base_group_id)
                    state.material_text=names.get(gid,"")
                if partial:
                    state.process_text = f"[부분 조립 {len(plan.steps)}/{len(plan.group_ids)-1}단계] {state.process_text}"
                vtk_scene.apply(state,scene_width,scene_height)
                raw_scene = vtk_scene.rgb_array()
                frame = self._compose(raw_scene, state, vehicle_name, product_name, project_name, width, height)
                process.stdin.write(np.asarray(frame.convert("RGB"), dtype=np.uint8).tobytes())
                if progress and (frame_index % fps == 0 or frame_index == frame_count - 1):
                    progress(frame_index + 1, frame_count)
            finalizing[0]=time.monotonic()
            process.stdin.close()
            return_code = process.wait(timeout=30)
            error_log.seek(0); error=error_log.read().decode('utf-8',errors='replace')
            if return_code != 0:
                raise RuntimeError(f"ENCODE_FAILED: {error.strip()}")
            if not temporary.exists() or temporary.stat().st_size < 1024:
                raise RuntimeError("ENCODE_FAILED: 생성된 MP4가 비어 있습니다.")
            temporary.replace(output_path)
            return VideoResult(output_path, sha256_file(output_path), frame_count / fps, frame_count, encoder+"/yuv420p",benchmarks)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            temporary.unlink(missing_ok=True)
            if cancel_event and cancel_event.is_set():raise InterruptedError('영상 생성을 취소했습니다.')
            if time.monotonic()>=deadline:raise TimeoutError('영상 생성 제한 시간을 초과했습니다.')
            raise
        finally:
            finished.set(); watcher.join(timeout=1)
            if process.stdin and not process.stdin.closed:process.stdin.close()
            error_log.close()
            vtk_scene.render_window.Finalize()

    def export(self, managed_video: Path, destination: Path) -> Path:
        if destination.exists():
            raise FileExistsError("내보낼 위치에 같은 이름의 파일이 이미 있습니다.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copyfile(managed_video, temporary)
        if sha256_file(temporary) != sha256_file(managed_video):
            temporary.unlink(missing_ok=True)
            raise IOError("내보낸 파일의 해시 검증에 실패했습니다.")
        temporary.replace(destination)
        return destination

    @lru_cache(maxsize=64)
    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/NotoSansKR-Regular.ttf")]
        for candidate in candidates:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size=size)
        return ImageFont.load_default()

    def _compose(self, scene_rgb, state, vehicle: str, product: str, project: str, width: int, height: int) -> Image.Image:
        if (width,height)!=(1920,1080):
            # Typography/padding live in the 1080p design coordinate system.
            return self._compose(scene_rgb,state,vehicle,product,project,1920,1080).resize(
                (width,height),Image.Resampling.LANCZOS)
        key=(vehicle,product,project,width,height,state.process_text,state.material_text,state.caution_text)
        if key in self._overlays:
            image=self._overlays[key].copy()
            x,y,w,h=self.template['regions']['scene']
            bounds=(int(x*width),int(y*height),int((x+w)*width),int((y+h)*height))
            scene_image=Image.fromarray(scene_rgb).resize((bounds[2]-bounds[0],bounds[3]-bounds[1]),Image.Resampling.LANCZOS)
            image.paste(scene_image,bounds[:2]); return image
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        regions = self.template["regions"]
        def box(name: str) -> tuple[int, int, int, int]:
            x, y, w, h = regions[name]
            return int(x*width), int(y*height), int((x+w)*width), int((y+h)*height)
        scene_box = box("scene")
        scene_image = Image.fromarray(scene_rgb).resize((scene_box[2]-scene_box[0], scene_box[3]-scene_box[1]), Image.Resampling.LANCZOS)
        image.paste(scene_image, scene_box[:2])
        blue = self.template["colors"]["primary"]
        if 'header' in regions:
            header=box('header')
            draw.rounded_rectangle(header,radius=20,fill='#E9EDFF',outline=blue,width=2)
            title=' · '.join(text for text in (project,vehicle,product) if text)
            self._fit_text(draw,title,header,36,'#111827',centered=True)
        else:  # Keep custom/older templates usable.
            draw.text((box("vehicle")[0], box("vehicle")[1]), vehicle, fill="#111827", font=self._font(36))
            draw.text((box("product")[0], box("product")[1]), f"{product} · {project}", fill="#111827", font=self._font(36))
        if self.logo:
            target = box("logo")
            logo = self.logo.copy()
            logo.thumbnail((target[2]-target[0], target[3]-target[1]), Image.Resampling.LANCZOS)
            image.paste(logo, (target[2]-logo.width, target[1]), logo)
        self._panel(draw, box("material"), "자재정보", state.material_text, blue)
        self._panel(draw, box("caution"), "주의사항", state.caution_text, "#D53232")
        process_box = box("process")
        draw.rounded_rectangle(process_box, radius=20, fill="#E9EDFF", outline=blue, width=2)
        self._fit_text(draw, state.process_text, process_box, 32, "#111827", centered=True)
        # Keep only a small number of full-size panels; the 3D region is replaced
        # on every hit. Static template, logo and text never need re-layout.
        self._overlays[key]=image.copy()
        if len(self._overlays)>4:self._overlays.pop(next(iter(self._overlays)))
        return image

    def _panel(self, draw: ImageDraw.ImageDraw, bounds: tuple[int,int,int,int], title: str, text: str, color: str) -> None:
        draw.rectangle(bounds, outline="#B8C0D8", width=2, fill="#FFFFFF")
        draw.text((bounds[0]+18, bounds[1]+14), title, fill=color, font=self._font(28))
        content = (bounds[0]+18, bounds[1]+62, bounds[2]-18, bounds[3]-14)
        self._fit_text(draw, text, content, 28, "#111827")

    def _fit_text(self, draw: ImageDraw.ImageDraw, text: str, bounds: tuple[int,int,int,int], start_size: int, color: str, centered: bool = False) -> None:
        if not text:
            return
        for size in range(start_size, 19, -1):
            font = self._font(size)
            lines = self._wrap(draw, text, font, bounds[2]-bounds[0]-20)
            line_height = int(size * 1.35)
            if len(lines) * line_height <= bounds[3]-bounds[1]-12:
                y = bounds[1] + ((bounds[3]-bounds[1]-len(lines)*line_height)//2 if centered else 8)
                for line in lines:
                    width = draw.textbbox((0,0), line, font=font)[2]
                    x = bounds[0] + ((bounds[2]-bounds[0]-width)//2 if centered else 8)
                    draw.text((x, y), line, fill=color, font=font)
                    y += line_height
                return
        raise ValueError("문구가 최소 20px에서도 영역을 넘습니다. 편집 화면에서 문구를 줄여 주세요.")

    @staticmethod
    def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            current = ""
            for character in paragraph:
                trial = current + character
                if current and draw.textbbox((0,0), trial, font=font)[2] > max_width:
                    lines.append(current)
                    current = character
                else:
                    current = trial
            lines.append(current)
        return lines

