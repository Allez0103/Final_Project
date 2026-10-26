from pathlib import Path


def test_toolbar_uses_existing_icon_and_keeps_product_name(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setenv('PA2_DATA_ROOT',str(tmp_path/'data'))
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication,QToolBar
    from pa2.ui.main_window import MainWindow
    app=QApplication.instance() or QApplication([])
    root=Path(__file__).resolve().parents[1]
    window=MainWindow(root)
    try:
        toolbar=window.findChild(QToolBar,'mainToolbar')
        assert toolbar.widgetForAction(toolbar.actions()[0]) is window.brand_icon
        assert toolbar.widgetForAction(toolbar.actions()[1]) is window.brand_title
        assert window.brand_title.text()=='Pilot Assembly Assistant'
        assert window.brand_icon.text()==''
        actual=window.brand_icon.pixmap()
        expected=QIcon(str(root/'assets/pa2_icon.ico')).pixmap(QSize(32,32),window.devicePixelRatioF())
        assert not actual.isNull()
        assert actual.toImage()==expected.toImage()
        assert actual.deviceIndependentSize().width()==32
        assert actual.deviceIndependentSize().height()==32
        assert window.brand_icon.accessibleName()=='PA² 프로그램 아이콘'
        assert window.windowTitle()=='PA² · Pilot Assembly Assistant'
        assert not window.windowIcon().isNull()
        assert not toolbar.isMovable()
    finally:
        window.model_page.vtk_scene.render_window.Finalize()
        window.close()
