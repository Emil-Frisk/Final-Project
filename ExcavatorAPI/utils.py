import logging
import psutil
import logging
from pathlib import Path
import math
import sys
from logging.handlers import RotatingFileHandler

def get_entry_point() -> str:
    return Path(sys.argv[0]).resolve().parent

def setup_logging(filename="ExcavatorAPI.log", logging_level="INFO", log_to_file=True, process_name="excavator"):
    if not ".log" in filename: 
        filename += ".log"
    
    parent_log_dir = get_entry_point() / "logs"
    parent_log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a unique logger name per process
    logger_name = __name__
    if process_name:
        logger_name = f"{__name__}.{process_name}"
    
    logger = logging.getLogger(logger_name)
    
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
    
def get_cpu_temperature():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp_str = f.read().strip()
            temp = float(temp_str) / 1000.0  # Convert from millidegree Celsius to Celsius
            return temp
    except IOError:
        return None

def get_cpu_core_usage(interval=1):
    cpu_percent = psutil.cpu_percent(interval=interval, percpu=False)
    return cpu_percent

def serialize_with_inf_handling(obj):
    if isinstance(obj, float) and math.isinf(obj):
        return None  # or "Infinity" or a large number like 999999
    return obj