import math
from utils.utils import unnormalize_decimal
from typing import Union

def calculate_motor_modbuscntrl_vals(self, left_revs, right_revs):
        try:
            POS_MIN_REVS = self.config.POS_MIN_REVS
            POS_MAX_REVS = self.config.POS_MAX_REVS
            modbus_percentile_left = (left_revs - POS_MIN_REVS) / (POS_MAX_REVS - POS_MIN_REVS)
            modbus_percentile_right = (right_revs - POS_MIN_REVS) / (POS_MAX_REVS - POS_MIN_REVS)
            modbus_percentile_left = max(0, min(modbus_percentile_left, 1))
            modbus_percentile_right = max(0, min(modbus_percentile_right, 1))

            position_client_left = math.floor(modbus_percentile_left * self.config.MODBUSCTRL_MAX)
            position_client_right = math.floor(modbus_percentile_right * self.config.MODBUSCTRL_MAX)

            return position_client_left, position_client_right
        except Exception as e:
            self.logger.error(f"soemthing went wrong in trying to calculate modbuscntrl vals")
            return False

def get_register_values(data):
    left_data, right_data = data
    left_vals = []
    right_vals = []
    for register in left_data.registers:
        left_vals.append(register)

    for register in right_data.registers:
        right_vals.append(register)
        
    return (left_vals, right_vals)

def clamp_target_revs(left_revs, right_revs, config) -> list[list, list]:
    """Clamps the motors revs within the safety limits (2-147mm)
        Returns:
            list[[left_decimal, left_whole], [right_decimal, right_whole)]]
    """
    ### unnormalize decimal values between 0-65535
    left_decimal, left_whole = math.modf(left_revs) 
    left_whole = int(left_whole)
    left_decimal = min(config.MAX_POS32_DECIMAL, left_decimal) 
    left_pos_low = unnormalize_decimal(left_decimal, 16)

    right_decimal, right_whole = math.modf(right_revs)
    right_whole = int(right_whole)
    right_decimal = min(config.MAX_POS32_DECIMAL, right_decimal)
    right_pos_low = unnormalize_decimal(right_decimal, 16)

    ### Clamp position to a safe range
    ### min 2mm
    if left_whole <= config.MIN_POS_WHOLE: 
            left_pos_low = max(config.MIN_POS_DECIMAL, left_pos_low)
            left_whole = config.MIN_POS_WHOLE
    
    ### min 2mm
    if right_whole <= config.MIN_POS_WHOLE: 
            right_pos_low = max(config.MIN_POS_DECIMAL, right_pos_low)
            right_whole = config.MIN_POS_WHOLE

    #### MAX 147 mm
    if left_whole >= config.MAX_POS_WHOLE:
            left_pos_low = min(config.MAX_POS_DECIMAL, left_pos_low)
            left_whole = config.MAX_POS_WHOLE

    #### MAX 147 mm
    if right_whole >= config.MAX_POS_WHOLE:
            right_pos_low = min(config.MAX_POS_DECIMAL, right_pos_low)
            right_whole = config.MAX_POS_WHOLE

    return [[left_pos_low, left_whole], [right_pos_low, right_whole]]

def calculate_target_revs(self, pitch_value, roll_value) -> Union[list, None]:
    """Calculates the target revolutions and unnormalizes the decimal part
    while respecting the  motors safety limits
    Args:
        pitch_value (float): -8.5-8.5
        roll_value (float): -15.0-15.0
    Returns:
        tuple or None: ((left_pos_low, left_whole), (right_pos_low, right_whole))
        if success, None if something went wrong
    """
    try:
        if abs(pitch_value) >= self.config.MAX_ANGLE_COMBO and abs(roll_value) >= self.config.MAX_ANGLE_COMBO:
             if pitch_value < 0:
                  pitch_value = -self.config.MAX_ANGLE_COMBO
             else:
                  pitch_value = self.config.MAX_ANGLE_COMBO
                  
             if roll_value < 0:
                  roll_value = -self.config.MAX_ANGLE_COMBO
             else:
                roll_value = self.config.MAX_ANGLE_COMBO
        roll_value = max(-17, min(roll_value, 17))
        pitch_value = max(-9, min(pitch_value, 9))
        #final1 & final2
        # VasenServo = 13.7504 + 1.8306*pitch_value - 0.8116*roll_value + 0.0046*math.pow(pitch_value, 2) - 0.0060*pitch_value*roll_value + 0.0009*math.pow(roll_value, 2)
        # OikeaServo = 13.5803 + 1.8614*pitch_value + 0.7981*roll_value + 0.0058*math.pow(pitch_value, 2) + 0.0052*pitch_value*roll_value + 0.0012*math.pow(roll_value, 2)
        # final1 mirrored
        VasenServo = 13.6775 + 1.8464*pitch_value - 0.8026*roll_value + 0.0053*math.pow(pitch_value, 2) - 0.0050*pitch_value*roll_value +  0.0011*math.pow(roll_value, 2)
        OikeaServo = 13.6775 + 1.8464*pitch_value + 0.8026*roll_value + 0.0053*math.pow(pitch_value, 2) + 0.0050*pitch_value*roll_value +  0.0011*math.pow(roll_value, 2)
       
        return VasenServo, OikeaServo
    except Exception as e:
        self.logger.error(f"soemthing went wrong in trying to calculate modbuscntrl vals")
        return None

def validate_dead_bandwidth(self,delta_revs) -> bool:
    """Returns True if delta revs is more than specified dead bandwidth"""
    left_delta_revs, right_delta_revs = delta_revs
    updated_values = [False,False]

    if self.config.DEADBANDREVS < left_delta_revs:
        updated_values[0] = True
    if self.config.DEADBANDREVS < right_delta_revs:
        updated_values[1] = True
    return updated_values

def update_previous_revs(self,shouldbe_updated,revs):
    if shouldbe_updated[0]:
        self.previous_revs[0] = revs[0]
    if shouldbe_updated[1]:
         self.previous_revs[1] = revs[1]

def calc_delta_revs(self, revs):
    left_revs, right_revs = revs
    if not self.previous_revs[0]:  
        left_delta_revs = revs[0]
    else:
        left_delta_revs = abs(left_revs - self.previous_revs[0])

    if not self.previous_revs[1]:  
        right_delta_revs = revs[1]
    else:
        right_delta_revs = abs(right_revs - self.previous_revs[1])
    

    return left_delta_revs, right_delta_revs

def calc_vel_proportional_scale(self, delta_revs, scale_factor=1):
    MAX_VEL = self.config.MAX_VEL 
    MIN_VEL = self.config.MIN_VEL
    left_delta_revs,right_delta_revs = delta_revs

    left_vel = max(MIN_VEL, min(((left_delta_revs / scale_factor) * MAX_VEL), MAX_VEL))
    right_vel = max(MIN_VEL, min(((right_delta_revs / scale_factor) * MAX_VEL), MAX_VEL))
    return left_vel, right_vel

def should_update_vel(self, vels):
    should_update = [False, False]
    left_prev_vel, rigth_prev_vel = self.prev_vels
    left_vel, right_vel = vels

    if not left_prev_vel:
         should_update[0] = True
    elif abs(left_prev_vel-left_vel) > 3:
         should_update[0] = True
    if not rigth_prev_vel:
         should_update[1] = True
    elif abs(rigth_prev_vel-right_vel) > 3:
         should_update[1] = True

    return should_update

def update_vel(should_update):
    update_left, update_right = should_update



    



     