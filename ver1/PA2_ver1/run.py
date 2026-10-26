import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--cli':
        from pa2.cli import main
        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv)==3 and sys.argv[1]=="--native-smoke":
        from pa2.diagnostics import native_smoke
        raise SystemExit(native_smoke(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--gui-smoke':
        from pa2.gui_diagnostics import gui_smoke
        raise SystemExit(gui_smoke(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--ui-v16-smoke':
        from pa2.ui_verify_v16 import verify_ui
        raise SystemExit(verify_ui(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--ui-v19-smoke':
        from pa2.ui_verify_v19 import verify_ui
        raise SystemExit(verify_ui(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--ui-v20-smoke':
        from pa2.ui_verify_v20 import verify_ui
        raise SystemExit(verify_ui(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--ui-v23-smoke':
        from pa2.ui_verify_v23 import verify_ui
        raise SystemExit(verify_ui(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--ui-v24-smoke':
        from pa2.ui_verify_v24 import verify_ui
        raise SystemExit(verify_ui(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=='--ui-v25-smoke':
        from pa2.ui_verify_v25 import verify_ui
        raise SystemExit(verify_ui(sys.argv[2]))
    from pa2.__main__ import main
    raise SystemExit(main())

