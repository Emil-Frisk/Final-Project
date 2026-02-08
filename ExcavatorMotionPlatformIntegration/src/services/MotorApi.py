from typing import List, Optional, Tuple, Union
from settings.motors_config import MotorConfig
from utils.utils import IEG_MODE_bitmask_default
import asyncio
from utils.utils import setup_logger
from helpers.fault_helpers import validate_fault_register
from time import time
from utils.utils import is_nth_bit_on, convert_to_revs, convert_vel_rpm_revs, convert_acc_rpm_revs, bit_high_low_both, registers_convertion, convert_val_into_format
from helpers.motor_api_helper import should_update_vel, calc_vel_proportional_scale, calc_delta_revs, update_previous_revs, validate_dead_bandwidth,calculate_target_revs, get_register_values, calculate_motor_modbuscntrl_vals, clamp_target_revs
import math
import logging

class MotorApi():
    def __init__(self, modbus_clients,config=MotorConfig(), retry_delay = 0.2, max_retries = 10, logger=None):
        self.logger = setup_logger(logger)
        self.client_right = modbus_clients.client_right
        self.client_left = modbus_clients.client_left
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.config = config
        self.analog_mode=True
        self.previous_revs = [14,14] # Left, right
        self.prev_vels = [None, None]
    
    async def _write_registers_left(self, address, vals):
        return await self.client_left.write_registers(
            address=address,
            values=vals,
            slave=self.config.SLAVE_ID
        )
    async def _write_registers_right(self, address, vals):
        return await self.client_right.write_registers(
            address=address,
            values=vals,
            slave=self.config.SLAVE_ID
        )
    async def _read_registers_left(self, address, count):
        return await self.client_left.read_holding_registers(
                address=address,
                count=count,
                slave=self.config.SLAVE_ID
            )
    async def _read_registers_right(self, address, count):
        return await self.client_right.read_holding_registers(
                address=address,
                count=count,
                slave=self.config.SLAVE_ID
            )
    def check_gather_result(self, results):
        left_result, right_result = results
        success_left = False
        success_right = False
        
        if not isinstance(left_result, Exception):
            success_left = True

        if not isinstance(right_result, Exception):
            success_right = True
        return success_left, success_right 

    async def retry_wrapper(self, func, description, address, vals, max_retries=5):
            success = False
            attempt=0
            while max_retries > attempt:
                if not success:
                    # response_left = await self._write_registers_left(vals=left_vals, address=address)
                    response = await func(address=address, vals=vals)

                if response.isError():
                    attempt += 1
                    self.logger.error(f"Failed to {description}. Attempt {attempt}")
                else:
                    success = True

                if success:
                    self.logger.info(f"succesfully {description} motor!")
                    return True
                
                # Delay between retries
                await asyncio.sleep(self.retry_delay)     
            self.logger.error(f"Failed to {description}")
            return False

    async def _write_left_wrapper(self, left_vals, address, description="write to left motors"):
            return await self.retry_wrapper(self._write_registers_left, description=description, address=address, vals=left_vals)

    async def _write_right_wrapper(self, right_vals, address, description="write to right motors"):
        return await self.retry_wrapper(self._write_registers_right, description=description, address=address, vals=right_vals)

    async def _write_both(self, address, description, left_vals=None, right_vals=None) -> bool:
        try:
            ### tries to _write_both to both registers in parallel first
            results = await asyncio.gather(self._write_registers_left(address, vals=left_vals), self._write_registers_right(address=address, vals=right_vals), return_exceptions=True)
            success_left, success_right = self.check_gather_result(results)
            if success_left and success_right:
                return True
            
            r_result = await self.retry_wrapper(self._write_registers_right, address=address, vals=right_vals, description=f"Failed to {description} on right motor")
            l_result = await self.retry_wrapper(self._write_registers_left, address=address, vals=right_vals, description=f"Failed to {description} on left motor")
            if not r_result or not l_result:
                return False
            return True
        except Exception as e:
            self.logger.error(f"Unexpected error while {description}: {str(e)}")
            return False
    async def _read(self, address, description, count=2, log=True) -> Union[tuple, bool]:
        """Reads the specified register addresses values and returns them
        as a tuple (left, right) or False if the operation was not successful"""
        try:
            attempt_left = 0
            attempt_right = 0
            success_left = False
            success_right = False
            max_retries = self.max_retries

            ### tries to _read to both registers in parallel first
            results = await asyncio.gather(self._read_registers_left(address, count=count), self._read_registers_right(address=address, count=count), return_exceptions=True)
            success_left, success_right = self.check_gather_result(results)
            if success_left and success_right:
                if log:
                    self.logger.info(f"Successfully {description} both motors")
                left_vals, right_vals = get_register_values(results)
                if count==1:
                    return (left_vals[0], right_vals[0])
                else:
                    return (left_vals, right_vals)

            while max_retries > attempt_left and max_retries > attempt_right:
                # _write_both to left motor if not yet successful
                if not success_left:
                    response_left = await self._read_registers_left(address=address, count=count)
                    if response_left.isError():
                        attempt_left += 1
                        self.logger.error(f"Failed to {description} on left motor. Attempt {attempt_left}/{max_retries}")
                    else:
                        success_left = True
                        if log:
                            self.logger.info(f"Successfully {description} on left motor")

                # _read from right motor if not yet successful
                if not success_right:
                    response_right = await self._read_registers_right(address=address, count=count)
                    if response_right.isError():
                        attempt_right += 1
                        self.logger.error(f"Failed to {description} on right motor. Attempt {attempt_right}/{max_retries}")
                    else:
                        success_right = True
                        if log:
                            self.logger.info(f"Successfully {description} on right motor")

                # Break if both are successful
                if success_left and success_right:
                    break

                # Delay between retries
                await asyncio.sleep(self.retry_delay)

            if not success_left or not success_right:
                self.logger.error(f"Failed to {description} on both motors. Left: {success_left}, Right: {success_right}")
                return False

            if log:
                self.logger.info(f"Successfully {description} on both motors")
            
            
            left_vals, right_vals = get_register_values((response_left, response_right))
            if count==1:
                return (left_vals[0], right_vals[0])
            else:
                return (left_vals, right_vals)

        except Exception as e:
            self.logger.error(f"Unexpected error while reading motor REVS: {str(e)}")
            return False
    async def reset_motors(self) -> bool:
        """ 
        Removes all temporary settings from both motors
        and goes back to default ones
        """
        return await self._write_both(address=self.config.SYSTEM_COMMAND_REGISTER, left_vals=[self.config.RESTART_VALUE], right_vals=[self.config.RESTART_VALUE], description="force a software power-on restart of the drive")
    async def get_recent_fault(self, count=1) -> tuple[Optional[int], Optional[int]]:
        """
        _read fault registers from both clients.
        Returns tuple of (left_fault, right_fault), None if _read fails
        """
        return await self._read(address=self.config.RECENT_FAULT_REGISTER, description="_read fault register", count=count)
    async def get_present_fault(self, count=1) -> tuple[Optional[int], Optional[int]]:
        """
        _read fault registers from both clients.
        Returns tuple of (left_fault, right_fault), None if _read fails
        """
        return await self._read(address=self.config.PRESENT_FAULT_REGISTER, description="_read present disabling fault status register", count=count)
    async def fault_reset(self) -> bool:
        # Makes sure bits can be only valid bits that we want to control
        # no matter what you give as a input
        return await self._write_both(values=[IEG_MODE_bitmask_default(65535)], address=self.config.IEG_MODE_REGISTER, description="reset faults")
    async def check_fault_stauts(self, log=True) -> Optional[bool]:
        """
        _read drive status from both motors.
        Returns (left, right) values as a tuple if success
        or False if it fails
        """
        return await self._read(log=log, address=self.config.OEG_STATUS_REGISTER, description="_read driver status",count=1)
    async def get_vel(self) -> bool:
        """
        Gets velocity feedback VEL32 register for both motors
        """
        return await self._read(address=self.config.VFEEDBACK_VELOCITY_REGISTER,description="_read velocity register", count=2)
    
    async def get_analog_vel(self) -> bool:
        """
        Gets velocity feedback VEL32 register for both motors
        """
        return await self._read(address=self.config.ANALOG_VEL_MAXIMUM_REGISTER,description="read analog velocity register", count=2)
    
    async def stop(self) -> bool:
        """
        Attempts to stop both motors by writing to the IEG_MOTION_REGISTER register.
        Returns True if successful, False if failed after retries.
        """
        return await self._write_both(address=self.config.IEG_MOTION_REGISTER, left_vals=[self.config.STOP_VALUE],right_vals=[self.config.STOP_VALUE], description="Stop motors")
    
    async def continue_motors(self) -> bool:
        """
        Attempts to remove stop bit from both motors by writing to the IEG_MOTION_REGISTER register.
        Returns True if successful, False if failed after retries.
        """
        return await self._write_both(address=self.config.IEG_MOTION_REGISTER, left_vals=[0],right_vals=[0], description="Continue motors")

    async def home(self) -> bool:
        try:
            ### Reset IEG_MOTION_REGISTER bit to 0 so we can trigger rising edge with our home command
            if not await self._write_both(address=self.config.IEG_MOTION_REGISTER, left_vals=[0],right_vals=[0], description="reset IEG_MOTION_REGISTER to 0"):
                return False
                
            ### Initiate homing command
            if not await self._write_both(left_vals=[self.config.HOME_VALUE],right_vals=[self.config.HOME_VALUE], address=self.config.IEG_MOTION_REGISTER, description="initiate homing command"): 
                return False
            
            ### homing order was success for both motos make a poller coroutine to poll when the homing is done.
            #Checks if both actuators are homed or not. Returns True when homed.
            homing_max_duration = 30
            start_time = time()
            elapsed_time = 0
            while elapsed_time <= homing_max_duration:
                response = await self._read(address=self.config.OEG_STATUS_REGISTER, description="_read OEG_STATUS_REGISTER",count=1)
                if not response:
                    await asyncio.sleep(self.retry_delay)
                    continue
                
                (OEG_STATUS_right, OEG_STATUS_left) = response
                
                ishomed_right = is_nth_bit_on(1, OEG_STATUS_right)
                ishomed_left = is_nth_bit_on(1, OEG_STATUS_left)

                # Success
                if ishomed_right and ishomed_left:
                    self.logger.info(f"Both motors homes successfully:")
                    await self._write_both(address=self.config.IEG_MOTION_REGISTER, left_vals=[0], right_vals=[0], description="reset IEG_MOTION_REGISTER to 0")
                    return True
                
                await asyncio.sleep(1)
                elapsed_time = time() - start_time
            
            self.logger.error(f"Failed to home both motors within the time limit of: {homing_max_duration}")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error while homing motors: {e}")
            return False
    async def set_analog_pos_max(self, decimal: int, whole: int) -> bool:
        """
        Sets the analog position maximum for both motors.
        Args:
            decimal (int): The decimal part of the position limit.
            whole (int): The whole number part of the position limit.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        values = [decimal, whole]
        if whole >= self.config.MAX_POS_WHOLE:
            assert whole <= self.config.MAX_POS_WHOLE and decimal <= self.config.MAX_POS_DECIMAL
        elif whole <= self.config.MIN_POS_WHOLE:
            assert whole >= self.config.MIN_POS_WHOLE and decimal >= self.config.MIN_POS_DECIMAL

        return await self._write_both(left_vals=values,right_vals=values, description="set analog positition max", address=self.config.ANALOG_POSITION_MAXIMUM_REGISTER)
    async def set_analog_pos_min(self, decimal: int, whole: int) -> bool:
        """
        Sets the analog position minium for both motors.
        Args:
            decimal (int): The decimal part of the position limit.
            whole (int): The whole number part of the position limit.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        values = [decimal, whole]
        if whole >= self.config.MAX_POS_WHOLE:
            assert whole <= self.config.MAX_POS_WHOLE and decimal <= self.config.MAX_POS_DECIMAL
        elif whole <= self.config.MIN_POS_WHOLE:
            assert whole >= self.config.MIN_POS_WHOLE and decimal >= self.config.MIN_POS_DECIMAL

        return await self._write_both(left_vals=values,right_vals=values, description="set analog position min", address=self.config.ANALOG_POSITION_MINIMUM_REGISTER)
    async def set_analog_vel_max(self, left_vals=None, right_vals=None) -> bool:
        """
        Sets the analog velocity maximum for both motors.
        Args:
            decimal (int): The decimal part of the velocity limit.
            whole (int): The whole number part of the velocity limit.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """

        if not left_vals and not right_vals:
            raise Exception("Invalid parameters")
        if left_vals:
            left_vals[0] = abs(left_vals[0])
            left_vals[1] = abs(left_vals[1])
            assert left_vals[1] <= self.config.MAX_VEL_REGISTERS_FORMAT, "Velocity exceeded MAXIMUM LIMIT!"

        if right_vals:
            right_vals[0] = abs(right_vals[0])
            right_vals[1] = abs(right_vals[1])
            assert right_vals[1] <= self.config.MAX_VEL_REGISTERS_FORMAT, "Velocity exceeded MAXIMUM LIMIT!"


        if left_vals and right_vals:
            return await self._write_both(left_vals=left_vals, right_vals=right_vals, description="set analog velocity max for both motors ", address=self.config.ANALOG_VEL_MAXIMUM_REGISTER)            
        elif left_vals and not right_vals:
            return await self._write_left_wrapper(left_vals=left_vals, address=self.config.ANALOG_VEL_MAXIMUM_REGISTER, description="Set analog velocity max for the left motor")
        elif right_vals and not left_vals:
            return await self._write_right_wrapper(right_vals=right_vals, address=self.config.ANALOG_VEL_MAXIMUM_REGISTER, description="Set analog velocity max for the right motor")

    async def set_host_vel_max(self, decimal: int, whole: int) -> bool:
        """
        Sets the host velocity maximum for both motors.
        Args:
            decimal (int): The decimal part of the velocity limit.
            whole (int): The whole number part of the velocity limit.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        values = [decimal, whole]
        return await self._write_both(values=values, description="set host velocity max", address=self.config.HOST_VEL_MAXIMUM_REGISTER)
    async def set_analog_acc_max(self, left_vals=None, right_vals=None) -> bool:
        """
        Sets the analog acceleration maxium for both motors.
        Args:
            decimal (int): The decimal part of the acceleration limit.
            whole (int): The whole number part of the acceleration limit.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        if not left_vals and not right_vals:
            raise ValueError("Invalid parameters")
         
        if left_vals:
            left_vals[0] = abs(left_vals[0])
            left_vals[1] = abs(left_vals[1])
            assert left_vals[1] <= self.config.MAX_ACC_REGISTERS_FORMAT, "Acceleration exceeded MAXIMUM LIMIT!"
        if right_vals:
            right_vals[0] = abs(right_vals[0])
            right_vals[1] = abs(right_vals[1])
            assert right_vals[1] <= self.config.MAX_ACC_REGISTERS_FORMAT, "Acceleration exceeded MAXIMUM LIMIT!"

        if left_vals and right_vals:
            return await self._write_both(left_vals=left_vals, right_vals=right_vals, description="set analog acceleration max for both motors ", address=self.config.ANALOG_ACCELERATION_MAXIMUM_REGISTER)            
        elif left_vals and not right_vals:
            return await self._write_left_wrapper(left_vals=left_vals, address=self.config.ANALOG_ACCELERATION_MAXIMUM_REGISTER, description="set analog acceleration maxium for left motor")
        elif right_vals and not left_vals:
            return await self._write_right_wrapper(right_vals=right_vals, address=self.config.ANALOG_ACCELERATION_MAXIMUM_REGISTER, description="set analog acceleration maxium for right motor")
    
        return await self._write_both(left_vals=left_vals, right_vals=right_vals, description="set analog acceleration maxium", address=self.config.ANALOG_ACCELERATION_MAXIMUM_REGISTER)
    async def set_host_acc_max(self, decimal: int, whole: int) -> bool:
        """
        Sets the host acceleration maxium for both motors.
        Args:
            decimal (int): The decimal part of the acceleration limit.
            whole (int): The whole number part of the acceleration limit.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        values = [decimal, whole]
        return await self._write_both(values=values, description="set host acceleration maxium", address=self.config.HOST_ACCELERATION_MAXIMUM_REGISTER)
    async def set_analog_input_channel(self, value: int) -> bool:
        """
        Sets the analog input channel for both motors.
        Args:
            value (int): The value for the analog input channel.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        return await self._write_both(left_vals=[value],right_vals=[value], address=self.config.ANALOG_INPUT_CHANNEL_REGISTER, description="set analog input channel")
    async def get_current_revs(self) ->  Union[Tuple[List[int], List[int]], bool]:
        """
        Gets the current REVS for both motors
        Returns:
             A tuple of (response_left, response_right), where each response is a list of two integers:
            - response_left: [decimal_part, whole_part] for the left motor
            - response_right: [decimal_part, whole_part] for the right motor
            Returns False if the operation is not successful.
        """
        return await self._read(address=self.config.PFEEDBACK_POSITION_REGISTER, description="_read current REVS", count=2)
    async def set_analog_modbus_cntrl(self, values: Tuple[int, int]) -> bool:
        """
        Sets the analog input Modbus control value for both motors,
        where 0 makes the motor go to the analog_pos_min position
        and 10,000 makes the motor go to the analog_pos_max position.
        Args:
            values: A tuple of (value_left, value_right) where each value is an integer
                    between 0 and 10,000 representing the control value for the left and right motors.
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        
        value_left, value_right = values
        assert value_left >= 0 and value_left <= 10000, "Modbus control value needs between 0-10000"
        assert value_right >= 0 and value_right <= 10000, "Modbus control value needs between 0-10000"

        return await self._write_both(right_vals=[value_right], left_vals=[value_left], description="Set analog modbus control value", address=self.config.ANALOG_MODBUS_CNTRL_REGISTER)
    async def set_host_position(self, values: Tuple[List,List]) -> bool:
            """
            Sets the host position values for both motors. 
            """
            values_left, values_right = values
            return await self._write_both(different_values=True, right_vals=values_right, left_vals=values_left, description="Set host position values", address=self.config.HOST_POSITION_REGISTER)
    async def set_host_current(self, value: int) -> bool:
        """
        Sets the host maxium current that will override IPEAK_REGISTER value(15A as long as its below it) UCUR16 - 9.7.
        """
        return await self._write_both(values=[value], description="Set host maximum current", address=self.config.HOST_CURRENT_MAXIMUM_REGISTER)
    async def wait_for_motors_to_stop(self) -> bool:
        """ Polls for motors to stop returns True or False"""
        try:
            waiting_duration = 30
            start_time = time()
            elapsed_time = 0
            while elapsed_time <= waiting_duration:
                response_left, response_right = await self.get_vel()
                if response_left == None or response_right == None:
                    await asyncio.sleep(0.2)
                    elapsed_time = time() - start_time
                    self.logger.error(f"Failed to get current motor velocity:")
                    continue
                
                ### get the whole number
                velocity_left = response_left >> 8
                velocity_right = response_right >> 8

                # Success
                if velocity_left == 0 and velocity_right == 0:
                    self.logger.info(f"Both motors have successfully stopped:")
                    await asyncio.sleep(0.5) ### add some safety buffer 
                    return True
                
                await asyncio.sleep(0.2)
                elapsed_time = time() - start_time
            
            self.logger.error(f"Waiting for motors to stop was not successful within the time limit of: {waiting_duration}")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error while waiting for motors to stop: {e}")
            return False
    async def set_host_command_mode(self, value: int) -> bool:
        """
        Sets both of the motors host command mode to value
        Args:
            value: 
            OPMODE MAP
                0: disabled
                1: digital inputs
                2: analog position
                5: host position
                6: host velocity
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        return await self._write_both(address=self.config.COMMAND_MODE, left_vals=[value], right_vals=[value], description="set host command mode")
    async def set_ieg_mode(self, value: int) -> bool:
        """
        Sets IEG_MODE_REGISTER bits
        !!! IMPORTANT NOTE !!! 
        WDO NOT EVER ACTIVATE ALL BITS IT WILL DEFINE NEW HOME AND THE HOLE SYSTEM
        WILL BRAKE, IT WILL ALSO DISABLE THE MOTORS BREAKS MAKE SURE TO USE
        BIT MAKS DEFINED IN THE UTILS (IEG_MODE_bitmask_default) and (IEG_MODE_bitmask_alternative)
        THESE BITMASKS WILL MAKE SURE DANGEROUS BITS WILL NEVER BE ON EVEN IF YOU USE MAX UINT32 VALUE
        Args:
            value: 
            bit map
                0: enable momentary
                1: enable maintained
                7: alt mode
                10: define home ( danger)
                11: define home 2(danger)¨
                14: release break ( danger )
                15: reset fault
        Returns:
            bool: True if successful for both motors, False otherwise.
        """
        return await self._write_both(description="set IEG_MODE_REGISTER", left_vals=[IEG_MODE_bitmask_default(value)], right_vals=[IEG_MODE_bitmask_default(value)], address=self.config.IEG_MODE_REGISTER)
    async def get_modbuscntrl_val(self) -> Union[tuple, bool]:
        """
        Gets the current revolutions of both motors and calculates with linear interpolation
        the percentile where they are in the current max_rev - min_rev range.
        After that we multiply it with the maxium modbuscntrl val (10k)
        """
        result = await self.get_current_revs()
        
        if result is False:
            return False

        try:
            pfeedback_client_left, pfeedback_client_right = result

            revs_left = convert_to_revs(pfeedback_client_left)
            revs_right = convert_to_revs(pfeedback_client_right)

            ## Percentile = x - pos_min / (pos_max - pos_min)
            POS_MIN_REVS = self.config.POS_MIN_REVS
            POS_MAX_REVS = self.config.POS_MAX_REVS
            modbus_percentile_left = (revs_left - POS_MIN_REVS) / (POS_MAX_REVS - POS_MIN_REVS)
            modbus_percentile_right = (revs_right - POS_MIN_REVS) / (POS_MAX_REVS - POS_MIN_REVS)
            modbus_percentile_left = max(0, min(modbus_percentile_left, 1))
            modbus_percentile_right = max(0, min(modbus_percentile_right, 1))

            position_client_left = math.floor(modbus_percentile_left * self.config.MODBUSCTRL_MAX)
            position_client_right = math.floor(modbus_percentile_right * self.config.MODBUSCTRL_MAX)
            return position_client_left, position_client_right
        except Exception as e:
            self.logger.error(f"Unexpected error while converting to revs: {e}")
            return False
        
    async def initialize_motors(self, gui_socket):
        """Initializes analog control mode"""
        if self.analog_mode:
            return await self.initialize_motors_analog(gui_socket)
        ## HOST CONTROL IS NOT IMPLEMENTED CORRECTLY. DONT USE THIS IF YOU DONT KNOW HOW TO FIX IT.
        # else:
        #     return await self.initialize_motor_host(gui_socket)

    async def initialize_motors_analog(self, gui_socket) -> bool:
        """ Tries to initialize the motors with initial values returns true if succesful """
        await self.set_host_command_mode(0)
        if not await validate_fault_register(self, gui_socket):
            return False
        await self.set_ieg_mode(self.config.RESET_FAULT_VALUE)
        homed = await self.home()
        # homed = True
        if homed: 
            ## Prepare motor parameters for operation
            ### MAX POSITION LIMITS FOR BOTH MOTORS | 147 mm
            if not await self.set_analog_pos_max(self.config.MAX_POS_DECIMAL, self.config.MAX_POS_WHOLE):
                return False

            ### MIN POSITION LIMITS FOR BOTH MOTORS || 2 mm
            if not await self.set_analog_pos_min(self.config.MIN_POS_DECIMAL, self.config.MIN_POS_WHOLE):
                return False

            vals = convert_vel_rpm_revs(self.config.MAX_VEL)
            if not await self.set_analog_vel_max(left_vals=vals, right_vals=vals):
                return False

            ### UACC32 whole number split in 12.4 format
            vals = convert_acc_rpm_revs(self.config.MAX_ACC)
            if not await self.set_analog_acc_max(left_vals=vals, right_vals=vals):
                return False

            ## Analog input channel set to use modbusctrl (2)
            if not await self.set_analog_input_channel(self.config.ANALOG_MODBUS_CNTRL_VALUE):
                return False

            response = await self.get_modbuscntrl_val()
            if not response:
                return False
            (position_client_left, position_client_right) = response

            # modbus cntrl 0-10k
            if not await self.set_analog_modbus_cntrl((position_client_left, position_client_right)):
                return False

            # # Finally - Ready for operation
            if not await self.set_host_command_mode(self.config.ANALOG_POSITION_MODE):
                return False

            # Enable motors
            if not await self.set_ieg_mode(self.config.ENABLE_MAINTAINED_VALUE):
                return False
            
            return True

    async def initialize_motor_host(self, gui_socket) -> bool:
        """ Tries to initialize the motors with initial values returns true if succesful """
        await self.set_host_command_mode(0)
        if not await validate_fault_register(self, gui_socket):
            return False
        
        await self.set_ieg_mode(self.config.RESET_FAULT_VALUE)
        homed = await self.home()

        if homed: 
            ### HOST MAX_VEL
            (velocity_decimal, velocity_whole) = convert_vel_rpm_revs(self.config.MAX_VEL)
            if not await self.set_host_vel_max(velocity_decimal, velocity_whole):
                return False
            ### HOST MAX_ACC
            (acc_decimal, acc_whole) = convert_acc_rpm_revs(self.config.MAX_ACC)
            if not await self.set_host_acc_max(acc_decimal, acc_whole):
                return False
            ### Plimits !!!!
            # results = convert_val_into_format(value=12,format="16.16")
            # if not await self.set_plimit_minus(results):
            #     return False
            # results = convert_val_into_format(value=16,format="16.16")
            # if not await self.set_plimit_plus(results):
            #     return False
            # if not await self.set_plimit_velocity():
            #     return False
            
            ### current revs for initializing host position
            response = await self.get_current_revs()
            if not response:
                return False
            (position_client_left, position_client_right) = response
            ### Set host position
            if not await self.set_host_position((position_client_left, position_client_right)):
                return False

            ### set host current limit
            if not await self.set_host_current(value=convert_val_into_format(5, format="9.7")):
                return False

            # # Finally - Ready for operation
            if not await self.set_host_command_mode(self.config.HOST_POSITION_MODE):
                return False

            # Enable motors
            if not await self.set_ieg_mode(self.config.ENABLE_MAINTAINED_VALUE):
                return False
            return True
        
    async def rotate(self, pitch, roll):
        if self.analog_mode: 
            await self.rotate_analog(pitch, roll)
        else:
            await self.rotate_host(pitch, roll)

    async def rotate_analog(self, pitch_value, roll_value):
        try:
            revs = calculate_target_revs(self,pitch_value=pitch_value, roll_value=roll_value)
            modbuscntrl_left, modbuscntrl_right = calculate_motor_modbuscntrl_vals(self, left_revs=revs[0],
                                                                                    right_revs=revs[1])            

            await self.set_analog_modbus_cntrl((modbuscntrl_left, modbuscntrl_right))
        except Exception as e:
            self.logger.error(f"Something went wrong trying to rotate the platform: {e}")

    async def rotate_host(self, pitch_value, roll_value):
        try:
            revs = calculate_target_revs(self,pitch_value=pitch_value, roll_value=roll_value)
            positions = clamp_target_revs(revs[0], revs[1], config=self.config)
            left_pos, right_pos = positions
            await self.set_host_position((left_pos, right_pos))
            self.previous_revs = revs
        except Exception as e:
            self.logger.error(f"Something went wrong trying to rotate the platform: {e}")
            
    async def get_telemetry_data(self) -> Union[tuple, bool]:
        """Reads the motors current board tempereature,
        actuator temperature, continuous current and present VBUS voltage
        Returns:
            ((left_board_tmp, right_board_tmp), (left_actuator_tmp, right_actuator_tmp), (left_IC, right_IC), (left_VBUS, right_VBUS))
        """
        vals = await self._read(address=self.config.BOARD_TMP, description="_read board temperature", count=1)
        if not vals:
            return False
        ### 11.5
        left_board_tmp, right_board_tmp = vals
        left_board_tmp = bit_high_low_both(left_board_tmp, 5, "high")
        right_board_tmp = bit_high_low_both(right_board_tmp, 5, "high")

        vals = await self._read(address=self.config.ACTUATOR_TMP, description="_read actuator temperature", count=1)
        if not vals:
            return False
        ### 13.3
        left_actuator_tmp, right_actuator_tmp = vals
        left_actuator_tmp = bit_high_low_both(left_actuator_tmp, 3, "high")
        right_actuator_tmp = bit_high_low_both(right_actuator_tmp, 3, "high")

        vals = await self._read(address=self.config.ICONTINUOUS, description="_read present current ", count=2)
        if not vals:
            return False
        
        left_IC, right_IC = vals
        left_VBUS = registers_convertion(left_IC, "9.23")
        right_VBUS = registers_convertion(right_VBUS, "9.23")

        vals = await self._read(address=self.config.VBUS, description="_read present VBUS voltage ", count=2)
        ### 11.21
        if not vals:
            return False
        left_VBUS, right_VBUS = vals

        ### Extract the high value part and deccimal part 11.21
        left_VBUS = registers_convertion(left_VBUS, "11.21", signed=True)
        right_VBUS = registers_convertion(right_VBUS, "11.21", signed=True)
        
        return ((left_board_tmp, right_board_tmp), (left_actuator_tmp, right_actuator_tmp), (left_IC, right_IC), (left_VBUS, right_VBUS))
    
    async def set_plimit_minus(self, values):
        return await self._write_both(description="set plimit_minus", values=values, address=self.config.PLIMIT_MINUS_REGISTER)
    
    async def set_plimit_plus(self, values):
        return await self._write_both(description="set plimit_plus", values=values, address=self.config.PLIMIT_PLUS_REGISTER)
    
    async def set_plimit_velocity(self, values=[0,0]):
        [decimal, whole] = values
        return await self._write_both(description="set plimit_velocity", values=[decimal,whole], address=self.config.PLIMIT_VELOCITY_REGISTER)
    async def get_oeg_motion(self):
        return await self._read(address=self.config.OEG_MOTION_REGISTER, description="reads oeg motion",count=1,log=True)
