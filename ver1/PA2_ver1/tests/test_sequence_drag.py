import pytest
from PySide6.QtCore import Qt,QSize,QPoint,QPointF,QMimeData,QTimer,QItemSelectionModel
from PySide6.QtGui import QDropEvent,QDrag,QPixmap,QIcon,QColor
from PySide6.QtWidgets import QApplication,QListWidgetItem
from PySide6.QtTest import QTest
from pa2.ui.sequence_cards import SequenceCards


@pytest.fixture
def cards(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    view=SequenceCards();view.resize(1020,148)
    for i,key in enumerate('ABCDEF'):
        pixmap=QPixmap(64,60);pixmap.fill(QColor.fromHsv(i*45,80,210))
        item=QListWidgetItem(QIcon(pixmap),key);item.setData(Qt.UserRole,key);view.addItem(item)
    view.show();app.processEvents()
    yield view
    view._clear_preview();view.close()


def order(view):return [view.item(i).data(Qt.UserRole) for i in range(view.count())]
def selected(view):return [view.item(i).data(Qt.UserRole) for i in range(view.count()) if view.item(i).isSelected()]
def choose(view,rows):
    view.clearSelection()
    for row in rows:view.item(row).setSelected(True)
    view.setCurrentItem(view.item(rows[-1]),QItemSelectionModel.NoUpdate)


class LocalDrop(QDropEvent):
    def __init__(self,view,x):
        self.view=view;self.mime=QMimeData();self.mime.setData(view.MIME,view._token.encode('ascii'))
        super().__init__(QPointF(x,60),Qt.MoveAction,self.mime,Qt.LeftButton,Qt.NoModifier)
    def source(self):return self.view


def preview(view,rows):
    choose(view,rows);view._drag_running=True;view._begin_preview(view.selectedItems())


def test_gap_is_visible_without_changing_sequence(cards):
    preview(cards,[1]);cards._set_target(4);cards._animation.setCurrentTime(140)
    assert order(cards)==list('ABCDEF')
    image=cards.viewport().grab().toImage()
    point=QPoint(4*170+14,15)
    color=image.pixelColor(round(point.x()*image.devicePixelRatio()),round(point.y()*image.devicePixelRatio()))
    assert color.blue()>color.red() and color!=QColor('white')
    assert cards._positions[4]==pytest.approx(3*170)


def test_drop_moves_one_card_once(cards):
    changes=[];cards.reordered.connect(lambda:changes.append(order(cards)))
    preview(cards,[0]);event=LocalDrop(cards,cards.viewport().width()-2);cards.dropEvent(event)
    assert event.isAccepted() and order(cards)==list('BCDEFA')
    assert changes==[list('BCDEFA')] and selected(cards)==['A']
    assert not cards._preview


def test_group_drop_keeps_relative_order_and_current_card(cards):
    preview(cards,[2,4]);event=LocalDrop(cards,170*1.1);cards.dropEvent(event)
    assert order(cards)==list('ACEBDF')
    assert selected(cards)==['C','E'] and cards.currentItem().data(Qt.UserRole)=='E'


def test_drop_in_original_slot_is_noop(cards):
    changes=[];cards.reordered.connect(lambda:changes.append(True))
    preview(cards,[1]);cards.dropEvent(LocalDrop(cards,170*1.5))
    assert order(cards)==list('ABCDEF') and changes==[]


def test_cancel_native_drag_preserves_order_and_selection(cards):
    choose(cards,[1,3]);before=order(cards);selection=selected(cards)
    QTimer.singleShot(10,QDrag.cancel)
    cards.startDrag(Qt.MoveAction)
    assert order(cards)==before and selected(cards)==selection
    assert not cards._preview and not cards._drag_running and not cards._scroll.isActive()


def test_dragging_selected_group_does_not_collapse_on_press(cards):
    choose(cards,[1,3]);point=cards.visualItemRect(cards.item(3)).center()
    QTest.mousePress(cards.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    assert selected(cards)==['B','D']
    QTest.mouseRelease(cards.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    assert selected(cards)==['D']


def test_edge_scroll_reaches_offscreen_cards(cards):
    cards.resize(400,148);QApplication.processEvents();preview(cards,[0])
    bar=cards.horizontalScrollBar();assert bar.maximum()>0
    before=bar.value();cards._last_pos=QPoint(cards.viewport().width()-1,60)
    for _ in range(5):cards._auto_scroll()
    assert bar.value()>before
    cards._last_pos=QPoint(1,60)
    for _ in range(10):cards._auto_scroll()
    assert bar.value()==0


def test_foreign_or_stale_drag_is_rejected(cards):
    preview(cards,[1]);event=LocalDrop(cards,1);event.mime.setData(cards.MIME,b'stale-token')
    cards.dropEvent(event)
    assert not event.isAccepted() and order(cards)==list('ABCDEF')
