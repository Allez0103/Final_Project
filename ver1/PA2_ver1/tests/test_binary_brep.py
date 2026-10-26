from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepTools import BRepTools
from pa2.cad.brep_io import read_shape,write_shape
from pa2.cad.prepare import _properties


def test_binary_roundtrip_preserves_geometry_and_supports_legacy(tmp_path):
    original=BRepPrimAPI_MakeBox(1.123456789012345,2,3).Shape()
    path=tmp_path/'shape.binbrep';write_shape(original,path)
    restored=read_shape(path)
    assert BRepCheck_Analyzer(restored,True).IsValid()
    assert _properties(original)==_properties(restored)
    legacy=tmp_path/'legacy.brep';assert BRepTools.Write_s(original,str(legacy))
    assert BRepCheck_Analyzer(read_shape(legacy),True).IsValid()


def test_reopen_rebuilds_new_cache_from_managed_asset_preserving_snapshot(tmp_path,monkeypatch):
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    from pa2.cli import _runtime
    from pa2.settings.config import AppSettings
    from pa2.cad.importer import StepImporter
    from pa2.storage.cache import cache_key
    writer=STEPControl_Writer();writer.Transfer(BRepPrimAPI_MakeBox(1,2,3).Shape(),STEPControl_AsIs)
    external=tmp_path/'source.step';writer.Write(str(external));before=external.read_bytes()
    layout,db,projects,imports=_runtime(tmp_path/'data')
    project=projects.create('binary','test','test')
    original=imports.prepare(project.id,external,[],AppSettings())
    old_key=cache_key('shape',[original.snapshot.assembly_asset_hash],StepImporter.VERSION,{'unit':'file'})
    old_cache=imports.cache.get('shape',old_key)
    monkeypatch.setattr(StepImporter,'VERSION','test-new-binary-version')
    read=imports.importer.read;calls=[]
    def tracked(path,*args,**kwargs):
        assert path!=external and path.is_relative_to(layout.assets)
        calls.append(path);return read(path,*args,**kwargs)
    monkeypatch.setattr(imports.importer,'read',tracked)
    reopened=imports.reopen(project.id)
    assert reopened.snapshot.id==original.snapshot.id
    assert [g.id for g in reopened.snapshot.groups]==[g.id for g in original.snapshot.groups]
    assert reopened.cache_misses==1 and len(calls)==1 and old_cache.is_dir()
    assert external.read_bytes()==before
    assert imports.reopen(project.id).cache_hits==1 and len(calls)==1
