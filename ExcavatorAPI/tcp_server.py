import asyncio
import websockets
import threading
import json
from dataclass_types import RenderViewInfo, ExcavatorAPIProperties
from PCA9685_controller import PWMController
from utils import setup_logging

class TCPServer:
    def __init__(self, actions, cleanup_callback=None, ip="localhost", port=5432):
        self.ip = ip
        self.port = port
        self.logger = setup_logging()
        self.actions = actions
        self.cleanup_callback = cleanup_callback
        self.server_running = False
        self.server_thread = None
        self.messages_loop_thread=None
        self.loop = None
        self.server = None
        self.clients = set()
        self.stop_event = threading.Event()

    def start(self):
        """Start the WebSocket server in a separate thread"""
        if self.server_running:
            self.logger.warning("Server is already running")
            return False
        
        self.server_thread = threading.Thread(
            target=self._run_async_server,
            daemon=True
        )
        self.messages_loop_thread=threading.Thread(
            target=self._run_messages_loop,
            daemon=True
        )
        self.server_thread.start()
        self.messages_loop_thread.start()
        return True

    def _run_messages_loop(self):
        try:
            self.messages_loop=asyncio.new_event_loop()
            self.messages_loop.run_until_complete(self._message_loop())
        except Exception as e:
            self.logger.error("Messages loop has crashed")
            
    async def _message_loop(self):
        """Dedicated loop for sending messages to the client from synchronous code"""
        self.logger.info("Dedicated messages event loop thread up and running")
        while not self.stop_event.is_set():
            await asyncio.sleep(6)

    def _run_async_server(self):
        """Run the asyncio event loop in a separate thread"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._start_server())
        except Exception as e:
            self.logger.error(f"Async server error: {e}")
            if self.cleanup_callback:
                self.cleanup_callback()

    async def _start_server(self):
        """Start the WebSocket server"""
        try:
            async with websockets.serve(
                self._handle_connection,
                self.ip,
                self.port,
                ping_interval=None,
                ping_timeout=None
            ) as ws_server:
                self.server = ws_server
                self.logger.info(f"WebSocket server listening on ws://{self.ip}:{self.port}")
                # Keep server running until stop_event is set
                self.server_running = True
                while not self.stop_event.is_set():
                    await asyncio.sleep(6)
        except Exception as e:
            self.logger.error(f"_Start_server caught error: {e}")

    async def _handle_connection(self, websocket):
        """Handle client connections"""
        client_addr = websocket.remote_address
        self.clients.add(websocket)
        self.logger.info(f"New client connected from {client_addr}")
        try:
            while not self.stop_event.is_set():
                try:
                    message=await asyncio.wait_for(websocket.recv(), timeout=1)
                    await self._handle_message(websocket, message)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    self.logger.info(f"Client {client_addr} disconnected")
                    break
        except Exception as e:
            self.logger.error(f"error while handling clients connections: {e}")
        finally:
            self.logger.info(f"cleaning up clients {client_addr} connection")
            self.clients.remove(websocket)
            if self.cleanup_callback:
                self.cleanup_callback()

    def __validate_channel_names(self, channel_names):
        if len(set(channel_names)) != len(channel_names):
            return self._format_error_response("Channel names must be unique")
        if "pump" in channel_names:
            return self._format_error_response("Pump is not allowed to be remote controlled")
        
        existing_channel_names=PWMController.get_channel_names()
        for name in channel_names:
            if name not in existing_channel_names:
                return self._format_error_response(f"Channel name {name} is not available. Available channels: {','.join(existing_channel_names)}")        
        
        return True, None, None

    def __arr_strs_lower(self, arr):
        for i, name in enumerate(arr):
            if not isinstance(name, str):
                return self._format_error_response("channel_names have to be strings :( !")
            arr[i]=name.lower()
        return True, arr, None

    def __validate_rate(self, rate, context, max=None):
        max_rate=ExcavatorAPIProperties.MAX_RATE
        if max is not None:
            max_rate=max
        
        if not (ExcavatorAPIProperties.MIN_RATE < rate < max_rate):
                return self._format_error_response(f"rate: {context} has to be between {ExcavatorAPIProperties.MIN_RATE}-{max_rate}")
        return True, None, None

    async def _handle_message(self, websocket, message):
        """Process incoming messages"""
        try:
            # Parse JSON command
            try:
                command = json.loads(message)
            except json.JSONDecodeError:
                await self._send_error(websocket,error_msg={"message":  "Command must be valid JSON", "context":  "unknown" })
                return
            
            print(f"Command: {command}")
            action = command.get("action")
                
            if not action:
                await self._send_error(websocket,error_msg={"message":  "No action provided", "context":  "unknown" })
                return
            
            if action not in self.actions:
                await self._send_error(websocket,error_msg={"message":  f"Action {action} does not exist", "context":  "unknown" })
                return
            
            # Route to appropriate parser and action
            if action == "screen_message":
                success, data, error_msg = self._parse_message(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "unknown" })
                    return
                await self._run_in_thread(
                    self.actions[action],
                    RenderViewInfo(
                        view="message",
                        header=data[0],
                        body=data[1],
                        render_time=data[2],
                        render_count=data[3]
                    ),
                    websocket
                )
            elif action == "configure_pwm_controller":
                success, data, error_msg = self._parse_config_pwm_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "unknown" })
                    return
                await self._run_in_thread(self.actions[action], data[0], data[1], websocket)
            elif action == "configure_screen":
                success, data, error_msg = self._parse_config_screen_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "unknown" })
                    return
                await self._run_in_thread(self.actions[action], data[0], websocket)
            elif action =="configure_orientation_tracker":
                success, data, error_msg = self._parse_cfg_orie_tracker_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "unknown" })
                    return
                await self._run_in_thread(self.actions[action], data[0], websocket)                
            elif action =="configure_excavator":
                success, data, error_msg = self._parse_cfg_excavator_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "configure_excavator" })
                    return
                await self._run_in_thread(self.actions[action], data[0], websocket)                
            elif action == "add_pwm_channel":
                success, data, error_msg = self._parse_add_pwm_channel_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "add_pwm_channel" })
                    return
                await self._run_in_thread(self.actions[action], data[0], data[1], data[2], websocket)
            elif action == "remove_pwm_channel":
                success, data, error_msg = self._parse_remove_pwm_channel_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message": error_msg, "context":  "unknown" })
                    return
                self.actions[action](data[0],websocket)   
            elif action=="start_mirroring":
                success, data, error_msg = self._parse_start_mirroring_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message": error_msg, "context":  "start_mirroring" })
                    return
                self.actions[action](data[0],websocket)
            elif action == "start_driving":
                success, data, error_msg = self._parse_start_driving_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message":  error_msg, "context":  "start_driving" })
                    return
                await self._run_in_thread(self.actions[action], data[0], data[1], websocket)
            elif action=="start_driving_and_mirroring":
                success, data, error_msg = self._parse_start_driving_and_mirroring_params(command)
                if not success:
                    await self._send_error(websocket,error_msg={"message": error_msg, "context":  "start_driving_and_mirroring" })
                    return
                self.actions[action](data[0],data[1],data[2],websocket)
            else:
                # Parameterless actions
                await self._run_in_thread(self.actions[action], websocket)
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
            await self._send_error(websocket,error_msg={"message":  str(e), "context":  "unknown" })

    async def _run_in_thread(self, func, *args):
        """Run blocking operations in a thread pool"""
        await self.loop.run_in_executor(None, func, *args)

    async def _send_error(self, websocket, error_msg):
        """Send error response to client"""
        response = json.dumps({"event": "error", "error": error_msg})
        await websocket.send(response)

    def send_error(self, websocket, error_msg):
        """Send error response to client"""
        asyncio.run_coroutine_threadsafe(
            self._send_error(websocket, error_msg),
            self.loop
        )

    async def _send_response(self, websocket, data):
        """Send response to client"""
        response = json.dumps(data)
        await websocket.send(response)
        
    def send_response(self, websocket, data):
        """Send response to client"""
        asyncio.run_coroutine_threadsafe(
            self._send_response(websocket, data),
            self.messages_loop
        )
 
    def _parse_remove_pwm_channel_params(self,message):
        channel_name = message.get("channel_name")
        if (channel_name==None):
            return self._format_error_response("No channel_name provided.")
        
        channel_name=channel_name.lower()
        channel_names = PWMController.get_channel_names(include_pump=True)
        if not channel_name in channel_names:
            return self._format_error_response(f"Channel name {channel_name} does not exist. Here all all the channels: {','.join(channel_names)}")
        
        return True, (channel_name,), None

    def _parse_message(self, command):
        header = command.get("header")
        body = command.get("body")
        render_time = command.get("render_time")
        render_count = command.get("render_count")
        
        if (not header or not render_time
            or not render_count or not body):
            return self._format_error_response("Give all needed message parameters <header,body,render_time,render_count>")
        
        try:
            render_time = float(render_time)
            render_count = int(render_count)
            if render_time <= 0 and render_count <= 0:
                return self._format_error_response("render_time has to be positive")
        except ValueError:
            return self._format_error_response("All numbers have to be positive!")
        
        # Valid data
        return True, (header, body, render_time, render_count), None
 
    def _parse_config_pwm_params(self,data):
        # NOTE: pump_configs and channel_configs value validations already happen in the action function itself
        channel_configs = data.get("channel_configs")
        # Check if at least one param is provided
        if channel_configs is None:
            return self._format_error_response("No channel_configs parameter provided.")

        pump=channel_configs.get("pump")
        used_channels=PWMController.get_used_channels()
        current_channel_configs, current_pump_config = PWMController.load_config()
        
        if pump != None:
            # Remove pump from the channel config list because they will have their own validation logic.
            pump=pump.copy()
            del channel_configs["pump"]
            r=self.validate_pump_config(pump, used_channels=used_channels, current_pump_cfg=current_pump_config)
            if r[0] is False: return r
            pump=r[1]
        if channel_configs != None:
            r=self.validate_channel_config(channel_configs, current_chan_cfg=current_channel_configs, used_channels=used_channels)
            if r[0] is False: return r
            channel_configs=r[1]
        # Success: return the values (None for unspecified params)
        return True, (pump, channel_configs), None
 
    def validate_channel_config(self, channel_configs, current_chan_cfg, used_channels, new_chan=False):
        """Validate all channel configs against ChannelConfig schema. return: [result, data, err_msg]"""
        if not isinstance(channel_configs, dict):
            return self._format_error_response("channel_configs has to be a dictionary")
        schema = ExcavatorAPIProperties.CHANNEL_CONFIG_SCEMA
        
        channel_names=PWMController.get_channel_names()
        
        for chan_name, chan_cfg in channel_configs.items():
            if not isinstance(chan_cfg, dict):
                return self._format_error_response(f"Channel '{chan_name}' must be a dictionary")
            
            if new_chan is False and chan_name not in channel_names:
                return self._format_error_response(f"Channel name: {chan_name} is not available. Here are all the channel names: {','.join(channel_names)}")
            
            for prop, val in chan_cfg.items():
                prop_schema = schema.get(prop)
                expected_type = prop_schema[0]
                has_limits=len(prop_schema) >= 2
                
                if expected_type is None:
                    return self._format_error_response(f"Unknown property '{prop}' in channel '{chan_name}'")
                
                # Skip None values (optional fields)
                if val is None:
                    continue
                
                if expected_type in [float, int]:
                    if expected_type == float:
                        r = self.__validate_float(val, prop)
                    else:
                        r = self.__validate_int(val, prop)
                    if r[0] is False: return r
                    chan_cfg[prop] = r[1]
                elif expected_type == bool:
                    r=self.__validate_boolean(val, prop)
                    if r[0] is False: return r
                    chan_cfg[prop] = r[1]
                
                if has_limits:
                    min_val=prop_schema[1].get("min")
                    max_val=prop_schema[1].get("max")
                    if chan_cfg[prop] < min_val:
                        return self._format_error_response(f"{chan_name} channels {prop} is smaller than minimum allowed: {min_val}")
                    if chan_cfg[prop] > max_val:
                        return self._format_error_response(f"{chan_name} channels {prop} is larger than maximum allowed: {max_val}")
                
                # Do not allow changing over a channel already in use
                if prop=="output_channel":
                    if prop in used_channels and prop != current_chan_cfg[chan_name]["output_channel"]:
                        return self._format_error_response(f"Output channel {chan_cfg['output_channel']} already in use by another servo")
        
        return (True, channel_configs, None)

    def validate_pump_config(self, pump_config, current_pump_cfg, used_channels):
        """Validate all channel configs against pump_config schema. return: [result, data, err_msg]"""
        if not isinstance(pump_config, dict):
            return self._format_error_response("Pump has to be a dictionary")
        
        schema = ExcavatorAPIProperties.PUMP_SCHEMA
        for prop, val in pump_config.items():
            prop_schema = schema.get(prop)
            expected_type=prop_schema[0]
            has_limits=len(prop_schema) >= 2
            
            if expected_type is None:
                return self._format_error_response(f"Unknown property '{prop}' for pump")
            
            if expected_type == float:
                r = self.__validate_float(val, prop)
            else:
                r = self.__validate_int(val, prop)
            if r[0] is False: return r
            pump_config[prop] = r[1]
            
            if has_limits:
                min_val=prop_schema[1].get("min")
                max_val=prop_schema[1].get("max")
                if pump_config[prop] < min_val:
                    return self._format_error_response(f"Pumps property {prop} is smaller than minimum allowed: {min_val}")
                if pump_config[prop] > max_val:
                    return self._format_error_response(f"Pumps property {prop} is larger than maximum allowed: {max_val}")
            
            if prop=="output_channel":
                if prop in used_channels and prop != current_pump_cfg["output_channel"]:
                    return self._format_error_response(f"Output channel {pump_config['output_channel']} already in use by another servo. Remove that channel first or use a different one.")
                
        return (True, pump_config, None)
 
    def __validate_float(self, num, ctx):
        try:
            num=float(num)
        except:
            return self._format_error_response(f"{ctx} has to be a number")
        return True,num,None
 
    def __validate_int(self, num, ctx):
        try:
            num=int(num)
        except:
            return self._format_error_response(f"{ctx} has to be a number")
        return True,num,None
 
    def _parse_config_screen_params(self, data):
        render_time_str = data.get("render_time")
        font_size_header_str = data.get("font_size_header")
        font_size_body_str = data.get("font_size_body")

        # Check if at least one param is provided
        if not (render_time_str or font_size_header_str or font_size_body_str):
            return self._format_error_response("No screen config parameters provided. Give at least one.")

        render_time = None
        font_size_header = None
        font_size_body = None

        if render_time_str:
            try:
                render_time = float(render_time_str)
                if not (ExcavatorAPIProperties.RENDERTIME_MIN < render_time < ExcavatorAPIProperties.RENDERTIME_MAX):
                    return self._format_error_response(f"render_time must be between {ExcavatorAPIProperties.RENDERTIME_MIN}-{ExcavatorAPIProperties.RENDERTIME_MAX}")
            except ValueError:
                return self._format_error_response("default_render_time must be a valid number")

        if font_size_header_str:
            try:
                font_size_header = int(font_size_header_str)

                if not (ExcavatorAPIProperties.FONTSIZE_MIN < font_size_header < ExcavatorAPIProperties.FONTSIZE_MAX):
                    return self._format_error_response(f"font_size_body must be between {ExcavatorAPIProperties.FONTSIZE_MIN}-{ExcavatorAPIProperties.FONTSIZE_MAX}")
            except ValueError:
                    return self._format_error_response("font_size_header must be a valid integer")

        if font_size_body_str:
            try:
                font_size_body = int(font_size_body_str)
                if not (ExcavatorAPIProperties.FONTSIZE_MIN < font_size_body < ExcavatorAPIProperties.FONTSIZE_MAX):
                    return self._format_error_response(f"font_size_body must be between {ExcavatorAPIProperties.FONTSIZE_MIN}-{ExcavatorAPIProperties.FONTSIZE_MAX}")
            except ValueError:
                return self._format_error_response("font_size_body must be a valid integer")

        # Success: return the values (None for unspecified params)
        parameters={"render_time": render_time,
                    "font_size_header":font_size_header,
                    "font_size_body": font_size_body}
        return True, (parameters,), None

    def _parse_add_pwm_channel_params(self,message):
        channel_name = message.get("channel_name")
        channel_type = message.get("channel_type")
        config=message.get("config")

        if (channel_name is None or channel_type is None or config is None):
            return self._format_error_response("No channel_name or channel_type or config - all have to provided")

        channel_name=channel_name.lower()
        channel_type=channel_type.lower()
        
        channel_names = PWMController.get_channel_names(include_pump=True)
        current_channel_configs, current_pump_config =  PWMController.load_config()
        used_channels=PWMController.get_used_channels()
        
        if channel_name in channel_names:
            return self._format_error_response(f"Channel name {channel_name} already taken.")

        if channel_type == "pump":
            try:
                config["output_channel"]
                config["pulse_min"]
                config["pulse_max"]
                config["idle"]
                config["multiplier"]
                r=self.validate_pump_config(pump_config=config, current_pump_cfg=current_pump_config, used_channels=used_channels)
                if r[0] is False: return r
                config = r[1]
            except Exception as e:
                return self._format_error_response(f"Provide all required pump attributes: {e}")
        elif channel_type == "channel_config":
            try:
                config["output_channel"]
                config["pulse_min"]
                config["pulse_max"]
                config["direction"]
                r=self.validate_channel_config(channel_configs={channel_name:config}, current_chan_cfg=current_channel_configs, used_channels=used_channels, new_chan=True)
                if r[0] is False: return r
                config = r[1][channel_name]
            except Exception as e:
                return self._format_error_response(f"Provide all required channel_config attributes: {e}")
        else:
            return self._format_error_response(f"unknown channel type: {channel_type}. Available types: {','.join(['pump', 'channel_config'])}")
        
        return True, (channel_name, channel_type, config), None

    def _parse_cfg_excavator_params(self, data):
        has_screen=data.get("has_screen")
        
        if has_screen is None:
            return self._format_error_response("No configure excavator parameters provided. Give atleast one")
        
        r=self.__validate_boolean(has_screen, "has_screen")
        if r[0] is False: return r
        has_screen=r[1]
        
        parameters={
            "has_screen": has_screen
        }
        return True, (parameters, ), None

    def _parse_cfg_orie_tracker_params(self, data):
        gyro_data_rate = data.get("gyro_data_rate")
        accel_data_rate = data.get("accel_data_rate")
        gyro_range = data.get("gyro_range")
        accel_range = data.get("accel_range")
        enable_lpf2 = data.get("enable_lpf2")
        enable_simple_lpf = data.get("enable_simple_lpf")
        alpha = data.get("alpha")
        tracking_rate = data.get("tracking_rate")
        
        print(f"Data. {data}")
        
        if (not gyro_data_rate and not accel_data_rate and not gyro_range
        and not accel_range and not enable_lpf2
        and not enable_simple_lpf and not alpha and not tracking_rate):
            return self._format_error_response("No configure orientation parameters provided give atleast one")
        
        if gyro_data_rate is not None:
            try:
                gyro_data_rate=int(gyro_data_rate)
                if gyro_data_rate not in ExcavatorAPIProperties.DATA_RATES:
                    return self._format_error_response(f"gyro_data_rate must be one of these possible data rates: {','.join(map(str,ExcavatorAPIProperties.DATA_RATES))}")
            except ValueError:
                return self._format_error_response("Gyro data rate must be an integer")
        if accel_data_rate is not None:
            try:
                accel_data_rate=int(accel_data_rate)
                if accel_data_rate not in ExcavatorAPIProperties.DATA_RATES:
                    return self._format_error_response(f"accel_data_rate must be one of these possible data rates: {','.join(map(str,ExcavatorAPIProperties.DATA_RATES))}")
            except ValueError:
                return self._format_error_response("accel_data_rate data rate must be an integer")
        if gyro_range is not None:
            try:
                gyro_range=int(gyro_range)
                print(f"Gyro range: {gyro_range}")
                if gyro_range not in ExcavatorAPIProperties.GYRO_RANGES:
                    return self._format_error_response(f"gyro_range must be one of thse possible values: {','.join(map(str,ExcavatorAPIProperties.GYRO_RANGES))}")
            except ValueError:
                return self._format_error_response(f"gyro_range must be one of thse possible values: {','.join(map(str,ExcavatorAPIProperties.GYRO_RANGES))}")
        if accel_range is not None:
            try:
                accel_range=int(accel_range)
                if accel_range not in ExcavatorAPIProperties.ACCEL_RANGES:
                    return self._format_error_response(f"accel_range must be one of thse possible values: {','.join(map(str,ExcavatorAPIProperties.ACCEL_RANGES))}")
            except ValueError:
                return self._format_error_response("accel_range must be an integer")
        if enable_lpf2 is not None:
            r=self.__validate_boolean(enable_lpf2, "enable_lpf2")
            if r[0] is False: return r
            enable_lpf2=r[1]
        if enable_simple_lpf is not None:
            r=self.__validate_boolean(value=enable_simple_lpf,context="enable_simple_lpf")
            if r[0] is False: return r
            enable_simple_lpf=r[1]
        if alpha is not None:
            try:
                alpha=float(alpha)
                if not (0 < alpha < 1):
                    return self._format_error_response("Alpha must be between 0-1")
            except ValueError:
                return self._format_error_response("alpha must be a float")
        if tracking_rate is not None:
            try:
                tracking_rate=int(tracking_rate)
                r=self.__validate_rate(rate=tracking_rate,context="tracking_rate")
                if r[0] is False: return r
            except ValueError:
                return self._format_error_response("tracking_rate must be an integer")

        # Success: return the values (None for unspecified params)
        parameters={"gyro_data_rate": gyro_data_rate, "accel_data_rate": accel_data_rate,
                    "gyro_range": gyro_range, "accel_range": accel_range,
                    "alpha":alpha, "tracking_rate":tracking_rate,
                    "enable_lpf2": enable_lpf2,
                    "enable_simple_lpf": enable_simple_lpf}
        return True, (parameters,), None

    def __validate_boolean(self, value, context):
        try: # Checks for 0/1/true/false
            value=int(value)
            value=False if value==0 else True
        except ValueError:
            value=value.lower()
            if "false" in value or "no" in value or "off" in value:
                value=False
            elif "true" in value or "yes" in value or "on" in value:
                value=True
            else:
                return self._format_error_response(f"Unvalid value for {context}. Possible values false/no/true/yes/0/1")
        return True, value, None

    def _parse_start_driving_params(self, data):
        channel_names=data.get("channel_names")
        data_sending_rate=data.get("data_sending_rate")
        
        if channel_names is None or data_sending_rate is None:
            return self._format_error_response("start driving parameters missing, both channel_numbers and data_sending_rate have to be provided")
        
        response=self.__validate_channel_names(channel_names)
        if not response[0]:
            return response
        
        if data_sending_rate: 
            try:
                data_sending_rate = float(data_sending_rate)
                response=self.__validate_rate(data_sending_rate, context="data_sending_rate", max=ExcavatorAPIProperties.COMMAND_RECEIVE_MAX_RATE)
                if response[0] is False: return response
            except ValueError:
                return self._format_error_response("data_sending_rate has to be an integer")
                
            if not (ExcavatorAPIProperties.MIN_RATE < data_sending_rate < ExcavatorAPIProperties.MAX_RATE):
                return self._format_error_response(f"data_sending_rate can not be smaller than {ExcavatorAPIProperties.MIN_RATE}")
        
        return True, (channel_names, data_sending_rate), None

    def _parse_start_driving_and_mirroring_params(self, data):
        channel_names = data.get("channel_names")
        data_sending_rate = data.get("data_sending_rate")
        data_receiving_rate = data.get("data_receiving_rate")
        
        if not channel_names or not data_sending_rate or not data_receiving_rate:
            return self._format_error_response("start driving&mirroring parameters missing, all have to be provided")
        
        try:
            data_receiving_rate=float(data_receiving_rate)
            data_sending_rate=float(data_sending_rate)
            r1=self.__validate_rate(data_receiving_rate, context="data_receiving_rate", max=ExcavatorAPIProperties.ORIENTATION_SEND_MAX_RATE)
            r2=self.__validate_rate(data_sending_rate, context="data_sending_rate", max=ExcavatorAPIProperties.COMMAND_RECEIVE_MAX_RATE)
            if r1[0] == False: return r1
            if r2[0] == False: return r2
        except ValueError:
            return self._format_error_response("Invalid parameter numbers")

        response=self.__validate_channel_names(channel_names)
        if not response[0]:
            return response
        
        if data_sending_rate < ExcavatorAPIProperties.MIN_RATE:
            return self._format_error_response(f"data_sending_rate can not be smaller than {ExcavatorAPIProperties.MIN_RATE}")

        return True, (channel_names, data_sending_rate, data_receiving_rate), None

    def _parse_start_mirroring_params(self, data):
        orientation_send_rate = data.get("orientation_send_rate")

        if orientation_send_rate:
            try:
                orientation_send_rate = float(orientation_send_rate)
                r1=self.__validate_rate(rate=orientation_send_rate, context="orientation_send_rate", max=ExcavatorAPIProperties.ORIENTATION_SEND_MAX_RATE)
                if r1[0] is False: return r1
            except ValueError:
                return self._format_error_response("orientation_send_rate must be a valid number")

        # Success: return the values (None for unspecified params)
        return True, (orientation_send_rate,), None

    def _format_error_response(self,msg):
        return False, None, msg

    def shutdown(self):
        """Shutdown the server"""
        self.stop_event.set()
        if self.clients and self.loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._close_all_clients(),
                    self.loop
                ).result(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
            except Exception as e:
                self.logger.error(f"Error closing clients: {e}")
        
        if self.server_thread and self.server_thread.is_alive():
            self.logger.info("Waiting for server thread to finish...")
            self.server_thread.join(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
        
        # Stop the event loop
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        
        self.server_running = False
        self.logger.info("WebSocket server shutdown complete")
        return True

    async def _close_all_clients(self):
        """Close all client connections"""
        for client in list(self.clients):
            await client.close()

    def is_ready(self):
        return self.server_running
    
        