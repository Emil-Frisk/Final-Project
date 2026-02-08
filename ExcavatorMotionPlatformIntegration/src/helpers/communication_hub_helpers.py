from utils.utils import extract_part
from time import time


def validate_update_values(values):
    acc = int(values["acceleration"])
    vel = int(values["velocity"])
    if (vel < 0) or acc < 0:
        return False
    return True

def close_tasks(self):
    if hasattr(self, "monitor_fault_poller"):
        self.monitor_fault_poller.cancel()
        self.logger.info("Closed monitor fault poller")
    # if hasattr(self, "monitor_velocity_controller"):
    #     self.monitor_velocity_controller.cancel()
    #     self.logger.info("Closed monitor velocity")

def validate_pitch_and_roll_values(pitch,roll):
    try:
        pitch = float(pitch)
        roll = float(roll)
        return (pitch,roll)
    except ValueError:
        raise
    
def validate_message(self,receiver, message):
    if not message:
        return (False, None, "event=error|message=Action message given, but no actual message found, example: message=<message>|")
    
    if not receiver:
        return (False, None, "event=error|message=No receiver given in the message, example: receiver=<receiver>|")

    for client, info in self.wsclients.items():
        if info["identity"] == receiver:
            return (True, client, message)
        
    return (False, None, f"event=error|message=No receiver was found in the server with this identity: {receiver}|")

def extract_parts(msg): # example message: "action=STOP|receiver=startup|identity=fault_poller|message=CRITICAL FAULT!|pitch=40.3"
    receiver = extract_part("receiver=", message=msg)
    identity = extract_part("identity=", message=msg)
    message = extract_part("message=", message=msg)
    event = extract_part("event=", message=msg)
    acceleration = extract_part("acc=", message=msg)
    velocity = extract_part("vel=", message=msg)
    if receiver:
        receiver = receiver.lower()
    ### if message has event append it to it
    if message and event:
        message = f"event={event}|message={message}|"

    return (receiver, identity, message,acceleration,velocity)

import asyncio
import psutil

async def monitor_fault_poller(self): 
    """
    Heathbeat monitor that makes sure fault poller
    stays alive and if it dies it restarts it
    """
    while True:
        if hasattr(self, 'fault_poller_pid'):
            pid = self.fault_poller_pid
            if pid and not psutil.pid_exists(pid):
                self.logger.warning(f"fault_poller (PID: {pid}) is not running, restarting...")
                new_pid = self.process_manager.launch_process("fault_poller")
                self.fault_poller_pid = new_pid
                self.logger.info(f"Restarted fault_poller with PID: {new_pid}")
                del self.process_manager.processes[pid]
        await asyncio.sleep(10)  # Check every 10 seconds
        
async def monitor_velocity_controller(self):
    """
    Heathbeat monitor that makes sure velocity controller
    stays alive and if it dies it restarts it
    """
    while True:
        if hasattr(self, 'velocity_controller_pid'):
            pid = self.velocity_controller_pid
            if pid and not psutil.pid_exists(pid):
                self.logger.warning(f"velocity_controller (PID: {pid}) is not running, restarting...")
                new_pid = self.process_manager.launch_process("velocity_controller")
                self.velocity_controller_pid = new_pid
                self.logger.info(f"Restarted velocity_controller with PID: {new_pid}")
                del self.process_manager.processes[pid]
        await asyncio.sleep(10)  # Check every 10 seconds


async def monitor_socket_server(self):
    """
    Heathbeat monitor that makes sure socket server     
    stays alive and if it dies it restarts it
    """
    while True:
        if hasattr(self, 'so_srv_pid'):
            pid = self.so_srv_pid
            if pid and not psutil.pid_exists(pid):
                self.logger.warning(f"socket server (PID: {pid}) is not running, restarting...")
                new_pid = self.process_manager.launch_process("websocket_server")
                self.so_srv_pid = new_pid
                self.logger.info(f"Restarted websocket server with PID: {new_pid}")
                del self.process_manager.processes[pid]
        await asyncio.sleep(60)

async def create_hearthbeat_monitor_tasks(self):
    self.monitor_fault_poller = asyncio.create_task(monitor_fault_poller(self))

def create_processes(self):
    result = self.process_manager.exterminate_lingering_process("fault_poller")
    if not result:
        self.logger.error(f"Unable to kill lingering process with name: main. Not launching a new process...")
        return
    elif result:
        self.logger.info(f"No lingering process remaining.")
    fault_poller_pid = self.process_manager.launch_process("fault_poller")
    self.fault_poller_pid = fault_poller_pid
    
def rate_limit(lastcall, max_freq):
    """
    Limits rate of requests to server.
    """
    min_interval = 1.0 / max_freq
    current_time = time()
    delta_time = current_time - lastcall
    
    if delta_time < min_interval:
        return False
    return True