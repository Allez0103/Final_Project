"""Compare saved edits and both immutable confirmations after EXE shutdown."""
import json
from pathlib import Path
from pa2.storage.database import Database
from pa2.storage.layout import DataLayout
from pa2.application.plan_service import PlanService
from pa2.application.project_service import ProjectService

def main():
    folder=Path('runtime-data/native-validation')
    read=lambda name:json.loads((folder/name).read_text(encoding='utf-8'))
    planning=read('planning-v17-final.json'); video=read('video-v17-final/video-validation.json'); ui=read('ui-review-v17-final.json')
    db=Database(DataLayout(Path('runtime-data/end-to-end-v17-final')))
    plans=PlanService(db); project=next(p for p in ProjectService(db).list() if p.id==planning['project_id'])
    draft=plans.load_current_draft(project.id); edited=plans.load_confirmation(project.current_confirmation_id)
    original=plans.load_confirmation(video['confirmation_id'])
    checks={'draft_order_persisted':[s.group_id for s in draft.steps]==ui['edited_order'],
            'edited_confirmation_order':[s.group_id for s in edited.steps]==ui['edited_order'],
            'draft_direction_persisted':list(draft.steps[0].removal_direction)==ui['new_direction'],
            'edited_confirmation_direction':list(edited.steps[0].removal_direction)==ui['new_direction'],
            'original_confirmation_order_unchanged':[s.group_id for s in original.steps]==ui['original_order'],
            'original_directions_unchanged':all(list(s.removal_direction)==p['removal_direction'] for s,p in zip(original.steps,planning['planning']['plan']['steps'])),
            'confirmation_ids_distinct':project.current_confirmation_id!=video['confirmation_id']}
    result={'ok':all(checks.values()),'checks':checks,'original_confirmation':video['confirmation_id'],
            'edited_confirmation':project.current_confirmation_id}
    (folder/'draft-persistence-v17.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if not result['ok']:raise AssertionError('Persisted edit/confirmation mismatch')

if __name__=='__main__':main()
