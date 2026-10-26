"""Names come only from selected part units; direction belongs to planning."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QComboBox,QListWidget,QDialogButtonBox


class ManualGroupDialog(QDialog):
    def __init__(self,groups,parent=None):
        super().__init__(parent);self.setWindowTitle('수동 그룹 만들기');self.resize(440,320)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('그룹 이름 · 직접 입력하거나 선택한 부품명에서 선택'))
        self.name=QComboBox();self.name.setEditable(True)
        self.name.addItems(list(dict.fromkeys(g.display_name for g in groups)))
        self.name.setEditText('수동 그룹');self.name.lineEdit().setMaxLength(120)
        layout.addWidget(self.name)
        selected=QListWidget();selected.addItems([g.display_name for g in groups]);layout.addWidget(selected)
        note=QLabel('하나의 부품으로 묶습니다.\n분해 방향과 이동 거리는 이후 순서 생성에서 자동으로 설정합니다.\n'
                    '예외 지정 부품이 포함되면 그룹 전체에 예외가 적용됩니다.')
        note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('그룹 만들기');buttons.button(QDialogButtonBox.Cancel).setText('취소')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.name.currentTextChanged.connect(lambda text:buttons.button(QDialogButtonBox.Ok).setEnabled(bool(text.strip())))

    def group_name(self):return self.name.currentText().strip()
