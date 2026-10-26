"""Capture native faults and the actual thread applying a reopened CAD scene."""
import argparse
import faulthandler
import json
import threading
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.with_suffix('.fault.log').open('w',encoding='utf-8') as log:
        faulthandler.enable(file=log,all_threads=True)
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        from pa2.ui.main_window import ModelPage
        from pa2.gui_diagnostics import gui_smoke
        original=ModelPage.set_result
        def observed(page,*values,**kwargs):
            args.output.with_suffix('.thread.json').write_text(json.dumps({
                'ui_update_on_main_thread':QThread.currentThread()==QApplication.instance().thread(),
                'python_thread_id':threading.get_ident()},indent=2),encoding='utf-8')
            return original(page,*values,**kwargs)
        ModelPage.set_result=observed
        return gui_smoke(str(args.output))


if __name__=='__main__':raise SystemExit(main())
