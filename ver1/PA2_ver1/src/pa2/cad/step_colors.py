"""Read XCAF styles without changing the geometry importer or its solid ordering."""
from collections import defaultdict

from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Quantity import Quantity_TOC_sRGB
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.XCAFPrs import XCAFPrs
from OCP.collections import (IndexedDataMap_TopoDS_Shape_XCAFPrs_Style_TopTools_ShapeMapHasher,
                             Sequence_TDF_Label)


def _rgb(style):
    if style.IsSetColorSurf():
        return tuple(style.GetColorSurf().Values(Quantity_TOC_sRGB))
    return None


def _subshapes(shape, kind):
    if shape.ShapeType() == kind:
        return [shape]
    explorer = TopExp_Explorer(shape, kind)
    items = []
    while explorer.More():
        items.append(explorer.Current())
        explorer.Next()
    return items


def apply_step_colors(reader, bodies, shapes):
    """Share the existing STEP work session: no second disk parse or shape edits.

    XCAFPrs resolves nested occurrence/reference placements and inherited styles.
    Whole-solid/part styles take precedence; face-only styles are area-voted.
    """
    caf = STEPCAFControl_Reader(reader.WS(), False)
    caf.SetColorMode(True)
    caf.SetNameMode(False)
    caf.SetLayerMode(False)
    document = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    if not caf.Transfer(document):
        raise RuntimeError('STEP 색상 문서 변환 실패')
    roots = Sequence_TDF_Label()
    XCAFDoc_DocumentTool.ShapeTool_s(document.Main()).GetFreeShapes(roots)
    styles = IndexedDataMap_TopoDS_Shape_XCAFPrs_Style_TopTools_ShapeMapHasher()
    for i in range(1, roots.Length()+1):
        XCAFPrs.CollectStyleSettings_s(roots.Value(i), TopLoc_Location(), styles)
    whole = {}
    face_colors = {}
    for i in range(1, styles.Extent()+1):
        shape, style = styles.FindKey(i), styles.FindFromIndex(i)
        color = _rgb(style)
        if color is None:
            continue
        if shape.ShapeType() == TopAbs_FACE:
            face_colors[hash(shape)] = color
        else:
            solids = _subshapes(shape, TopAbs_SOLID)
            for solid in solids:
                prior = whole.get(hash(solid))
                if prior is None or len(solids) <= prior[0]:
                    whole[hash(solid)] = (len(solids), color)
    # XCAF may copy topology while adding labels. Match metadata back using
    # world-space bounds + volume + area, never by a changed explorer index.
    from .importer import _bounds, _properties
    colored = []
    seen = set()
    for i in range(1, roots.Length()+1):
        root_shape = XCAFDoc_DocumentTool.ShapeTool_s(document.Main()).GetShape_s(roots.Value(i))
        for shape in _subshapes(root_shape, TopAbs_SOLID):
            if hash(shape) in seen:
                continue
            seen.add(hash(shape))
            color = None
            if hash(shape) in whole:
                color = whole[hash(shape)][1]
            else:
                areas = defaultdict(float)
                for face in _subshapes(shape, TopAbs_FACE):
                    rgb = face_colors.get(hash(face))
                    if rgb is not None:
                        props = GProp_GProps()
                        BRepGProp.SurfaceProperties_s(face, props)
                        areas[rgb] += abs(float(props.Mass()))
                if areas:
                    color = max(areas, key=lambda c: (areas[c], c))
            if color is not None:
                volume, area, _ = _properties(shape)
                colored.append((_bounds(shape), volume, area, color))
    count = 0
    for body in bodies:
        matches = []
        b = body.bounds
        for bounds, volume, area, color in colored:
            a = bounds
            if (max(abs(x-y) for x,y in zip(
                    (a.xmin,a.ymin,a.zmin,a.xmax,a.ymax,a.zmax),
                    (b.xmin,b.ymin,b.zmin,b.xmax,b.ymax,b.zmax))) <= 1e-5
                    and abs((volume or 0)-(body.volume_mm3 or 0)) <= max(1e-6,abs(body.volume_mm3 or 0)*1e-8)
                    and abs((area or 0)-(body.area_mm2 or 0)) <= max(1e-6,abs(body.area_mm2 or 0)*1e-8)):
                matches.append(color)
        if matches and len(set(matches)) == 1:
            body.color_rgb = matches[0]
        count += body.color_rgb is not None
    return count
