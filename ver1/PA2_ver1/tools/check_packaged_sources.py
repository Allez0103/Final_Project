"""Read the packaged bytecode and compare it to current optimized sources."""
import argparse,hashlib,json
from pathlib import Path
from types import CodeType
from PyInstaller.archive.readers import CArchiveReader


def normalized(code):
    return code.replace(co_filename='<module>',co_consts=tuple(
        normalized(x) if isinstance(x,CodeType) else x for x in code.co_consts))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path,default=Path('PA2.exe'));args=p.parse_args()
    exe=args.exe;z=CArchiveReader(str(exe)).open_embedded_archive('PYZ.pyz')
    modules=['pa2.planning.engine','pa2.planning.two_stage','pa2.planning.fastener_direction','pa2.cad.direction_policy',
        'pa2.cad.native_worker','pa2.cad.prepare','pa2.cad.sweep','pa2.cad.path_check',
        'pa2.domain.models','pa2.rendering.scene','pa2.rendering.vtk_scene','pa2.video.renderer',
        'pa2.ui.main_window','pa2.ui.model_editor','pa2.ui.video_page','pa2.planning.attachments',
        'pa2.settings.config','pa2.application.plan_service','pa2.gui_diagnostics','pa2.ui_verify_v16','pa2.diagnostics',
        'pa2.cad.grouping','pa2.cad.boolean_options','pa2.cad.shapes','pa2.cad.brep_io','pa2.video.encoding','pa2.storage.layout',
        'pa2.__main__','pa2.ui.settings_dialog','pa2.application.manual_grouping',
        'pa2.application.video_library','pa2.application.import_service','pa2.storage.database',
        'pa2.ui.group_dialog','pa2.ui_verify_v19','pa2.ui_verify_selection',
        'pa2.planning.manual','pa2.cad.step_colors','pa2.learning.collection',
        'pa2.learning.comparison','pa2.learning.offline','pa2.learning.ranker','pa2.ui_verify_v20',
        'pa2.learning.data','pa2.learning.models','pa2.learning.registry',
        'pa2.learning.pipeline','pa2.learning.idle','pa2.cli',
        'pa2.domain.classification','pa2.cad.rotation_signature','pa2.cad.step_name_hints',
        'pa2.ui.theme','pa2.ui.sequence_cards','pa2.ui.viewport','pa2.ui.transport',
        'pa2.rendering.orbit','pa2.ui_verify_v23','pa2.ui.part_list','pa2.ui_verify_v24','pa2.ui_verify_v25']
    rows=[]
    for name in modules:
        source=Path('src').joinpath(*name.split('.')).with_suffix('.py')
        compiled=compile(source.read_text(encoding='utf-8'),str(source),'exec',optimize=1)
        rows.append(dict(module=name,matches=normalized(compiled)==normalized(z.extract(name)),
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    assets=[]
    for filename in ('video_template_v1.json','thn_logo.png','pa2_icon.png','pa2_icon.ico'):
        source=Path('assets')/filename
        packaged=exe.parent/'_internal/assets'/filename
        assets.append(dict(asset=filename,matches=packaged.is_file() and source.read_bytes()==packaged.read_bytes()))
    output=dict(ok=all(r['matches'] for r in rows+assets) and not (exe.parent/'_internal/icuuc.dll').exists(),
        executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),modules=rows,assets=assets,
        incompatible_icu_bundled=(exe.parent/'_internal/icuuc.dll').exists())
    import struct,pefile
    ico=Path('assets/pa2_icon.ico').read_bytes(); count=struct.unpack_from('<H',ico,4)[0]
    expected=set()
    for i in range(count):
        length,offset=struct.unpack_from('<II',ico,6+i*16+8)
        expected.add(hashlib.sha256(ico[offset:offset+length]).hexdigest())
    pe=pefile.PE(str(exe)); actual=set()
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id==3:
            for entry in kind.directory.entries:
                for language in entry.directory.entries:
                    data=language.data.struct
                    actual.add(hashlib.sha256(pe.get_data(data.OffsetToData,data.Size)).hexdigest())
    pe.close()
    output['embedded_icon_matches']=expected<=actual and bool(expected)
    output['ok']=output['ok'] and output['embedded_icon_matches']
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
    return 0 if output['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
