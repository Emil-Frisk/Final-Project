from PyQt6.QtWidgets import QWidget,  QLabel,QFormLayout
from PyQt6.QtCore import Qt
from widgets.widgets import LabelButtonGroup

class FaultTab(QWidget):
    def __init__(self, styles=None, clear_fault_cb=None):
        super().__init__() 

        self.styles = styles
        self.clear_fault_cb=clear_fault_cb

        self.init_ui()

    def init_ui(self):
        self.layout = QFormLayout()
        self.setLayout(self.layout)

        # Message Display Label
        self.default_fault_msg_lbl = QLabel("Servo motors have no faults currently")
        self.default_fault_msg_lbl.setWordWrap(True)
        self.default_fault_msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.fault_group = LabelButtonGroup(styles=self.styles, label_text="msg", button_text="Clear Fault", visible=False)

        if self.clear_fault_cb:
            self.fault_group.connect_button(self.clear_fault_cb)

        self.layout.addWidget(self.fault_group)
        self.layout.addWidget((self.default_fault_msg_lbl))
    
    def hide_fault_group(self):
        self.fault_group.toggle_visibility()
        self.default_fault_msg_lbl.setVisible(True)

    def show_fault_group(self):
        self.fault_group.toggle_visibility()
        self.default_fault_msg_lbl.setVisible(False)

    def update_fault_message(self, txt):
        self.fault_group.set_label_text(txt)

    def hide_fault(self):
        self.fault_group.setVisible(False)

