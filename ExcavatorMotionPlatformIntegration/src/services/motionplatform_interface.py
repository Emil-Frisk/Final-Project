import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from colorama import init, Fore, Style
import sys
from typing import Union
import subprocess
from time import time, sleep
from concurrent.futures import ThreadPoolExecutor
import threading



"""MOTIONPLATFORM INTERFACE"""

def format_response(**kwargs):
       """
       Expects possible kwargs of event=event, action=action, message=message
       """
       msg_parts = []
       for key, val in kwargs.items():
              msg_parts.append(f"|{key}={val}|")
        
       return "".join(msg_parts)

class MotionPlatformInterface():
    def __init__(self, logging=True):
        self.logging = logging
        self.error = False
        self.warnings = {}
        self._loop = None
        self._loop_thread = None
        self.stopped = False

    async def _init(self):
        """
        Initializes logger for motionplatform_interface class and WebsocketClient object.
        Connects to websocket server.
        """
        try:
            # if not get_process_info(self,"gui"):
            #     raise Exception("Run motionplatform.bat file first!")
            if not get_process_info(self,"main"):
                raise Exception("Start server first!")
            self.logger.info("_init ran")
            self.wsclient = WebSocketClient(logger=self.logger, identity="interface", on_message=self._handle_client_message)
            self.logger.info("Ws client obj made")
            await self.wsclient.connect()
        except Exception as e:
            self.logger.error(str(e))
            os._exit(1)

    async def _rotate(self,pitch,roll):
            """
            Takes parameters pitch and roll and rotates motionplatform accordingly with given values.
            Raises ValueError if rotate frequency is too fast.
            """
            try:
                if self.error:
                    self.logger.error(f"Error rotating motionplatform. Error: {self.error}")
                    raise ValueError(f"Error rotating motionplatform. Error: {self.error}")
                await self.wsclient.send(f"action=rotate|pitch={pitch}|roll={roll}|")
            except Exception as e:
                self.logger.error(f"Error while calling rotate function.{e}")

    async def _stop(self):
            """
            Tries to stop both motors
            """
            try:
                await self.wsclient.send(format_response(action="stop"))
                self.stopped = True
            except Exception as e:
                self.logger.error(f"Error while calling stop function.{e}")

    async def _continue(self):
            """
            Tries to remove stop state from both motors
            """
            try:
                await self.wsclient.send(format_response(action="continue"))
                ### wait for the API to process the command
                await asyncio.sleep(0.1)
                self.stopped = False
            except Exception as e:
                self.logger.error(f"Error while calling continue function.{e}")

    def _start_background_loop(self):
        """Start event loop in background thread"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.logger.info("Background event loop has been registered and is running")
        self._loop.run_forever()
    def _handle_client_message(self, message): 
        """
        Handles messages recevied from server.
        """
        event = extract_part("event=", message=message)
        clientmessage = extract_part("message=", message=message)
        if not event:
            self.logger.error("No event specified in message.")
            return 
        if not clientmessage: 
            self.logger.error("No client message specified in message.")
            return
        elif event == "error":
            self.error = clientmessage
        elif event == "warning":
            if not clientmessage in self.warnings:
                self.warnings[clientmessage] = clientmessage
                self.logger.warning(clientmessage)
    def init(self):
        """Initialize with background event loop"""
        if self._loop_thread is None:
            self.logger = setup_logging("motionplatform_interface", "motionplatform_interface.log", extensive_logging=self.logging)
            self._loop_thread = threading.Thread(target=self._start_background_loop, daemon=True)
            self._loop_thread.start()
            
            # Wait for loop to be ready
            while self._loop is None:
                sleep(0.01)
                
            # Schedule the init on the background loop
            future = asyncio.run_coroutine_threadsafe(self._init(), self._loop)
            future.result()  # Wait for completion
            self.logger.info("future ressult for _init() done")
        
    def set_angles(self, pitch, roll):
        """Synchronous method that uses background event loop"""
        if self._loop is None:
            raise RuntimeError("Must call init() first")
        
        pitch=float(pitch)
        roll=float(roll)
            
        future = asyncio.run_coroutine_threadsafe(self._rotate(pitch, roll), self._loop)
        future.result()  # Wait for completion
    
    def stop(self):
        """Synchronous method that uses background event loop"""
        if self._loop is None:
            raise RuntimeError("Must call init() first")
            
        future = asyncio.run_coroutine_threadsafe(self._stop(), self._loop)
        future.result()  # Wait for completion

    def continue_motors(self):
        """Synchronous method that uses background event loop"""
        if self._loop is None:
            raise RuntimeError("Must call init() first")
            
        future = asyncio.run_coroutine_threadsafe(self._continue(), self._loop)
        future.result()  # Wait for completion

    def close(self):
        """Perform a clean shutdown of the client, motors, and event loop."""
        if self._loop is None:
            raise RuntimeError("Must call init() first")

        # Ensure motors able to move back into neutral position
        if self.stopped:
            future = asyncio.run_coroutine_threadsafe(self._continue(), self._loop)
            try:
                self.logger.info("Resuming motors after shutdown")
            except Exception as e:
                self.logger.error(f"Failed to resume motors: {e}")

        # Stop motor rotation
        self.logger.info("rotating motors")
        ### Makes sure that the rotate command is not too fast 
        sleep(0.1)
        future = asyncio.run_coroutine_threadsafe(self._rotate(0, 0), self._loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            self.logger.error(f"Failed to stop motors: {e}")

        # Close WebSocket client
        self.logger.info("Closing WebSocket client")
        future = asyncio.run_coroutine_threadsafe(self.wsclient.close(), self._loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            self.logger.error(f"WebSocket client close failed or timed out: {e}")
                
"""THIS IS FOR LOGGING"""        
# Initialize colorama for cross-platform colored output
init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to console output based on log level."""
    # Define color formats for different log levels
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def __init__(self, fmt, use_hyperlinks=True):
        super().__init__(fmt)
        self.use_hyperlinks = use_hyperlinks
        
    def format(self, record):
        try:
            # Apply the color based on the log level
            color = self.LEVEL_COLORS.get(record.levelno, Fore.WHITE)  # Default to white if level not found
            if self.use_hyperlinks and record.levelno in (logging.ERROR, logging.CRITICAL):
                # Ensure the filename is an absolute path
                record.hyperlink = f"{os.path.abspath(record.pathname)}:{record.lineno}"
            else:
                record.hyperlink = f"{record.module}:{record.lineno}"
            # Format the message with color and reset
            formatted = color + super().format(record) + Style.RESET_ALL
            return formatted
        except Exception as e:
            # Fallback if path resolution fails
            record.hyperlink = f"{record.filename}:{record.lineno}"
            logging.getLogger(__name__).warning(
                f"Failed to resolve path for {record.filename}:{record.lineno}: {str(e)}"
            )
def setup_logging(name, filename,extensive_logging, log_to_file=False):
    log_dir = "logs"
    parent_log_dir = os.path.join(Path(__file__).parent.parent.parent, "logs")
    if not os.path.exists(parent_log_dir):
        os.makedirs(parent_log_dir)
    
    log_format = '%(asctime)s - %(levelname)s - MODULE: - %(hyperlink)s - %(message)s'

    # Set up file handler
    log_file = os.path.join(parent_log_dir, filename)
    # Set up file handler (plain text, no colors or hyperlinks)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1024*1024,
        backupCount=1,
        encoding='utf-8'
    )
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    console_formatter = ColoredFormatter(log_format, use_hyperlinks=True)    
    #setup console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    # config root logger
    logger = logging.getLogger(name)

    if extensive_logging:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)
    if not logger.handlers:
        if log_to_file:
            logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger         

def get_process_info(self,process_name) -> Union[int, bool]:
    """returns the processes PID or False if not successful"""
    
    ps_command= f"""
        Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
        Where-Object {{ $_.CommandLine -like "*entrypoint={process_name}*" }} |
        Select-Object ProcessId, CommandLine
        """

    try:
        result = subprocess.run(
            ["powershell.exe", "-Command", ps_command],
            capture_output=True,
            text=True,
            check=True
        )
        
        if result.stdout:
            pid = extract_pid_from_commandline(self,result.stdout)
            if not pid:
                return False
            self.logger.info(f"Existing pid found with a process name: {process_name} pid: {pid}")
            return pid
        else:
            return False
        
    except subprocess.CalledProcessesError as e:
        self.logger.error(f"Error running PowerShell command: {e.stderr}")
        return False

def extract_pid_from_commandline(self, result) -> Union[int, bool]:
    try:
        trimmed = result.replace(" ", "")
        results = trimmed.split("\n")
        command_lines = []
        for r in results:
            if len(r.split(".exe")) == 1:
                continue
            else:
                command_lines.append(r)
        
        temp = command_lines[0]
        self.logger.info(f"Found {len(command_lines)} command lines")
        pid_list = []
        for ch in temp:
            try:
                int(ch)
                pid_list.append(ch)
            except ValueError as e:
                break
        pid_list = "".join(pid_list)
        return int(pid_list)
    except ValueError:
        self.logger.error("Unable to extract pid from a found commandline")
        return False
    except Exception as e:
        self.logger.error("Unexpected error while extracting pid from a commandline string")

from dataclasses import dataclass

@dataclass
class Config:
    WEBSOCKET_SRV_PORT = 7000
    
    ### SERVER CONFIG
    SERVER_IP_LEFT: str = '192.168.0.211'  
    SERVER_IP_RIGHT: str = '192.168.0.212'
    SERVER_PORT: int = 502  
    WEB_SERVER_PORT: int = 5001

    ### USEFUL MAX VALUES
    UINT32_MAX = 65535

    ### 
    MODULE_NAME = None
    POLLING_TIME_INTERVAL: float = 5.0
    POS_UPDATE_HZ: int = 1
    START_TID: int = 10001 # first TID will be startTID + 1
    LAST_TID: int = 20000
    CONNECTION_TRY_COUNT = 5

import asyncio
import websockets
from websockets.exceptions import ConnectionClosed

config = Config()

class WebSocketClient():
    def __init__(self, logger, identity="unknown", uri=f"ws://localhost:{config.WEBSOCKET_SRV_PORT}", on_message=None, reconnect_interval=2.5, max_reconnect_attempt=10):
        self.uri = uri
        self.socket = None
        self.is_running = False
        self.on_message = on_message
        self._listen_task = None
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempt = max_reconnect_attempt
        self.reconnect_count = 0
        self.logger = logger
        self.identity = identity
        self._connection_lock = asyncio.Lock()
        
    async def connect(self):
        async with self._connection_lock:
            try:
                if self.is_running:
                    self.logger.info("Client is already connected, can't connect again")
                    return 
                
                await self._cleanup_connection()
                
                self.socket = await websockets.connect(
                    self.uri,
                    ping_interval=None,  # Disable automatic ping
                    ping_timeout=None    # Disable ping timeout
                )
                await self.socket.send(f"action=identify|identity={self.identity}|")
                self.is_running = True
                self.reconnect_count = 0
                self.logger.info(f"client connected to server: {self.uri}")
                
                if self.on_message:
                    self.on_message(f"event=connected|message=Client connected to server.|")
                # Create new listen task
                self._listen_task = asyncio.create_task(self._listen())
            except asyncio.TimeoutError:
                await self._handle_connection_failure(f"Connection timed out")
            except Exception as e:
                await self._handle_connection_failure(f"Error connecting to the server: {e}")
            finally:
                pass
    
    async def _handle_connection_failure(self, error_msg):
        """Handle a connection failure by scheduling a reconnect or closing the client."""
        async with self._connection_lock:
            self.logger.error(f"Connection failed: {error_msg}")
            self.is_running = False
                
            self.reconnect_count += 1
            if self.reconnect_count < self.max_reconnect_attempt:
                asyncio.create_task(self._schedule_reconnect())
            else:
                self.logger.info("Maximum reconnect attempts reached, closing client")
                await self._cleanup_connection()
    async def _listen(self):
        try:
            self.logger.info("Creating listening coroutine for client")
            while self.is_running and self.socket:
                try:
                    response = await self.socket.recv()
                    if self.on_message:
                        self.on_message(response)
                except ConnectionClosed:
                    self.logger.info("Client disconnected from the server")
                    # Expected client closage dont try to reconnect
                    self.is_running = False
                    self.logger.error("server closed connection, likely two different connetions")
                    os._exit(1)
                except Exception as e:
                    self.logger.error(f"Error receiving message: {e}")
                    break
                    
        except Exception as e:
            self.logger.error(f"Exception in the listen coroutine: {e}")
        finally:
            # Only trigger reconnection if we were supposed to be running
            if self.is_running:
                await self._handle_connection_failure("Listen coroutine ended unexpectedly")

    async def _schedule_reconnect(self):
        """Schedule a reconnection attempt after a delay."""
        try:
            await asyncio.sleep(self.reconnect_interval)
            await self.connect()
        except Exception as e:
            self.logger.error(f"Error during reconnection: {e}")

    async def send(self, message):
        try:
            if not self.is_running or not self.socket:
                self.logger.info("Client not connected, can't send a message")
                return False

            await self.socket.send(message)
            return True
        except ConnectionClosed:
            self.logger.warning("Connection closed while sending message")
            await self._handle_connection_failure("Connection closed during send")
            return False
        except Exception as e:
            self.logger.error(f"Error while client was sending a message: {e}")
            await self._handle_connection_failure(f"Send error: {e}")
            return False

    async def _cleanup_connection(self):
        """Clean up existing connection and tasks."""
        # Cancel and wait for listen task
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # Close socket
        if self.socket:
            try:
                await self.socket.close()
            except Exception as e:
                self.logger.error(f"Error closing socket: {e}")
            finally:
                self.socket = None

    async def close(self):
        """Close the websocket connection and clean up resources."""
        async with self._connection_lock:
            try:
                self.is_running = False
                await self._cleanup_connection()
                self.logger.info("Client socket closed")
            except Exception as e:
                self.logger.error(f"Exception while closing client: {e}")

    async def _wait_for_connection(self, timeout=10):
        """Wait for the client to be connected, useful for testing."""
        start_time = asyncio.get_event_loop().time()
        while not self.is_running and (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.1)
        return self.is_running

def extract_part(part, message):
    start_idx = message.find(part)
    if start_idx == -1:
        return False
    
    start_idx += len(part)
    pipe_idx = message.find("|", start_idx)
    if pipe_idx == -1:
        return False
    
    return  message[start_idx:pipe_idx]