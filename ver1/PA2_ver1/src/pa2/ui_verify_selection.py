"""Read-only real-model selection check, explicitly enabled by GUI smoke."""
def verify_selection(window,destination):
    from PySide6.QtCore import Qt
    from PIL import Image
    from pa2.jobs.isolated import IsolatedCadWorker
    from pa2.cad.path_check import ConservativePathChecker
    page=window.model_page;scene=page.vtk_scene
    before=page.plan.to_dict();snapshot_id=window.import_result.snapshot.id
    camera=scene.renderer.GetActiveCamera()
    def pose():return (camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp(),camera.GetParallelScale(),camera.GetViewAngle())
    initial_camera=pose();baseline={gid for gid,a in scene.actors.items() if a.GetVisibility()}
    groups=[g for g in window.import_result.snapshot.groups if g.id!=page.base.currentData()]
    groups.sort(key=lambda g:(not g.id.startswith('manual-'),g.display_name))
    ids={g.id for g in groups[:2]}
    calls=[];native=IsolatedCadWorker.call;check=ConservativePathChecker.check
    def forbidden(*args,**kwargs):calls.append(True);raise AssertionError('Selection invoked CAD validation')
    IsolatedCadWorker.call=forbidden;ConservativePathChecker.check=forbidden
    def require(condition,message):
        if not condition:raise AssertionError(message)
    def select(selected):
        page.parts.blockSignals(True)
        try:
            for i in range(page.parts.count()):page.parts.item(i).setSelected(page.parts.item(i).data(Qt.UserRole) in selected)
        finally:page.parts.blockSignals(False)
        page.parts.itemSelectionChanged.emit()
    def visible():return {gid for gid,actor in scene.actors.items() if actor.GetVisibility()}
    try:
        select(ids);require(visible()==baseline,'Selection changed explicit visibility')
        require(all(abs(a.GetProperty().GetOpacity()-(1 if gid in ids else .1))<1e-8
                    for gid,a in scene.actors.items()),'Multi context opacity differs')
        require(page.group_button.isEnabled(),'Grouping became disabled')
        Image.fromarray(scene.rgb_array()).save(destination.with_name(destination.stem+'-selection.png'))
        select({next(iter(ids))});require(visible()==baseline,'Single selection did not restore model')
        select(ids);select(set());require(visible()==baseline,'Clearing selection did not restore model')
        select(ids);page._show_all();require(visible()==set(scene.actors),'Show-all override failed')
        select(ids)
        page.order.clearSelection()
        for i in range(page.order.count()):page.order.item(i).setSelected(page.order.item(i).data(Qt.UserRole) in ids)
        require(visible()==set(scene.actors),'Sequence card selection still isolates model')
        select(set())
        require(pose()==initial_camera,'Camera zoom or pose changed')
        require(page.plan.to_dict()==before,'Selection modified sequence')
        require(window.import_result.snapshot.id==snapshot_id,'Selection modified grouping snapshot')
        require(not calls,'Selection called CAD')
        return {'ok':True,'selected_ids':sorted(ids),'total_groups':len(scene.actors),'highlighted_count':len(ids),
            'multi_context_opacity':.1,
            'single_and_clear_restore':True,'show_all_override':True,'cards_do_not_isolate':True,
            'camera_unchanged':True,'plan_and_snapshot_unchanged':True,'cad_calls':len(calls)}
    finally:
        IsolatedCadWorker.call=native;ConservativePathChecker.check=check
        page._clear_part_isolation()
        for gid,actor in scene.actors.items():actor.SetVisibility(gid in baseline)
        scene.highlight(set())
