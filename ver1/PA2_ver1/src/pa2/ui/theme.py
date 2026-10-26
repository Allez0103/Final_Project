"""Engineering Light palette for the native PA2 interface."""
# Existing PA2 brand screen color for the requested PANTONE 2736 PC identity;
# reused from the approved video template, not a print-color conversion claim.
PRIMARY = "#2633C5"
PRIMARY_HOVER = "#202BA6"
SELECTION = "#EAF2FD"
SURFACE = "#F3F6FA"

STYLESHEET = f"""
QWidget {{ color: #34465C; font-family: 'Malgun Gothic'; font-size: 13px; }}
QMainWindow, QDialog, QTabWidget::pane {{ background: {SURFACE}; }}
QTabWidget::pane {{ border: 0; }}
QToolBar {{ background: {SURFACE}; border: 0; spacing: 10px; padding: 9px 16px; }}
QLabel {{ background: transparent; }}
QLabel#brandTitle {{ color: #173454; font-size: 19px; font-weight: 700; }}
QLabel[muted="true"] {{ color: #66758A; font-size: 12px; }}
QTabBar::tab {{ min-width: 110px; padding: 10px 20px; color: #66758A;
    background: {SURFACE}; border: 0; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: #173454; background: white; border-bottom: 2px solid {PRIMARY}; }}
QPushButton {{ min-height: 23px; border: 1px solid #CFD9E5; border-radius: 5px;
    padding: 5px 10px; background: white; }}
QPushButton:hover {{ background: #EDF3FA; border-color: #9BB6D7; }}
QPushButton:pressed, QPushButton:checked {{ background: {SELECTION}; color: #173454; border-color: {PRIMARY}; }}
QPushButton[primary="true"] {{ color: white; background: {PRIMARY}; border-color: {PRIMARY}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton:disabled {{ color: #9AA6B5; background: #F5F7FA; border-color: #E0E6EE; }}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    border: 1px solid #CFD9E5; border-radius: 4px; padding: 5px; background: #F7F9FC;
    selection-background-color: {PRIMARY}; selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {PRIMARY}; }}
QListWidget, QTreeWidget {{ background: white; border: 1px solid #D9E2EC;
    border-radius: 5px; alternate-background-color: #F8FAFD; outline: 0; }}
QListWidget::item {{ padding: 6px 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {SELECTION}; color: #173454; }}
QListWidget#sequenceCards::item {{ margin: 4px; padding: 5px; border: 1px solid #D9E2EC;
    border-radius: 5px; background: white; }}
QListWidget#sequenceCards::item:selected {{ background: {SELECTION}; border: 2px solid {PRIMARY}; }}
QGroupBox {{ background: white; font-weight: 600; border: 1px solid #D9E2EC;
    border-radius: 7px; margin-top: 17px; padding: 12px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; background: {SURFACE}; }}
QScrollArea {{ border: 0; background: white; }}
QWidget#propertiesBody, QFrame#viewerFrame, QWidget#playbackBar {{ background: white; }}
QFrame#viewerFrame {{ border: 0; border-radius: 6px; }}
QFrame#whiteCard {{ background: white; border: 1px solid #D9E2EC; border-radius: 7px; }}
QLabel[cardTitle="true"] {{ color: #34465C; font-size: 14px; font-weight: 700; background: white; padding: 2px 0 5px; }}
QSplitter::handle {{ background: #E4EAF2; width: 6px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid #D9E2EC; color: #66758A; }}
QProgressBar {{ background: #E4EAF2; border: 0; border-radius: 4px; text-align: center; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}
QSlider::groove:horizontal {{ height: 4px; background: #DFE7F1; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: #8EB8EC; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; margin: -4px 0; background: {PRIMARY}; border-radius: 6px; }}
QPushButton[transport="true"] {{ min-height: 0; padding: 0; border: 0; background: transparent; }}
QPushButton[transport="true"]:hover {{ background: {SELECTION}; }}
QPushButton#playTransport {{ background: {PRIMARY}; border-radius: 6px; }}
QPushButton#playTransport:hover {{ background: {PRIMARY_HOVER}; }}
QToolTip {{ background: #173454; color: white; padding: 5px; border: 0; }}
QFrame#viewportToolbar {{ background: white; border: 1px solid #D9E2EC; border-radius: 8px; }}
QPushButton[viewportTool="true"] {{ min-height: 0; background: transparent; border: 0; padding: 0; border-radius: 5px; }}
QPushButton[viewportTool="true"]:hover, QPushButton[viewportTool="true"]:checked {{ background: {SELECTION}; }}
QPushButton[viewportTool="true"]::menu-indicator {{ image: none; }}
QMenu {{ background: white; border: 1px solid #CFD9E5; padding: 4px; }}
QMenu::item {{ padding: 7px 22px; }}
QMenu::item:selected {{ background: {SELECTION}; }}
"""

