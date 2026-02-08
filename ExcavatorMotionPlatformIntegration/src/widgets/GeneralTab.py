from PyQt6.QtWidgets import QWidget, QSpinBox, QFormLayout
from PyQt6.QtCore import Qt

class GeneralTab(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.layout = QFormLayout()
        self.setLayout(self.layout)

        # Speed Field
        self.speed_input = QSpinBox()
        self.speed_input.setRange(1, 600)
        self.layout.addRow("Velocity (RPM):", self.speed_input)

        # Acceleration Field
        self.accel_input = QSpinBox()
        self.accel_input.setRange(1, 1500)
        self.layout.addRow("Acceleration (RPM):", self.accel_input)

    def set_acceleration(self, val):
        self.accel_input.setValue(int(val))
    
    def set_velocity(self, val):
        self.speed_input.setValue(int(val))

    def get_acceleration(self):
        return self.accel_input.value()
    
    def get_velocity(self):
        return self.speed_input.value()


