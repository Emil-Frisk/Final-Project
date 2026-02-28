import threading
import atexit
from screen_manager import ScreenManager
from time import sleep, perf_counter, time
from dataclasses import asdict
from inspect import currentframe
from service_listener import ServiceListener
from dataclass_types import RenderViewInfo, ExcavatorAPIProperties
from PCA9685_controller import PWMController, ChannelConfig
from orientation_tracker import OrientationTracker
from tcp_server import TCPServer
from pathlib import Path
import json
import yaml
from udp_socket import UDPSocket
from utils import setup_logging, get_cpu_core_usage, get_cpu_temperature, get_entry_point

def status_to_dict(status):
    """Convert UDPSocket::Status object to a JSON-serializable dictionary"""
    return {
        "running": status.running,
        "packets_received": status.packets_received,
        "packets_sent": status.packets_sent,
        "packets_expired": status.packets_expired,
        "packets_corrupted": status.packets_corrupted,
        "packets_shape_invalid": status.packets_shape_invalid,
        "time_since_last_packet": status.time_since_last_packet,
        "has_data": status.has_data,
        "receive_type": status.receive_type,
        "send_type": status.send_type,
        "num_inputs": status.num_inputs,
        "num_outputs": status.num_outputs
    }


""""The ExcavatorAPI's public action functions use symmetric
transition guards to ensure thread-safe state management.
Each action (screen, mirroring, orientation tracking, UDP server)
has associated starting and stopping flags. When an action is invoked,
if its service is already active or transitioning(stopping/starting),
the request is rejected. This prevents concurrent initialization
or shutdown of the same service and ensures consistent state across
multiple threads. Private helper functions operate under the assumption
of valid state and do not require additional synchronization, as they
are only called through protected public endpoints."""
class ExcavatorAPI:
    CONFIG_FILE_NAME="excavator_config.yaml"
    def __init__(self, tcp_ip="0.0.0.0", tcp_port=5432, pwm_enabled=True):
        # Callback functions that anyone can use 
        self.actions = {
            "screen_message": self.screen_message,
            "start_screen": self.start_screen,
            "stop_screen": self.stop_screen, 
            "start_mirroring": self.start_mirroring,  
            "stop_mirroring": self.stop_mirroring,
            "start_driving": self.start_driving, 
            "stop_driving": self.stop_driving, 
            "start_driving_and_mirroring": self.start_driving_and_mirroring,
            "stop_driving_and_mirroring": self.stop_driving_and_mirroring,
            "add_pwm_channel": self.add_pwm_channel,
            "remove_pwm_channel": self.remove_pwm_channel, 
            "configure_screen": self.configure_screen,
            "configure_orientation_tracker": self.configure_orientation_tracker,
            "configure_pwm_controller": self.configure_pwm_controller,
            "configure_excavator": self.configure_excavator,
            "get_orientation_tracker_config": self.get_orientation_tracker_config,
            "get_excavator_config": self.get_excavator_config,
            "get_screen_config": self.get_screen_config,
            "get_pwm_config": self.get_pwm_config,
            "status_screen": self.status_screen,
            "status_excavator": self.get_status,
            "status_orientation_tracker": self.status_orientation_tracker,
            "status_udp": self.status_udp
        }

        self.logger = setup_logging(logging_level="INFO")
    
        self.excavator_config = ExcavatorAPI.load_config(self.logger)
        self.data_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.running = False
        self.start_time=0
        self.current_operation = ExcavatorAPIProperties.OPERATIONS["none"]
        # Clients socket who started the current operation - this is used because not all cleanup callback have access to the socket who started the operation that needs to be cancelled
        self.operation_initator_socket = None 
        
        # TCP server
        self.tcp_server = None
        self.tcp_port = tcp_port
        self.tcp_ip = tcp_ip
        
        # Screen
        self.has_screen = self.excavator_config["has_screen"]
        self.screen = None
        self.screen_starting = False
        self.screen_stopping = False
        
        # Orientation tracker
        self.orientation_tracker = None
        self.orientation_tracker_starting = False
        self.orientation_tracker_stopping = False
        
        # PWM controller
        self.pwm_controller=None
        self.pwm_enabled=pwm_enabled
        
        # Mirroring
        self.mirroring = False
        self.mirroring_starting = False
        self.mirroring_stopping = False
        self.orientation_sending_thread = None
        self.data_sending_rate=None # TODO - os KILL EI TOIMI SAMALLA LAILLA takes 2 args:?
        
        # UDP socket (this is only for mirroring action for now atleast)
        self.udp_server = None
        self.udp_server_starting = False
        self.udp_server_stopping = False
        # NOTE: Service listener is atm very tightly coupled with udp_server because it is likely the only service that will be using lower level language, at least for now.
        self.service_listener=None
        self.service_listener_thread=None
        self.service_listener_port=7123
        
        # driving
        self.driving = False
        self.driving_starting=False
        self.driving_stopping=False
        self.driving_receive_thread=False
        self.data_receiving_rate = None
        
        # driving&mirroring
        self.driving_and_mirroring=False
        self.driving_and_mirroring_starting=False
        self.driving_and_mirroring_stopping=False
        
        # Config
        self.screen_config_reserved=False
        self.orientation_tracker_config_reserved=False
        self.pwm_controller_config_reserved=False
        self.excavator_config_reserved=False
    
    def start(self):
        with self.data_lock:
            if self.running:
                return False
            
        self.tcp_server = TCPServer(cleanup_callback=self._on_client_disconnected, actions=self.actions, port=self.tcp_port, ip=self.tcp_ip)
        if not self.tcp_server.start():
            raise RuntimeError("Failed to start TCPServer")
        if self.has_screen:
            try:
                self.screen = ScreenManager()
                if not self.screen.start():
                    raise RuntimeError("Failed to start oled screen manager")
            except Exception as e:
                # NOTE: Screen is not available just change config automatically to false
                self.configure_excavator({"has_screen":False})
                self.logger.error(e)
                
                
        self.running = True
        self.start_time=time()
        self.logger.info("ExcavatorAPI has been started successfully")
        atexit.register(self.shutdown)
        self.logger.info(f"ExcavatorAPI has registered cleanup atexit function: {self.shutdown}")
        return True
    
    def get_orientation_tracker_config(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if self.orientation_tracker_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return
            self.orientation_tracker_config_reserved=True
        try:
            cfg = OrientationTracker.load_config()
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="orientation_tracker",context="get_config")
                self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
        except Exception as e:
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
            self.logger.error(f"Error at get_orientation_tracker_config: {e}")
        finally:
                with self.data_lock:
                    self.orientation_tracker_config_reserved = False
    
    def get_screen_config(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if self.screen_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="screen_config configuration already underway, wait a moment.", context=fun_name))
                return
            self.screen_config_reserved=True
        try:
            cfg = ScreenManager.load_config() # TODO - investigate
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="screen",context="get_config")
                self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
        except Exception as e:
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
            self.logger.error(f"Error at get_screen_config: {e}")
        finally:
            with self.data_lock:
                self.screen_config_reserved = False

    def get_excavator_config(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name 
        with self.data_lock:
            if self.excavator_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="excavator configuration already underway, wait a moment.", context=fun_name))
                return
            self.excavator_config_reserved=True
        try:
            cfg = ExcavatorAPI.load_config()
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="excavator",context="get_config")
                self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
        except Exception as e:
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
            self.logger.error(f"Error at {fun_name}: {e}")
        finally:
            with self.data_lock:
                self.excavator_config_reserved = False

    def get_pwm_config(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if self.pwm_controller_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="pwm_config configuration already underway, wait a moment.", context=fun_name))
                return
            self.pwm_controller_config_reserved=True
        try:
            channel_configs, pump_config = PWMController.load_config()
            cfg=PWMController.build_channel_config(channel_configs=channel_configs,pump_config=pump_config)
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="pwm_controller",context="get_config")
                self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
        except Exception as e:
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
            self.logger.error(f"Error at get_pwm_config: {e}")
        finally:
            with self.data_lock:
                self.pwm_controller_config_reserved = False

    def configure_orientation_tracker(self, edited_config, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return
            if self.orientation_tracker_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="orientation_tracker configuration already underway, wait a moment.", context=fun_name))
                return
            self.orientation_tracker_config_reserved=True
        try:
            # Load config and see if something has changed
            cfg = OrientationTracker.load_config()
            cfg_changed, cfg = self._update_config(old_cfg=cfg, edited_cfg=edited_config)
                    
            # Validate and update
            if cfg_changed:
                OrientationTracker.validate_config(cfg)
                OrientationTracker.update_config(cfg)
                if self.orientation_tracker:
                    self.orientation_tracker.reload_config()
                if client_tcp_sck:
                    data=self._format_configuration_response(cfg=cfg,target="orientation_tracker",context="configure_orientation_tracker")
                    self.tcp_server.send_response(websocket=client_tcp_sck, data=data)
                self.logger.info("Configuration file updated for the orientation tracker")
            else:
                raise ValueError("no values were new")
        except Exception as e:
            self.logger.error(f"Failed to configure orientation tracker: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
        finally:
            with self.data_lock:
                self.orientation_tracker_config_reserved=False

    def configure_screen(self, edited_config, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return
            if self.screen_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="screen configuration already underway, wait a moment.", context=fun_name))
                return
            self.screen_config_reserved=True
        try:
            # Load config and only update it if its a new value
            old_cfg = ScreenManager.load_config()
            cfg_changed, cfg = self._update_config(old_cfg=old_cfg,edited_cfg=edited_config)
            if cfg_changed:
                ScreenManager.validate_config(cfg)
                ScreenManager.update_config(cfg)
                if self.screen:
                    self.screen.reload_config()
            else:
                raise ValueError("No value was new")
            
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="screen",context="configure_screen")
                self.tcp_server.send_response(websocket=client_tcp_sck, data=data)
        except Exception as e:
            self.logger.error(f"Failed to configure screen: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
        finally:
            with self.data_lock:
                self.screen_config_reserved=False

    def configure_pwm_controller(self, new_pump_config, new_channel_configs, client_tcp_sck):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return
            if self.pwm_controller_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="pwm configuration already underway, wait a moment.", context=fun_name))
                return
            self.pwm_controller_config_reserved=True
        try:
            # Load config and see if something has changed
            channel_configs, pump_config = PWMController.load_config()
            
            cfg1_changed=False
            cfg2_changed=False
            if new_pump_config is not None:
                cfg1_changed, pump_config = self._update_config(old_cfg=pump_config, edited_cfg=new_pump_config)
            if new_channel_configs is not None:
                cfg2_changed, channel_configs = self._update_config(old_cfg=channel_configs, edited_cfg=new_channel_configs)
                                
            # Only update the config if the new values are valid and safe
            if cfg1_changed is True or cfg2_changed is True:
                PWMController.validate_config(pump_config=pump_config, channel_configs=channel_configs)
                cfg=PWMController.build_channel_config(pump_config=pump_config, channel_configs=channel_configs)
                PWMController.update_config(cfg)
                if self.pwm_controller:
                    self.pwm_controller.reload_config()
                
                if client_tcp_sck:
                    data=self._format_configuration_response(cfg=cfg,target="pwm_controller",context="configure_pwm_controller")
                    self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
                self.logger.info("Configuration file updated for the PWM controller")
            else:
                raise ValueError("No value was new")
        except Exception as e:
            self.logger.error(f"Failed to configure the PWM controller: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
        finally:
            with self.data_lock:
                self.pwm_controller_config_reserved=False

    def configure_excavator(self, new_excavator_cfg, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return
            if self.excavator_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Excavator configuration already underway, wait a moment.", context=fun_name))
                return
            self.excavator_config_reserved=True
        try:
            # Load config and see if something has changed
            old_exc_cfg = ExcavatorAPI.load_config()
            
            cfg_changed=False
            if new_excavator_cfg is not None:
                cfg_changed, cfg = self._update_config(old_cfg=old_exc_cfg, edited_cfg=new_excavator_cfg)
                                
            # Only update the config if the new values are valid and safe
            if cfg_changed is True:
                ExcavatorAPI.validate_config(cfg)
                ExcavatorAPI.update_config(cfg)
                self.reload_config(cfg=cfg)
                
                if client_tcp_sck:
                    data=self._format_configuration_response(cfg=cfg,target="excavator",context="configure_excavator")
                    self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
                self.logger.info("Configuration file updated for the excavator")
            else:
                raise ValueError("No value was new")
        except Exception as e:
            self.logger.error(f"Failed to configure the excavator: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
        finally:
            with self.data_lock:
                self.excavator_config_reserved=False

    def add_pwm_channel(self, channel_name, channel_type, config, client_tcp_sck):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return
            if self.pwm_controller_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="pwm configuration already underway, wait a moment.", context=fun_name))
                return
            self.pwm_controller_config_reserved=True
        try:
            
            # Load config and see if something has changed
            channel_configs, pump_config=PWMController.load_config()
            
            if channel_type=="pump":
                PWMController.validate_config(config, channel_configs=channel_configs)
                cfg=PWMController.build_channel_config(pump_config=config, channel_configs=channel_configs)
                PWMController.update_config(config=cfg)
            elif channel_type=="channel_config":
                if channel_configs is None:
                    channel_configs = {}
                # Create config with default values and then replace thewm with possible new ones.
                channel_config=ChannelConfig(output_channel=config["output_channel"],
                              pulse_min=config["pulse_min"],
                              pulse_max=config["pulse_max"],
                              direction=config["direction"])
                channel_config=asdict(channel_config)
                cfg_changed,channel_config=self._update_config(old_cfg=channel_config, edited_cfg=config)
                
                channel_configs.update({f"{channel_name}":channel_config})
                PWMController.validate_config(pump_config, channel_configs=channel_configs)
                cfg=PWMController.build_channel_config(pump_config=pump_config, channel_configs=channel_configs)
                PWMController.update_config(config=cfg)
            else:
                raise RuntimeError(f"Unknown channel type: {channel_type}")
            
            self.logger.info(f"PWM channel: {channel_name} has been added successfully")
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="pwm_controller",context="add_pwm_channel")
                data["channel_name"]=channel_name
                self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
        except Exception as e:
            self.logger.error(f"Failed to configure the PWM controller: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
        finally:
            with self.data_lock:
                self.pwm_controller_config_reserved=False
    
    def remove_pwm_channel(self, channel_name, client_tcp_sck):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return
            if self.pwm_controller_config_reserved:
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="pwm configuration already underway, wait a moment.", context=fun_name))
                return
            self.pwm_controller_config_reserved=True
        try:
            channel_configs, pump_config = PWMController.load_config()
            
            if channel_name in channel_configs.keys():
                del channel_configs[channel_name]
            else:
                pump_config = None
            
            cfg=PWMController.build_channel_config(channel_configs=channel_configs, pump_config=pump_config)
            PWMController.update_config(config=cfg)
            
            self.logger.info(f"PWM channel: {channel_name} has been removed successfully")
            if client_tcp_sck:
                data=self._format_configuration_response(cfg=cfg,target="pwm_controller",context="remove_pwm_channel")
                data["channel_name"]=channel_name
                self.tcp_server.send_response(websocket=client_tcp_sck,data=data)
        except Exception as e:
            self.logger.error(f"Failed to remove the PWM channel: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=self.format_unexpected_err_msg(context=fun_name,e=e), context=fun_name))
        finally:
            with self.data_lock:
                self.pwm_controller_config_reserved=False
    
    def screen_message(self, view_info: RenderViewInfo, client_tcp_sck=None):
        with self.data_lock:
            if not self.screen:
                self.logger.warning("Screen has not been initiazed")
                return False
        try:
            self.screen.add_to_renderq(view_info)
            if client_tcp_sck:
                self.tcp_server.send_response(websocket=client_tcp_sck, data={"event": "screen_message_displayed","message": f"Screen message added to the render queue successfully"})
        except Exception as e:
            self.logger.error(f"Error in screen_message: {e}")
    
    def start_screen(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        error=False
        with self.data_lock:
            if self.screen:
                if client_tcp_sck:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_screen"})
                return True
            if self.screen_starting or self.screen_stopping:
                err_msg="screen is transitioning"
                self.logger.warning(err_msg)
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Screen already in transition", context=fun_name))
                return False
            self.screen_starting = True
        try:
            self.screen = ScreenManager()
            if not self.screen.start():
                raise RuntimeError("Failed to start oled screen manager")
        
            if client_tcp_sck:
                self.tcp_server.send_response(websocket=client_tcp_sck,data={"event": "started_screen"})
            return True
        except Exception as e:
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=f"Error starting oled {e}", context=fun_name))
            self.logger.error(f"Error starting oled: {e}")
            error=True
        finally:
            with self.data_lock:
                self.screen_starting = False
            if error:
                self.stop_screen()
    
    def stop_screen(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self.screen:
                if client_tcp_sck:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event": "stopped_screen"})
                return True
            if self.screen_stopping or self.screen_starting: 
                self.logger.warning("stop_screen: screen is transitioning")
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Screen already in transition", context=fun_name))
                return False
            self.screen_stopping = True
        try:
            if not self.screen.shutdown():
                raise RuntimeError("Failed to shutdown oled screen manager")
            if client_tcp_sck:
                self.tcp_server.send_response(websocket=client_tcp_sck,data={"event": "stopped_screen"})
            return True
        except Exception as e:
            self.logger.error(f"Error shutting down oled: {e}")
            return False
        finally:
            with self.data_lock:
                self.screen = None
                self.screen_stopping = False
    
    def start_orientation_tracking(self):
        error=False
        with self.data_lock:
            if self.orientation_tracker: return True 
            if self.orientation_tracker_starting or self.orientation_tracker_stopping:
                self.logger.warning("start_orientation_tracking: Orientation tracker is transitioning")
                return False
            self.orientation_tracker_starting = True
        try:
            
            self.orientation_tracker = OrientationTracker(cleanup_callback=self._on_orientation_shutdown)
            if not self.orientation_tracker.start():
                raise RuntimeError("Failed to start orientation tracking")
            return True
        except Exception as e:
            self.logger.error(f"Error starting orientation tracking: {e}")
            error=True
        finally:
            with self.data_lock:
                self.orientation_tracker_starting = False
            if error:
                self.stop_orientation_tracking()

    def stop_orientation_tracking(self):
        with self.data_lock:
            if not self.orientation_tracker:
                return True
            if self.orientation_tracker_stopping or self.orientation_tracker_starting:
                self.logger.warning("stop_orientation_tracking: Orientation tracking is in transition")
                return False
            self.orientation_tracker_stopping = True
        try:
            if not self.orientation_tracker.shutdown():
                raise RuntimeError("Failed to stop orientation tracking")
            return True
        except Exception as e:
            self.logger.error(f"Error stopping orientation tracking: {e}")
        finally:
            with self.data_lock:
                self.orientation_tracker = None
                self.orientation_tracker_stopping = False
    
    def _start_service_listener(self, service_name):
        if self.service_listener_thread is None:
            self.service_listener = ServiceListener(ip="localhost", port=self.service_listener_port, service_name=service_name, cleanup_cb=self._cleanup_operation)
            self.service_listener_thread = threading.Thread(target=self.service_listener.start, daemon=True)
            self.service_listener_thread.start()
            return self.service_listener.wait_for_ready()
        else:
            return False
    
    def _stop_service_listener(self):
        if self.service_listener_thread is not None:
            self.service_listener.close(threading.current_thread())
            if self.service_listener_thread is not None and self.service_listener_thread.is_alive() and self.service_listener_thread != threading.current_thread():
                self.service_listener_thread.join(ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
            self.service_listener=None
            self.service_listener_thread=None

    def start_udp_server(self, operation,client_tcp_sck, num_inputs=0, num_outputs=0):
        with self.data_lock:
            if self.udp_server: return True
            if self.udp_server_starting or self.udp_server_stopping:
                self.logger.warning("start_udp_server: UDP server is transitioning")
                return False
            self.udp_server_starting = True
        try:
            error=False
            max_age_seconds = 5
            self._start_service_listener(service_name="udp_socket")
            self.udp_server = UDPSocket(max_age_seconds=max_age_seconds, tcp_port=self.service_listener_port)
            if not self.udp_server.setup(host="0.0.0.0", port=self.tcp_port-1, num_inputs=num_inputs, num_outputs=num_outputs, is_server=True):
                raise RuntimeError("Failed to setup UDP server")
            # Inform excavatorClient its time for handshake
            self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"handshake", "operation": operation})
            # NOTE: handshake is blocking so sleep a little to let the event for handshake actually get off
            sleep(1)
            if not self.udp_server.handshake(15):
                raise RuntimeError("Handshake failed")
            if not self.udp_server.start():
                raise RuntimeError("UDPSocket failed to start receiving")
        
            return True
        except Exception as e:
            self.logger.error(f"Error starting UDP server: {e}")
            error=True
            return False
        finally:
            with self.data_lock:
                self.udp_server_starting = False
            if error:
                self.stop_udp_server()

    def stop_udp_server(self):
        with self.data_lock:
            if not self.udp_server: return True
            if self.udp_server_stopping or self.udp_server_starting:
                return True
            self.udp_server_stopping = True
        try:
            self._stop_service_listener()
            self.udp_server.close()
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop UDP server: {e}")
            return False
        finally:
            with self.data_lock:
                self.udp_server = None
                self.udp_server_stopping = False

    def get_current_operation(self):
        return ExcavatorAPIProperties.OPERATIONS_REVERSE[self.current_operation]

    def _check_operation(self, client_tcp_sck, context):
        if self.current_operation != 0:
            err_msg=f"Operation: {self.get_current_operation()} already underway stop it first to start a different one."
            self.logger.warning(err_msg)
            self.tcp_server.send_error(websocket=client_tcp_sck, error_msg=self.format_error_event_response(message=err_msg, context=context))
            return False
        return True

    def start_driving(self, channel_names, data_receiving_rate, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return 
            if self.driving:
                if client_tcp_sck:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_driving"})
                return True
            if self.driving_starting or self.driving_stopping:
                err_msg="Driving operation is in transition"
                self.logger.warning(err_msg)
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return
            self.driving_starting=True
            # These states are set beforehand to guarantee cleanup
            self.current_operation=ExcavatorAPIProperties.OPERATIONS["driving"]
            self.driving = True
        try:
            error=False
            self.data_receiving_rate = data_receiving_rate
            self._start_driving_services(num_outputs=len(channel_names), channel_names=channel_names,client_tcp_sck=client_tcp_sck)
            
            with self.data_lock:
                if client_tcp_sck:
                    self.operation_initator_socket = client_tcp_sck
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_driving"})
            return True
        except Exception as e:
            self.logger.error(f"Failed to start driving operation: {e}")
            error=True
        finally:
            with self.data_lock:
                self.driving_starting=False
            if error:
                self.driving = False
                self.stop_driving()
            
    def stop_driving(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self.driving:
                if client_tcp_sck:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"stopped_driving"})
                return True
            if self.driving_starting or self.driving_stopping:
                err_msg="Driving operation in transition"
                self.logger.warning(err_msg)
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return False
            self.driving_stopping=True
        try:
            self._stop_driving_services()
            if self.operation_initator_socket:
                try:
                    self.tcp_server.send_response(websocket=self.operation_initator_socket,data={"event":"stopped_driving"})
                except Exception:
                    self.logger.warning("Client socket not valid anymore")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop driving operation: {e}")
            return False
        finally:
            self._reset_operation_values()

    def start_mirroring(self, data_sending_rate, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return False
            if self.mirroring:
                if client_tcp_sck:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_mirroring"})
                return True
            if self.mirroring_starting or self.mirroring_stopping:
                self.logger.warning("start_mirroring: Mirroring is transitioning")
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return False
            self.mirroring_starting = True
            self.mirroring = True
            self.current_operation=ExcavatorAPIProperties.OPERATIONS["mirroring"]
        try:
            error=False
            self.logger.info(f"Starting mirroring... Client TCP socket: {client_tcp_sck}")
            self.data_sending_rate=data_sending_rate
            self._start_mirroring_services(client_tcp_sck)
            with self.data_lock:
                if client_tcp_sck: 
                    self.operation_initator_socket = client_tcp_sck
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_mirroring"})
            return True
        except Exception as e:
            self.logger.error(f"Failed to start mirroring: {e}")
            error=True
        finally:
            with self.data_lock:
                self.mirroring_starting = False
            if error:
                self.stop_mirroring()
                    
    def stop_mirroring(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self.mirroring:
                if client_tcp_sck:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"stopped_mirroring"})
                return True
            if self.mirroring_starting or self.mirroring_stopping:
                self.logger.warning("stop_mirroring: Mirroring is transitioning")
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return True
            self.mirroring_stopping = True
        try:
            self.logger.info(f"Stopping mirroring..")
            self._stop_mirroring_services()
            try:
                if self.operation_initator_socket:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"stopped_mirroring"})
            except Exception:
                    self.logger.warning("Client socket not valid anymore")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop mirroring: {e}")
            return False
        finally:
            self._reset_operation_values()
    
    def _reset_operation_values(self):
        with self.data_lock:
            current_operation=self.get_current_operation()
            self.logger.info(f"Resetting operation {current_operation}s values")
            self.current_operation=ExcavatorAPIProperties.OPERATIONS["none"]
            self.operation_initator_socket = None
            self.data_receiving_rate=None
            self.data_sending_rate=None
            self.stop_event.clear()
        if current_operation == "mirroring":
            self.mirroring = False
            self.mirroring_stopping = False
        elif current_operation == "driving": 
            self.driving=False
            self.driving_stopping=False
        elif current_operation =="driving_and_mirroring":
            self.driving_and_mirroring=False
            self.driving_and_mirroring_stopping=False
        else:
            self.logger.error(f"Unknown operation: {current_operation} ongoing...?")

    def _update_config(self,old_cfg,edited_cfg):
        """Goes through the config you want to update
        and only updates it if the property exists and the value is new"""
        cfg_changed =False
        for prop, new_value in edited_cfg.items():
            if new_value is None: continue
            old_value = old_cfg.get(prop)
            
            if old_value is not None and old_value != new_value:
                old_cfg[prop] = new_value
                cfg_changed=True
        return cfg_changed, old_cfg

    # NOTE: Data receiving rate and data sending rates are flipped so it makes sense for both ends
    def start_driving_and_mirroring(self, channel_names, data_receiving_rate, data_sending_rate, client_tcp_sck): 
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self._check_operation(client_tcp_sck,fun_name): return False
            if self.driving_and_mirroring:
                if client_tcp_sck:
                     self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_driving_and_mirroring"})
                return True
            if self.driving_and_mirroring_stopping or self.driving_and_mirroring_starting:
                self.logger.warning("start_driving_and_mirroring: Operation in transition")
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return False
            self.driving_and_mirroring_starting = True
            self.driving_and_mirroring = True
            self.current_operation=ExcavatorAPIProperties.OPERATIONS["driving_and_mirroring"]
        try:
            error=False
            self.data_receiving_rate=data_receiving_rate
            self.data_sending_rate=data_sending_rate
            self._start_driving_and_mirroring_services(client_tcp_sck=client_tcp_sck, num_outputs=len(channel_names), channel_names=channel_names)
            with self.data_lock:
                if client_tcp_sck: 
                    self.operation_initator_socket = client_tcp_sck
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"started_driving_and_mirroring"})
            return True
        except Exception as e:
            self.logger.error(f"Failed to start driving and mirroring: {e}")
            error=True
        finally:
            with self.data_lock:
                self.driving_and_mirroring_starting = False
            if error:
                self.stop_driving_and_mirroring()

    def start_pwm_controller(self):
        try:
            # rate_treshold=self.data_receiving_rate/16 TODO -undo
            rate_treshold=1
            if rate_treshold == 0:
                self.logger.warning("Input rate treshold too small, monitoring will be disabled.")
            self.pwm_controller=PWMController(input_rate_threshold=rate_treshold)
            self.logger.info("Started pwm controller")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start pwm controller: {e}")
            return False
        
    def stop_pwm_controller(self):
        try:
            self.pwm_controller._simple_cleanup()
            self.pwm_controller=None
            self.logger.info("shut down pwm controller")
        except Exception as e:
            self.logger.error(f"Failed to cleanup pwm controller: {e}")
        
    def stop_driving_and_mirroring(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        with self.data_lock:
            if not self.driving_and_mirroring:
                if client_tcp_sck:
                     self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"stopped_driving_and_mirroring"})
                return True
            if self.driving_and_mirroring_stopping or self.driving_and_mirroring_starting:
                self.logger.warning("stop_driving_and_mirroring: Operation in transition already")
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
                return False
            self.driving_and_mirroring_stopping = True
        try:
            self.logger.info(f"Stopping driving and mirroring operation")
            self._stop_driving_and_mirroring_services()
            try:
                if self.operation_initator_socket:
                    self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"stopped_driving_and_mirroring"})
            except Exception:
                    self.logger.warning("Client socket not valid anymore")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop operation driving&mirroring: {e}")
            return False
        finally:
            self._reset_operation_values()
    
    def _start_driving_and_mirroring_services(self,client_tcp_sck, num_outputs, channel_names):
        self.logger.info("Starting driving and mirroring services...")
        if not self.start_udp_server(num_inputs=num_outputs, num_outputs=3, operation="driving_and_mirroring", client_tcp_sck=client_tcp_sck):
            raise RuntimeError("Failed to start udp server")
        # Mirroring services
        if not self.start_orientation_tracking():
            raise RuntimeError("Failed to start orientation tracking")
        if not self._start_mirroring_threads():
            raise RuntimeError("Failed to start sending orientation data")
        
        # Driving services
        if self.pwm_enabled: 
            if not self.start_pwm_controller():
                raise RuntimeError("Failed to start pwm controller")
            
        self._start_driving_threads(channel_names=channel_names)
    
    def _stop_driving_and_mirroring_services(self):
        self.logger.info("Stopping driving and mirroring services...")
        # Driving services
        if self.pwm_enabled: 
            self.stop_pwm_controller()
        self.stop_event.set()
        self.stop_udp_server()
        self._stop_driving_threads()
        if self.mirroring and not self._stop_mirroring_threads():
            raise RuntimeError("Failed to stop mirroring threads")
        if self.orientation_tracker and not self.stop_orientation_tracking():
            raise RuntimeError("Failed to stop orientation tracking")        
    
    def _start_mirroring_services(self, client_tcp_sck):
        self.logger.info("Starting mirroring servides...")
        if not self.start_udp_server(num_outputs=3,operation="mirroring", client_tcp_sck=client_tcp_sck):
            raise RuntimeError("Failed to start udp server")
        if not self.start_orientation_tracking():
            raise RuntimeError("Failed to start orientation tracking")
        if not self._start_mirroring_threads():
            raise RuntimeError("Failed to start sending orientation data")

    def _start_driving_services(self, num_outputs, channel_names,client_tcp_sck):
        self.logger.info("Starting driving services...") 
        self.start_udp_server(num_inputs=num_outputs,operation="driving", client_tcp_sck=client_tcp_sck)
        if self.pwm_enabled: 
            if not self.start_pwm_controller():
                raise RuntimeError("Failed to start pwm controller")
        self._start_driving_threads(channel_names=channel_names)
      
    def _stop_driving_services(self):
        self.logger.info("Stopping driving services...")
        if self.pwm_enabled:
            self.stop_pwm_controller()
        self.stop_event.set()
        self.stop_udp_server()
        self._stop_driving_threads()
    
    def _start_driving_threads(self,channel_names):
        self.driving_receive_thread=threading.Thread(target=self._driving_commands_receiver_loop, args=(channel_names,),daemon=True)
        self.driving_receive_thread.start()
    
    def _stop_driving_threads(self):
        if self.driving_receive_thread != threading.current_thread():
            self.driving_receive_thread.join(ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
    
    def _driving_commands_receiver_loop(self, channel_names):
        try:
            self.logger.info(f"driving_commands_receiver_loop started with receiving rate: {self.data_receiving_rate}")
            sleep_time=1/self.data_receiving_rate
            
            while not self.stop_event.is_set():
                if self.udp_server:
                    # Build commands for pwm controller
                    commands={}
                    command_values = self.udp_server.get_latest()
                    if command_values:
                        for i, val in enumerate(command_values):
                            commands[channel_names[i]] = val
                    
                    if self.pwm_enabled:
                        self.pwm_controller.update_named(commands=commands, unset_to_zero=True, one_shot_pump_override=False)
                    self.logger.debug(f"Driving commands: {commands}")
                sleep(sleep_time)
            self.logger.info("Driving commands receiving loop stopped")
        except Exception as e:
            self.logger.error(f"Error at _driving_commands_receiver_loop: {e}")
            self._cleanup_operation()

    def _stop_mirroring_services(self):
        self.logger.info("Stopping mirroring services")
        self.stop_event.set()
        if self.mirroring and not self._stop_mirroring_threads():
            raise RuntimeError("Failed to stop mirroring threads")
        if self.orientation_tracker and not self.stop_orientation_tracking():
            raise RuntimeError("Failed to stop orientation tracking")
        if self.udp_server and not self.stop_udp_server():
            raise RuntimeError("Failed to close UDP server")

    def _stop_mirroring_threads(self):
        exclude_thread = threading.current_thread()
        with self.data_lock:
            self.mirroring = False
        if self.orientation_sending_thread and self.orientation_sending_thread.is_alive():
            if self.orientation_sending_thread != exclude_thread:
                self.orientation_sending_thread.join(ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
        self.logger.info("Mirroring threads stopped")
        return True
    
    def _start_mirroring_threads(self):
        try:
            self.orientation_sending_thread = threading.Thread(
                target=self._orientation_data_sending_loop,
                daemon=True
            )
            self.orientation_sending_thread.start()
            return True
        except Exception as e:
            self.logger.error(f"Error starting orientation data loop: {e}")
            return False

    def _orientation_data_sending_loop(self):
        # Validate data_sending_rate important for "guaranteening" no hanging threads with join
        if self.data_sending_rate < ExcavatorAPIProperties.MIN_RATE:
            raise RuntimeError(f"data_sending_rate is below the minimum {ExcavatorAPIProperties.MIN_RATE} rate allowed")
        try: 
            iteration_duration = 1/self.data_sending_rate
            self.logger.info(f"Starting orientation data sending loop with sending rate of {self.data_sending_rate}")
            while not self.stop_event.is_set():
                desired_next = perf_counter() + iteration_duration
                if self.orientation_tracker:
                    orientation = self.orientation_tracker.get_orientation()
                    if orientation is not None and self.udp_server:
                        self.udp_server.send(orientation)
                        
                sleep_duration = desired_next - perf_counter()
                if sleep_duration > 0:
                    sleep(sleep_duration)
        except Exception as e:
            self.logger.error(f"Error in _orientation_data_sending_loop: {e}")
            self._cleanup_operation()

    def _cleanup_operation(self):
        current_operation=self.get_current_operation()
        if current_operation == "none":
            return
        elif current_operation == "mirroring":
            self.stop_mirroring()
        elif current_operation == "driving":
            self.stop_driving()
        elif current_operation == "driving_and_mirroring":
            self.stop_driving_and_mirroring()
        else:
            self.logger.error(f"Unknown current operation: {current_operation}")        

    def _on_screen_closed(self):
        self.logger.warning("ScreenManager unexpectedly crashed")
        self.stop_screen()

    def _on_udp_srv_closed(self):
        self.logger.warning("UDP server unexpectedly crashed")
        self._cleanup_operation()

    def _on_client_disconnected(self):
        self._cleanup_operation()

    def _on_orientation_shutdown(self):
        # NOTE: Assumes mirroring is the only operation that actually uses orientation tracking for now
        self.logger.warning("Orientation tracker unexpectedly crashed")
        self._cleanup_operation()

    def _format_configuration_response(self, target, cfg, context="unknown"):
        return {"event":"configuration",
        "message": "Configuration Succeeded",
        "target": target,
        "context": context,
        "config": json.dumps(cfg)}

    def get_status(self, client_tcp_sck=None):
        status={
            "cpu_temperature": f"{get_cpu_temperature()}°C",
            "cpu_core_usage": f"{get_cpu_core_usage()}%",
            "current_operation": self.get_current_operation(),
            "uptime": f"{(time() - self.start_time) / 60:.2f} minutes"
        }
        if client_tcp_sck:
            self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"status", "status": status,"target":"excavator"})
        self.logger.info(f"ExcavatorAPI:s current status: {status}")
        

    def status_screen(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        if not self.screen:
            self.logger.warning("status_screen: Screen not initialized")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
            return 
        status = self.screen.get_status()
        if client_tcp_sck:
            self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"status", "status":status,"target":"screen"})
        self.logger.info(f"Screens current status: {status}")

    def status_orientation_tracker(self, client_tcp_sck=None):
        fun_name=currentframe().f_code.co_name
        if not self.orientation_tracker:
            self.logger.warning("status_orientation_tracker: orientation tracker is not intialized")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="Orientation tracker is not intialized. start_mirroring first", context=fun_name))
            return 
        status = self.orientation_tracker.get_status()
        if client_tcp_sck:
            self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"status", "status": status, "target": "orientation"})
        self.logger.info(f"Screens current status: {status}")

    def format_error_event_response(self, message, context="unknown"):
        return {
            "message": message,
            "context": context
        }

    def format_unexpected_err_msg(self, context, e):
        return f"Unexpected error occured while trying to {context} status - {e}"

    def status_udp(self, client_tcp_sck=None):
        try:
            fun_name=currentframe().f_code.co_name
            if not self.mirroring:
                self.logger.warning("status_udp: mirroring has not been started")
                if client_tcp_sck:
                    self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message="UDP service is shutdown - Start a operation to see the status of it.", context=fun_name))
                return 
            status = status_to_dict(self.udp_server.get_status())
            if client_tcp_sck:
                self.tcp_server.send_response(websocket=client_tcp_sck,data={"event":"status", "status": status, "target":"udp"})
            self.logger.info(f"Mirroring operations current status: {status}")
        except Exception as e:
            self.logger.error(f"Failed to get udp status: {e}")
            if client_tcp_sck:
                self.tcp_server.send_error(websocket=client_tcp_sck,error_msg=self.format_error_event_response(message=f"Failed to get udp status: {e}", context=fun_name))

    def is_ready(self):
        oled_ready = True
        server_ready = True
        if self.screen:
            oled_ready = self.screen.is_ready()
        server_ready = self.tcp_server.is_ready()
        return oled_ready and server_ready
    
    def shutdown(self):
        with self.data_lock:
            if not self.running:
                return True
        try:
            self.logger.info("Shutting down ExcavatorAPIProperties...")
            # Shutdown in reverse order of initialization
            srv_shutdown = self.tcp_server.shutdown()
            self._cleanup_operation()
            oled_shutdown = self.stop_screen() if self.screen else True
            
            if srv_shutdown and oled_shutdown:
                with self.data_lock:
                    self.running = False
                self.logger.info("ExcavatorAPI has been successfully shutdown")
                return True
            else:
                raise RuntimeError(
                    f"ExcavatorAPI shutdown incomplete - TCPServer: {srv_shutdown} | "
                )
        except Exception as e:
            self.logger.error(f"Error during ExcavatorAPI shutdown: {e}")
            return False
        finally:
            with self.data_lock:
                self.running = False
    
    def reload_config(self, cfg=None):
        if cfg is None:
            cfg=ExcavatorAPI.load_config()
        self.has_screen=cfg["has_screen"]
    
    @staticmethod
    def _parse_config(cfg):
        config = {
            "has_screen": bool(cfg['has_screen']),
        }
        return config

    @staticmethod
    def validate_config(parsed_config):
        errors = []
        if not isinstance(parsed_config["has_screen"], bool):
            errors.append(f"validate_config: has_screen must be a boolean")

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(errors))
    
    @staticmethod
    def load_config(logger=None):
        config_path = get_entry_point() / "config" / ExcavatorAPI.CONFIG_FILE_NAME
        # config_path = Path().home() / "excavator" / "config" / ExcavatorAPI.CONFIG_FILE_NAME # TODO - undo

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{ExcavatorAPI.CONFIG_FILE_NAME}' not found. Full path: {config_path}")
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
    
        parsed_config = ExcavatorAPI._parse_config(raw_config)
        ExcavatorAPI.validate_config(parsed_config)
        if logger:
            logger.info(f"ExcavatorAPI config has been validated and loaded: {parsed_config}")
        return parsed_config

    @staticmethod
    def update_config(config):
        config_path= get_entry_point() / "config" / ExcavatorAPI.CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{ExcavatorAPI.CONFIG_FILE_NAME}' not found. Full path: {config_path}")
        
        with open(config_path, 'w') as f:
            yaml.safe_dump(config, f,default_flow_style=False)

if __name__ == "__main__":
    try:
        excavator = ExcavatorAPI()
        excavator.start()
        # Wait for everything to be ready
        while not excavator.is_ready():
            sleep(1)
        print("ExcavatorAPI is ready!")
        while True:
            sleep(3600)
    except KeyboardInterrupt:
        excavator.shutdown()
    except Exception as e:
        print(f"Error at excavatorAPI: {e}")
