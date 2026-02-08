import math
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

FAULT_RESET_BIT = 15
ENABLE_MAINTAINED_BIT = 1
ALTERNATE_MODE_BIT = 7
CONTINIOUS_CURRENT_BIT = 1
BOARD_TEMPERATURE_BIT = 7
ACTUATOR_TEMPERATURE = 8

UVEL32_RESOLUTION = 1 / (2**24)
UACC32_RESOLUTION = 1 / (2**20)
UCUR16_RESOLUTION = 1 / (2**7)

UCUR16_LOW_MAX = 2**7
UCUR32_DECIMAL_MAX = 2**23
UVOLT32_DECIMAL_MAX = 2**21

def get_entry_point() -> str:
    return Path(sys.argv[0]).resolve()

def convert_val_into_twoscomplenent(target_value, n) -> int:
       """ Expects the target value to be expressed as negative
       if desired to have it in twos complement form """
       if target_value < 0:
        highest_bit = 2**n
        target = target_value+highest_bit
        return target
       else:
              return target_value

def convert_val_into_format(value, format, signed=False):
    """
    Takes in a desired value and register format as
      a param and returns it in the correct form
    """
    formats = format.split(".")
    register_size = 16
    if len(formats) < 2:
        raise ValueError()

    try:
        format1 = abs(int(formats[0]))
        format2 = abs(int(formats[1]))
    except ValueError:
        raise
    
    decimal, whole = math.modf(value) 
    n = format1-1
    whole = int(whole)
    
    ### 1 register
    if format1 <= 16 and format2 <= 16 and format1+format2 == 16:
        if format2 == 0:
            return whole
            
        low_val = unnormalize_decimal(decimal, format2)
        whole_val = whole << format2
        if signed:
               whole = convert_val_into_twoscomplenent(target_value=whole, n=n)

        result = whole_val | low_val
        return result
    ### 2 registers
    elif format1 <= 16 and format2 >= 16 and format1+format2 == 32:
        low_val = unnormalize_decimal(decimal=decimal, max_n=format2)
        format_diff = format2 - register_size 
        whole_val = whole << format_diff
        if signed:
                whole = convert_val_into_twoscomplenent(target_value=whole, n=n)
        high_decimal_part = format2 - register_size
        low_dec_val, high_dec_val = split_nbit_to_decimal_components(value=low_val, high_decimal_part=high_decimal_part)

        return [low_dec_val, whole_val | high_dec_val]
    else:
        raise Exception("Unsupported format")

def format_response(**kwargs):
       """
       Expects possible kwargs of event=event, action=action, message=message
       """
       msg_parts = []
       for key, val in kwargs.items():
              msg_parts.append(f"|{key}={val}|")
        
       return "".join(msg_parts)

def registers_convertion(registers,format,signed=False, scale=1):
        formats = format.split(".")
        
        if len(formats) < 2:
                raise(ValueError)
        
        format_1, format_2 = formats
        try:
                format_1 = int(format_1)
                format_2 = int(format_2)
        except ValueError:
                raise
        format1_n = format_1-1
        register_size = 16
        if len(registers) == 1 and format_1 + format_2 == 16: # Single register Example 9.7
                # Seperates single register by format
                register_high, register_low = bit_high_low_both(registers[0], format_2)
                # Normalizes decimal between 0-1
                register_low_normalized = general_normalize_decimal(register_low, format_2)
                # If signed checks whether if its two complement
                if signed: 
                        register_high = get_twos_complement(format_1 - 1, register_high)
                return (register_high + register_low_normalized) * scale
        else: # Two registers
                # Checks what's the format. Examples: 16.16, 8.24, 12.20
                decimal_lower_register = registers[0]
                shared_register = registers[1]
                if format_1 <= 16 and format_2 >= 16 and format_1 + format_2 == 32: 
                        # Format difference for seperating "shared" register
                        upper_decimal_format = register_size - format_1 
                        # Seperates "shared" register
                        integer_part, decimal_higher_bits = bit_high_low_both(shared_register, upper_decimal_format)
                        # Combines decimal values into a single binary
                        decimal_combined = combine_bits(decimal_higher_bits,decimal_lower_register)
                        # Normalizes decimal between 0-1
                        register_low_normalized = general_normalize_decimal(decimal_combined, format_2)
                        # If signed checks whether if its two complement
                        if signed: 
                                integer_part = get_twos_complement(format1_n, integer_part)
                        return (integer_part + register_low_normalized) * scale
                else: # Examples: 32.0 20.12 30.2
                        # Format difference for seperating "shared" register
                        decimal_format = 32 - format_1
                        # Seperates "shared" register
                        register_val_high, register_val_low = bit_high_low_both(registers[0], decimal_format)
                        # Combines integer values into a single binary
                        register_val_high = combine_bits(registers[1],register_val_high)
                        # Normalizes decimal between 0-1
                        register_low_normalized = general_normalize_decimal(register_val_low, format_2)
                        # If signed checks whether if its two complement
                        if signed:
                                register_val_high = get_twos_complement(format1_n, register_val_high)
                        return (register_val_high + register_low_normalized) * scale

def combine_bits(high_bit_part, low_bit_part):
        return (high_bit_part << 16) | low_bit_part

def general_normalize_decimal(value, max_n):
        return value / 2**max_n

def unnormalize_decimal(decimal, max_n):
        return abs(int(decimal * 2**max_n))

def convert_to_revs(pfeedback):
    decimal = pfeedback[0] / 65536
    num = pfeedback[1]
    return num + decimal

def extract_part(part, message):
    start_idx = message.find(part)
    if start_idx == -1:
        return False
    
    start_idx += len(part)
    pipe_idx = message.find("|", start_idx)
    if pipe_idx == -1:
        return False
    
    return  message[start_idx:pipe_idx]

def is_nth_bit_on(n, number):
            mask = 1 << n
            return (number & mask) != 0

# Only allows the needed bits
def IEG_MODE_bitmask_default(number):
        mask = (1 << FAULT_RESET_BIT) | (1 << ENABLE_MAINTAINED_BIT)
        number = number & 0xFFFF
        return number & mask

# Only allows the needed bits
def is_fault_critical(number):
        mask = (1 << CONTINIOUS_CURRENT_BIT) | (1 << BOARD_TEMPERATURE_BIT) | (1 << ACTUATOR_TEMPERATURE)
        number = number & 0xFFFF
        return (number & mask) != 0

def IEG_MODE_bitmask_alternative(number):
        mask = (1 << FAULT_RESET_BIT) | (1 << ALTERNATE_MODE_BIT) |(1 << ENABLE_MAINTAINED_BIT) 
        number = number & 0xFFFF
        return number & mask

def IEG_MODE_bitmask_enable(number):
        mask = (1 << ENABLE_MAINTAINED_BIT)
        number = number & 0xFFFF
        return number & mask

def split_nbit_to_decimal_components(value, high_decimal_part, low_decimal_part=16):
       """Takes in low registers decimal count and high registers decimal count
         and the combined value and splits it to all the different parts"""
       low_mask = (2**low_decimal_part)-1
       high_mask = (2**high_decimal_part) - 1
       low_value = value & low_mask
       high_value = (value >> low_decimal_part) & high_mask
       return low_value, high_value

def get_twos_complement(bit, value):
       """Bit tells how manieth bit 2^n"""
       is_highest_bit_on = value & 1 << bit

       if is_highest_bit_on:
                base = 2**bit
                if bit == 0:
                        return -1
                lower_mask = (2**bit) -1
                lower = value & lower_mask
                return (lower - base)
                
       return value

def convert_vel_rpm_revs(rpm):
        """
        Takes in velocity rpm and converts it into revs 
        return tuple with higher register value first
        8.24 format
        """
        rpm = abs(rpm)
        try:
                rpm = int(rpm)
        except ValueError:
                raise
        if rpm > 600:
                rpm = 600
        
        revs = rpm/60.0
        return convert_val_into_format(revs, format="8.24")

def convert_acc_rpm_revs(rpm):
        """
        Takes in acceleration rpm and converts it into revs 
        return tuple with higher register value first
        12.20 format
        """
        rpm = abs(rpm)
        try:
                rpm = int(rpm)
        except ValueError:
                raise
        
        if rpm > 1500:
                rpm = 1500
        
        revs = rpm/60.0
        return convert_val_into_format(revs, "12.20")

def get_current_path(file):
        return Path(file).parent

def bit_high_low_both(number, low_bit, output="both"):
        low_mask = (2**low_bit) - 1
        register_val_high = number >> low_bit
        register_val_low = number & low_mask
        if output=="both":
                return (register_val_high, register_val_low)
        elif output == "high":
                return register_val_high
        elif output == "low":   
                return register_val_low
        else:
                raise Exception
        

def setup_logger(logger):
        """
        Setup logger for the MotorApi class.
        If no logger is provided, creates a basic console logger.
        """
        if logger is not None:
                return logger

        # Create a new logger
        logger = logging.getLogger(f"{__name__}")
        logger.setLevel(logging.INFO)

        # Avoid adding multiple handlers if logger already exists
        if not logger.handlers:
                # Create console handler
                console_handler = logging.StreamHandler()
                console_handler.setLevel(logging.INFO)
                
                # Create formatter
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                console_handler.setFormatter(formatter)
                
                # Add handler to logger
                logger.addHandler(console_handler)

        return logger

def setup_logging(filename="ExcavatorAPI.log",logging_level="INFO", log_to_file=True, process_name="main"):
    if not ".log" in filename: filename+=".log"
    parent_log_dir =  get_entry_point().parent.parent / "logs"
    parent_log_dir.mkdir(parents=True, exist_ok=True)
    
    # config root logger
    logger = logging.getLogger(f"{process_name}{__name__}")
    level = getattr(logging, logging_level.upper(), logging.WARNING)
    logger.setLevel(level)    

    if logger.handlers: # only setup if not already
        return logger
    else:
        # Set up file handler
        log_file = Path(parent_log_dir) / filename
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=1024*1024,
            backupCount=1,
            encoding='utf-8'
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(formatter)
        #setup console
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        if log_to_file:
            logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        return logger

from dataclasses import dataclass
@dataclass
class RenderViewInfo:
    view: str
    render_count: int
    render_time: float
    header: str = ""
    body: str = ""

class ExcavatorAPIProperties:
    """
    ExcavatorAPI configuration constants.
    
    CRITICAL: MIN_RATE and SHUTDOWN_GRACE_PERIOD are tightly coupled.
    - MIN_RATE defines the maximum socket timeout (in seconds, inverted as rate)
    - SHUTDOWN_GRACE_PERIOD must be > (1 / MIN_RATE) to guarantee no hanging threads
    
    Example: If MIN_RATE = 0.1 (10s max join time), SHUTDOWN_GRACE_PERIOD must be > 10s.
    If you change one, you MUST update the other.
    """
    GYRO_RANGES = [250, 500, 1000, 2000]
    ACCEL_RANGES = [2, 4, 8, 16]
    TRACKING_RATE_MIN = 1
    TRACKING_RATE_MAX = 300
    DATA_RATES = [104, 208, 416, 833, 1666, 3333, 6666]
    
    OPERATIONS={
        "none": 0,
        "mirroring": 1,
        "driving": 2,
        "driving_and_mirroring": 3
    }
    OPERATIONS_REVERSE={v:k for k,v in OPERATIONS.items()}
        # This is used to validate for maximum sleep times when closing down threads with join. Without this threads might be left hanging in the background unwantedly after clearing the stop_event in the clean up functions.
    MAX_NETWORK_TIMEOUT=5 # used by udpsocket
    MIN_RATE=0.1 # 10 seconds -> 1 / 0.1 = 10s
    MAX_RATE=300
    SHUTDOWN_GRACE_PERIOD=11 # NOTE: assumes MIN_RATE is 0.1
    
    # SCreen
    RENDERTIME_MIN=0.1
    RENDERTIME_MAX=1000
    FONTSIZE_MIN=1
    FONTSIZE_MAX=30
    
    # Pump schema
    PUMP_SCHEMA = {
        "output_channel": [int, {"min": 1, "max": 15}],
        "pulse_min": [int,{"min": 0,"max": 4095}],
        "pulse_max": [int,{"min": 0,"max": 4095}],
        "idle": [float, {"min": -1,"max": 0.6 }],
        "multiplier": [float, {"min": 0.0 ,"max": 1.0}],
    }
    
    CHANNEL_CONFIG_SCEMA={
        "output_channel": [int, {"min": 1,"max": 15}],
        "pulse_min": [int, {"min": 0,"max": 4095}],
        "pulse_max": [int, {"min": 0,"max": 4095}],
        "direction": [int, {"min": -1,"max": 1}],
        "center": [float],
        "deadzone": [float, {"min": 0,"max": 1000}],
        "affects_pump": [bool],
        "toggleable": [bool],
        "deadband_us_pos": [float, {"min": 0,"max": 4095}],
        "deadband_us_neg": [float, {"min": 0,"max": 4095}],
        "dither_enable": [bool],
        "dither_amp_us": [float, {"min": 0,"max": 4095}],
        "dither_hz": [float, {"min": 0,"max": 200.0}],
        "ramp_enable": [bool],
        "ramp_limit": [float, {"min": 0,"max": 10000}],
        "gamma": [float, {"min": 0.0,"max": 5.0}],
    }