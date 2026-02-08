import board
import threading
from adafruit_lsm6ds.lsm6ds3 import LSM6DS3
from adafruit_lsm6ds import AccelRange, Rate, GyroRange
from smbus2 import SMBus
from time import perf_counter, sleep
from math import degrees
import imufusion
import numpy as np
from pathlib import Path
import yaml
from dataclass_types import ExcavatorAPIProperties
from utils import setup_logging

# NOTE: ExcavatorAPI is responsible for cleaning up with
# cleanup_callback on unexpected thread crashes
class OrientationTracker:
    default_address=0x6A
    addresses = [0x6A, 0x6B]
    CTRL8_XL_ADDRESS = 0x17
    default_data_rate = 104
    default_accel_range = 2
    default_gyro_range = 250
    accel_formats = ["m/s","g"] # m/s^2/gravity
    gyro_formats = ["r", "dps"] # radians/degreesPerSecond
    orientation_formats=["r","d","q"] # radians/degrees/quaternions
    CONFIG_FILE_NAME = "orientation_tracker_config.yaml"
    
    def __init__(self, cleanup_callback=None, address=0x6A, orientation_tracking_enabled=True, orientation_format="d", reporting_enabled=False, reporting_interval=1, accel_format="g", gyro_format="dps", perf_tracking_enabled=False):
        self.logger = setup_logging()
        self.config = OrientationTracker.load_config(logger=self.logger)
        self.running = False
        self.cleanup_callback = cleanup_callback
        
        # Can't be initialied here for some reason
        self.data_rates = None
        self.accel_ranges = None
        self.gyro_ranges = None
        
        # Parameters
        self.address = address
        self.orientation_tracking_enabled = orientation_tracking_enabled
        self.reporting_enabled = reporting_enabled
        self.reporting_interval = reporting_interval
        self.accel_format = accel_format
        self.gyro_format = gyro_format
        self.perf_tracking_enabled = perf_tracking_enabled
        self.orientation_format = orientation_format
        self._validate_parameters()
        
        # Threading
        self._stop_event = threading.Event()
        self.orientation_thread = None
        self.reporting_thread = None
        self.last_orientation = np.zeros(3)
        self.last_update = 0
        # For simple lpf
        self._prev_gyro = np.zeros(3)
        self._prev_accel = np.zeros(3)
        
        # Performance tracking 
        self.perf_n = 0
        self.perf_mean = 0.0
        self.perf_m2 = 0.0
        self.perf_min = float("inf")
        self.perf_max = float("-inf")
        self.perf_prev_timestamp = None
        
        # Stats
        self.read_count = 0
        self.read_miss_target_time_count = 0
        
        self._init_sensor(address)
    
    def start(self):
        if self.running: return
        if self.reporting_enabled:
            self._start_reporting()
        
        if self.orientation_tracking_enabled:
            self._start_orientation_tracking()
        
        self.running = True
        self.logger.info("OrientationTracker service has been started")
        return True
    
    def _validate_parameters(self):
        errors = []
        
        if self.address not in OrientationTracker.addresses:
            errors.append(f"Sensor address needs to be one of these: {','.join(map(str,OrientationTracker.addresses))}")
        if self.accel_format not in OrientationTracker.accel_formats:
            errors.append("accel_format needs to be either m/s or g")
        if self.gyro_format not in OrientationTracker.gyro_formats:
            errors.append("gyro_format needs to be either dps or r")
        if self.orientation_format not in OrientationTracker.orientation_formats:
            errors.append("orientation_format needs to be either r,d or q")
        
        if errors:
            raise Exception("\n".join(errors))
    
    def _set_address(self, address):
        if address in OrientationTracker.addresses:
            self.address = address
        else: #default 
            self.logger.warning(f"Address: {address} invalid. Setting it to the default {OrientationTracker.default_address} address")
            self.address = OrientationTracker.default_address
    
    def _init_sensor(self, address):
        i2c = board.I2C()
        self._set_address(address)
        self.sensor = LSM6DS3(i2c, address=self.address)
        
        # These have to be set after inititalizing the sensor object for some reason
        self.gyro_ranges ={
            250: GyroRange.RANGE_250_DPS,
            500: GyroRange.RANGE_500_DPS,
            1000: GyroRange.RANGE_1000_DPS,
            2000: GyroRange.RANGE_2000_DPS
        }
        self.accel_ranges ={
            2: AccelRange.RANGE_2G,
            4: AccelRange.RANGE_4G,
            8: AccelRange.RANGE_8G,
            16: AccelRange.RANGE_16G
        }
        self.data_rates={
            104:  Rate.RATE_104_HZ,
            208:  Rate.RATE_208_HZ,
            416:  Rate.RATE_416_HZ,
            833: Rate.RATE_833_HZ,
            1666: Rate.RATE_1_66K_HZ,
            3333: Rate.RATE_3_33K_HZ,
            6666:  Rate.RATE_6_66K_HZ
        }
        
        self.bus = SMBus(1)
        
        # data rates
        self.set_accel_data_rate(self.config["accel_data_rate"])
        self.set_gyro_data_rate(self.config["gyro_data_rate"])
        # set data ranges
        self.set_accel_range(self.config["accel_range"])
        self.set_gyro_range(self.config["gyro_range"])
        
        # This is necessery because adafruit does not provide API 
        # to enable lpf2
        if self.config["enable_simple_lpf"]:
            self.bus.write_byte_data(self.address, OrientationTracker.CTRL8_XL_ADDRESS, 128) 
    
    def read_gyro(self): # default - radians/s
        gyro = np.array(self.sensor.gyro)
        if self.gyro_format == "dps":
            gyro = np.degrees(gyro)
        return gyro
    
    def read_accel(self): # default - m/s^2
        accel = np.array(self.sensor.acceleration)
        if self.accel_format == "g":
            accel = accel / 9.81
        return accel
    
    def set_gyro_data_rate(self, rate):
        if rate in self.data_rates: 
            self.sensor.gyro_data_rate = self.data_rates[rate]
            self.config["gyro_data_rate"] = rate
            self.logger.info(f"Sensors gyro data rate has been set to: {rate} Hz")
        else: #default
            self.logger.warning(f"Invalid gyro data rate using default rate: {OrientationTracker.default_data_rate} Hz")
            self.config["gyro_data_rate"] = OrientationTracker.default_data_rate
            self.sensor.gyro_data_rate = self.data_rates[OrientationTracker.default_data_rate]
            
    def set_accel_data_rate(self, rate):
        if rate in self.data_rates: 
            self.sensor.accelerometer_data_rate = self.data_rates[rate]
            self.config["accel_data_rate"] = rate
            self.logger.info(f"Sensors acceleration data rate has been set to: {rate} Hz")
        else: #default
            self.logger.warning(f"Invalid accel data rate using default rate: {OrientationTracker.default_data_rate} Hz")
            self.config["accel_data_rate"] = OrientationTracker.default_data_rate
            self.sensor.accelerometer_data_rate = self.data_rates[OrientationTracker.default_data_rate]
            
    def set_gyro_range(self, gyro_range):
        if gyro_range in self.gyro_ranges: 
            self.sensor.gyro_range = self.gyro_ranges[gyro_range]
            self.config["gyro_range"] = gyro_range
            self.logger.info(f"Sensors gyroscopes dps range has been set to: {gyro_range} DPS")
        else: #default
            self.logger.warning(f"Invalid gyro range using default range: {OrientationTracker.default_gyro_range} DPS")
            self.config["gyro_range"] = OrientationTracker.default_gyro_range
            self.sensor.gyro_range = self.gyro_ranges[OrientationTracker.default_gyro_range]
            
    def set_accel_range(self, accel_range):
        if accel_range in self.accel_ranges: 
            self.sensor.accelerometer_range = self.accel_ranges[accel_range]
            self.config["accel_range"] = accel_range
            self.logger.info(f"Sensors accelerometer g range has been set to: {accel_range} G")
        else: #default
            self.logger.warning(f"Invalid accel range using default range: {OrientationTracker.default_accel_range} G")
            self.config["accel_range"] = OrientationTracker.default_accel_range
            self.sensor.accelerometer_range = self.accel_ranges[OrientationTracker.default_accel_range]
    
    def is_lpf2_enabled(self):
        if (self.bus.read_byte_data(self.address, OrientationTracker.CTRL8_XL_ADDRESS) & 0x80) != 0:
            return "Yes"
        return "No"
    
    def disable_lpf2(self):
        self.bus.write_byte_data(self.address, OrientationTracker.CTRL8_XL_ADDRESS, 0)
        self.config["enable_lpf2"]=False
        self.logger.info("Sensors LPF2 filter has been disabled")
    
    def enable_lpf2(self):
        self.bus.write_byte_data(self.address, OrientationTracker.CTRL8_XL_ADDRESS, 128)
        self.config["enable_lpf2"] =True
        self.logger.info("Sensors LPF2 filter has been enabled")
    
    def enable_simple_lpf(self):
        if not self.config["enable_simple_lpf"]:
            self.config["enable_simple_lpf"] = True
            self.logger.info("Simple lpf has been enabled")
            
    def disable_simple_lpf(self):
        if self.config["enable_simple_lpf"]:
            self.config["enable_simple_lpf"] = False
            self.logger.info("Simple lpf has been disabled")
            
    def set_alpha(self, alpha):
        if not (0 < alpha < 1):
            raise ValueError("Alpha must be between 0-1")
        self.config["alpha"] = alpha
        self.logger.info(f"Simple LPF's alpha has been set to: {alpha}")
    
    def set_tracking_rate(self, rate):
        if not (ExcavatorAPIProperties.TRACKING_RATE_MIN <= rate <= ExcavatorAPIProperties.TRACKING_RATE_MAX):
            raise RuntimeError("Orientation tracking rate must be between 0-300")
        self.config["tracking_rate"] = rate
        self.logger.info(f"Orientation tracking rate has been set to: {rate} hz")
    
    def _start_reporting(self):
        self.reporting_thread = threading.Thread(
            target=self._reporting_loop,
            daemon=True
        )
        self.reporting_thread.start()

    def _reporting_loop(self):
        self.logger.info("Starting status reporting loop")
        try:
            while not self._stop_event.is_set():
                self.report_status()
                sleep(self.reporting_interval)
        except Exception as e:
            self.logger.error(f"Reporting loop thread crashed: {e}")
    
    def _start_orientation_tracking(self):
        self.orientation_thread = threading.Thread(
            target=self._orientation_tracking_loop,
            daemon=True
        )
        self.orientation_thread.start()

    def _orientation_tracking_loop(self):
        self.logger.info("Orientation tracking loop has started")
        # Warn if formats don't match imufusion's requirements
        if self.gyro_format != "dps":
            self.logger.warning(f"imufusion requires gyro in degrees/s, but gyro_format is '{self.gyro_format}'. Results may be incorrect.")
        if self.accel_format != "g":
            self.logger.warning(f"imufusion requires accel in g, but accel_format is '{self.accel_format}'. Results may be incorrect.")
        self.last_update = perf_counter()
        self.perf_prev_timestamp = perf_counter()
        ahrs = imufusion.Ahrs()
        now = perf_counter()
        
        while not self._stop_event.is_set():
            try: # Iteration duration calculated each time because it allows client to change it later
                iteration_duration=1/self.config["tracking_rate"]
                desired_next = perf_counter() + iteration_duration
                
                gyro = self.read_gyro()
                accel = self.read_accel()
                
                if self.config["enable_simple_lpf"]: # Apply simple lpf
                    gyro = (1-self.config["alpha"])*self._prev_gyro+(self.config["alpha"]*gyro)
                    accel = (1-self.config["alpha"])*self._prev_accel+(self.config["alpha"]*accel)
                    self._prev_accel=accel
                    self._prev_gyro=gyro
                
                dt = perf_counter() - self.last_update
                
                ahrs.update_no_magnetometer(gyro, accel, dt)
                self.last_update = perf_counter()
                
                if self.orientation_format == "d":
                    self.last_orientation = ahrs.quaternion.to_euler()
                elif self.orientation_format == "q":
                    self.last_orientation = np.array([ahrs.quaternion.w, ahrs.quaternion.x, ahrs.quaternion.y, ahrs.quaternion.z])
                elif self.orientation_format == "r":
                    self.last_orientation = np.radians(ahrs.quaternion.to_euler())
                else:
                    raise Exception("invalid orientation format")
                
                self.read_count += 1
                
                # reset counters
                if self.read_count % 65535 == 0 and self.read_count > 0:
                    self.read_count = 0
                    self.read_miss_target_time_count = 0
                
                if self.perf_tracking_enabled:
                    now = perf_counter()
                    interval = (now - self.perf_prev_timestamp) * 1000
                    self.perf_n += 1
                    delta = interval - self.perf_mean
                    self.perf_mean += delta / self.perf_n
                    self.perf_m2 += delta * (interval - self.perf_mean)
                    self.perf_max = max(interval, self.perf_max)
                    self.perf_min = min(interval, self.perf_min)
                    self.perf_prev_timestamp = now
                
                sleep_time = desired_next - perf_counter()
                if sleep_time > 0:
                    sleep(sleep_time)
                else:
                    self.read_miss_target_time_count += 1
            except Exception as e:
                self.logger.error(f"Sensor read error: {e}")
                if self.cleanup_callback:
                    self.cleanup_callback()
                
        self.logger.info("Orientation tracking loop exited")
 
    def get_status(self):
        cur_or=""
        orientation=self.get_orientation()
        for axis in orientation:
            cur_or+=f"{axis:.2f}° "
        read_target_time_miss_rate=0
        if self.read_miss_target_time_count > 0 and self.read_count > 0:
            read_target_time_miss_rate=self.read_miss_target_time_count / self.read_count
            
        return {
            "read_target_time_miss_rate": f"{read_target_time_miss_rate:.2f}%",
            "current_orientation": cur_or
        }
 
    def get_orientation(self):
        return self.last_orientation
 
    def report_status(self):
        missing_target_time = (self.read_miss_target_time_count/self.read_count) if self.read_count != 0 else 0
        self.logger.info(f"Current orientation: x: {self.last_orientation[0]:.2f}° y: {self.last_orientation[1]:.2f}° z: {self.last_orientation[2]:.2f}°")
        self.logger.info(f"Read count: {self.read_count}")
        self.logger.info(f"Read target miss count: {self.read_miss_target_time_count}")
        self.logger.info(f"Missing target time: {missing_target_time*100:.2f}%")
        
        if self.perf_tracking_enabled:
            if self.perf_n > 1: 
                variance = self.perf_m2 / (self.perf_n - 1) 
                std_dev = variance ** 0.5
                self.logger.info(f"Reading delay std dev: {std_dev} ms")
                self.logger.info(f"Reading delay min: {self.perf_min} ms")
                self.logger.info(f"Reading delay max: {self.perf_max} ms")
                self.logger.info(f"Reading delay mean: {self.perf_mean} ms")
    
    def shutdown(self):
        self._stop_event.set()
        calling_thread=threading.current_thread()
        if self.orientation_thread and self.orientation_thread.is_alive():
            if self.orientation_thread !=calling_thread:
                self.orientation_thread.join(timeout=1.0)
        self.logger.info("Orientation tracking thread shutdown")
    
        if self.reporting_thread and self.reporting_thread.is_alive():
            if self.reporting_thread != calling_thread:
                self.reporting_thread.join(timeout=1.0)
        self.logger.info("OrientationTrackers status reporting thread shutdown")
        self.running = False
        self.logger.info("OrientationTracker service has been shutdown")
        return True

    def update_state(self):
        # Updates all the states that are not automatically updated
        if self.config["enable_lpf2"]:
            self.enable_lpf2()
        else:
            self.disable_lpf2()

    def reload_config(self):
        self.config = OrientationTracker.load_config(logger=self.logger)
        self.logger.info("OrientationTracker config has been reloaded")
        self.update_state()

    @staticmethod
    def load_config(logger=None): # NOTE: script will have to be ran as root so home path is hardcoded for now
        config_path = Path("/home") / "savonia" / "excavator" / "config" / OrientationTracker.CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{OrientationTracker.CONFIG_FILE_NAME}' not found")
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
    
        parsed_config = OrientationTracker._parse_config(raw_config)
        OrientationTracker.validate_config(parsed_config)
        if logger:
            logger.info(f"OrientationTrackers config has been validated and loaded: {parsed_config}")
        return parsed_config
    
    @staticmethod
    def _parse_config(cfg):
        config = {
            "gyro_data_rate": int(cfg['gyro_data_rate']),
            "accel_data_rate": int(cfg['accel_data_rate']),
            "gyro_range": int(cfg['gyro_range']),
            "accel_range": int(cfg['accel_range']),
            "tracking_rate": int(cfg['tracking_rate']),
            "enable_simple_lpf": cfg['enable_simple_lpf'],
            "enable_lpf2": cfg['enable_lpf2'],
            "alpha": float(cfg['alpha'])
        }
        return config

    @staticmethod
    def validate_config(parsed_config):
        errors = []
        
        if parsed_config["gyro_data_rate"] not in ExcavatorAPIProperties.DATA_RATES:
            errors.append(f"validate_config: Gyro data rate: {parsed_config['gyro_data_rate']} is not valid. Valid rates: {', '.join(map(str, ExcavatorAPIProperties.DATA_RATES))}")
        if parsed_config["accel_data_rate"] not in ExcavatorAPIProperties.DATA_RATES:
            errors.append(f"validate_config: accel_data_rate: {parsed_config['accel_data_rate']} is not valid. Valid rates: {', '.join(map(str, ExcavatorAPIProperties.DATA_RATES))}")
        
        if parsed_config["gyro_range"] not in ExcavatorAPIProperties.GYRO_RANGES:
            errors.append(f"validate_config: Gyro range: {parsed_config['gyro_range']} is not valid. Valid gyro ranges: {', '.join(map(str, ExcavatorAPIProperties.GYRO_RANGES))}")
        if parsed_config["accel_range"] not in ExcavatorAPIProperties.ACCEL_RANGES:
            errors.append(f"validate_config: accel_range: {parsed_config['accel_range']} is not valid. Valid accel_ranges: {', '.join(map(str, ExcavatorAPIProperties.ACCEL_RANGES))}")
        
        if not (ExcavatorAPIProperties.TRACKING_RATE_MIN <= parsed_config["tracking_rate"] <= ExcavatorAPIProperties.TRACKING_RATE_MAX):
            errors.append(f"validate_config: Tracking rate is not valid, must be between values: {ExcavatorAPIProperties.TRACKING_RATE_MIN}-{ExcavatorAPIProperties.TRACKING_RATE_MAX}.")
        if not (0 < parsed_config["alpha"] < 1):
            errors.append(f"validate_config:  Alpha must be between 0-1")
        if not isinstance(parsed_config["enable_simple_lpf"], bool):
            errors.append(f"validate_config: enable_simple_lpf must be a boolean")
        if not isinstance(parsed_config["enable_lpf2"], bool):
            errors.append(f"validate_config: enable_lpf2 must be a boolean")

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(errors))
        
    @staticmethod
    def update_config(config):
        config_path = Path("/home") / "savonia" / "excavator" / "config" / OrientationTracker.CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{OrientationTracker.CONFIG_FILE_NAME}' not found")
        
        with open(config_path, 'w') as f:
            yaml.safe_dump(config, f,default_flow_style=False)
            
# example usage     
# if __name__ == "__main__":
#     try:
#         orientation_tracker = OrientationTracker()
#         orientation_tracker.start()
#         sleep(3600)
#     except KeyboardInterrupt:
#         print("received a stop signal shutting down...")