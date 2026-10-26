"""Lossless binary BREP for new caches/jobs; read legacy ASCII when requested."""
from pathlib import Path
from OCP.BinTools import BinTools
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape
from pa2.storage.layout import ensure_writable_directory


def write_shape(shape,path):
    ensure_writable_directory(Path(path).parent)
    if not BinTools.Write_s(shape,str(path)):
        raise IOError(f'Binary BREP write failed: {path}')


def read_shape(path):
    shape=TopoDS_Shape()
    ok=BinTools.Read_s(shape,str(path)) if Path(path).suffix=='.binbrep' else BRepTools.Read_s(shape,str(path),BRep_Builder())
    if not ok or shape.IsNull():raise IOError(f'BREP read failed: {path}')
    return shape
