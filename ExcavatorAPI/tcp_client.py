import threading
from time import sleep
from typing import List
from udp_socket import UDPSocket
from dataclass_types import ExcavatorAPIProperties
from utils import setup_logging

from random import uniform
import json
import asyncio
import logging
import atexit
import websockets
import psutil
import multiprocessing
import os

# Maps to which index to read from in the controller loop
controller_channelname_map={
    "lift_boom": 0,
    "tilt_boom": 1,
    "scoop": 2,
    "rotate": 3
}

EVENTS={"handshake","screen_message_displayed","configuration","status","started_screen","started_mirroring","started_driving","stopped_driving","stopped_mirroring","started_driving_and_mirroring","stopped_driving_and_mirroring","stopped_screen","error"}

def simulate_joystick_data(channel_names):
    inputs = []
    deadzone=0.2
    for i in range(4):
        new_val=uniform(-1, 1)
        if not (abs(new_val) > deadzone):
            new_val=0
        inputs.append(new_val)

    mapped_inputs=[]
    for channel_name in channel_names:
        mapped_inputs.append(inputs[controller_channelname_map[channel_name]])
    return mapped_inputs

def controller_poller_loop(controller_stop_queue, controller_data_queue, polling_rate, channel_names):
    controller_data_queue.put(os.getpid())
    sleep_time=1/polling_rate
    logger=setup_logging("controller_poller")
    previous_inputs=[0]*len(channel_names)
    simulation=True
    try:
        try:
            from services.NiDAQ_controller import NiDAQJoysticks
            controller=NiDAQJoysticks(output_format="float")
            simulation=False
        except Exception:
            logger.error("Could not import nidaq controllers. Using simulated values instead")
        logger.info("[Controller Process] Controller poller loop has started")
        while True:
            new_value=False
            if simulation is True:
                inputs=simulate_joystick_data(channel_names=channel_names)
            else:
                ai_values, di_values = controller.read()
                inputs = [0]*len(channel_names)
                for j, chan_name in enumerate(channel_names):
                    inputs[j]=(ai_values[controller_channelname_map[chan_name]])

            # Only update the que if there is a new value
            for i, input in enumerate(inputs):
                if previous_inputs[i] != input:
                    new_value=True
                    break

            # Update the queue only if its empty
            if controller_data_queue.empty() and new_value:
                controller_data_queue.put(inputs)
                previous_inputs = [0]*len(channel_names)
            elif not controller_data_queue.empty() and new_value:
                # Update the non consumed queue
                prev_queue_vals=controller_data_queue.get()
                for i, prev_val in enumerate(prev_queue_vals):
                    # Only update if the prev value was 0
                    if prev_val != inputs[i] and prev_val == 0:
                        prev_queue_vals[i]=prev_val
                controller_data_queue.put(prev_queue_vals)
                previous_inputs = [0]*len(channel_names)

            # Check for stop signal
            if not controller_stop_queue.empty():
                logger.info("[Controller Process] Received shutdown signal")
                break
            sleep(sleep_time)
        logger.info("[Controller Process] Controller poller loop has exited")
    except Exception as e:
        logger.error(f"[Controller Process] Controller poller crashed: {e}")
        controller.close()
        controller_data_queue.put("^")

def client_operation(func):
    def wrapper(self, *args, **kwargs):
        if not self.client_running:
            raise RuntimeError("Can't perform client operation without client connected to the server")
        if self.client is None:
            raise RuntimeError("Can't perform client operation without a client object!")
        if not self.loop:
            raise RuntimeError("Can't find the event loop")
        return func(self,*args,**kwargs)
    return wrapper

class TCPClient:
    def __init__(self, srv_ip="10.214.33.25", srv_port=5432, controller_monitor_interval=7,controller_poll_rate=128, testing_enabled=False, socket_timeout=3, logging_level="INFO",client_timeout=5,mpi_enabled=False):
        self.logger = setup_logging(filename="ExcavatorAPIClient",logging_level=logging_level)
        # TCP Client
        self.client_run_thread=None
        self.client_timeout=client_timeout
        self.client_running = False
        self.loop=None
        self.shutdown_event = threading.Event()
        self.final_cleanup_done = threading.Event()
        self.stop_event = threading.Event()
        self.data_lock = threading.Lock()
        self.testing_enabled=testing_enabled
        self.socket_timeout=socket_timeout
        self.current_operation = ExcavatorAPIProperties.OPERATIONS["none"]
        self.logging_level=logging_level
        self.srv_ip = srv_ip
        self.srv_port = srv_port
        self.client = None

        # Mirroring
        self.mirroring = False
        self._read_orientation_thread=None
        self.orientation_reading_rate=None
        self.orientation_reading_rate_tmp=None
        self.mirroring_starting=False
        self.mirroring_stopping=False

        # Controller
        self.controller_monitor_thread=None
        self.controller_monitor_interval=controller_monitor_interval
        self.controller_poll_rate=controller_poll_rate
        self.controller_stop_queue=None
        self.controller_data_queue=None
        self.controller_pid=None
        self.controller_process=None

        # Driving
        self.driving=False
        self._driving_commands_thread=None
        self.drive_sending_rate=None
        self.drive_sending_rate_tmp=None
        self.driving_starting=False
        self.driving_stopping=False
        self.channel_names=None

        # Driving&Mirroring
        self.driving_and_mirroring=False
        self.driving_and_mirroring_starting=False
        self.driving_and_mirroring_stopping=False

        # UDP server
        self.udp_server = None
        self.num_outputs=0
        self.num_outputs_tmp=0
        self.num_inputs=0
        self.udp_server_starting=False
        self.udp_server_stopping=False

        # MPI
        self.mpi=None
        self.mpi_enabled=mpi_enabled

        # Testing stoff
        self.errors_counter=0
        self.recent_config=None
        self.test_continuation_signal=threading.Event()

    def start(self):
        if self.client_running: return False
        self.client_run_thread=threading.Thread(target=self._run_client_async, daemon=True)
        self.client_run_thread.start()

        # Poll until ready...
        for _ in range(5):
            if self.is_ready(): return True
            sleep(1)
        return False

    def is_ready(self):
        return self.client_running

    def _run_client_async(self):
        try:
            self.loop=asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._start_client())
        except Exception as e:
            self.logger.error(f"Async client error: {e}")
            self._cleanup_operation()

    async def _start_client(self):
        try:
            websocket = await asyncio.wait_for(
                websockets.connect(f"ws://{self.srv_ip}:{self.srv_port}"),
                timeout=3.0
            )
            async with websocket:
                self.client=websocket
                self.logger.info(f"Client connected to WebSocket server at ws://{self.srv_ip}:{self.srv_port}")
                atexit.register(self.shutdown)
                self.client_running = True
                asyncio.create_task(self._ws_receiver())
                while not self.shutdown_event.is_set():
                    await asyncio.sleep(self.client_timeout)
            self.logger.info("Event loop thread has been shutdown")
        except asyncio.TimeoutError:
            self.logger.error(f"Failed to find excavatorAPI {self.srv_ip}:{self.srv_port}")
        except Exception as e:
            self.logger.error(f"Failed to start the tcp client: {e}")

    async def _ws_receiver(self):
        try:
            self.logger.info("Websocket has started listening for messages")
            while not self.stop_event.is_set():
                try:
                    message= await asyncio.wait_for(self.client.recv(), timeout=self.client_timeout)
                    await self.__handle_message(message)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    self.logger.info("Connection closed by the server")
                    break
        except Exception as e:
            self.logger.error(f"Error while listening for messages: {e}")

        self.logger.info("TCPClient has stopped listening for messages...")
        await self.__cleanup_operation()
        self.shutdown_event.set()
        self.stop_event.set()
        with self.data_lock:
            self.client_running=False

    def get_current_operation(self):
        if not self.client_running: return
        return ExcavatorAPIProperties.OPERATIONS_REVERSE[self.current_operation]

    def send_data(self,data):
        asyncio.run_coroutine_threadsafe(self._send_data(data=data),self.loop)

    async def _send_data(self,data):
        await self.client.send(json.dumps(data))

    @client_operation
    def send_screen_message(self, header, body, render_count=1, render_time=10.0):
        try:
            command={
                "action": "screen_message",
                "render_count": render_count,
                "render_time": render_time,
                "body": body,
                "header": header
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Client failed to send a message: {e}")

    @client_operation
    def start_screen(self):
        try:
            command={
                "action": "start_screen",
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Client failed to send a message: {e}")

    @client_operation
    def stop_screen(self):
        try:
            command={
                "action": "stop_screen",
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Client failed to send a message: {e}")

    @client_operation
    def get_screen_config(self):
        try:
            command={"action": "get_screen_config"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"get_screen_config: {e}")
    @client_operation
    def get_excavator_config(self):
        try:
            command={"action": "get_excavator_config"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"get_excavator_config: {e}")
    @client_operation
    def get_pwm_config(self):
        try:
            command={"action": "get_pwm_config"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"get_pwm_config: {e}")
    @client_operation
    def get_orientation_tracker_config(self):
        try:
            command={"action": "get_orientation_tracker_config"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"get_orientation_tracker_config: {e}")

    @client_operation
    def start_mirroring(self, orientation_send_rate=3):
        float(orientation_send_rate)
        self.orientation_reading_rate_tmp = orientation_send_rate
        try:
            command={
                "action": "start_mirroring",
                "orientation_send_rate": orientation_send_rate
            }
            self.send_data(command)
        except Exception as e:
            self.logger.info(f"Error at start_mirroring: {e}")

    @client_operation
    def start_driving(self, channel_names: List[str], drive_sending_rate=3):
        self.drive_sending_rate_tmp=drive_sending_rate
        self.num_outputs_tmp = len(channel_names)
        try:
            command = {
                "action": "start_driving",
                "channel_names": channel_names,
                "data_sending_rate": drive_sending_rate
            }
            self.channel_names=channel_names
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at start_mirroring: {e}")

    @client_operation
    def start_driving_and_mirroring(self, channel_names, drive_sending_rate=2, orientation_send_rate=3):
        self.orientation_reading_rate_tmp=orientation_send_rate
        self.drive_sending_rate_tmp=drive_sending_rate
        self.num_outputs_tmp=len(channel_names)
        try:
            command={
                "action":"start_driving_and_mirroring",
                "channel_names": channel_names,
                "data_sending_rate": drive_sending_rate,
                "data_receiving_rate": orientation_send_rate
            }
            self.channel_names=channel_names
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at start_mirroring: {e}")

    @client_operation
    def stop_driving_and_mirroring(self):
        try:
            command={"action":"stop_driving_and_mirroring"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at start_mirroring: {e}")

    @client_operation
    def stop_driving(self):
        try:
            command={"action": "stop_driving"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at start_mirroring: {e}")

    @client_operation
    def stop_mirroring(self):
        try:
            command = {"action":"stop_mirroring"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at stop_mirroring: {e}")

    @client_operation
    def configure_pwm_controller(self, pump=None, channel_configs=None):
        try:
            if pump == None and channel_configs == None:
                raise ValueError("Either pump config or channel_configs have to be provided")
            command={
                "action":"configure_pwm_controller",
            }
            command["channel_configs"] = {}
            if channel_configs:
                command["channel_configs"].update(channel_configs)
            if pump:
                command["channel_configs"].update({"pump":pump})
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at configure_pwm_controller: {e}")

    @client_operation
    def add_pwm_channel(self, channel_name, channel_type, config):
        try:
            command={
                "action": "add_pwm_channel",
                "channel_name": channel_name,
                "channel_type": channel_type,
                "config": config
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at start_mirroring: {e}")

    @client_operation
    def remove_pwm_channel(self, channel_name):
        try:
            command={
                "action":"remove_pwm_channel",
                "channel_name":channel_name
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at start_mirroring: {e}")

    @client_operation
    def configure_screen(self, default_render_time=None, font_size_header=None, font_size_body=None):
        try:
            command={
                "action":"configure_screen",
                "render_time":default_render_time,
                "font_size_header": font_size_header,
                "font_size_body": font_size_body
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at configure_screen: {e}")
    @client_operation
    def configure_excavator(self, has_screen=None):
        try:
            command={
                "action":"configure_excavator",
                "has_screen":has_screen
            }
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at configure_screen: {e}")

    @client_operation
    def configure_orientation_tracker(self,gyro_data_rate=None, accel_data_rate=None, gyro_range=None, accel_range=None, enable_lpf2=None,enable_simple_lpf=None,alpha=None,tracking_rate=None):
        try:
            # Convert False to 0 for filter params
            enable_lpf2 = 0 if enable_lpf2 is False else 1
            enable_simple_lpf = 0 if enable_simple_lpf is False else 1
            # Build the command up!
            command={"action": "configure_orientation_tracker"}
            if gyro_data_rate is not None: command["gyro_data_rate"] = gyro_data_rate
            if accel_data_rate is not None: command["accel_data_rate"]=accel_data_rate
            if gyro_range is not None: command["gyro_range"]=gyro_range
            if accel_range is not None: command["accel_range"]=accel_range
            if enable_lpf2 is not None: command["enable_lpf2"]=enable_lpf2
            if enable_simple_lpf is not None: command["enable_simple_lpf"]=enable_simple_lpf
            if alpha is not None: command["alpha"]=alpha
            if tracking_rate is not None: command["tracking_rate"]=tracking_rate
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at configure_screen: {e}")

    @client_operation
    def get_screen_status(self):
        try:
            command={"action":"status_screen"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at get_screen_status:  {e}")

    @client_operation
    def get_orientation_tracker_status(self):
        try:
            command={"action":"status_orientation_tracker"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at get_orientation_tracker_status:  {e}")

    @client_operation
    def get_mirroring_status(self):
        try:
            command={"action":"status_udp"}
            self.send_data(command)
        except Exception as e:
            self.logger.error(f"Error at get_orientation_tracker_status:  {e}")

    def set_log_level(self, level: str) -> None:
        """Change the logging level at runtime.

        Args:
            level: One of "DEBUG", "INFO", "WARNING", "ERROR"
        """
        self.logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    def __start_mirroring_threads(self):
        if self._read_orientation_thread is not None and self._read_orientation_thread.is_alive():
            raise RuntimeError("Failed to start mirroring op. Orientation reading thread already running.")
        self._read_orientation_thread = threading.Thread(target=self.__read_orientation_loop,daemon=True)
        self._read_orientation_thread.start()
        return True

    def __start_controller_process(self):
        with self.data_lock:
            if self.controller_process is not None:
                raise RuntimeError("Controller process already exists...?")
        self.__validate_rate(self.controller_poll_rate, context="self.controller_poll_rate")

        self.controller_stop_queue=multiprocessing.Queue()
        self.controller_data_queue=multiprocessing.Queue()
        self.controller_process =multiprocessing.Process(
            target=controller_poller_loop,
            args=(self.controller_stop_queue, self.controller_data_queue, self.controller_poll_rate, self.channel_names),
            daemon=True
        )
        self.controller_process.start()
        self.controller_pid=self.controller_data_queue.get()
        self.logger.info(f"Controller poller process has been started with pid: {self.controller_pid}")

    def __reset_controller_process_values(self):
        with self.data_lock:
            self.controller_process=None
            self.controller_data_queue=None
            self.controller_stop_queue=None
            self.controller_pid=None

    async def __shutdown_controller_process(self):
        self.logger.info("Shutting down controller process")
        
        # Always check if the PID actually exists first
        if self.controller_pid is not None:
            try:
                self.controller_stop_queue.put(1)
                for _ in range(int(ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)):
                    await asyncio.sleep(1)
                    p = psutil.Process(self.controller_pid)
                    self.logger.debug(f"Process status: {p.status()}, cmdline: {p.cmdline()}")
            except psutil.NoSuchProcess:
                self.logger.info("Controller process shutdown...")
                self.__reset_controller_process_values()
                return

            self.logger.warning("Controller not responding. Force killing...")
            try:
                p = psutil.Process(self.controller_pid)
                p.kill()
                await asyncio.sleep(1)
            except psutil.NoSuchProcess:
                return 

            if not psutil.pid_exists(self.controller_pid):
                self.__reset_controller_process_values()
            else:
                self.logger.error(f"Failed to shutdown controller process with pid: {self.controller_pid}")
        else: # Does not exist
            self.__reset_controller_process_values()

    def __start_driving_threads(self):
        if self._driving_commands_thread is not None and self._driving_commands_thread.is_alive():
            raise RuntimeError("Failed to start driving op. Driving commands thread already running.")
        self._driving_commands_thread = threading.Thread(target=self.__drive_commands_loop,daemon=True)
        self._driving_commands_thread.start()
        return True

    def __stop_driving_threads(self):
        if self._driving_commands_thread and self._driving_commands_thread.is_alive():
            if self._driving_commands_thread != threading.current_thread():
                self._driving_commands_thread.join(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)

    def __stop_mirroring_threads(self):
        if self._read_orientation_thread and self._read_orientation_thread.is_alive():
            if self._read_orientation_thread != threading.current_thread():
                self._read_orientation_thread.join(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)

    def __validate_rate(self,rate, context):
        if rate < ExcavatorAPIProperties.MIN_RATE:
            raise RuntimeError(f"Rate {context}: {rate} can't be smaller than {ExcavatorAPIProperties.MIN_RATE}")

    def __drive_commands_loop(self):
        try:
            sleep_time=1/self.drive_sending_rate
            self.__validate_rate(rate=self.drive_sending_rate, context="drive sending rate")
            self.logger.info(f"drive_commands_loop started. Sleep time: {sleep_time}")
            while not self.stop_event.is_set():
                command_values=[0] * self.num_outputs
                if self.controller_process is not None and not self.controller_data_queue.empty():
                    command_values = self.controller_data_queue.get()
                    # Check for error signal [^]
                    if not isinstance(command_values, list):
                        raise RuntimeError("Received error signal from the controller process")
                if self.udp_server:
                    self.udp_server.send(command_values)
                sleep(sleep_time)

            self.logger.info("Driving commands sending loop exited")
        except Exception as e:
            self.logger.error(f"Error occured in drive commands loop {e}")
            self._cleanup_operation()

    def __read_orientation_loop(self):
        try:
            sleep_time=1/self.orientation_reading_rate
            self.__validate_rate(rate=self.orientation_reading_rate, context="self.orientation_reading_rate")
            self.logger.info(f"orientation reading loop started. Sleep time: {sleep_time}")
            while not self.stop_event.is_set():
                if self.udp_server:
                    orientation=self.udp_server.get_latest()
                    if orientation is not None and self.mpi is not None:
                        self.mpi.set_angles(orientation[0],orientation[1])
                    else:
                        self.logger.info(f"orientation: {orientation}")
                sleep(sleep_time)
            self.logger.info("Orientation reading loop exited")
        except Exception as e:
            self.logger.error(f"Error occured in read_orientatioN_loop: {e}")
            self._cleanup_operation()

    async def _start_driving(self):
        with self.data_lock:
            if self.driving:
                return True
            if not self.__check_operation(): return False
            if self.driving_starting or self.driving_stopping:
                self.logger.warning("_start_driving: driving in transition")
                return False
            self.driving_starting=True
            self.drive_sending_rate=self.drive_sending_rate_tmp
            self.num_outputs=self.num_outputs_tmp
        try:
            error=False
            with self.data_lock:
                self.driving = True
                self.current_operation=ExcavatorAPIProperties.OPERATIONS["driving"]
            await self.__start_driving_services()
            self.logger.info("Driving operation has started")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start _start_driving: {e}")
            error=True
            return False
        finally:
            with self.data_lock:
                self.driving_starting=False
            if error:
                await self._stop_driving()

    async def _stop_driving(self):
        with self.data_lock:
            if not self.driving:
                return True
            if self.driving_starting or self.driving_stopping:
                self.logger.warning("_stop_driving: Driving in transtition.")
                return False
            self.driving_stopping=True
        try:
            await self._stop_driving_services()
            return True
        except Exception as e:
            self.logger.info(f"Failed to stop driving: {e}")
            return False
        finally:
            self.__reset_operation_values()

    async def __start_driving_services(self):
        self.logger.info("Starting driving services...")
        if not self.__start_udp_server(num_inputs=0, num_outputs=self.num_outputs):
            raise RuntimeError("Failed to start udp server")
        self.__start_controller_process()
        if not self.__start_driving_threads():
            raise RuntimeError("failed __start_driving_threads")

    async def _stop_driving_services(self):
        self.logger.info("Stopping driving services...")
        self.stop_event.set()
        await self.__shutdown_controller_process()
        self.__stop_driving_threads()
        if self.udp_server and not self.__stop_udp_server():
            raise RuntimeError("Failed to close UDP server")

    async def _start_driving_and_mirroring(self):
        with self.data_lock:
            if self.driving_and_mirroring: return True
            if not self.__check_operation(): return False
            if self.driving_and_mirroring_stopping or self.driving_and_mirroring_starting:
                self.logger.warning("start_driving_and_mirroring: Operation in transition")
                return False
            self.driving_and_mirroring_starting = True
            self.orientation_reading_rate=self.orientation_reading_rate_tmp
            self.drive_sending_rate=self.drive_sending_rate_tmp
            self.num_outputs=self.num_outputs_tmp
        try:
            error=False
            with self.data_lock:
                self.driving_and_mirroring = True
                self.current_operation=ExcavatorAPIProperties.OPERATIONS["driving_and_mirroring"]
            await self.__start_driving_and_mirroring_services()
            return True
        except Exception as e:
            self.logger.error(f"Failed to start driving and mirroring: {e}")
            error=True
        finally:
            with self.data_lock:
                self.driving_and_mirroring_starting = False
            if error:
                await self._stop_driving_and_mirroring()

    async def _stop_driving_and_mirroring(self):
        with self.data_lock:
            if not self.driving_and_mirroring: return True
            if self.driving_and_mirroring_stopping or self.driving_and_mirroring_starting:
                self.logger.warning("stop_driving_and_mirroring: Operation in transition already")
                return False
            self.driving_and_mirroring_stopping = True
        try:
            self.logger.info(f"Stopping driving and mirroring operation")
            await self._stop_driving_and_mirroring_services()
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop operation driving&mirroring: {e}")
            return False
        finally:
            self.__reset_operation_values()

    async def __start_driving_and_mirroring_services(self):
        self.logger.info("Starting driving&mirroring services...")
        if not self.__start_udp_server(num_inputs=3, num_outputs=self.num_outputs):
            raise RuntimeError("Failed to start udp client")
        if self.mpi_enabled: self._start_mpi()
        self.__start_controller_process()
        if not self.__start_driving_threads():
            raise RuntimeError("failed __start_driving_threads")
        if not self.__start_mirroring_threads():
                raise RuntimeError("failed __start_mirroring_threads")

    async def _stop_driving_and_mirroring_services(self):
        self.logger.info("Stopping driving&mirroring services...")
        self.stop_event.set()
        if self.udp_server: self.__stop_udp_server()
        if self.mpi_enabled: self._stop_mpi()
        self.__stop_mirroring_threads()
        await self.__shutdown_controller_process()
        self.__stop_driving_threads()

    def _start_mpi(self):
        from services.motionplatform_interface import MotionPlatformInterface
        self.mpi=MotionPlatformInterface()
        self.mpi.init()

    def _stop_mpi(self):
        self.mpi.close()
        self.mpi = None

    async def _start_mirroring(self):
        with self.data_lock:
            if self.mirroring: return True
            if not self.__check_operation(): return False
            if self.mirroring_stopping or self.mirroring_starting:
                self.logger.info("_start_mirroring: Mirroring in transition")
                return False
            self.mirroring_starting=True
            self.orientation_reading_rate=self.orientation_reading_rate_tmp
        try:
            error=False
            with self.data_lock:
                self.mirroring=True
                self.current_operation = ExcavatorAPIProperties.OPERATIONS["mirroring"]
            await self.__start_mirroring_services()
            return True
        except Exception as e:
            self.logger.error(f"Failed to start mirroring: {e}")
            error=True
            return False
        finally:
            with self.data_lock:
                self.mirroring_starting=False
            if error:
                await self._stop_mirroring()

    async def _stop_mirroring(self):
        with self.data_lock:
            if not self.mirroring: return True
            if self.mirroring_starting or self.mirroring_stopping:
                self.logger.info(f"_stop_mirroring: mirroring in transition")
                return False
            self.mirroring_stopping=True
        try:
            await self.__stop_mirroring_services()
            self.logger.info("Mirroring stopped")
            return True
        except Exception as e:
            self.logger.info(f"Failed to stop mirroring: {e}")
            return False
        finally:
            self.__reset_operation_values()

    async def __start_mirroring_services(self):
        self.logger.info("Starting mirroring services...")
        if not self.__start_udp_server(num_inputs=3, num_outputs=0):
            raise RuntimeError("Failed to start udp server")
        if self.mpi_enabled: self._start_mpi()
        if not self.__start_mirroring_threads():
            raise RuntimeError("failed __start_mirroring_threads")

    async def __stop_mirroring_services(self):
        self.logger.info("Stopping mirroring services...")
        self.stop_event.set()
        if self.mpi_enabled: self._stop_mpi()
        self.__stop_mirroring_threads()
        if self.udp_server and not self.__stop_udp_server():
            raise RuntimeError("Failed to close UDP server")

    def __start_udp_server(self, num_outputs, num_inputs):
        with self.data_lock:
            if self.udp_server:
                return True
            if self.udp_server_starting or self.udp_server_stopping:
                self.logger.info("start_udp_server: UDP server in transition")
                return False
            self.udp_server_starting=True
        try:
            error=False
            max_age_seconds = 1
            if self.orientation_reading_rate:
                max_age_seconds=max(ExcavatorAPIProperties.MAX_NETWORK_TIMEOUT, (1/self.orientation_reading_rate)*8)
            self.udp_server = UDPSocket(cleanup_callback=self._cleanup_operation, max_age_seconds=max_age_seconds)
            if not self.udp_server.setup(host=self.srv_ip, port=self.srv_port-1, num_inputs=num_inputs, num_outputs=num_outputs, is_server=False):
                raise RuntimeError("Failed to setup UDP server")
            if not self.udp_server.handshake():
                raise RuntimeError("Handshake failed")
            if not self.udp_server.start():
                raise RuntimeError("UDPSocket failed to start()")
            return True
        except Exception as e:
            self.logger.error(f"Error starting UDP server: {e}")
            error=True
            return False
        finally:
            with self.data_lock:
                self.udp_server_starting = False
            if error:
                self.__stop_udp_server()

    def __stop_udp_server(self):
        with self.data_lock:
            if not self.udp_server:
                return True
            if self.udp_server_starting or self.udp_server_stopping:
                self.logger.warning("__stop_udp_server: UDP server in transition")
                return False
            self.udp_server_stopping=True
        try:
            self.udp_server.close()
            self.udp_server = None
            self.logger.info("UDP server stopped")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop UDP server: {e}")
            return False
        finally:
            with self.data_lock:
                self.udp_server_stopping=False

    async def __cleanup_operation(self):
        current_operation=self.get_current_operation()
        if current_operation == "none":
            self.logger.warning("Can't cleanup operation. Current operation is none?")
            return
        elif current_operation == "mirroring":
            await self._stop_mirroring()
        elif current_operation == "driving":
            await self._stop_driving()
        elif current_operation == "driving_and_mirroring":
            await self._stop_driving_and_mirroring()
        else:
            self.logger.error(f"Unknown current operation: {current_operation}")

    def _cleanup_operation(self):
        asyncio.run_coroutine_threadsafe(self.__cleanup_operation(),self.loop).result(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)

    async def __handle_message(self, message):
        try:
            message=json.loads(message)
        except Exception:
            self.logger.error("Message was not in json format")
            return
        event=message.get("event")
        if event is None:
            self.logger.error(f"No event in the message: {message}")
            return

        if not (event in EVENTS):
            self.logger.error(f"Unknown event: {event}")
            return

        print(f"[Client]: event: {event}")
        try:
            if event=="handshake":
                operation = message.get("operation")
                if operation is None:
                    self.logger.error("Operation not provided in a handshake event")
                    return
                self.logger.info(f"Received handshake for operation: {operation}")
                if operation=="mirroring":
                    if not await self._start_mirroring():
                        raise RuntimeError("Failed to inititate mirroring services...")
                elif operation=="driving":
                    if not await self._start_driving():
                        raise RuntimeError("Failed to inititate driving services...")
                elif operation=="driving_and_mirroring":
                    if not await self._start_driving_and_mirroring():
                        raise RuntimeError("Failed to inititate driving&mirroring services...")
            elif event=="screen_message_displayed":
                self.logger.info(f"[Server] Screen message has been added to the render queue")
                if self.testing_enabled:
                        self.test_continuation_signal.set()
            elif event=="configuration":
                # Get the configuration target
                target = message.get("target")
                context = message.get("context")
                config = message.get("config")
                if config is None:
                    self.logger.error("Config not found.")
                    return
                try:
                    config = json.loads(config)
                except Exception:
                    self.logger.error("Config is not in json format.")
                    return
                if config is not None:
                    self.logger.debug(f"[Server] Config for {target}: {config} ")
                    if self.testing_enabled:
                        self.recent_config=config
                        self.test_continuation_signal.set()
                else:
                    self.logger.error(f"get_config received undefined config: {message}")
                    if self.testing_enabled:
                        self.errors_counter+=1
                    return
            elif event=="status":
                status=message.get("status")
                if status is None:
                    self.logger.error("Status not provided in the message")
                    return
                self.logger.info(f"Received status: {status}")
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="started_screen":
                self.logger.info(f"[Server] Screen has been started")
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="started_mirroring":
                self.logger.info(f"[Server] Mirroring has been started")
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="started_driving":
                self.logger.info(f"[Server] driving operation has started")
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="started_driving_and_mirroring":
                self.logger.info(f"[Server] started_driving_and_mirroring operation has started")
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="stopped_driving":
                self.logger.info(f"[Server] driving operation has stopped")
                await self._stop_driving()
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="stopped_mirroring":
                self.logger.info(f"[Server] mirroring operation has stopped")
                await self._stop_mirroring()
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="stopped_driving_and_mirroring":
                self.logger.info(f"[Server] driving&mirroring operation has stopped")
                await self._stop_driving_and_mirroring()
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="stopped_screen":
                self.logger.info(f"[Server] Screen has been stopped")
                if self.testing_enabled:
                    self.test_continuation_signal.set()
            elif event=="error":
                err=message.get("error")
                err_msg=err.get("message")
                err_ctx=err.get("context")
                self.logger.error(f"Received error message from the server: {err_msg} - context: {err_ctx}")
                if self.testing_enabled:
                    self.errors_counter+=1
                    self.test_continuation_signal.set()
            else:
                self.logger.error(f"Client received an unknown event: {event}")
        except Exception as e:
            self.logger.error(f"Error in message handler: {e}")

    def __on_udp_srv_closed(self):
        if not self.client_running: return
        self.logger.warning("udp server crashed unexpectedly")
        self._cleanup_operation()

    def __reset_operation_values(self):
        with self.data_lock:
            current_operation=self.get_current_operation()
            if current_operation == "none":
                self.logger.error("Can't reset operation values. Current operation is none?")
                return False
            self.logger.info(f"Cleaning up operation {current_operation}s values")
            self.current_operation=ExcavatorAPIProperties.OPERATIONS["none"]
            self.stop_event.clear()
        if current_operation == "mirroring":
            self.mirroring = False
            self.mirroring_stopping = False
            self.logger.info("mirroring operation has ended")
        elif current_operation == "driving":
            self.driving=False
            self.driving_stopping=False
            self.logger.info("Driving operation has ended")
        elif current_operation =="driving_and_mirroring":
            self.driving_and_mirroring=False
            self.driving_and_mirroring_stopping=False
            self.logger.info("Driving&mirroring operation has ended")
        else:
            self.logger.error(f"Unknown operation: {current_operation} ongoing...?")

    def _reset_values(self):
        self.client = None
        self.client_running = False
        self.client_run_thread=None

    def __check_operation(self):
        if self.current_operation != 0:
            err_msg=f"Operation: {ExcavatorAPIProperties.OPERATIONS_REVERSE[self.current_operation]} already underway stop them first to start a different one."
            self.logger.warning(err_msg)
            return False
        return True

    async def __final_cleanup(self):
        await self.__cleanup_operation()
        self._reset_values()
        self.logger.info("TCPClient has been shutdown")
        self.final_cleanup_done.set()

    def stop_current_operation(self):
        self._cleanup_operation()

    def shutdown(self):
        if not self.client_running: return
        try:
            self.logger.info("Starting to shutdown TCPClient")
            self.shutdown_event.set()
            self.stop_event.set()
            asyncio.run_coroutine_threadsafe(self.__final_cleanup(), self.loop)

            # Signal for shutdown finished - set from close connections
            for _ in range(30):
                if self.final_cleanup_done.is_set():
                    # Clean up successfull
                    self.final_cleanup_done.clear()
                    return True
                sleep(1)
            self.logger.error("Final Clean up timed out.")
            return False
        except Exception as e:
            self.logger.error(f"Failed to shutdown TCPServer: {e}")
            return False

if __name__ == "__main__":
    client = TCPClient(srv_ip="192.168.1.120")
    if client.start():
        client.start_mirroring()
        sleep(10)
        # client.get_mirroring_status()
        # sleep(5)
        client.stop_mirroring()
        sleep(3600)
