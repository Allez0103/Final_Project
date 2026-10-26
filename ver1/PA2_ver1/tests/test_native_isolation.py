import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from pa2.cad.contacts import ContactService
from pa2.cad.isolated import NativeCadSession
from pa2.domain.models import AssemblyGroup, Bounds, MatchingStatus, PartType
from pa2.jobs.isolated import IsolatedCadWorker, NativeCallError, NativeTimeout


def make_group(index):
    return AssemblyGroup(str(index),str(index),[str(index)],PartType.UNKNOWN,
        Bounds(index,0,0,index+1,1,1),1.0,(index+.5,.5,.5),True,MatchingStatus.UNMATCHED)


def stall_worker(connection, cancel, files):
    connection.recv()
    connection.send(("operation", "TEST_UNRESPONSIVE_NATIVE"))
    time.sleep(30)


def crash_worker(connection, cancel, files):
    import os
    connection.recv()
    os._exit(7)


def test_more_than_32_groups_completes_exact_contact_graph(tmp_path):
    groups=[make_group(i) for i in range(33)]
    shapes={str(i):BRepPrimAPI_MakeBox(gp_Pnt(i,0,0),1,1,1).Shape() for i in range(33)}
    result=ContactService(.05,20).build(groups,[],SimpleNamespace(shapes=shapes),jobs_dir=tmp_path)
    assert result.complete
    assert result.candidate_count == 32
    assert len(result.edges) == 32
    assert not result.unknown_pairs
    assert not list(tmp_path.iterdir())


def test_hung_native_call_times_out_and_worker_can_restart(tmp_path,monkeypatch):
    import pa2.jobs.isolated as module
    original=module._serve
    monkeypatch.setattr(module,"_serve",stall_worker)
    worker=IsolatedCadWorker({},native_timeout=2)
    started=time.monotonic()
    with pytest.raises(NativeTimeout):
        worker.call("anything",{},deadline=time.monotonic()+3)
    assert time.monotonic()-started < 5
    assert worker.process is None
    monkeypatch.setattr(module,"_serve",original)
    # A real BREP operation succeeds after a prior worker termination.
    groups=[make_group(0),make_group(1)]
    shapes={str(i):BRepPrimAPI_MakeBox(gp_Pnt(i,0,0),1,1,1).Shape() for i in range(2)}
    with NativeCadSession(groups,shapes,native_timeout=20,jobs_dir=tmp_path) as restarted:
        assert restarted.call("distance",("0","1")) == pytest.approx(0)


def test_cancel_interrupts_hung_native_call_within_five_seconds(monkeypatch):
    import pa2.jobs.isolated as module
    monkeypatch.setattr(module,"_serve",stall_worker)
    cancel=threading.Event()
    worker=IsolatedCadWorker({},native_timeout=30,cancel_check=cancel.is_set)
    timer=threading.Timer(.5,cancel.set)
    started=time.monotonic()
    timer.start()
    try:
        with pytest.raises(InterruptedError):
            worker.call("anything",{})
        assert time.monotonic()-started < 5
        assert worker.process is None
    finally:
        timer.cancel()
        worker.close()


def test_worker_crash_does_not_hang_parent(monkeypatch):
    import pa2.jobs.isolated as module
    monkeypatch.setattr(module,"_serve",crash_worker)
    worker=IsolatedCadWorker({},native_timeout=20)
    with pytest.raises(NativeCallError):
        worker.call("anything",{})
    assert worker.process is None


def test_threshold_solver_respects_holes_and_detects_face_only_contact(tmp_path):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from pa2.cad.native_worker import CadDispatcher
    from OCP.BRepTools import BRepTools
    ring=BRepAlgoAPI_Cut(BRepPrimAPI_MakeCylinder(2,1).Shape(),BRepPrimAPI_MakeCylinder(1,1).Shape()).Shape()
    center=BRepPrimAPI_MakeCylinder(.5,1).Shape()
    a=BRepPrimAPI_MakeBox(gp_Pnt(-2,-.25,0),4,.5,1).Shape()
    b=BRepPrimAPI_MakeBox(gp_Pnt(-.25,-2,1),.5,4,1).Shape()
    files={}
    for identifier,shape in (("ring",ring),("center",center),("a",a),("b",b)):
        path=tmp_path/f"{identifier}.brep"
        assert BRepTools.Write_s(shape,str(path))
        files[identifier]=str(path)
    worker=IsolatedCadWorker(files,native_timeout=20)
    try:
        assert worker.call("distance",{"groups":("ring","center"),"gap":.05})>.05
        assert worker.call("distance",{"groups":("a","b"),"gap":.05})<=.05
    finally:
        worker.close()


def test_native_support_uses_faces_and_rejects_side_contact(tmp_path):
    from OCP.BRepTools import BRepTools
    shapes={"base":BRepPrimAPI_MakeBox(gp_Pnt(0,0,0),2,2,1).Shape(),
            "top":BRepPrimAPI_MakeBox(gp_Pnt(0,0,1),1,1,1).Shape(),
            "side":BRepPrimAPI_MakeBox(gp_Pnt(2,0,0),1,1,1).Shape()}
    files={}
    for identifier,shape in shapes.items():
        path=tmp_path/f"{identifier}.brep"
        assert BRepTools.Write_s(shape,str(path))
        files[identifier]=str(path)
    worker=IsolatedCadWorker(files,20)
    try:
        assert worker.call("support",{"groups":("top","base"),"gap":.05,"epsilon":.001})==[("top","base")]
        assert worker.call("support",{"groups":("side","base"),"gap":.05,"epsilon":.001})==[]
    finally:
        worker.close()
