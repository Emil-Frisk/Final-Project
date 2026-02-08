import sys
import asyncio
import qasync
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget, QWidget, QVBoxLayout,QMessageBox
from PyQt6.QtGui import QFont
from services.WebSocketClient import WebSocketClient
import os
from services.excavator_client import TCPClient as ExcavatorClient
from constants.pwm_channels import PWM_CHANNELS
from utils.utils import get_current_path, extract_part, setup_logging, get_entry_point
from helpers import gui_helpers as helpers
from pathlib import Path
from services.process_manager import ProcessManager

class ServerStartupGUI(QWidget):
    excavator_disconnected = pyqtSignal()
    excavator_event = pyqtSignal(str)
    excavator_error = pyqtSignal(str,str)
    
    def __init__(self):
        super().__init__()
        # Connect signal to a slot
        self.excavator_disconnected.connect(self.on_excavator_disconnected)
        self.excavator_event.connect(self.on_excavator_event)
        self.excavator_error.connect(self.on_excavator_error)
        
        self.logger = setup_logging("startup", "startup.log")
        self.excavator_client=None
        self.process_manager = ProcessManager(logger=self.logger, target_dir=get_current_path(__file__).parent)
        self.setWindowTitle("Server Startup")
        self.setGeometry(100, 100, 400, 600)
        self.path = get_entry_point().parent
        self.styles_path = self.path / "styles.json"
        self.CONFIG_FILE = self.path / "config.json"

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)
        font = QFont("Arial", 14)
        self.setFont(font)

        helpers.load_styles(self)
        helpers.create_tabs(self)
        helpers.load_config(self)
        helpers.create_server_buttons(self)
        helpers.create_status_label(self)
        helpers.store_current_field_values(self)

        self.faults_tab.update_fault_message("test")

        # Initialize WebSocket client
        self.websocket_client = WebSocketClient(identity="gui", logger=self.logger, on_message=self.handle_client_message)

    def start_websocket_client(self):
        """Start the WebSocket client."""
        asyncio.create_task(self.websocket_client.connect())
        self.logger.info("startweboscketclient okay")

    def handle_button_click(self):
        helpers.start_server(self)

    def shutdown_websocket_client(self):
        """Shutdown the WebSocket client."""
        asyncio.create_task(self.websocket_client.close())

    def shutdown_server(self):
        try:
            # Stop any potential operation first since they might rely on MPI
            self.excavator_client.stop_current_operation()
            self.disable_excavator_action_buttons()

            # First, close the WebSocket client
            loop = asyncio.get_event_loop()
            loop.create_task(self.websocket_client.send("action=shutdown|"))
            self.start_button.setText("Start Server")
            self.start_button.setEnabled(False)
            self.shutdown_button.setEnabled(False)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to shutdown server: {str(e)}")

    def handle_client_message(self, message):
        """Update the GUI label with WebSocket messages."""
        event = extract_part("event=", message=message)
        clientmessage = extract_part("message=", message=message)
        if not event:
            self.logger.error("No event specified in message.")
            return
        if not clientmessage:
            self.logger.info("No client message specified in message.")

        if event == "error":
            self.logger.error(message)
        elif event == "fault":
            self.logger.warning("Fault event has arrived to GUI!")
            QMessageBox.warning(self, "Error", clientmessage+"\n Check faults tab for more info")
            self.faults_tab.update_fault_message(clientmessage)
            self.faults_tab.show_fault_group()
        elif event == "absolutefault":
            QMessageBox.warning(self, "Error", "Absolute fault has occured! DO NOT continue using the motors anymore, they need some serious maintance.")
        elif event == "faultcleared":
            self.logger.info("Fault cleared event has reached gui")
            QMessageBox.information(self, "Info", "fault was cleared successfully")
            self.faults_tab.hide_fault_group()
        elif event == "motors_initialized":
            self.shutdown_button.setEnabled(True)
            QMessageBox.information(self, "Info", "Motors have been initialized successfully")
            self.enable_excavator_action_buttons()
        elif event == "connected":
            self.message_label.setText(clientmessage)
        elif event == "shutdown":
            asyncio.create_task(self.websocket_client.close())
            QMessageBox.information(self, "Info", "Motors have been shutdown successfully")
            self.shutdown_button.setEnabled(False)
            self.start_button.setEnabled(True)
            self.faults_tab.hide_fault()
            self.excavator_client.stop_current_operation()

    def find_excavator(self):
        self.excavator_tab.find_excavator_btn.setEnabled(False)
        ip=self.excavator_tab.get_excavator_ip()
        try:
            self.excavator_client=ExcavatorClient(srv_ip=ip, on_disconnected=self.emit_excavator_disconnected, mpi_enabled=True, on_excavator_event=self.emit_excavator_event, on_excavator_error=self.emit_excavator_error, logging_level="DEBUG") 
            # Excavator Found!
            if self.excavator_client.start(): 
                QMessageBox.information(self, "Info", f"Excavator found with ip: {ip}")
                (ip1, ip2, speed, accel,excavator_ip) = helpers.get_field_values(self)
                helpers.save_config(self, ip1, ip2, speed, accel, excavator_ip)
                # Only allow motion platform to be started after excavator has been found
                self.start_button.setEnabled(True) 
                self.excavator_tab.start_driving_btn.setEnabled(True)
                # self.enable_excavator_action_buttons() # for testing
            else:
                QMessageBox.critical(self, "Error", f"Could not find excavator with ip: {ip}")
                self.excavator_tab.find_excavator_btn.setEnabled(True)
        except Exception as e:
            self.logger.error(f"Could not find excavator: {e}")
            QMessageBox.critical(self, "Error", f"Could not find excavator with ip: {ip}")

    def enable_excavator_action_buttons(self):
        """Enables all start action buttons"""
        self.excavator_tab.start_mirroring_btn.setEnabled(True)
        self.excavator_tab.start_driving_btn.setEnabled(True)
        self.excavator_tab.start_driving_and_mirroring_btn.setEnabled(True)

    def disable_excavator_action_buttons(self):
        self.excavator_tab.start_mirroring_btn.setEnabled(False)
        self.excavator_tab.stop_mirroring_btn.setEnabled(False)
        self.excavator_tab.start_driving_btn.setEnabled(False)
        self.excavator_tab.stop_driving_btn.setEnabled(False)
        self.excavator_tab.start_driving_and_mirroring_btn.setEnabled(False)
        self.excavator_tab.stop_driving_and_mirroring_btn.setEnabled(False)

    def emit_excavator_disconnected(self):
        """This will be called from a different thread and needs the use of signal-slot system"""
        self.excavator_disconnected.emit()

    def emit_excavator_event(self,event):
        """This will be called from a different thread and needs the use of signal-slot system"""
        self.excavator_event.emit(event)

    def emit_excavator_error(self,error_msg,context):
        """This will be called from a different thread and needs the use of signal-slot system"""
        self.excavator_error.emit(error_msg, context)

    def on_excavator_disconnected(self):
        """This runs on the main thread"""
        QMessageBox.information(self, "Info", "Excavator connection has been closed")
        self.start_button.setEnabled(False) 
        self.excavator_tab.find_excavator_btn.setEnabled(True)
        self.disable_excavator_action_buttons()

    def start_mirroring(self):
        receive_rate=self.excavator_tab.orientation_receive_rate.text().strip()
        r=self._validate_float(receive_rate)
        if r[0] is False:
            QMessageBox.critical(self, "Error", r[2])
            return
        receive_rate=r[1]
        self.disable_excavator_action_buttons()
        self.excavator_client.start_mirroring(orientation_send_rate=receive_rate)

    def toggle_channel_selection(self, mode):
        self.excavator_tab.channel_group.setVisible(mode == "Manual Selection")

    def get_selected_channels(self):
        """Return: result, data, err_msg"""
        if self.excavator_tab.channel_mode.currentText() == "All Channels":
            return True, PWM_CHANNELS, None
        channels=[]
        for i, cb in enumerate(self.excavator_tab.channel_checkboxes):
            if cb.isChecked(): channels.append(PWM_CHANNELS[i])
        if len(channels) == 0:
            return False, None, "Atleast one controllable PWM channel must be selected."
        return True, channels, None

    def _validate_float(self, num):
        """Returns result,data,err_msg"""
        try:
            num=float(num)
            return True, num, None
        except ValueError:
            return False, None, f"Invalid Number {num}"
        
    def stop_mirroring(self):
        self.disable_excavator_action_buttons()
        self.excavator_client.stop_mirroring()

    def start_driving(self):
        send_rate=self.excavator_tab.commands_send_rate.text().strip()
        # Validate
        r1 = self.get_selected_channels()
        if r1[0] is False: 
            QMessageBox.critical(self, "Error", r1[2])
            return
        r2=self._validate_float(send_rate)
        if r2[0] is False:
            QMessageBox.critical(self, "Error", r2[2])
            return
        
        controllable_chans=r1[1]
        send_rate=r2[1]
        self.disable_excavator_action_buttons()
        self.excavator_client.start_driving(drive_sending_rate=send_rate, channel_names=controllable_chans)

    def stop_driving(self):
        self.disable_excavator_action_buttons()
        self.excavator_client.stop_driving()

    def start_driving_and_mirroring(self):
        receive_rate=self.excavator_tab.orientation_receive_rate.text().strip()
        send_rate=self.excavator_tab.commands_send_rate.text().strip()
        # Validate
        r1=self._validate_float(send_rate)
        r2=self._validate_float(receive_rate)
        if r1[0] is False:
            QMessageBox.critical(self, "Error", r1[2])
            return
        if r2[0] is False:
            QMessageBox.critical(self, "Error", r2[2])
            return
        r3 = self.get_selected_channels()
        if r3[0] is False: 
            QMessageBox.critical(self, "Error", r3[2])
            return
        
        controllable_chans=r3[1]
        self.disable_excavator_action_buttons()
        send_rate=r1[1]
        receive_rate=r2[1]
        self.excavator_client.start_driving_and_mirroring(orientation_send_rate=receive_rate, drive_sending_rate=send_rate, channel_names=controllable_chans)

    def stop_driving_and_mirroring(self):
        self.disable_excavator_action_buttons()
        self.excavator_client.stop_driving_and_mirroring()

    def on_excavator_event(self, event):
        print(f"event cb: {event}")
        if event=="started_mirroring":
            QMessageBox.information(self, "Info", "Successfully started mirroring operation!")
            self.excavator_tab.stop_mirroring_btn.setEnabled(True)
        elif event == "started_driving":
            QMessageBox.information(self, "Info", "Successfully started driving operation!")
            self.excavator_tab.stop_driving_btn.setEnabled(True)
        elif event=="started_driving_and_mirroring":
            QMessageBox.information(self, "Info", "Successfully started driving&mirroring operation!")
            self.excavator_tab.stop_driving_and_mirroring_btn.setEnabled(True)
        elif event == "stopped_driving":
            QMessageBox.information(self, "Info", "Successfully stopped driving operation!")
            self.excavator_tab.start_driving_btn.setEnabled(True)
            self.excavator_tab.stop_driving_btn.setEnabled(False)
        elif event=="stopped_driving_and_mirroring":
            QMessageBox.information(self, "Info", "Successfully stopped driving&mirroring operation!")
            self.excavator_tab.start_driving_and_mirroring_btn.setEnabled(True)
            self.excavator_tab.stop_driving_and_mirroring_btn.setEnabled(False)
        elif event=="stopped_mirroring":
            QMessageBox.information(self, "Info", "Successfully stopped mirroring operation!")
            self.excavator_tab.start_mirroring_btn.setEnabled(True)
            self.excavator_tab.stop_mirroring_btn.setEnabled(False)

    def on_excavator_error(self, error_msg, context):
        if context=="start_mirroring":
            QMessageBox.critical(self, "Info", f"Error starting mirroring: {error_msg}")
            self.enable_excavator_action_buttons()
        elif context == "start_driving":
            QMessageBox.critical(self, "Info", f"Error starting driving: {error_msg}")
            self.enable_excavator_action_buttons()
        elif context=="start_driving_and_mirroring":
            QMessageBox.critical(self, "Info", f"Error starting driving and mirroring: {error_msg}")
            self.enable_excavator_action_buttons()
        elif context == "stop_driving":
            QMessageBox.critical(self, "Info", f"Error stopping driving: {error_msg}")
            self.enable_excavator_action_buttons()
        elif context=="stop_driving_and_mirroring":
            QMessageBox.critical(self, "Info", f"Error stopping driving and mirroring: {error_msg}")
            self.enable_excavator_action_buttons()
        elif context=="stop_mirroring":
            QMessageBox.critical(self, "Info", f"Error stopping mirroring: {error_msg}")
            self.enable_excavator_action_buttons()

    def clear_fault(self):
        asyncio.create_task(helpers.clear_fault(self))

    def kill_mevea_processes(self):
        """
        Checks if any mevea releated process are on going. If so terminates them.
        """
        try:
            meVEAMotionPlatformUIApp = helpers.findProcessByName("MeVEAMotionPlatformUIApp")
            meveaSimulatorWatchdog = helpers.findProcessByName("MeveaSimulatorWatchdog")
            simulatorLauncher = helpers.findProcessByName("SimulatorLauncher")

            if meVEAMotionPlatformUIApp.stdout:
                self.process_manager.kill_process(meVEAMotionPlatformUIApp.stdout.strip())
            if simulatorLauncher.stdout:
                self.process_manager.kill_process(simulatorLauncher.stdout.strip())
            if meveaSimulatorWatchdog.stdout:
                self.process_manager.kill_process(meveaSimulatorWatchdog.stdout.strip())
        except Exception as e:
            self.logger.error(f"Error checking mevea processes. Error: {e}")
            os._exit(0)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Initialize qasync event loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = ServerStartupGUI()
    window.kill_mevea_processes()
    window.show()

    with loop:
        loop.run_forever()