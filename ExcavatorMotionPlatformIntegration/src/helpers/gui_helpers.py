from PyQt6.QtWidgets import QLabel, QPushButton, QMessageBox, QTabWidget
from widgets.FaultTab import FaultTab
from widgets.GeneralTab import GeneralTab
from widgets.AdvancedTab import AdvancedTab
from widgets.ExcavatorTab import ExcavatorTab
import json
import subprocess

def load_styles(self):
    try:
        with open(self.styles_path, "r") as f:
            data = json.load(f)
        
        styles = data["styles"]
        self.styles = {}
        for style in styles:
            for key, val in style.items():
                self.styles[key] = val
    except FileNotFoundError:
        print(f"Error: styles.json not found at {self.styles_path}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        
def create_tabs(self):
    # Create Tab Widget
    self.tabs = QTabWidget()
    self.main_layout.addWidget(self.tabs)
    create_general_tab(self)    
    create_advanced_tab(self)
    create_faults_tab(self)
    create_excavator_tab(self)
    
def create_server_buttons(self):
    # Start Button
    self.start_button = QPushButton("Start Server")
    self.start_button.clicked.connect(self.handle_button_click)
    self.start_button.setStyleSheet(self.styles["start_up_btn"])
    self.start_button.setEnabled(False)
    self.main_layout.addWidget(self.start_button)
    
    # Shutdown Button (Initially Disabled)
    self.shutdown_button = QPushButton("Shutdown Server")
    self.shutdown_button.setEnabled(False)
    self.shutdown_button.clicked.connect(self.shutdown_server)
    self.shutdown_button.setStyleSheet(self.styles["shutdown_btn"])
    self.main_layout.addWidget(self.shutdown_button)
    
def load_config(self):
    try:
        config_path = self.CONFIG_FILE
        with open(config_path, "r") as f:
            config = json.load(f)
            self.advanced_tab.set_left_motor(config.get("servo_ip_1", ""))
            self.advanced_tab.set_right_motor(config.get("servo_ip_2", ""))
            self.general_tab.set_velocity(config.get("speed", 50))
            self.general_tab.set_acceleration(config.get("acceleration", 100))
            self.excavator_tab.set_excavator_ip(config.get("excavator_ip"))
    except FileNotFoundError as e:
        self.logger.error(f"Config file not found: {e}")

def store_current_field_values(self):
    # store initial values of the input fields
        self.stored_values = {
            'ip_input1': self.advanced_tab.get_left_motor(),
            'ip_input2': self.advanced_tab.get_right_motor(),
            'speed_input': self.general_tab.get_velocity(),
            'accel_input': self.general_tab.get_acceleration(),
        }
       
def update_stored_values(self):
    store_current_field_values(self)
    
def get_field_values(self):
    ip1 = self.advanced_tab.get_left_motor().strip()
    ip2 = self.advanced_tab.get_right_motor().strip()
    speed = self.general_tab.get_velocity()
    accel = self.general_tab.get_acceleration()
    excavator_ip = self.excavator_tab.get_excavator_ip()
    return (ip1, ip2, speed, accel, excavator_ip)

async def clear_fault(self):
    await self.websocket_client.send("action=clearfault|")
    
def create_general_tab(self):
    self.general_tab = GeneralTab()
    self.tabs.addTab(self.general_tab, "General")
    
def create_advanced_tab(self):
    self.advanced_tab = AdvancedTab()
    self.tabs.addTab(self.advanced_tab, "Advanced")
    
def create_faults_tab(self):
    self.faults_tab = FaultTab(styles=self.styles, clear_fault_cb=self.clear_fault)
    self.tabs.addTab(self.faults_tab, "Faults")

def create_excavator_tab(self):
    self.excavator_tab = ExcavatorTab(main_self=self, styles=self.styles)
    self.tabs.addTab(self.excavator_tab, "Excavator")

def create_status_label(self):
    self.message_label = QLabel("WebSocket Messages: Not connected")
    self.message_label.setWordWrap(True)
    self.main_layout.addWidget(self.message_label)
    set_styles(self)
    self.setLayout(self.main_layout)
    self.stored_values = {
        'ip_input1': self.advanced_tab.get_left_motor(),
        'ip_input2': self.advanced_tab.get_right_motor(),
        'speed_input': self.general_tab.get_velocity(),
        'accel_input': self.general_tab.get_acceleration(),
    }

def set_styles(self):
    try:
        styles_path = self.styles_path
        # Load the JSON from the file
        with open(styles_path, "r") as f:
            data = json.load(f)
        for style in data["styles"]:
            if "start_up_btn" in style:
                self.start_button.setStyleSheet(style["start_up_btn"])
            if "shutdown_btn" in style:
                self.shutdown_button.setStyleSheet(style["shutdown_btn"])
    except FileNotFoundError:
        print(f"Error: styles.json not found at {styles_path}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")


def save_config(self, ip1, ip2, speed, accel, excavator_ip):
    with open(self.CONFIG_FILE, "w") as f:
        json.dump({
            "servo_ip_1": ip1,
            "servo_ip_2": ip2,
            "speed": speed,
            "acceleration": accel,
            "excavator_ip": excavator_ip
        }, f)

    
def start_server(self):
    (ip1, ip2, speed, accel,excavator_ip)  = get_field_values(self)
    if not ip1 or not ip2:
        QMessageBox.warning(self, "Input Error", "Please enter valid IP addresses for both servo arms.")
        return

    save_config(self, ip1, ip2, speed, accel, excavator_ip)
    
    try:
        ### Make sure the process main.py is not already running for some reason
        result = self.process_manager.exterminate_lingering_process("main")
        if not result:
            self.logger.error(f"Unable to kill lingering process with name: main. Not launching a new process...")
            return
        elif result:
            self.logger.info(f"No lingering process remaining.")
        
        self.process_manager.launch_process("main", args=["--server_left", ip1, "--server_right", ip2, "--acc", str(accel), "--vel", str(speed)])
        # Start WebSocket client after server starts
        self.start_websocket_client()
        self.start_button.setEnabled(False)
    except FileNotFoundError as e:
        self.logger.error(f"Could not find venv: {e}")
    except Exception as e:
        QMessageBox.critical(self, "Error", f"Failed to start server: {str(e)}")





def findProcessByName(processname):
    """
    Finds process by given name. Returns result object. 
    """
    try:
        result = subprocess.run(
            ["powershell", "-Command", f"(Get-Process -Name {processname} -ErrorAction SilentlyContinue).Id"],
            capture_output=True,
            text=True
        )
        return result
    except:
        raise