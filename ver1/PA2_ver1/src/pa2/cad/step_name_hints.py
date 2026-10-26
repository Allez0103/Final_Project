"""Native STEP reference names for an already geometry-qualified tie only.

Read metadata from the scene's original/managed STEP; never run adjacent scripts
or read external labels as instructions. Missing/conflicting names are not a
reason to guess. Existing imported shapes, body IDs and placements are untouched.
"""
from __future__ import annotations

from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label

from pa2.domain.classification import normalized_stem


def definition_hints(scene, body_ids):
    if not scene.source_path.is_file() or not body_ids:return {}
    from pa2.storage.assets import sha256_file
    if sha256_file(scene.source_path)!=scene.source_hash:return {}
    from .importer import _bounds, _properties
    reader=STEPCAFControl_Reader()
    reader.SetNameMode(True);reader.SetColorMode(False);reader.SetLayerMode(False)
    if reader.ReadFile(str(scene.source_path))!=IFSelect_RetDone:return {}
    reader.Reader().SetSystemLengthUnit(1.)
    document=TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    if not reader.Transfer(document):return {}
    tool=XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots=Sequence_TDF_Label();tool.GetFreeShapes(roots)
    bodies=[b for b in scene.bodies if b.id in body_ids]
    result={b.id:set() for b in bodies}
    def name(label):
        attribute=TDataStd_Name()
        return normalized_stem(attribute.Get().ToExtString()) if label.FindAttribute(TDataStd_Name.GetID_s(),attribute) else ''
    def walk(label, parent, names, depth=0):
        if depth>64:raise ValueError('STEP 참조 깊이 제한')
        names=names|{name(label)}
        referred=TDF_Label()
        if tool.GetReferredShape_s(label,referred):
            walk(referred,parent.Multiplied(tool.GetLocation_s(label)),names,depth+1);return
        children=Sequence_TDF_Label()
        if tool.GetComponents_s(label,children):
            for i in range(1,children.Length()+1):walk(children.Value(i),parent,names,depth+1)
            return
        shape=tool.GetShape_s(label).Moved(parent)
        solids=[]
        if shape.ShapeType()==TopAbs_SOLID:solids=[shape]
        else:
            explorer=TopExp_Explorer(shape,TopAbs_SOLID)
            while explorer.More():solids.append(explorer.Current());explorer.Next()
        for solid in solids:
            box=_bounds(solid)
            values=(box.xmin,box.ymin,box.zmin,box.xmax,box.ymax,box.zmax)
            for body in bodies:
                b=body.bounds
                target=(b.xmin,b.ymin,b.zmin,b.xmax,b.ymax,b.zmax)
                if max(abs(x-y) for x,y in zip(values,target))>1e-5:continue
                volume,area,_=_properties(solid)
                if (volume is not None and area is not None and body.volume_mm3 is not None and body.area_mm2 is not None
                    and abs(volume-body.volume_mm3)<=max(abs(volume),1.)*1e-8
                    and abs(area-body.area_mm2)<=max(abs(area),1.)*1e-8):
                    result[body.id].update(n for n in names if n)
                    # Some AP242 exporters use "part_id | description". Only
                    # the explicit left-hand ID token is eligible, never a
                    # substring or a guessed word from the description.
                    result[body.id].update(n.split('|',1)[0].strip() for n in names if '|' in n)
    for i in range(1,roots.Length()+1):walk(roots.Value(i),TopLoc_Location(),set())
    return result if sha256_file(scene.source_path)==scene.source_hash else {}
