from dataclasses import replace

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir
from OCP.gp import gp_Pnt

from pa2.cad.path_check import ConservativePathChecker
from pa2.cad.support import support_check
from pa2.domain.models import AssemblyGroup, Bounds, GeometryDecision, MatchingStatus, PartType
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings


def group(identifier, bounds):
    return AssemblyGroup(identifier, identifier, [identifier], PartType.UNKNOWN, bounds, 1.0, bounds.center, True, MatchingStatus.UNMATCHED)


def box(x, y, z, dx, dy, dz):
    return BRepPrimAPI_MakeBox(gp_Pnt(x,y,z), dx,dy,dz).Shape()


def test_thin_intermediate_obstacle_is_not_skipped():
    moving = group("moving", Bounds(0,0,0,1,1,1)); obstacle = group("thin", Bounds(5,0,0,5.05,1,1))
    checker = ConservativePathChecker(0.001, 0.01, 10)
    result = checker.check(moving, box(0,0,0,1,1,1), [(obstacle, box(5,0,0,.05,1,1))], (1,0,0), 10, {"moving","thin"})
    assert result.decision == GeometryDecision.BLOCKED


def test_boundary_contact_moving_apart_has_swept_proof():
    moving = group("moving", Bounds(0,0,0,1,1,1)); behind = group("behind", Bounds(-1,0,0,0,1,1))
    checker = ConservativePathChecker(0.001, 0.01, 10)
    result = checker.check(moving, box(0,0,0,1,1,1), [(behind, box(-1,0,0,1,1,1))], (1,0,0), 3, {"moving","behind"})
    assert result.decision == GeometryDecision.PASS


def test_boundary_slide_is_clear_but_thin_obstacle_blocks():
    moving = group("moving", Bounds(0,0,1,1,1,2))
    floor = group("floor", Bounds(-1,-1,0,8,2,1))
    checker = ConservativePathChecker(.001,.001,10)
    shape = box(0,0,1,1,1,1)
    slide = checker.check(moving,shape,[(floor,box(-1,-1,0,9,3,1))],(1,0,0),10,{"moving","floor"})
    assert slide.decision == GeometryDecision.PASS
    thin = group("thin", Bounds(5,0,1,5.01,1,2))
    blocked = checker.check(moving,shape,[(floor,box(-1,-1,0,9,3,1)),(thin,box(5,0,1,.01,1,1))],(1,0,0),10,{"moving","floor","thin"})
    assert blocked.decision == GeometryDecision.BLOCKED


def test_initial_overlap_is_blocked_and_reported():
    moving = group("moving",Bounds(0,0,0,1,1,1))
    obstacle = group("obstacle",Bounds(.5,0,0,1.5,1,1))
    result = ConservativePathChecker(.001,.001,10).check(moving,box(0,0,0,1,1,1),[(obstacle,box(.5,0,0,1,1,1))],(-1,0,0),3,{"moving","obstacle"})
    assert result.decision == GeometryDecision.BLOCKED
    assert result.reason_code == "INITIAL_OVERLAP"


def test_cylinder_axial_removal_from_touching_plate():
    moving=group("pin",Bounds(-.5,-.5,1,.5,.5,2))
    floor=group("plate",Bounds(-2,-2,0,2,2,1))
    shape=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0,0,1),gp_Dir(0,0,1)),.5,1).Shape()
    result=ConservativePathChecker(.001,.001,10).check(moving,shape,
        [(floor,box(-2,-2,0,4,4,1))],(0,0,1),3,{"pin","plate"})
    assert result.decision==GeometryDecision.PASS


def test_side_contact_is_not_support():
    base = group("base", Bounds(0,0,0,1,1,1)); side = group("side", Bounds(1,0,1,2,1,2))
    result, evidence = support_check([base, side], "base", 0.05, True)
    assert result == GeometryDecision.UNKNOWN
    assert evidence["unsupported"] == ["side"]


def test_planner_reverses_verified_removal_order():
    base = group("base", Bounds(-2,0,0,-1,1,1)); a = group("a", Bounds(0,0,0,1,1,1)); b = group("b", Bounds(3,0,0,4,1,1))
    shapes = {"base":box(-2,0,0,1,1,1), "a":box(0,0,0,1,1,1), "b":box(3,0,0,1,1,1)}
    settings = replace(AppSettings(), support_enabled=False, max_directions=6, generation_timeout_sec=1800)
    result = Planner(settings).generate("p",1,"s",[base,a,b],[],shapes,"base")
    assert result.status.value == "COMPLETE"
    assert [step.group_id for step in result.assembly_plan.steps] == list(reversed(result.removal_order))
    result.assembly_plan.validate()


def test_touching_stack_generates_complete_order_with_support_enabled(tmp_path):
    base=group("base",Bounds(0,0,0,2,2,1))
    top=group("top",Bounds(0,0,1,1,1,2))
    result=Planner(AppSettings()).generate("p",1,"s",[base,top],[],
        {"base":box(0,0,0,2,2,1),"top":box(0,0,1,1,1,1)},"base",jobs_dir=tmp_path)
    assert result.status.value == "COMPLETE"
    assert result.removal_order == ["top"]
    result.assembly_plan.validate()


def test_cancelling_planner_returns_cancelled_not_partial(tmp_path):
    import threading
    cancelled=threading.Event()
    base=group("base",Bounds(0,0,0,1,1,1))
    top=group("top",Bounds(0,0,1,1,1,2))
    result=Planner(AppSettings()).generate("p",1,"s",[base,top],[],
        {"base":box(0,0,0,1,1,1),"top":box(0,0,1,1,1,1)},"base",
        jobs_dir=tmp_path,cancel_check=cancelled.is_set,progress=lambda *_:cancelled.set())
    assert result.status.value == "CANCELLED"


def test_three_touching_layers_support_graph_allows_order(tmp_path):
    from pa2.domain.models import ContactEdge
    base=group("base",Bounds(0,0,0,2,2,1))
    middle=group("middle",Bounds(0,0,1,2,2,2))
    top=group("top",Bounds(0,0,2,1,1,3))
    contacts=[ContactEdge("base","middle",0),ContactEdge("middle","top",0)]
    result=Planner(AppSettings()).generate("p",1,"s",[base,middle,top],contacts,
        {"base":box(0,0,0,2,2,1),"middle":box(0,0,1,2,2,1),"top":box(0,0,2,1,1,1)},"base",jobs_dir=tmp_path)
    assert result.status.value == "COMPLETE"
    assert result.removal_order == ["top","middle"]
    assert result.metrics["support_edges"]==2

