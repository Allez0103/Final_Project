from __future__ import annotations

import copy
import uuid
import hashlib
import json
from dataclasses import asdict

from pa2.domain.models import GeometryStatus, Plan
from pa2.domain.models import PlanningStatus, PlanStep
from pa2.storage.database import ConfirmationRecord, Database, PlanRecord, PlanStepRecord, Project
from pa2.storage.database import PlanningPresetRecord, GenerationRecord, ConfirmationAnalysis


class PlanService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_preset(self, project_id, snapshot_id, base_group_id, exception_ids):
        ids=list(dict.fromkeys(exception_ids))
        if not base_group_id:raise ValueError('기준 부품을 선택하세요.')
        if base_group_id in ids:
            raise ValueError('기준 부품은 간섭 예외로 지정할 수 없습니다.')
        with self.database.session() as session:
            if session.get(Project,project_id) is None:raise KeyError('프로젝트를 찾을 수 없습니다.')
            row=session.get(PlanningPresetRecord,project_id)
            if row is None:
                row=PlanningPresetRecord(project_id=project_id); session.add(row)
            row.snapshot_id=snapshot_id; row.base_group_id=base_group_id; row.exception_ids_json=ids

    def load_preset(self, project_id, snapshot_id):
        with self.database.session() as session:
            row=session.get(PlanningPresetRecord,project_id)
            if row is None or row.snapshot_id!=snapshot_id:return None
            return {'base_group_id':row.base_group_id,'exception_ids':list(row.exception_ids_json)}

    def save_draft(self, plan: Plan) -> str:
        with self.database.session() as session:
            project = session.get(Project, plan.project_id)
            if project is None:
                raise KeyError("프로젝트를 찾을 수 없습니다.")
            if project.current_snapshot_id and project.current_snapshot_id!=plan.input_snapshot_id:
                raise ValueError('그룹 구성이 변경됐습니다. 순서를 다시 생성하세요.')
            existing = session.get(PlanRecord, plan.id)
            if existing is None:
                existing = PlanRecord(
                    id=plan.id, project_id=plan.project_id, revision=plan.revision,
                    base_group_id=plan.base_group_id, group_ids_json=plan.group_ids,
                    status=plan.status.value, source_algorithm=plan.source_algorithm,
                    user_modified=plan.user_modified, input_snapshot_id=plan.input_snapshot_id,
                    settings_version=plan.settings_version, preview_version=0,
                )
                session.add(existing)
            else:
                existing.revision += 1
                existing.user_modified = plan.user_modified
                existing.status = plan.status.value
            for old in list(session.query(PlanStepRecord).filter_by(plan_id=plan.id)):
                session.delete(old)
            for step in plan.steps:
                session.add(PlanStepRecord(
                    id=str(uuid.uuid4()), plan_id=plan.id, step_index=step.step_index, group_id=step.group_id,
                    removal_direction_json=list(step.removal_direction), assembly_direction_json=list(step.assembly_direction),
                    travel_mm=step.travel_mm, camera_json={"mode": step.camera_mode, "roll_deg": step.camera_roll_deg}, process_text=step.process_text,
                    material_text=step.material_text, caution_text=step.caution_text,
                    geometry_status=step.geometry_status.value, source_run_id=step.source_run_id,
                    final_transform_json=list(step.final_transform),
                ))
            if project.current_draft_plan_id!=plan.id:project.current_confirmation_id=None
            project.current_draft_plan_id = plan.id
            plan.revision = existing.revision
            return plan.id

    def save_generated(self, result, settings=None):
        """Called once at generation; subsequent edits cannot overwrite this baseline."""
        plan = result.assembly_plan
        if plan is None:
            raise ValueError('저장할 순서가 없습니다.')
        plan_id = self.save_draft(plan)
        with self.database.session() as session:
            if session.query(GenerationRecord).filter_by(plan_id=plan_id).first() is None:
                session.add(GenerationRecord(id=str(uuid.uuid4()), project_id=plan.project_id,
                    plan_id=plan_id, snapshot_id=plan.input_snapshot_id,
                    generation_mode='manual' if plan.source_algorithm.startswith('manual-') else 'auto',
                    plan_snapshot_json=copy.deepcopy(plan.to_dict()), metrics_json=copy.deepcopy(result.metrics),
                    path_results_json=[asdict(p) for p in result.path_results],
                    settings_json=asdict(settings) if settings else {}))
        from pa2.run_log import safe_log
        safe_log(self,'generated',self.generation(plan_id))
        return plan_id

    def generation(self, plan_id):
        with self.database.session() as session:
            return session.query(GenerationRecord).filter_by(plan_id=plan_id).first()

    def load_original(self, plan_id):
        row = self.generation(plan_id)
        return self._from_dict(row.plan_snapshot_json) if row else None

    def analyze_confirmation(self, confirmation_id, groups, exception_ids=()):
        from pa2.learning.comparison import compare_orders
        confirmed = self.load_confirmation(confirmation_id)
        generation = self.generation(confirmed.id)
        if generation is None:
            # A saved, user-edited draft must never be substituted for a missing original.
            return {'available': False, 'reason': '최초 생성 원본이 없는 이전 프로젝트입니다.'}
        original = self._from_dict(generation.plan_snapshot_json)
        exceptions = set(exception_ids) | {s.group_id for s in original.steps+confirmed.steps
                                           if s.geometry_status == GeometryStatus.USER_COLLISION_EXCEPTION}
        metrics = compare_orders(original, confirmed, groups, exceptions)
        metrics.update(available=True, generation_mode=generation.generation_mode)
        with self.database.session() as session:
            if session.get(ConfirmationAnalysis, confirmation_id) is None:
                session.add(ConfirmationAnalysis(confirmation_id=confirmation_id,
                    generation_id=generation.id, metrics_json=metrics))
        from pa2.run_log import safe_log
        with self.database.session() as session:record=session.get(ConfirmationRecord,confirmation_id)
        safe_log(self,'confirmed',generation,record,metrics)
        return metrics

    def recover_original(self, project_id):
        """Recover old generated JSON only; never treat edited DB steps as a baseline."""
        directory = self.database.layout.projects/project_id/'planning'
        for path in sorted(directory.glob('*.json')):
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
                payload = raw.get('assembly_plan') or raw.get('plan')
                if not payload or payload.get('project_id') != project_id:
                    continue
                with self.database.session() as session:
                    row = session.get(PlanRecord, payload['id'])
                    if row is None or session.query(GenerationRecord).filter_by(plan_id=row.id).first():
                        continue
                    session.add(GenerationRecord(id=str(uuid.uuid4()), project_id=project_id,
                        plan_id=row.id, snapshot_id=payload['input_snapshot_id'],
                        generation_mode='manual' if payload['source_algorithm'].startswith('manual-') else 'auto',
                        plan_snapshot_json=payload, metrics_json=raw.get('metrics', {}),
                        path_results_json=raw.get('path_results', raw.get('paths', [])), settings_json={}))
            except (ValueError, KeyError, TypeError, OSError):
                continue

    @staticmethod
    def content_signature(plan):
        fields=('group_id','step_index','removal_direction','assembly_direction','travel_mm',
                'camera_mode','camera_roll_deg','process_text','material_text','caution_text','final_transform')
        raw={'base':plan.base_group_id,'groups':sorted(plan.group_ids),'snapshot':plan.input_snapshot_id,
             'steps':[{field:getattr(step,field) for field in fields} for step in plan.steps]}
        # SQLite Float columns restore 10 as 10.0; that must not invalidate an
        # otherwise unchanged confirmation after a project is reopened.
        for step in raw['steps']:
            step['travel_mm']=float(step['travel_mm'])
            for field in ('removal_direction','assembly_direction','final_transform'):
                step[field]=[float(value) for value in step[field]]
        return hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def matches_confirmation(self,plan,confirmation_id):
        if not plan or not confirmation_id:return False
        try:confirmed=self.load_confirmation(confirmation_id)
        except KeyError:return False
        return confirmed.project_id==plan.project_id and self.content_signature(confirmed)==self.content_signature(plan)

    def refresh_preview(self, plan: Plan) -> Plan:
        # The scene evaluator consumes the same immutable copy later used by video rendering.
        candidate = copy.deepcopy(plan)
        for index, step in enumerate(candidate.steps, start=1):
            step.step_index = index
            step.validate()
        with self.database.session() as session:
            record = session.get(PlanRecord, plan.id)
            if record is not None:
                record.preview_version += 1
        return candidate

    def confirm(self, plan: Plan, *, allow_partial: bool = False) -> str:
        plan.validate(allow_partial=allow_partial)
        if allow_partial and not plan.steps:
            raise ValueError("확정할 단계가 없습니다.")
        if plan.user_modified:
            for step in plan.steps:
                if step.geometry_status != GeometryStatus.USER_COLLISION_EXCEPTION:
                    step.geometry_status = GeometryStatus.USER_CONFIRMED_UNCHECKED
        self.save_draft(plan)
        confirmation_id = str(uuid.uuid4())
        with self.database.session() as session:
            session.add(ConfirmationRecord(
                id=confirmation_id, project_id=plan.project_id, plan_id=plan.id,
                plan_snapshot_json=plan.to_dict(),
            ))
            project = session.get(Project, plan.project_id)
            if project is not None:
                project.current_confirmation_id = confirmation_id
        from pa2.run_log import safe_log
        with self.database.session() as session:record=session.get(ConfirmationRecord,confirmation_id)
        safe_log(self,'confirmed',self.generation(plan.id),record)
        return confirmation_id

    def load_current_draft(self, project_id: str) -> Plan | None:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None or not project.current_draft_plan_id:
                return None
            record = session.get(PlanRecord, project.current_draft_plan_id)
            if record is None:
                return None
            rows = list(session.query(PlanStepRecord).filter_by(plan_id=record.id).order_by(PlanStepRecord.step_index))
            steps = [PlanStep(
                group_id=row.group_id, step_index=row.step_index,
                removal_direction=tuple(row.removal_direction_json), assembly_direction=tuple(row.assembly_direction_json),
                travel_mm=row.travel_mm, camera_mode=row.camera_json.get("mode", "AUTO"),
                camera_roll_deg=row.camera_json.get("roll_deg", 0),
                process_text=row.process_text, material_text=row.material_text, caution_text=row.caution_text,
                geometry_status=GeometryStatus(row.geometry_status), source_run_id=row.source_run_id,
                final_transform=tuple(row.final_transform_json),
            ) for row in rows]
            return Plan(
                id=record.id, project_id=record.project_id, revision=record.revision,
                base_group_id=record.base_group_id, group_ids=list(record.group_ids_json), steps=steps,
                status=PlanningStatus(record.status), source_algorithm=record.source_algorithm,
                user_modified=record.user_modified, input_snapshot_id=record.input_snapshot_id,
                settings_version=record.settings_version,
            )

    def load_confirmation(self, confirmation_id: str) -> Plan:
        with self.database.session() as session:
            record=session.get(ConfirmationRecord,confirmation_id)
            if record is None:raise KeyError('확정본을 찾을 수 없습니다.')
            raw=copy.deepcopy(record.plan_snapshot_json)
        return self._from_dict(raw)

    @staticmethod
    def _from_dict(raw):
        raw=copy.deepcopy(raw)
        steps=[]
        for item in raw['steps']:
            item['geometry_status']=GeometryStatus(item['geometry_status'])
            for field in ('removal_direction','assembly_direction','final_transform'):item[field]=tuple(item[field])
            steps.append(PlanStep(**item))
        raw['steps']=steps; raw['status']=PlanningStatus(raw['status'])
        return Plan(**raw)

