from PyQt6.QtWidgets import QWidget, QLineEdit, QFormLayout, QPushButton, QComboBox, QGroupBox, QVBoxLayout, QCheckBox
from constants.pwm_channels import PWM_CHANNELS

class ExcavatorTab(QWidget):
    def __init__(self, main_self, styles):
        super().__init__()
        self.main_self=main_self
        self.styles=styles
        self.init_ui()

    def init_ui(self):
        self.layout = QFormLayout()
        self.setLayout(self.layout)

        # IP Field for ExcavatorAPI
        self.excavator_ip = QLineEdit()
        self.layout.addRow("Minuature Excavators IP address", self.excavator_ip)

        # Find Excavator 
        self.find_excavator_btn = QPushButton("Find Excavator")
        self.find_excavator_btn.clicked.connect(self.main_self.find_excavator)
        self.find_excavator_btn.setEnabled(True)
        self.layout.addWidget(self.find_excavator_btn)
        
        # How fast the excavator will send orientation information
        self.orientation_receive_rate = QLineEdit()
        self.orientation_receive_rate.setText("1")
        self.layout.addRow("Orientation Receive Rate", self.orientation_receive_rate)

        # How fast the excavator client will send control commands
        self.commands_send_rate = QLineEdit()
        self.commands_send_rate.setText("10")
        self.layout.addRow("Control Commands Send Rate", self.commands_send_rate)

        # Channel control selection
        self.channel_mode = QComboBox()
        self.channel_mode.addItems(["All Channels", "Manual Selection"])
        self.channel_mode.currentTextChanged.connect(self.main_self.toggle_channel_selection)
        self.layout.addRow("Control Mode", self.channel_mode)
    
        # Manual channel selection (hidden by default)
        self.channel_group = QGroupBox("Select Channels")
        channel_layout = QVBoxLayout()
        self.channel_checkboxes = []
        for channel in PWM_CHANNELS:
            cb = QCheckBox(channel)
            cb.setChecked(True) 
            channel_layout.addWidget(cb)
            self.channel_checkboxes.append(cb)
        self.channel_group.setLayout(channel_layout)
        self.channel_group.setVisible(False)
        self.layout.addRow(self.channel_group)
      
        ### - ###
      
        # Start mirroring
        self.start_mirroring_btn = QPushButton("Start Mirroring")
        self.start_mirroring_btn.clicked.connect(self.main_self.start_mirroring)
        self.start_mirroring_btn.setStyleSheet(self.styles["start_up_btn"])
        self.start_mirroring_btn.setEnabled(False)
        self.layout.addWidget(self.start_mirroring_btn)
        
        # Stop mirroring
        self.stop_mirroring_btn = QPushButton("Stop Mirroring")
        self.stop_mirroring_btn.clicked.connect(self.main_self.stop_mirroring)
        self.stop_mirroring_btn.setStyleSheet(self.styles["shutdown_btn"])
        self.stop_mirroring_btn.setEnabled(False)
        self.layout.addWidget(self.stop_mirroring_btn)
    
        # Start driving
        self.start_driving_btn = QPushButton("Start Driving")
        self.start_driving_btn.clicked.connect(self.main_self.start_driving)
        self.start_driving_btn.setStyleSheet(self.styles["start_up_btn"])
        self.start_driving_btn.setEnabled(False)
        self.layout.addWidget(self.start_driving_btn)
        
        # Stop driving
        self.stop_driving_btn = QPushButton("Stop Driving")
        self.stop_driving_btn.clicked.connect(self.main_self.stop_driving)
        self.stop_driving_btn.setStyleSheet(self.styles["shutdown_btn"])
        self.stop_driving_btn.setEnabled(False)
        self.layout.addWidget(self.stop_driving_btn)
        
        # Start driving&Mirroring
        self.start_driving_and_mirroring_btn = QPushButton("Start Driving and Mirroring")
        self.start_driving_and_mirroring_btn.clicked.connect(self.main_self.start_driving_and_mirroring)
        self.start_driving_and_mirroring_btn.setStyleSheet(self.styles["start_up_btn"])
        self.start_driving_and_mirroring_btn.setEnabled(False)
        self.layout.addWidget(self.start_driving_and_mirroring_btn)
        
        # Stop driving&Mirroring
        self.stop_driving_and_mirroring_btn = QPushButton("Stop Driving and Mirroring")
        self.stop_driving_and_mirroring_btn.clicked.connect(self.main_self.stop_driving_and_mirroring)
        self.stop_driving_and_mirroring_btn.setStyleSheet(self.styles["shutdown_btn"])
        self.stop_driving_and_mirroring_btn.setEnabled(False)
        self.layout.addWidget(self.stop_driving_and_mirroring_btn)
    
    def get_excavator_ip(self):
        return self.excavator_ip.text()
    
    def set_excavator_ip(self, ip):
        self.excavator_ip.setText(ip)