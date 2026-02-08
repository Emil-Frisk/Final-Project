
from pymodbus.client import AsyncModbusTcpClient
from typing import Optional
from utils.utils import setup_logger

class ModbusClients:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = setup_logger(logger)
        self.client_left: Optional[AsyncModbusTcpClient] = None
        self.client_right: Optional[AsyncModbusTcpClient] = None
        self.max_retries = 10

    async def connect(self):
        """
        Establishes connections to both Modbus clients.
        Returns True if both connections are successful, or False if either fails
        and returns None if error
        """
        try:
            self.client_left = AsyncModbusTcpClient(
                host=self.config.SERVER_IP_LEFT,
                port=self.config.SERVER_PORT 
            )

            self.client_right = AsyncModbusTcpClient(
                host=self.config.SERVER_IP_RIGHT,
                port=self.config.SERVER_PORT  
            )

            left_connected = False
            right_connected = False
            max_attempts = self.max_retries
            attempt_left = 0
            attempt_right = 0

            while (not left_connected or not right_connected) and \
            (attempt_left < max_attempts or attempt_right < max_attempts):
                if not left_connected:
                    left_connected = await self.client_left.connect()
                    attempt_left += 1
                    if not left_connected:
                         self.logger.debug(f"Left connection attempt {attempt_left} failed")

                if not right_connected:
                    right_connected = await self.client_right.connect()
                    attempt_right += 1
                    if not right_connected:
                         self.logger.debug(f"Right connection attempt {attempt_right} failed")
                
            if left_connected and right_connected:
                self.logger.info("Both clients connected succesfully")

                # if "fault_poller.py" in self.config.MODULE_NAME:
                #     self.client_left.ctx.next_tid = self.config.START_TID
                #     self.client_right.ctx.next_tid = self.config.START_TID

                return True
            else: 
                self.logger.warning(f"Connection failed after {max_attempts} attempts. "
                                    f"Left: {left_connected}, right: {right_connected}")
                return False
            
        except Exception as e:
            self.logger.error(f"Error connecting to clients {str(e)}")
            return None

    def cleanup(self):
        try:
            self.logger.info(f"cleanup function executed at module {self.config.MODULE_NAME}")
            if self.client_left is not None:
                self.client_left.close()
            if self.client_right is not None:
                self.client_right.close()    
        except Exception as e:
            self.logger.info(f"error happened: {e}")


    def check_and_reset_tids(self):
        for client in [self.client_left, self.client_right]:
            if client and client.ctx.next_tid >= self.config.LAST_TID:
                client.ctx.next_tid = self.config.START_TID
                self.logger.debug(f"Reset TID for client")