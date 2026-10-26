"""Manual grouping revisions preserve imported atomic groups and old plans."""
import copy
import uuid
from dataclasses import asdict

from sqlalchemy import select

from pa2.domain.models import AssemblyGroup, Bounds, ContactEdge, MatchingStatus, PartType
from pa2.storage.database import (Project, ProjectAsset, ImportSnapshotRecord, AtomicBodyRecord,
    AssemblyGroupRecord, GroupMember, ContactRecord, GroupingStructureRecord, PlanningPresetRecord)


def imported_node(group):
    return {'kind':'import','group':asdict(group)}


def node_id(node):
    return node['id'] if node['kind']=='manual' else node['group']['id']


def leaf_groups(node):
    if node['kind']=='manual':
        return [g for member in node['members'] for g in leaf_groups(member)]
    data=copy.deepcopy(node['group'])
    data['bounds']=Bounds(**data['bounds'])
    data['part_type']=PartType(data['part_type'])
    data['matching_status']=MatchingStatus(data['matching_status'])
    return [AssemblyGroup(**data)]


def composed_group(node):
    if node['kind']!='manual':return leaf_groups(node)[0]
    children=[composed_group(child) for child in node['members']]
    bounds=Bounds.union(g.bounds for g in children)
    volume=sum(g.volume_mm3 or 0 for g in children) if all(g.volume_mm3 is not None for g in children) else None
    center=bounds.center
    if volume and all(g.centroid for g in children):
        center=tuple(sum((g.volume_mm3 or 0)*g.centroid[i] for g in children)/volume for i in range(3))
    kinds={g.part_type for g in children}
    kind=next(iter(kinds)) if len(kinds)==1 else PartType.UNKNOWN
    # A name or bundling operation must not silently bypass general-part paths.
    if kind in (PartType.BOLT,PartType.NUT):kind=PartType.UNKNOWN
    return AssemblyGroup(node['id'],node['name'],[bid for g in children for bid in g.body_ids],
        kind,bounds,volume,center,all(g.geometry_valid for g in children),MatchingStatus.UNKNOWN)


class ManualGroupingService:
    def __init__(self,database):self.database=database

    def structure(self,snapshot_id,groups):
        with self.database.session() as session:
            record=session.get(GroupingStructureRecord,snapshot_id)
            return {'source_snapshot_id':record.source_snapshot_id,'roots':copy.deepcopy(record.roots_json)} if record else {
                'source_snapshot_id':snapshot_id,'roots':[imported_node(g) for g in groups]}

    def change(self,result,selected_ids,*,name=None,ungroup=False,base_id=None,exception_ids=()):
        snapshot=result.snapshot
        structure=self.structure(snapshot.id,snapshot.groups)
        roots=structure['roots']; selected=set(selected_ids)
        if not selected or selected-{node_id(n) for n in roots}:raise ValueError('현재 부품만 선택하세요.')
        if base_id in selected:raise ValueError('기준 부품은 그룹화·해제할 수 없습니다. 기준을 먼저 변경하세요.')
        members=[node for node in roots if node_id(node) in selected]
        if ungroup:
            if len(members)!=1 or members[0]['kind']!='manual':
                raise ValueError('사용자가 만든 수동 그룹만 해제할 수 있습니다. 자동 그룹은 잠겨 있습니다.')
            replacements=members[0]['members']
        else:
            if len(members)<2:raise ValueError('그룹화할 부품을 2개 이상 선택하세요.')
            name=(name or '').strip()
            if not name or len(name)>120:raise ValueError('그룹 이름을 1~120자로 입력하세요.')
            replacements=[{'kind':'manual','id':'manual-'+uuid.uuid4().hex[:20],'name':name,'members':members,
                           'exception_member_ids':sorted(selected & set(exception_ids))}]
        index=next(i for i,node in enumerate(roots) if node_id(node) in selected)
        roots=[node for node in roots if node_id(node) not in selected]
        roots[index:index]=replacements
        groups=[composed_group(node) for node in roots]
        expected={bid for group in snapshot.groups for bid in group.body_ids}
        actual=[bid for group in groups for bid in group.body_ids]
        if set(actual)!=expected or len(actual)!=len(expected):raise ValueError('부품 구성에 중복 또는 누락이 있습니다.')
        # Reuse the original contact graph, so ungrouping recovers exact edges.
        owner={g.id:node_id(node) for node in roots for g in leaf_groups(node)}
        new_sid=str(uuid.uuid4())
        with self.database.session() as session:
            project=session.get(Project,snapshot.project_id)
            if not project or project.current_snapshot_id!=snapshot.id:
                raise ValueError('프로젝트가 변경됐습니다. 다시 불러오세요.')
            source=session.get(ImportSnapshotRecord,structure['source_snapshot_id'])
            current=session.get(ImportSnapshotRecord,snapshot.id)
            edges={}
            for edge in session.scalars(select(ContactRecord).where(ContactRecord.snapshot_id==source.id)):
                a,b=owner[edge.group_a],owner[edge.group_b]
                if a==b:continue
                a,b=sorted((a,b)); pair=(a,b)
                if pair not in edges:edges[pair]=ContactEdge(a,b,edge.distance_mm,{'manual_group_aggregate':True},edge.policy_version)
                elif edge.distance_mm is not None:
                    old=edges[pair].distance_mm
                    edges[pair].distance_mm=edge.distance_mm if old is None else min(old,edge.distance_mm)
            diagnostics=copy.deepcopy(source.diagnostics_json)
            diagnostics=[d for d in diagnostics if d.get('code') not in ('MANUAL_GROUPING','UNMATCHED_BODIES')]
            diagnostics.append({'code':'MANUAL_GROUPING','source_snapshot_id':source.id,
                'manual_group_ids':[node_id(n) for n in roots if n['kind']=='manual'],
                'prior_snapshot_id':snapshot.id,'sequence_regeneration_required':True})
            diagnostics.append({'code':'UNMATCHED_BODIES','body_ids':[bid for n,g in zip(roots,groups)
                if n['kind']=='import' and g.matching_status!=MatchingStatus.MATCHED for bid in g.body_ids]})
            project.revision+=1
            session.add(ImportSnapshotRecord(id=new_sid,project_id=project.id,project_revision=project.revision,
                assembly_asset_hash=current.assembly_asset_hash,scene_ready=True,groups_ready=True,
                calculation_ready=source.calculation_ready,diagnostics_json=diagnostics))
            session.flush()
            for body in session.scalars(select(AtomicBodyRecord).where(AtomicBodyRecord.snapshot_id==snapshot.id)):
                data={c.name:copy.deepcopy(getattr(body,c.name)) for c in AtomicBodyRecord.__table__.columns}
                data.update(id=new_sid+':'+body.id.split(':',1)[1],snapshot_id=new_sid)
                session.add(AtomicBodyRecord(**data))
            for group in groups:
                session.add(AssemblyGroupRecord(id=f'{new_sid}:{group.id}',snapshot_id=new_sid,
                    display_name=group.display_name,part_type=group.part_type.value,part_definition_id=group.part_definition_id,
                    matching_status=group.matching_status.value,bounds_json=asdict(group.bounds),volume_mm3=group.volume_mm3,
                    centroid_json=list(group.centroid) if group.centroid else None,geometry_valid=group.geometry_valid))
            session.flush()
            for group in groups:
                for bid in group.body_ids:session.add(GroupMember(group_id=f'{new_sid}:{group.id}',body_id=f'{new_sid}:{bid}'))
            for edge in edges.values():session.add(ContactRecord(pair_id=f'{new_sid}:{edge.pair_id}',snapshot_id=new_sid,
                group_a=edge.group_a,group_b=edge.group_b,distance_mm=edge.distance_mm,
                evidence_json=edge.evidence,policy_version=edge.policy_version))
            for asset in session.scalars(select(ProjectAsset).where(ProjectAsset.project_id==project.id,
                    ProjectAsset.project_revision==snapshot.project_revision)):
                data={c.name:copy.deepcopy(getattr(asset,c.name)) for c in ProjectAsset.__table__.columns}
                data.update(id=str(uuid.uuid4()),project_revision=project.revision);session.add(ProjectAsset(**data))
            session.add(GroupingStructureRecord(snapshot_id=new_sid,source_snapshot_id=source.id,roots_json=roots))
            preset=session.get(PlanningPresetRecord,project.id)
            if preset is None:preset=PlanningPresetRecord(project_id=project.id);session.add(preset)
            exceptions=set(exception_ids)
            if exceptions & selected:
                exceptions-=selected
                restored=members[0].get('exception_member_ids') if ungroup else None
                exceptions.update(restored or [node_id(n) for n in replacements])
            preset.snapshot_id=new_sid;preset.base_group_id=base_id or (snapshot.groups[0].id)
            preset.exception_ids_json=sorted(exceptions)
            project.current_snapshot_id=new_sid
            project.current_draft_plan_id=None;project.current_confirmation_id=None
        return new_sid
