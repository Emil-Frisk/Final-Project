import asyncio
import websockets
import json
from tcp_client import TCPClient
import json
import queue
import threading

class ProxyServer:
    def __init__(self):
        self.ws_server=None
        self.wsclients=set()
        self.stop_event=threading.Event()
        # Simple way to assume who to send a possible error message for.
        self.prev_command_client=None
        
        self.excavator_client=None
        self.messages_queue=asyncio.Queue()
    
    
    async def start(self):
        self.ws_server=await websockets.serve(self.handle_client,"localhost", 5433)
    
    async def start_excavator_client(self, ip):
        if self.excavator_client is not None: return True
        
        self.excavator_client=TCPClient(srv_ip=ip, message_queue=self.messages_queue)
        result = self.excavator_client.start()
        if result is False:
            await ProxyServer.send_error(self.prev_command_client, f"Could not find excavator with ip: {ip}. Make sure you are in the same network")
            return False
        return True
    
    async def shutdown(self):
        self.stop_event.set()
        if self.excavator_client: 
            self.excavator_client.shutdown()
        await self.close_clients()
        if self.ws_server is not None:
            self.ws_server.close()
    
    async def close_clients(self):
        if self.wsclients:
            for cl in list(self.wsclients):
                print(f"Closing connection for client: {cl.remote_address}")
                await cl.close()
    
    async def handle_client(self, websocket):
        """Handle a connected client"""
        client_addr = websocket.remote_address
        print(f"Client connected: {client_addr}")
        self.wsclients.add(websocket)
        
        try:
            async for message in websocket:
                print(f"Received from {client_addr}: {message}")
                
                parameters, action = await self._parse_message(message, websocket)
                if parameters is None or action is None: continue
                
                self.prev_command_client=websocket
                
                if action=="start_excavator_client":
                    excavator_ip=parameters.get("ip")
                    result = await self.start_excavator_client(ip=excavator_ip)
                    if result is False: continue
                    await ProxyServer.send_event(client=websocket,event="started_excavator_client")                    
                    continue
                    
                # No other action is allowed if excavatorclient is not available
                if self.excavator_client is None:
                    await ProxyServer.send_error(websocket,"ExcavatorClient needs to be initialized first.")
                    continue
                
                if action=="get_screen_config":
                    self.excavator_client.get_screen_config()
                elif action=="get_pwm_config":
                    self.excavator_client.get_pwm_config()
                elif action=="get_orientation_tracker_config":
                    self.excavator_client.get_orientation_tracker_config()
                
                # TODO - add configuration methods here...
                continue                
        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected: {client_addr}")
        except Exception as e:
            print(f"Error with {client_addr}: {e}")
        finally:
            self.wsclients.remove(websocket)

    async def _parse_message(self, msg, client):
        try:
            parameters=json.loads(msg)
        except Exception:
            await ProxyServer.send_error(client,"Message has to be in json format")
            return None, None
        
        action = parameters.get("action")
        if action is None:
            await ProxyServer.send_error(client,"No action given.")
            return None, None
        
        return parameters, action
    
    async def send_queued_messages(self):
        while not self.stop_event.is_set():
            if not self.messages_queue.empty():
                msg=await self.messages_queue.get()
                event=msg.get("event")
                if event == "error":
                    err_msg=msg.get("message")
                    await ProxyServer.send_error(client=self.prev_command_client, msg=err_msg)
                elif event == "configuration":
                    await ProxyServer.send_message(self.prev_command_client,msg=msg)
                else:
                    print(f"Unknown event: {event}")
            await asyncio.sleep(1)
     
    @staticmethod
    async def send_error(client,msg):
        await client.send(json.dumps({"event": "error", "message": msg}))

    @staticmethod
    async def send_event(client,event, msg=""):
        await client.send(json.dumps({"event": event, "message": msg}))

    @staticmethod
    async def send_message(client,msg):
        await client.send(json.dumps(msg))

async def main():
    """Start the WebSocket server"""
    try:
        proxy_server=ProxyServer()
        asyncio.create_task(proxy_server.send_queued_messages())
        await proxy_server.start()
        print("WebSocket server started on ws://localhost:5433")
        await proxy_server.ws_server.wait_closed()
    except Exception as e:
        print(f"ProxyServer has crashed: {e}")
    finally:
        if proxy_server:
            await proxy_server.shutdown()

if __name__ == "__main__":
    asyncio.run(main())