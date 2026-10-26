from pathlib import Path

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.gp import gp_Pnt

from pa2.cli import _runtime
from pa2.cad.shapes import compound
from pa2.cad.contacts import ContactService
from pa2.settings.config import AppSettings
from pa2.storage.database import ContactRecord, ImportSnapshotRecord, Project


def test_old_snapshot_upgrade_persists_and_cancel_preserves_existing(tmp_path):
    path=tmp_path/"assembly.step"
    writer=STEPControl_Writer()
    writer.Transfer(compound([BRepPrimAPI_MakeBox(gp_Pnt(0,0,0),1,1,1).Shape(),
                              BRepPrimAPI_MakeBox(gp_Pnt(1,0,0),1,1,1).Shape()]),STEPControl_AsIs)
    writer.Write(str(path))
    layout,db,projects,imports=_runtime(tmp_path/"data")
    project=projects.create("upgrade","test","test")
    result=imports.prepare(project.id,path,[],AppSettings())
    assert result.snapshot.calculation_ready
    with db.session() as session:
        row=session.get(ImportSnapshotRecord,result.snapshot.id)
        row.calculation_ready=False
        row.diagnostics_json=[{"code":"CONTACT_GRAPH","complete":False,"unknown_pairs":[["a","b"]]}]
        session.get(Project,project.id).current_confirmation_id="preserved-confirmation"
    old=imports.reopen(project.id)
    assert not old.snapshot.calculation_ready
    with pytest.raises(InterruptedError):
        imports.ensure_contacts(old,AppSettings(),cancel_check=lambda:True)
    assert not imports.reopen(project.id).snapshot.calculation_ready
    imports.ensure_contacts(old,AppSettings())
    upgraded=imports.reopen(project.id)
    assert upgraded.snapshot.calculation_ready
    assert len(upgraded.snapshot.contacts)==1
    graph=next(d for d in upgraded.snapshot.diagnostics if d["code"]=="CONTACT_GRAPH")
    assert graph["version"]==ContactService.VERSION
    with db.session() as session:
        assert session.get(Project,project.id).current_confirmation_id=="preserved-confirmation"
        assert session.query(ContactRecord).filter_by(snapshot_id=result.snapshot.id).count()==1
    # Repeated generation reuses a compatible completed graph.
    imports.ensure_contacts(upgraded,AppSettings(),progress=lambda *_:pytest.fail("unexpected recomputation"))
