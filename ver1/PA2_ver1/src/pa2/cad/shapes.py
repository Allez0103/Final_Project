from __future__ import annotations

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
from OCP.gp import gp_Trsf, gp_Vec


def compound(shapes: list[TopoDS_Shape]) -> TopoDS_Shape:
    if len(shapes) == 1:
        return shapes[0]
    builder = BRep_Builder()
    result = TopoDS_Compound()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def translated(shape: TopoDS_Shape, vector: tuple[float, float, float]) -> TopoDS_Shape:
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(*vector))
    # A rigid translation can share immutable geometry and carry a location.
    # Booleans use NonDestructive=True, so cached source geometry stays intact.
    return BRepBuilderAPI_Transform(shape, transform, False).Shape()

