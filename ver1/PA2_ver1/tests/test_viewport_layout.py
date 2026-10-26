from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QLabel,QPushButton,QMenu,QWidget,QHBoxLayout
from pa2.ui.viewport import ModelViewport,ViewportMenuButton,configure_viewport_button


def make_viewport():
    app=QApplication.instance() or QApplication([])
    surface=ModelViewport(QLabel('test canvas'))
    for name in ('rotate','pan','fit','view','zoom_out','zoom_in','show'):
        button=QPushButton();configure_viewport_button(button,name,name);surface.tools.addWidget(button)
    return app,surface


def require_separate_rectangles(surface):
    canvas=surface.canvas.geometry()
    assert not canvas.intersects(surface.footer.geometry())
    assert surface.rect().contains(canvas)
    assert surface.rect().contains(surface.footer.geometry())


def test_viewer_text_never_overlaps_the_native_render_area(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app,surface=make_viewport()
    try:
        surface.resize(900,450);surface.show();app.processEvents()
        require_separate_rectangles(surface)
        assert not surface.findChildren(QLabel)[1:]
        assert surface.overlays()==()
    finally:surface.close()


def test_resize_and_repaint_keep_labels_in_their_own_regions(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app,surface=make_viewport()
    try:
        surface.show()
        for size in ((1000,600),(460,300),(800,420),(1000,600)):
            surface.resize(*size);surface.repaint();app.processEvents()
            require_separate_rectangles(surface)
            assert surface.toolbar.isVisible()
    finally:surface.close()


def test_viewport_text_is_single_and_survives_model_reload():
    from pa2.rendering.vtk_scene import VtkScene
    scene=VtkScene(offscreen=True)
    try:
        assert scene._viewer_text==[]  # Export renderers get no editor labels.
        scene._configure_viewer_text()
        for _ in range(3):
            scene.clear();scene._configure_viewer_text()
            assert len(scene._viewer_text)==1
            assert scene.renderer.GetActors2D().GetNumberOfItems()==1
            assert all(scene.renderer.HasViewProp(actor) for actor in scene._viewer_text)
        assert '드래그 회전' in scene._viewer_text[0].GetInput()
    finally:scene.render_window.Finalize()


def test_menu_icon_remains_centred_in_its_highlight(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from pa2.ui.theme import STYLESHEET
    app=QApplication.instance() or QApplication([])
    surface=QWidget();surface.setStyleSheet(STYLESHEET);layout=QHBoxLayout(surface)
    normal=QPushButton();menu_button=ViewportMenuButton()
    menu_button.setMenu(QMenu(menu_button));menu_button.menu().addAction('등각')
    for button in (normal,menu_button):
        configure_viewport_button(button,'view','시점 선택');button.setCheckable(True);layout.addWidget(button)
    try:
        surface.show();app.processEvents()
        for checked in (False,True):
            bounds=[]
            for button in (normal,menu_button):
                button.setChecked(checked);image=button.grab().toImage();points=[]
                for y in range(image.height()):
                    for x in range(image.width()):
                        color=image.pixelColor(x,y)
                        if color.red()<150 and color.blue()>80 and color.blue()>color.red()+15:points.append(x)
                left,right=min(points),max(points);bounds.append((left,right))
                assert abs((left+right)/2-(image.width()-1)/2)<=image.devicePixelRatio()
            assert bounds[0]==bounds[1]
    finally:surface.close()
