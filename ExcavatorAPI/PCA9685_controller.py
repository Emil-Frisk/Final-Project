"""
Valve testing PWM controller with:
- Derived PWM period from actual PCA9685 frequency
- Simple deadband: compresses command range to skip dead zone (linear throughout!)
- Optional dither (per-channel) to prevent valve stiction
- Optional per-channel ramp/slew limiting to smooth step inputs

Maintains linearity by packing commands into the working range around the dead zone.
"""

import atexit
import threading
import time
from time import sleep
from math import sin
import logging
import yaml
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Any
from pathlib import Path
from adafruit_pca9685 import PCA9685
import board 
import busio 
import os
import psutil
import multiprocessing
from utils import setup_logging


# ============================================================================
# Configuration Data Classes
# ============================================================================

@dataclass
class ChannelConfig:
    """Configuration for a single PWM channel."""
    output_channel: int
    pulse_min: int
    pulse_max: int
    direction: int  # +1 or -1; maps sign of input to physical pulse side
    center: Optional[float] = None
    deadzone: float = 0.0  # percent of full-scale input mapped to zero (rarely used here)
    affects_pump: bool = False
    toggleable: bool = False

    # Simple deadband (separate per sign) - jumps over dead zone by compressing command range
    # Offsets from center (us) where the working range starts for positive/negative inputs
    deadband_us_pos: float = 0.0
    deadband_us_neg: float = 0.0

    # Dither settings to prevent valve stiction - DISABLED by default
    dither_enable: bool = False
    dither_amp_us: float = 8.0  # vibration amplitude in microseconds
    dither_hz: float = 40.0  # vibration frequency

    # Slew rate limiting (microseconds per second) to soften command steps
    ramp_enable: bool = False
    ramp_limit: float = 0.0  # us/s; ignored when ramp_enable is False

    # Symmetric gamma shaping (1.0 = linear). Applied to magnitude for both directions.
    gamma: float = 1.0

    def __post_init__(self):
        self.pulse_range = self.pulse_max - self.pulse_min
        if self.center is None:
            self.center = self.pulse_min + (self.pulse_range / 2)
        self.deadzone_threshold = self.deadzone / 100.0
        
    def __getitem__(self,key):
        return getattr(self,key)

@dataclass
class PumpConfig:
    """Configuration specific to pump control (not typically used in valve_testing)."""
    output_channel: int
    pulse_min: int
    pulse_max: int
    idle: float
    multiplier: float
    # Manual pump via input channel removed in testing controller.
    
    def __getitem__(self,key):
        return getattr(self,key)
    
class PWMConstants:
    """Hardware and timing constants."""
    PWM_FREQUENCY_DEFAULT = 50  # 50 Hz, standard RC pulse rate
    MAX_CHANNELS = 16
    DUTY_CYCLE_MAX = 65535

    # Validation limits
    PULSE_MIN = 0
    PULSE_MAX = 4095
    PUMP_IDLE_MIN = -1.0
    PUMP_IDLE_MAX = 0.6
    PUMP_MULTIPLIER_MAX = 1.0

    # Safety parameters
    DEFAULT_TIME_WINDOW = 5  # seconds
    SAFE_STATE_THRESHOLD = 0.25

def format_watchdog_msg(msg):
    return f"[WATCHDOG] {msg}"

def _watchdog_loop(main_pid, pwm_heartbeat, watchdog_heartbeat, shutdown_queue, pwm_timeout):
    """Monitors the main process for possible deadlocks and
    sets the PWM to a safe state if heartbeat timesout"""
    # Use different log file because different process
    logger = setup_logging("watchdog.log", process_name="watchdog")
    
    timeout = pwm_timeout
    last_heartbeat = time.time()
    watchdog_heartbeat.put(os.getpid())
    logger.info(format_watchdog_msg(f"Watchdog started monitoring main process with pid: {main_pid}"))
    logger.debug(f"[WATCHDOG] PWM_HEARTBEAT_QUEUE: {pwm_heartbeat}")
    logger.debug(f"[WATCHDOG] WATCHDOG_HEARTHBEAT_QUEUE: {watchdog_heartbeat}")
    logger.debug(f"[WATCHDOG] WATCHDOG_SHUTDOWN_QUEUE: {shutdown_queue}")
    logger.debug(f"[WATCHDOG] PWM_TIMEOUT: {pwm_timeout}")
    sleep_time=timeout/2
    while True:
        try:
            if not shutdown_queue.empty():
                logger.info(format_watchdog_msg("Watchdog received shutdown signal"))
                break
            if not psutil.pid_exists(main_pid):
                raise Exception(format_watchdog_msg("Main process has died"))
            if not pwm_heartbeat.empty():
                pwm_heartbeat.get()
                last_heartbeat = time.time()
            if watchdog_heartbeat.empty():
                watchdog_heartbeat.put(0)
            if time.time() - last_heartbeat > timeout:
                raise Exception("No PWM heartbeat")
            time.sleep(sleep_time)
        except Exception as e:
            logger.error(format_watchdog_msg(f"exception: {e}"))
            try: 

                # Try to kill the main process because
                # we don't want it hogging any i2c resources
                # Because we want to maximize succes on
                # reseting the PWM state
                os.kill(main_pid, 9) 
                logger.info(format_watchdog_msg(f"Killed main process because of {e}"))
                time.sleep(0.3) # give kernel time to release
            except ProcessLookupError:
                logger.info(format_watchdog_msg(f"Main process already dead"))

            try_count=0
            retries=3
            for _ in range(retries):
                try:
                    pwm_controller = PWMController(
                    pump_variable=False,
                    toggle_channels=False,
                    input_rate_threshold=0,
                    default_unset_to_zero=True,
                    emergency_reset=True
                    )
                    try_count+=1
                    if pwm_controller.is_safe_state: # Failed
                        logger.warning(format_watchdog_msg(f"Watchdog failed to reset pwm controller: {try_count}/{retries}"))
                        continue
                    
                    logger.info(format_watchdog_msg("Watchdog successfully reseted PWM controller"))
                    break
                except Exception as e:
                    logger.error(format_watchdog_msg(f"Watchdog failed to reset pwm controller: {e}"))
                    continue
                
            break # exit the main loop
        
    logger.info(format_watchdog_msg("Watchdog shutdown"))

class PWMController:
    """Simple PWM controller with piecewise deadband and dither for valve testing."""
    CONFIG_FILE_NAME="servo_config.yaml"

    def __init__(self, pump_variable: bool = False,
                 toggle_channels: bool = True, input_rate_threshold: float = 0,
                 default_unset_to_zero: bool = True, log_level: str = "INFO",emergency_reset=False):
        """Initialize PWM controller.

        Args:
            pump_variable: Enable variable pump speed
            toggle_channels: Enable toggleable channels
            input_rate_threshold: Input rate threshold for safety monitoring
            default_unset_to_zero: Default unset channels to zero
            log_level: Logging level - "DEBUG", "INFO", "WARNING", "ERROR"
        """
        # Setup logger
        process_name="excavator"
        if emergency_reset:
            process_name="watchdog"
        self.logger = setup_logging(logging_level=log_level)
        
        # Check if emergency reset (likely called by the watchdog process)
        # Sets up only the absolute minimum + logger to reset the PWM to a safe state
        if emergency_reset:
            try:
                self._pwm_emergency_reset()
            except Exception as e:
                # Becaue __init__ can't return anything use
                # is_safe_state to indicate reset has failed
                self.logger.error(f"PWM reset failed: {e}")
                self.is_safe_state=True
            return # Exit early - only here to reset state

        self.pump_variable = pump_variable
        self.toggle_channels = toggle_channels
        self.pump_enabled = True
        self.manual_pump_load = 0.0
        self.pump_variable_sum = 0.0
        self._pump_override_throttle: Optional[float] = None
        self.pump_config = None
        self.channel_configs = None

        # Rate monitoring (optional)
        self.input_rate_threshold = input_rate_threshold
        self.skip_rate_checking = (input_rate_threshold == 0)
        self.is_safe_state = not self.skip_rate_checking
        self.time_window = PWMConstants.DEFAULT_TIME_WINDOW
        self.pwm_heartbeat = None
        self.pwm_pid = os.getpid()
        if self.input_rate_threshold != 0:
            self.pwm_timeout = (1.0 / self.input_rate_threshold) * 10
        else:
            self.pwm_timeout = 10
        self.running = False

        # Watchdog (only active if rate monitoring is too)
        self.watchdog_heartbeat = None
        self.watchdog_shutdown_queue = None
        self.watchdog_pid = None
        self.watchdog_process = None
        self.watchdog_last_timestamp = None
        self.watchdog_timeout = 25.0 

        # Threads/monitoring
        self.input_event = threading.Event()
        self.start_monitoring_event = threading.Event()
        self.monitor_thread = None
        self.input_count = 0
        self.last_input_time = time.time()
        # Load config
        self.channel_configs, self.pump_config = PWMController.load_config(return_as_dict=False)
        self._hardware_init()

        # Current normalized values per channel
        self.values = [0.0] * PWMConstants.MAX_CHANNELS

        # Monitoring counters
        self.input_counter = 0
        self.rate_window_start = time.time()

        # Register simple cleanup and start monitoring
        atexit.register(self._simple_cleanup)
        self.reset(reset_pump=True)

        if not self.skip_rate_checking:
            self._start_monitoring()
        
        # Behavior defaults
        self._default_unset_to_zero = default_unset_to_zero
        
        self.logger.info("PWMController service has been started")

    def _start_watchdog(self, restart=False):
        self._shutdown_watchdog() 
        
        # Create new queues to make sure the buffers will be empty
        self.pwm_heartbeat = multiprocessing.Queue()
        self.watchdog_heartbeat = multiprocessing.Queue()
        self.watchdog_shutdown_queue = multiprocessing.Queue()
        # Make watchdog a separate process so it will not crash
        # with the main process and can reset PWM reliably
        self.watchdog_process = multiprocessing.Process(
            target=_watchdog_loop,
            args=(self.pwm_pid, self.pwm_heartbeat, self.watchdog_heartbeat, self.watchdog_shutdown_queue, self.pwm_timeout)
        )
        self.watchdog_process.start()
        self.watchdog_pid = self.watchdog_heartbeat.get()
        self.watchdog_last_timestamp = time.time()
        self.logger.info(f"Watchdog started with pid: {self.watchdog_pid}")
        # Since monitor thread is spawning the watchdog this time we donn't need to set the event
        if not restart:
            self.start_monitoring_event.set()
        else:
            self.watchdog_last_timestamp = time.time()

    def _hardware_init(self):
        i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(i2c)
        self.pca.frequency = PWMConstants.PWM_FREQUENCY_DEFAULT
        self._pwm_period_us = 1e6 / float(self.pca.frequency)
        if self._pwm_period_us < PWMConstants.PULSE_MAX:
            raise RuntimeError(f"_pwm_period_us({self._pwm_period_us}) is smaller than PWM's max pulse ({PWMConstants.PULSE_MAX}) - Duty cycle calculations assume this is never the case.")
        
    def _shutdown_watchdog(self):
        if self.start_monitoring_event.is_set():
            self.start_monitoring_event.clear()
        if self.watchdog_process and self.watchdog_process.is_alive():
            self.logger.info("Closing old watchdog process")
            try:
                self.watchdog_shutdown_queue.put(1)
                self.watchdog_process.join(timeout=self.watchdog_timeout)
            except Exception:
                pass
            if self.watchdog_process.is_alive():
                self.logger.warning("Force killing watchdog process...")
                self.watchdog_process.kill()  
        self.logger.info("Watchdog shutdown")

    def _pwm_emergency_reset(self):
        # Load config
        self.logger.warning("Performing emergency reset!")
        self.channel_configs, self.pump_config = PWMController.load_config(return_as_dict=False)
        self._hardware_init()
        self.reset(reset_pump=True)

    def load_config_cached(self):
        if self.pump_config != None and self.channel_config != None:
            return (self.channel_config, self.pump_config)
        else:
            self.logger.warning("COnfiguration not cached for some reason?")
            self.channel_configs, self.pump_config = PWMController.load_config()
            return (self.channel_configs, self.pump_config)

    @staticmethod
    def load_config(return_as_dict=True):
        """Loads config from a file without needing to create an instance"""
        config_path = Path("/home") / "savonia" / "excavator" / "config" / PWMController.CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{PWMController.CONFIG_FILE_NAME}' not found")
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
        channel_configs, pump_config = PWMController.parse_config(raw_config)
        PWMController.validate_config(pump_config=pump_config, channel_configs=channel_configs)
        if return_as_dict:
            for name, cfg in channel_configs.items():
                channel_configs[name] = asdict(cfg)
            
            if pump_config:
                pump_config = asdict(pump_config)
            return channel_configs, pump_config
        else:
            return channel_configs, pump_config

    @staticmethod
    def parse_config(raw_config: Dict) -> tuple[Dict[str, ChannelConfig], Optional[PumpConfig]]:
        channel_configs: Dict[str, ChannelConfig] = {}
        pump_config = None

        for name, cfg in raw_config['CHANNEL_CONFIGS'].items():
            if name == 'pump':
                pump_config = PumpConfig(
                    output_channel=cfg['output_channel'],
                    pulse_min=cfg['pulse_min'],
                    pulse_max=cfg['pulse_max'],
                    idle=cfg['idle'],
                    multiplier=cfg['multiplier'],
                )
            else:
                channel_configs[name] = ChannelConfig(
                    output_channel=cfg['output_channel'],
                    pulse_min=cfg['pulse_min'],
                    pulse_max=cfg['pulse_max'],
                    direction=cfg['direction'],
                    center=cfg.get('center'),
                    deadzone=cfg.get('deadzone', 0.0),
                    affects_pump=cfg.get('affects_pump', False),
                    toggleable=cfg.get('toggleable', False),
                    # Simple deadband (separate per sign)
                    deadband_us_pos=float(cfg['deadband_us_pos']),
                    deadband_us_neg=float(cfg['deadband_us_neg']),
                    # Dither settings - opt-in only
                    dither_enable=cfg.get('dither_enable', False),
                    dither_amp_us=cfg.get('dither_amp_us', 8.0),
                    dither_hz=cfg.get('dither_hz', 40.0),
                    # Ramp/slew limiting - opt-in per channel
                    ramp_enable=cfg.get('ramp_enable', False),
                    ramp_limit=float(cfg.get('ramp_limit', 0.0)),
                    # Symmetric gamma shaping
                    gamma=float(cfg.get('gamma', 1.0)),
                )

        return channel_configs, pump_config

    @staticmethod
    def _normalize_none(value: Any) -> Optional[Any]:
        none_values = [None, "None", "none", "null", "NONE", "Null", "NULL", "", "n/a", "N/A"]
        return None if value in none_values else value

    @staticmethod
    def validate_config(pump_config=None, channel_configs=None):
        errors = []
        used_outputs = {}
        if channel_configs != None:
            for name, config in channel_configs.items():
                if config["direction"] not in [-1, 1]:
                    errors.append(f"Channel '{name}': direction must be -1 or 1")

                if config["output_channel"] in used_outputs:
                    errors.append(f"Channel '{name}': output {config['output_channel']} already used")
                if not 0 <= config["output_channel"] < PWMConstants.MAX_CHANNELS:
                    errors.append(f"Channel '{name}': output must be 0-{PWMConstants.MAX_CHANNELS - 1}")
                else:
                    used_outputs[config["output_channel"]] = name

                if not PWMConstants.PULSE_MIN <= config["pulse_min"] <= PWMConstants.PULSE_MAX:
                    errors.append(f"Channel '{name}': pulse_min out of range")
                if not PWMConstants.PULSE_MIN <= config["pulse_max"] <= PWMConstants.PULSE_MAX:
                    errors.append(f"Channel '{name}': pulse_max out of range")
                if config["pulse_min"] >= config["pulse_max"]:
                    errors.append(f"Channel '{name}': pulse_min must be less than pulse_max")

                # Center sanity
                if config["center"] is not None and not (config["pulse_min"] <= float(config["center"]) <= config["pulse_max"]):
                    errors.append(f"Channel '{name}': center: {config['center']} must be within [pulse_min{config['pulse_min']}-pulse_max{config['pulse_max']}]")

                # Deadband and dither bounds
                rng = config["pulse_max"] - config["pulse_min"]
                # deadband_us_pos/neg should not exceed half of span and must be >=0
                if float(config["deadband_us_pos"]) < 0.0 or float(config["deadband_us_pos"]) > (rng * 0.5):
                    errors.append(f"Channel '{name}': deadband_us_pos is unrealistic (0 .. {rng*0.5:.1f}us)")
                if float(config["deadband_us_neg"]) < 0.0 or float(config["deadband_us_neg"]) > (rng * 0.5):
                    errors.append(f"Channel '{name}': deadband_us_neg is unrealistic (0 .. {rng*0.5:.1f}us)")
                # dither amplitude reasonable vs span
                if float(config["dither_amp_us"]) < 0.0 or float(config["dither_amp_us"]) > (rng * 0.25):
                    errors.append(f"Channel '{name}': dither_amp_us is unrealistic (0 .. {rng*0.25:.1f}us)")
                # dither frequency sensible
                if float(config["dither_hz"]) <= 0.0 or float(config["dither_hz"]) > 200.0:
                    errors.append(f"Channel '{name}': dither_hz must be within (0, 200]")
                # ramp limits: enabled channels need a positive rate
                if config["ramp_enable"] and float(config["ramp_limit"]) <= 0.0:
                    errors.append(f"Channel '{name}': ramp_limit must be > 0 when ramp_enable is true")
                # gamma shaping bounds (keep reasonable)
                if float(config["gamma"]) <= 0.0 or float(config["gamma"]) > 5.0:
                    errors.append(f"Channel '{name}': gamma must be within (0, 5]")
                # 
                if float(config["deadzone"]) < 0.0 or float(config["deadzone"]) > 100.0:
                    errors.append(f"Channel '{name}': deadzone must be between 0-100")

        if pump_config != None:
            if pump_config["output_channel"] in used_outputs:
                errors.append(f"Pump: output {pump_config['output_channel']} already used")
            if not 0 <= pump_config["output_channel"] < PWMConstants.MAX_CHANNELS:
                errors.append(f"Channel pump: output must be 0-{PWMConstants.MAX_CHANNELS - 1}")
            if not PWMConstants.PUMP_IDLE_MIN <= pump_config['idle'] <= PWMConstants.PUMP_IDLE_MAX:
                errors.append(f"Pump: idle: {pump_config['idle']} out of range {PWMConstants.PUMP_IDLE_MIN} - {PWMConstants.PUMP_IDLE_MAX}")
            if not 0 < pump_config["multiplier"] <= PWMConstants.PUMP_MULTIPLIER_MAX:
                errors.append(f"Pump: multiplier: {pump_config['multiplier']} out of range [{0}-{PWMConstants.PUMP_MULTIPLIER_MAX}]")
            if not PWMConstants.PULSE_MIN <= pump_config['pulse_min'] <= PWMConstants.PULSE_MAX:
                errors.append(f"Channel pump: pulse_min: {pump_config['pulse_min']} out of range. [{PWMConstants.PULSE_MIN}-{PWMConstants.PULSE_MAX}]")
            if not PWMConstants.PULSE_MIN <= pump_config['pulse_max'] <= PWMConstants.PULSE_MAX:
                errors.append(f"Channel pump: pulse_max: {pump_config['pulse_max']} out of range. [{PWMConstants.PULSE_MIN}-{PWMConstants.PULSE_MAX}]")
            if pump_config["pulse_min"] >= pump_config["pulse_max"]:
                errors.append(f"Channel '{name}': pulse_min must be less than pulse_max")

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(errors))

    @staticmethod
    def update_config(config):
        config_path = Path("/home") / "savonia" / "excavator" / "config" / PWMController.CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{PWMController.CONFIG_FILE_NAME}' not found")
        with open(config_path, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)  

    def _start_monitoring(self):
        if self.skip_rate_checking or (self.monitor_thread and self.monitor_thread.is_alive()):
            return
        self.logger.debug("Started monitoring")
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        # Only start watchdog if there is something to watch
        self._start_watchdog()

    def _stop_monitoring(self):
        if not self.running:
            return
        self.running = False
        self.input_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        self.monitor_thread = None
        self.logger.info("Monitoring has been stopped")
        
    def _monitor_loop(self):
            self.watchdog_last_timestamp = time.time()

            while not self.start_monitoring_event.is_set():
                sleep(0.250)

            while self.running:
                # NOTE: # Queue.empty() has Minimal overhead ~ 2US
                # It is vital here because then we can avoid consuming more than
                # one entry from the buffer at a time, when both ends follow this
                # there will never be more than 1 heartbeat in the buffer
                if not self.watchdog_heartbeat.empty():
                    self.watchdog_heartbeat.get()
                    self.watchdog_last_timestamp = time.time()
                
                if time.time() - self.watchdog_last_timestamp > self.watchdog_timeout:
                    self.logger.info("Watchdogs heartbeat has died")
                    self._start_watchdog(restart=True)
                    
                if self.pwm_heartbeat.empty():
                    self.pwm_heartbeat.put(0)
                
                # Goes into safe state if input rate treshold is not satisfied
                if self.input_event.wait(timeout=1.0 / self.input_rate_threshold):
                    self.input_event.clear()
                    current_time = time.time()
                    time_diff = current_time - self.last_input_time
                    self.last_input_time = current_time
                    if time_diff > 0:
                        current_rate = 1 / time_diff
                        if current_rate >= self.input_rate_threshold:
                            self.input_count += 1
                            required_count = int(self.input_rate_threshold * PWMConstants.SAFE_STATE_THRESHOLD)
                            if self.input_count >= required_count:
                                self.is_safe_state = True
                                self.input_count = 0
                        else:
                            self.input_count = 0
                        self.input_counter += 1
                else:
                    if self.is_safe_state:
                        self.reset(reset_pump=False)
                        self.is_safe_state = False
                        self.input_count = 0
                        self.logger.info("PWMController has entered safe state")

    def update_named(self, commands: Dict[str, float], *, unset_to_zero: Optional[bool] = None,
                     one_shot_pump_override: bool = True):
        print("### DEBUG UPDATE NAMED ###")
        print(f"received commands: {commands}")
        print(f"is safe state: {self.is_safe_state}")
        if not self.skip_rate_checking:
            self.input_event.set()
            if not self.is_safe_state:
                return
        if 'pump' in commands and self.pump_config:
            try:
                pump_val = float(commands['pump'])
                self._pump_override_throttle = max(-1.0, min(1.0, pump_val))
            except Exception:
                self.logger.error(f"Received invalid pump value {value}")
                pass
        do_zero = self._default_unset_to_zero if unset_to_zero is None else unset_to_zero
        if do_zero:
            for cfg in self.channel_configs.values():
                self.values[cfg.output_channel] = 0.0
        self.pump_variable_sum = 0.0
        for name, val in commands.items():
            cfg = self.channel_configs.get(name)
            if cfg is None:
                self.logger.error(f"Could not find config for {name}")
                continue
            try:
                value = float(val)
            except Exception:
                self.logger.error(f"Config {name} value: {value} is invalid")
                continue
            value = max(-1.0, min(1.0, value))
            if abs(value) < cfg.deadzone_threshold:
                value = 0.0
            self.values[cfg.output_channel] = value
        for cfg in self.channel_configs.values():
            if cfg.affects_pump:
                self.pump_variable_sum += abs(self.values[cfg.output_channel])
        self._update_channels()
        self._update_pump()

        if one_shot_pump_override:
            self._pump_override_throttle = None

    def _update_channels(self):
        for name, config in self.channel_configs.items():
            if not self.toggle_channels and config.toggleable:
                continue

            now = time.time() #
            value = self.values[config.output_channel]
            pulse = self._pulse_from_value(config, value, now, apply_ramp=True)

            # Convert to duty and push
            duty_cycle = int((pulse / self._pwm_period_us) * PWMConstants.DUTY_CYCLE_MAX)
            self.pca.channels[config.output_channel].duty_cycle = duty_cycle
            self.logger.debug(f"Updating channel {config.output_channel} into a pulse: {pulse} => dutycycle: {duty_cycle}")

    def _pulse_from_value(self, config: ChannelConfig, value: float, now: Optional[float] = None,
                          apply_ramp: bool = False) -> float:
        """Compute output pulse width (us) from normalized value using current config.

        Applies deadzone treshold
        Applies gamma
        Applies simple deadband by compressing command range into working area.
        Optional ramp limits slew rate so even deadband jumps are spread over time.
        Optional dither adds vibration to prevent valve stiction.
        """
        if now is None:
            now = time.time()

        # Enforce input deadzone locally so preview/compute_pulse() honors it too
        if abs(value) < float(getattr(config, 'deadzone_threshold', 0.0)):
            value = 0.0
        # Apply symmetric gamma shaping for both directions
        value = self._apply_gamma(value, float(config.gamma))

        base_pulse = self._compute_base_pulse(config, value)
        if apply_ramp:
            base_pulse = self._apply_ramp(config, base_pulse, now)
        pulse = self._apply_dither(config, base_pulse, value, now)

        # Clamp to limits
        pulse = max(config.pulse_min, min(config.pulse_max, pulse))
        return pulse

    def _compute_base_pulse(self, config: ChannelConfig, value: float) -> float:
        """Map normalized value to physical pulse without dither or ramp."""
        # Simple deadband by physical sign (value * direction):
        # - s > 0 => physical positive: jump to center + deadband_us_pos, then scale to pulse_max
        # - s < 0 => physical negative: jump to center - deadband_us_neg, then scale to pulse_min
        # - s == 0 => center
        s = float(value) * float(config.direction)
        if s == 0.0:
            return float(config.center)
        elif s > 0.0:
            base = float(config.center) + float(config.deadband_us_pos)
            working_range = float(config.pulse_max) - base
            return base + abs(float(value)) * working_range
        else:  # s < 0.0
            base = float(config.center) - float(config.deadband_us_neg)
            working_range = base - float(config.pulse_min)
            return base - abs(float(value)) * working_range

    def _apply_dither(self, config: ChannelConfig, pulse: float, value: float, now: float) -> float:
        # Dither to prevent valve stiction (only when actively commanding)
        if config.dither_enable and abs(value) >= float(getattr(config, 'deadzone_threshold', 0.0)):
            # Per-channel phase offset using output_channel index to avoid perfect sync
            phase = 2.0 * 3.141592653589793 * config.dither_hz * now + (config.output_channel * 1.0471975512)
            dither = config.dither_amp_us * sin(phase)
            pulse += dither
        return pulse

    def _apply_ramp(self, config: ChannelConfig, target_pulse: float, now: float) -> float:
        """Limit slew rate so large steps are spread over time."""
        state_container = getattr(self, "_channel_ramp_state", None)
        if state_container is None:
            self.logger.error("State container is not initialized...")
            self._init_ramp_state()
            state_container = getattr(self, "_channel_ramp_state", None)
        state = state_container.get(config.output_channel)
        if state is None:
            # Initialize state lazily if a channel was added later
            self._channel_ramp_state[config.output_channel] = (target_pulse, now)
            return target_pulse

        last_pulse, last_time = state
        if not config.ramp_enable or float(config.ramp_limit) <= 0.0:
            self._channel_ramp_state[config.output_channel] = (target_pulse, now)
            return target_pulse

        dt_raw = max(0.0, now - last_time)
        # Clamp dt so a stalled loop cannot create a giant one-shot jump; allow up to 2x the prior interval.
        if self._last_ramp_dt > 0.0:
            dt = min(dt_raw, self._last_ramp_dt * 2.0)
        else:
            dt = dt_raw
        if dt <= 0.0:
            self._channel_ramp_state[config.output_channel] = (last_pulse, now)
            return last_pulse

        allowed_step = float(config.ramp_limit) * dt  # microseconds permitted in this interval
        delta = target_pulse - last_pulse
        if abs(delta) <= allowed_step:
            new_pulse = target_pulse
        else:
            new_pulse = last_pulse + allowed_step * (1 if delta > 0 else -1)

        self._channel_ramp_state[config.output_channel] = (new_pulse, now)
        # Remember unclamped dt to keep the clamp adaptive to the real loop cadence
        if dt_raw > 0.0:
            self._last_ramp_dt = dt_raw
        return new_pulse

    # Public helper for testers to preview the pulse for a value
    def compute_pulse(self, name: str, value: float, now: Optional[float] = None) -> Optional[float]:
        cfg = self.channel_configs.get(name)
        if cfg is None:
            return None
        value = max(-1.0, min(1.0, float(value)))
        return self._pulse_from_value(cfg, value, now)

    @staticmethod
    def _apply_gamma(value: float, gamma: float) -> float:
        """Apply symmetric gamma shaping to a normalized command."""
        if gamma == 1.0 or value == 0.0:
            return value
        sign = 1.0 if value >= 0 else -1.0
        return sign * (abs(value) ** gamma)

    def _update_pump(self):
        self.logger.debug("Updating pump?")
        if not self.pump_config:
            return
        if self._pump_override_throttle is not None:
            throttle = self._pump_override_throttle
        elif not self.pump_enabled:
            throttle = -1.0
        else: 
            # Default behaviour
            if self.pump_variable: # aggrogate from how many channels are being used that should affect pump
                throttle = self.pump_config.idle + (self.pump_config.multiplier * self.pump_variable_sum / 10)
            else: # Static idle
                throttle = self.pump_config.idle + (self.pump_config.multiplier / 10)
            throttle += self.manual_pump_load
        throttle = max(-1.0, min(1.0, throttle))
        pulse_range = self.pump_config.pulse_max - self.pump_config.pulse_min
        pulse = self.pump_config.pulse_min + (pulse_range * ((throttle + 1) / 2))
        duty_cycle = int((pulse / self._pwm_period_us) * PWMConstants.DUTY_CYCLE_MAX)
        self.logger.debug(f"Pump pulse: {pulse} - dutycycle: {duty_cycle}")
        self.pca.channels[self.pump_config.output_channel].duty_cycle = duty_cycle

    def reset(self, reset_pump: bool = True):
        self.logger.debug("### RESETTING PWM CONTROLLER ###")
        for name, config in self.channel_configs.items():
            duty_cycle = int((config.center / self._pwm_period_us) * PWMConstants.DUTY_CYCLE_MAX)
            self.pca.channels[config.output_channel].duty_cycle = duty_cycle
            self.logger.debug(f"Resetting Channel: {config.output_channel} to a pulse: {config.center}")
        self._init_ramp_state()
        if reset_pump and self.pump_config:
            duty_cycle = int((self.pump_config.pulse_min / self._pwm_period_us) * PWMConstants.DUTY_CYCLE_MAX)
            self.pca.channels[self.pump_config.output_channel].duty_cycle = duty_cycle
            self.logger.debug(f"Resetting PUMP: {self.pump_config.output_channel} to a pulse: {self.pump_config.pulse_min}")
        self.is_safe_state = False
        self.input_count = 0
        self._pump_override_throttle = None
        self.logger.info("PWM channels has been reseted to neutral states")

    def get_average_input_rate(self) -> float:
        current_time = time.time()
        elapsed = current_time - self.rate_window_start
        if elapsed <= 0:
            return 0.0
        rate = self.input_counter / elapsed
        if elapsed >= self.time_window:
            self.input_counter = 0
            self.rate_window_start = current_time
        return rate

    def set_pump(self, enabled: bool):
        self.pump_enabled = enabled

    def toggle_pump_variable(self, variable: bool):
        self.pump_variable = variable

    def update_pump_load(self, adjustment: float):
        self.manual_pump_load = max(-1.0, min(0.3, self.manual_pump_load + adjustment / 10))

    def reset_pump_load(self):
        self.manual_pump_load = 0.0
        self._update_pump()

    def disable_channels(self, disabled: bool):
        self.toggle_channels = not disabled

    def clear_pump_override(self):
        self._pump_override_throttle = None

    @staticmethod
    def get_channel_names(include_pump: bool = False) -> List[str]:
        channel_configs, pump_config = PWMController.load_config()
        channel_names = list(channel_configs.keys())
        if include_pump:
            if pump_config:
                channel_names.append("pump")
        return channel_names

    @staticmethod
    def get_channel_names_by_channels(channel_numbers):
        channel_names=[]
        channel_configs, pump_config = PWMController.load_config()
        
        for chan_num in channel_numbers:
            if chan_num == pump_config["output_channel"]:
                channel_names.append("pump")
            else:
                for name, cfg in channel_configs.items():
                    if cfg["output_channel"] == chan_num:
                        channel_names.append(name)
                        break
                    
        if len(channel_numbers) == len(channel_names):
            return channel_names
        else: # Didn't find them all
            return None

    def build_zero_commands(self, include_toggleable: bool = True, include_pump: bool = False) -> Dict[str, float]:
        commands: Dict[str, float] = {}
        for name, cfg in self.channel_configs.items():
            if include_toggleable or not cfg.toggleable:
                commands[name] = 0.0
        if include_pump and self.pump_config:
            commands['pump'] = 0.0
        return commands

    @staticmethod
    def build_channel_config(pump_config=None, channel_configs=None):
        """Builds the expected channel config format from the separate config objects"""
        channel_cfg={}
        if pump_config:
            channel_cfg={'pump': pump_config}
        if channel_configs:
            channel_cfg.update(channel_configs)
        return {"CHANNEL_CONFIGS": channel_cfg}

    @staticmethod
    def get_used_channels():
        # NOTE: Do not change the order of the channels
        # pump is assumed to be the first index by the TCPServers parseValidation function
        used_channels=[]
        channel_configs, pump_config = PWMController.load_config()
        if pump_config is not None:
            used_channels.append(pump_config["output_channel"])
        for name, cfg in channel_configs.items():
            used_channels.append(cfg["output_channel"])
        return used_channels

    def reload_config(self) -> bool:
        self.reset(reset_pump=True)
        try:
            was_monitoring = self.running
            if was_monitoring:
                self._stop_monitoring()
            self.channel_configs, self.pump_config = PWMController.load_config()
            self.reset(reset_pump=True)
            if was_monitoring:
                self._start_monitoring()
            self.logger.info("Config has been reloaded")
            return True
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            return False

    def set_log_level(self, level: str) -> None:
        """Change the logging level at runtime.

        Args:
            level: One of "DEBUG", "INFO", "WARNING", "ERROR"
        """
        self.logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    def _init_ramp_state(self):
        now = time.time()
        self._channel_ramp_state: Dict[int, tuple[float, float]] = {}
        for cfg in self.channel_configs.values():
            self._channel_ramp_state[cfg.output_channel] = (float(cfg.center), now)
        # Track last observed dt for adaptive clamp
        self._last_ramp_dt: float = 0.0
        self.logger.info("Ramp state has been initialized")

    def _simple_cleanup(self):
        try:
            self.logger.info("Performing simple cleanup!")
            self._shutdown_watchdog() 
            self._stop_monitoring()
            self.reset(reset_pump=True)
        except:
            pass
