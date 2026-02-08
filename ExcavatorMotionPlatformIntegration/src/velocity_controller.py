from utils import utils
from time import sleep
from utils import launch_params
from ModbusClients import ModbusClients
from utils.setup_logging import setup_logging
from services.MotorApi import MotorApi
import asyncio

class VelocityController():
    def __init__(self):
        self.config , self.motor_config = launch_params.handle_launch_params(b_motor_config=True)
        self.logger = setup_logging(name="velocity_controller", filename="velocity_controller.log")
        self.clients = None
        self.motor_api = None
        self.MAX_VEL = self.motor_config.MAX_VEL
        self.hz = 30
        self.vel_increment = (self.MAX_VEL / self.hz) * 2
        self.starting_vel_rpm = 30
        self.starting_vel = [39321, 25]
        self.max_analog_vel_left =  self.starting_vel_rpm
        self.max_analog_vel_right =  self.starting_vel_rpm
       

    async def start(self):
        try:
            self.clients = ModbusClients(config = self.config,logger = self.logger)
            await self.clients.connect()
            self.motor_api = MotorApi(logger=self.logger, modbus_clients=self.clients)
            await self.control()
        except Exception as e:
            self.logger.error(f"Error while starting velocity controller {e}")
    async def get_vel(self):
            (left_vel, right_vel) = await self.motor_api.get_vel()
            left_vel = abs(utils.registers_convertion(registers=left_vel,format="8.24", signed=True,scale=60))
            right_vel = abs(utils.registers_convertion(registers=right_vel,format="8.24", signed=True, scale=60))
            return left_vel,right_vel
            
    def increment_vel(self):
        if self.max_analog_vel_left < self.MAX_VEL and self.max_analog_vel_right < self.MAX_VEL:
            self.max_analog_vel_left = max(0, min((self.max_analog_vel_left + self.vel_increment),self.MAX_VEL))
            self.max_analog_vel_right = max(0, min((self.max_analog_vel_right + self.vel_increment),self.MAX_VEL))
        elif self.max_analog_vel_left < self.MAX_VEL:
            self.max_analog_vel_left = max(0, min((self.max_analog_vel_left + self.vel_increment),self.MAX_VEL))
        else:
            self.max_analog_vel_right = max(0, min((self.max_analog_vel_right + self.vel_increment),self.MAX_VEL))
    
    def in_position(self, value):
         return utils.is_nth_bit_on(12,value)  
    
    async def update_vel(self,l_oeg_motion, r_oeg_motion):
            left_vel_revs = utils.convert_val_into_format((self.max_analog_vel_left / 60) ,"8.24")
            right_vel_revs = utils.convert_val_into_format((self.max_analog_vel_left / 60) ,"8.24")
            # both moving
            if not self.in_position(l_oeg_motion) and not self.in_position(r_oeg_motion):
                await self.motor_api.set_analog_vel_max(left_vals=left_vel_revs, right_vals=right_vel_revs)
            # left moving
            elif not self.in_position(l_oeg_motion):
                await self.motor_api.set_analog_vel_max(left_vals=left_vel_revs)
            # right moving
            elif not self.in_position(r_oeg_motion):
                await self.motor_api.set_analog_vel_max(right_vals=right_vel_revs)
            
            # both stopped
            elif self.in_position(l_oeg_motion) and self.in_position(r_oeg_motion):
                await self.motor_api.set_analog_vel_max(left_vals=self.starting_vel, right_vals=self.starting_vel)
                self.max_analog_vel_right = self.starting_vel_rpm
                self.max_analog_vel_left = self.starting_vel_rpm
            # left stopped
            elif self.in_position(l_oeg_motion):
                await self.motor_api.set_analog_vel_max(left_vals=self.starting_vel)
                self.max_analog_vel_left = self.starting_vel_rpm
            # right stopped
            elif self.in_position(r_oeg_motion):
                await self.motor_api.set_analog_vel_max(right_vals=self.starting_vel)
                self.max_analog_vel_right = self.starting_vel_rpm
                
    async def control(self):
        try:
            while True:
                (l_oeg_motion, r_oeg_motion) = await self.motor_api.get_oeg_motion()
                self.increment_vel()
                await self.update_vel(l_oeg_motion,r_oeg_motion)
                await asyncio.sleep((1/self.hz))
        except Exception as e:
            self.logger.error(f"Error in velocity control loop: {e}")

    
if __name__ == "__main__":
    velocity_controller = VelocityController()
    asyncio.run(velocity_controller.start())