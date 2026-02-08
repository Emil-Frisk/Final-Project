import asyncio
import os
import websockets
from ModbusClients import ModbusClients
from services.process_manager import ProcessManager
from utils.launch_params import handle_launch_params
from utils.setup_logging import setup_logging
from utils.utils import format_response, extract_part
from services.MotorApi import MotorApi
from handlers import actions
from helpers import communication_hub_helpers as helpers
from pathlib import Path
from time import time

class CommunicationHub: 
    def __init__(self):
        self.wsclients = {}
        self.logger = setup_logging("server", "server.log")
        self.process_manager = None 
        self.config = None
        self.motor_config = None
        self.clients = None
        self.motor_api = None
        self.is_process_done = False
        self.server = None
        self.motors_initialized = False
        self.shutdown = False
        self.start_time = None
        self.counter = 0
    async def init(self, gui_socket):
        try:
            # Connect to both drivers
            connected = await self.clients.connect()

            if not connected:
                self.logger.error(f"""could not form a connection to both motors,
                            Left motors ips: {self.config.SERVER_IP_LEFT},
                            Right motors ips: {self.config.SERVER_IP_RIGHT},
                            shutting down the server """)
                helpers.close_tasks(self)
                self.process_manager.cleanup_all()
                return 1

            if not await self.motor_api.initialize_motors(gui_socket):
                self.logger.error(f"""
                                  Failed to initialize motors.""")
                self.clients.cleanup()
                helpers.close_tasks(self)
                self.process_manager.cleanup_all()
                return 1
            helpers.create_processes(self)
            await helpers.create_hearthbeat_monitor_tasks(self)
            ## success
            self.motors_initialized = True
            await gui_socket.send("event=motors_initialized|")
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")

    async def shutdown_server(self, wsclient=None):
        """stops and disables motors and closes sub processes"""
        self.logger.info("Shutdown request received. Cleaning up...")
        self.server_shutdown = True
        try:
            success = await self.motor_api.stop()
            if not success:
                self.logger.error("Stopping motors was not successful, will not shutdown server")
                return
        except Exception as e:
            self.logger.error("Stopping motors was not successful, will not shutdown server")
            return

        #########################################################################################
        #########################################################################################
        ####NOTE DO NOT REMOVE THIS LINE -IMPORTANT FOR MOTORS TO HAVE TIME TO STOP################
        await asyncio.sleep(5)
        #########################################################################################
        #########################################################################################
        #########################################################################################

        helpers.close_tasks(self)
        await self.motor_api.reset_motors()

        self.process_manager.cleanup_all()

        if self.clients is not None:
            self.clients.cleanup()
        await asyncio.sleep(20)

        if wsclient:
            await wsclient.send("event=shutdown|message=Server has been shutdown.|")

        if hasattr(self, "server") and self.server != None:
                try:
                    self.logger.info("Closing websocket server...")
                    self.logger.info("Websocket server closed successfully.")
                except Exception as e:
                    print("Error closing webosocket server.")
                    self.logger.error("Error while closing the websocket server.")
                finally:
                    os._exit(0)

    async def handle_client(self, wsclient, path=None):
        # Store client metadata
        client_info = {"identity": "unknown", "last_call": 0}
        self.wsclients[wsclient] = client_info
        self.logger.info(f"Client {wsclient.remote_address} connected! Path: {path or '/'}")

        try:
            async for message in wsclient:
                self.start_time = time()
                print(f"Received: {message}")
                action = extract_part("action=", message)
                pitch = extract_part("pitch=", message)
                roll = extract_part("roll=", message)
                modbus_left = extract_part("modbus_left=", message)
                modbus_right = extract_part("modbus_right=", message)
                
                if action == "rotate" and not helpers.rate_limit(self.wsclients[wsclient]["last_call"], max_freq=self.config.RATELIMIT):
                    await wsclient.send(format_response(event="warning", message=f"Motorapi only support: {self.config.RATELIMIT} hz."))
                    continue

                if action and action == "rotate":
                    await actions.rotate(self, pitch, roll, wsclient)
                    self.wsclients[wsclient]["last_call"] = time()
                    continue

                (receiver, identity, message,acceleration,velocity) = helpers.extract_parts(message)

                if action != "identify" and action != "clearfault" and not self.motors_initialized or self.shutdown:
                    await wsclient.send(format_response(event="error", message="message=Motors are not initialized or server has been given an order to shutdown"))    
                    continue
                    
                if not action:
                    await wsclient.send(format_response(event="error", message="message=No action given, example action=<action>"))
                else:
                    # "endpoints"
                    self.logger.info(f"processing action: {action}")
                    if action == "write":
                        await actions.write(self, pitch, roll, wsclient)
                    elif action == "identify":
                        await actions.identify(self, identity, wsclient)
                    elif action == "shutdown":
                        await self.shutdown_server(wsclient)
                    elif action == "stop":
                        await actions.stop_motors(self)
                    elif action == "continue":
                        await actions.continue_motors(self)
                    # For dataset
                    elif action == "modbusvalues":
                        await actions.set_modbusvalues(self, modbus_left, modbus_right)
                    # elif action == "updatevalues":
                    #     await actions.update_input_values(self,acceleration,velocity)
                    elif action == "message":
                        await actions.message(self, receiver, wsclient, message)
                    elif action == "clearfault":
                        await actions.clear_fault(self, wsclient=wsclient)
                    elif action == "absolutefault":
                        await actions.absolutefault(self)
                    elif action == "readtelemetry":
                        await actions.read_telemetry(self, wsclient)
                    elif action == "closefile":
                        # self.ow_file.close()
                        # self.logger.warning("Closed file!")
                        pass
                    else:
                        await wsclient.send(format_response(event="error", message="message=no action found here is all the actions"))
        except websockets.ConnectionClosed as e:
            self.logger.error(f"Client {wsclient.remote_address} (identity: {client_info['identity']}) disconnected with code {e.code}, reason: {e.reason}")
        except Exception as e:
            self.logger.error(f"Unexpected error for client {wsclient.remote_address} (identity: {client_info['identity']}): {e}")
        finally:
            self.logger.info(f"Cleaning up for client {wsclient.remote_address} (identity: {client_info['identity']})")
            await self.cleanup_client(wsclient)

    async def cleanup_client(self, client_socket):
        # print(f"Cleaning up client: {client_socket.remote_address} (identity: {self.clients[client_socket]["identity"]})")
        if client_socket in self.wsclients:
            del self.wsclients[client_socket]
        try:
            await client_socket.close()
        except Exception as e:
            self.logger.error(f"Error closing connection for {client_socket.remote_address}: {e}")

    async def start_server(self):
        try:
            # self.ow_file = open("overhead.txt" , "w")
            self.config , self.motor_config = handle_launch_params(b_motor_config=True)
            self.clients = ModbusClients(self.config, self.logger)
            await self.clients.connect()
            self.process_manager = ProcessManager(self.logger, target_dir=Path(__file__).parent)
            self.motor_api = MotorApi(logger=self.logger,
                            modbus_clients=self.clients,
                            config = self.motor_config,
                            )
            # self.motor_api.ow_file = self.ow_file
            self.server = await websockets.serve(self.handle_client, "localhost", self.config.WEBSOCKET_SRV_PORT, ping_timeout=None)
            self.logger.info(f"WebSocket serverwebsocket running on ws://localhost:{self.config.WEBSOCKET_SRV_PORT}")
        except Exception as e:
            self.logger.error(f"Error while launching  server{e}")