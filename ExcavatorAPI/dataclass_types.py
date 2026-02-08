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
    ORIENTATION_SEND_MAX_RATE=150
    COMMAND_RECEIVE_MAX_RATE=25
    
    # SCreen
    RENDERTIME_MIN=0.1
    RENDERTIME_MAX=1000
    FONTSIZE_MIN=1
    FONTSIZE_MAX=30
    
    # Pump schema
    PUMP_SCHEMA = {''
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
        "deadzone": [float, {"min": 0.0,"max": 100.0}],
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