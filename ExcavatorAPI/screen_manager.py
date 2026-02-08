import subprocess
import os
import board
import digitalio
import threading
import adafruit_ssd1306 as SSD1306
from PIL import Image, ImageDraw, ImageFont
from time import sleep, time
from dataclasses import dataclass
from dataclass_types import ExcavatorAPIProperties
from math import ceil
from collections import deque
import yaml
from pathlib import Path
from utils import setup_logging, get_cpu_temperature

@dataclass
class RenderViewInfo:
    view: str
    render_count: int
    render_time: float
    header: str = ""
    body: str = ""

# ============================================================================
# Helper Functions - Network Utilities
# Credit: https://github.com/AI-MaSi/Excavator
# ============================================================================

def get_active_interface():
    try:
        cmd = "ip route get 1.1.1.1 | awk '{print $5}' | head -n 1"
        interface = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return interface
    except subprocess.CalledProcessError:
        return None

def get_ip_address(interface):
    try:
        cmd = f"ip addr show {interface} | grep 'inet ' | awk '{{print $2}}' | cut -d'/' -f1"
        IP = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return IP
    except subprocess.CalledProcessError:
        return "No IP Found"

def get_ssid(interface):
    try:
        cmd = f"iwgetid -r {interface}"
        SSID = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return SSID
    except subprocess.CalledProcessError:
        return "Not Connected"

def get_rssi(interface):
    try:
        # First try to get Signal level in standard format
        cmd = f"iwconfig {interface} | grep 'Signal level' | awk '{{print $4}}' | cut -d'=' -f2"
        rssi = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()

        # Check if the format is XX/100
        if '/' in rssi:
            numerator, denominator = rssi.split('/')
            # Convert percentage to approximate dBm value
            # Typically, 100% ≈ -50 dBm, 0% ≈ -100 dBm
            percentage = float(numerator)
            fine_tune = 20 # to make the bars make more sense
            rssi_dbm = -100 + (percentage / 100.0) * 50 + fine_tune
            print(f"after: {rssi_dbm}")
            return int(rssi_dbm)

        # If it's already in dBm format, just return the integer
        return int(rssi)
    except (subprocess.CalledProcessError, ValueError):
        return None

def draw_wifi_signal(draw, rssi, x, y):
    if rssi is None:
        return

    # Adjust thresholds for percentage-based values converted to dBm
    bars = 0
    if rssi > -65:  # About 70% signal strength
        bars = 3
    elif rssi > -75:  # About 50% signal strength
        bars = 2
    elif rssi > -85:  # About 30% signal strength
        bars = 1

    bar_width = 5
    bar_height = 3
    spacing = 2

    for i in range(bars):
        draw.rectangle(
            (x, y - i * (bar_height + spacing),
             x + bar_width, y - i * (bar_height + spacing) + bar_height),
            outline=255,
            fill=255
        )



# 128x64 self.oled display
# Can only realistically display 3 lines of text in the body section 
# without wrapping, which is roughly 60 characters
class ScreenManager: 
    FONT_PATH = Path("/home") / "savonia" / "excavator" / 'Montserrat-VariableFont_wght.ttf'
    CONFIG_FILE_NAME = "screen_config.yaml"
    RENDERQ_BUFFER_SIZE = 100
    def __init__(self, cleanup_callback=None,width=128, height=64, padding=2):
        self.logger = setup_logging()
        # Config
        self.config = ScreenManager.load_config(self.logger)
        
        # Parameters
        self.padding=padding
        self.width = width
        self.height=height
        self.running=False
        self.cleanup_callback = cleanup_callback
        
        # default view 
        self.default_TIME_DELAY = 4  # switch between screens every 4 seconds
        self.previous_network_name, self.previous_IP, self.previous_rssi, self.previous_toggle_display = None, None, None, None
        self.toggle_display = False
        self.last_toggle_time = time()
        self.font_body = ImageFont.truetype(ScreenManager.FONT_PATH, self.config["font_size_body"])
        self.font_header = ImageFont.truetype(ScreenManager.FONT_PATH, self.config["font_size_header"])
        
        self.stop_event = threading.Event()
        
        # RenderQueue - rolling window -> removes oldest when overflowing
        self.render_que_thread = None
        self.render_queue = deque(maxlen=ScreenManager.RENDERQ_BUFFER_SIZE)
        self.que_lock = threading.Lock()
        
    
    def start(self):
        if self.running:
            self.logger.info("SSD1306 manager is already running")
            return True
        self._init_ssd1306()
        self.running=True
        self.clear_display()
        self._start_render_que()
        self.logger.info("ScreenManager service has been started")
        return True
    
    def is_ready(self):
        return self.running
    
    def clear_display(self):
        if not self.running:
            self.logger.warning("SSD1306Manger.start() first")
            return False
        
        self.oled.fill(0)
        self.oled.show()
        return True

    def get_status(self):
        return {
            "running": self.running,
            "render_queue_count": len(self.render_queue)
        }

    def add_to_renderq(self, item: RenderViewInfo):
        if not self.running:
            self.logger.warning("SSD1306Manger.start() first")
            return
        
        errors = self._validate_renderview_parameter(item)
        if errors:
            self.logger.error(f"Invalid RenderViewInfo object given: {','.join(errors)}")
            return 

        # Clean the message up, the screen can only fit roughly 60 chars + the header
        # Text Wrapping has to be done manually so lets remove all special chars
        item.header = item.header.replace('\t', '').replace('\n', '').strip().replace('  ', ' ')[:32]
        item.body = item.body.replace('\t', '').replace('\n', '').strip().replace('  ', ' ')[:100]
        
        with self.que_lock:
            self.render_queue.append(item)
        self.logger.info(f"Item: {item} has been added to the screens render queue")

    def _init_ssd1306(self):
        i2c = board.I2C()
        self.oled = SSD1306.SSD1306_I2C(self.width, self.height, i2c, addr=0x3D, reset=None)
        self.logger.info("SSD1306 has been setup")

    def _validate_renderview_parameter(self, item: RenderViewInfo):
        errors = []
        # Values
        if item.render_count <= 0:
            errors.append("Render count needs to be > 0")
        if item.render_time <= 0:
            errors.append("Render time needs to be > 0")
        
        return errors

    def _update_default_view(self, interface, network_name, IP, rssi=None, show_cpu_temp=False):
        image = Image.new("1", (self.oled.width, self.oled.height))
        draw = ImageDraw.Draw(image)

        if show_cpu_temp:
            cpu_temp = get_cpu_temperature()
            if cpu_temp is not None:
                cpu_temp_str = f"CPU: {cpu_temp:.0f}C"
                cpu_temp_width = draw.textlength(cpu_temp_str, font=self.font_body)
                cpu_temp_x = (self.oled.width - cpu_temp_width) // 2
                draw.text((cpu_temp_x, 0), cpu_temp_str, font=self.font_body, fill=255)
        else:
            network_label = "SSID:" if "wlan" in interface else "Network:"
            network_label_width = draw.textlength(network_label, font=self.font_body)
            network_label_x = (self.oled.width - network_label_width) // 2
            draw.text((network_label_x, 0), network_label, font=self.font_body, fill=255)

        network_name_width = draw.textlength(network_name, font=self.font_body)
        IP_width = draw.textlength(IP, font=self.font_header)

        network_name_x = (self.oled.width - network_name_width) // 2
        IP_x = (self.oled.width - IP_width) // 2

        draw.text((network_name_x, 16), network_name, font=self.font_body, fill=255)
        draw.text((IP_x, 32), IP, font=self.font_header, fill=255)
        draw.line((0, 14, self.oled.width, 14), fill=255)

        if rssi:
            draw_wifi_signal(draw, rssi, self.oled.width - 10, 10)

        self.oled.image(image)
        self.oled.show()
    
    def set_default_render_time(self, duration):
        if (not isinstance(duration, float) and not isinstance(duration, int)) or duration <= 0:
            raise ValueError("set_default_render_time: duration is invalid")
        self.config["render_time"]=duration
        self.logger.info(f"Default views render time has been set to: {duration}")
    
    def set_font_header(self, size):
        if size <= 0:
            self.logger.error("size must be positive")
            return
        self.config["font_size_header"] = size
        self.font_header = ImageFont.truetype(ScreenManager.FONT_PATH, self.config['font_size_header'])
        self.logger.info(f"font_size_header has been set to {self.config['font_size_header']}")

    def set_font_body(self, size):
        if size <= 0:
            self.logger.error("set_font_body: size is invalid")
            return
        self.config["font_size_body"] = size
        self.font_body = ImageFont.truetype(ScreenManager.FONT_PATH, self.config['font_size_body'])
        self.logger.info(f"font_size_body has been set to {self.config['font_size_body']}")
    
    def _render_default_view(self):
        start = time()
        # elapsed <= duration
        while (time() - start) <= self.config["render_time"]:
            current_time = time()
            if current_time - self.last_toggle_time >= self.default_TIME_DELAY:
                self.toggle_display = not self.toggle_display
                self.last_toggle_time = current_time

            interface = get_active_interface()
            IP = get_ip_address(interface) if interface else "NONE"
            network_name = get_ssid(interface) if "wlan" in interface else "Wired" if interface else ""
            rssi = get_rssi(interface) if "wlan" in interface else None

            if network_name != self.previous_network_name or IP != self.previous_IP or (
                    rssi and self.previous_rssi != rssi) or self.toggle_display != self.previous_toggle_display:
                self._update_default_view(interface, network_name, IP, rssi, show_cpu_temp=self.toggle_display)
                self.previous_network_name, self.previous_IP, self.previous_rssi, self.previous_toggle_display = network_name, IP, rssi, self.toggle_display

            sleep(1)

    def _render_message_view(self, header="no header", body="no message"):
        image = Image.new("1", (self.oled.width, self.oled.height))
        draw = ImageDraw.Draw(image)
        
        header_width = draw.textlength(header, font=self.font_header)
        header_x = (self.oled.width - header_width) // 2
        
        draw.text((header_x, 0), header, font=self.font_header, fill=255)
        line_y = self.config["font_size_header"]+1
        draw.line((0, line_y, self.oled.width, line_y), fill=255)
        
        body_width = draw.textlength(body, font=self.font_body)
        max_text_width = self.oled.width-(self.padding*2)
        
        # Handle possible wrapping 
        # TODO - maybe rolling text if > 3 lines
        if body_width >= max_text_width:
            body_row_count = ceil(body_width / max_text_width)
            row_letter_count = int(len(body) / body_row_count)
            rows = []
            start_index = 0
            end_index = row_letter_count
            
            for i in range(body_row_count):
                rows.append(body[start_index:end_index])
                start_index+=row_letter_count
                end_index=start_index+row_letter_count
                
            for i, row in enumerate(rows):
                body_x = (self.padding)
                draw.text((body_x, (line_y+1)+i*12), row, font=self.font_body, fill=255)
        else: # Text fits on a single row
            body_x = (self.padding)
            draw.text((body_x, line_y+1), body, font=self.font_body, fill=255)
        
        self.oled.image(image)
        self.oled.show()

    def _start_render_que(self):
        if self.render_que_thread and self.render_que_thread.is_alive():
            self.logger.warning("render queue thread is already running")
            return False
        self.render_que_thread = threading.Thread(
            target=self._render_que_loop,
            daemon=True
        )
        self.render_que_thread.start()
        return True

    def _render_que_loop(self):
        self.logger.info("Starting render queue")
        while not self.stop_event.is_set():
            try:
                # When render_queue is empty display the default view
                with self.que_lock:
                    renderq_len=len(self.render_queue)
                if renderq_len == 0:
                    self._render_default_view()
                else: 
                    with self.que_lock:
                        next_view_index = renderq_len-1
                        next_view = self.render_queue[next_view_index]
                
                    if next_view.view == "message":
                        self._render_message_view(header=next_view.header, body=next_view.body)
                        sleep(next_view.render_time)
                        # Update render count and remove it if 0
                        with self.que_lock:
                            self.render_queue[next_view_index].render_count = next_view.render_count - 1
                            if self.render_queue[next_view_index].render_count == 0:
                                self.render_queue.pop()
            except Exception as e:
                self.logger.error(f"Error occured in _render_que_loop: {e}")
                if self.cleanup_callback:
                    self.cleanup_callback()
        self.logger.info("Render queue has been shutdown")

    def shutdown(self):
        if not self.running:
            self.logger.warning("ScreenManager is not running, can't shutdown")
            return True
            
        self.stop_event.set()
        calling_thread=threading.current_thread()
        if self.render_que_thread and self.render_que_thread.is_alive():
            if calling_thread != self.render_que_thread:
                self.render_que_thread.join(timeout=10)
         
        self.clear_display()
        self.stop_event.clear()
        self.running=False
        self.logger.info("ScreenManager service has been shutdown")
        return True

    def update_state(self):
        # Updates all the states that are not automatically updated when reloading the config
        self.set_font_header(self.config["font_size_header"])
        self.set_font_body(self.config["font_size_body"])

    def reload_config(self):
        self.config = ScreenManager.load_config(self.logger)
        self.update_state()
        self.logger.info("ScreenManagers config has been reloaded")
    
    @staticmethod
    def load_config(logger=None):
        config_path = Path("/home") / "savonia" / "excavator" / "config" / ScreenManager.CONFIG_FILE_NAME

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{ScreenManager.CONFIG_FILE_NAME}' not found")
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
    
        parsed_config = ScreenManager._parse_config(raw_config)
        ScreenManager.validate_config(parsed_config)
        if logger:
            logger.info(f"ScreenManagers config has been validated and loaded: {parsed_config}")
        return parsed_config
    
    @staticmethod
    def _parse_config(cfg):
        config = {
            "render_time": int(cfg['render_time']),
            "font_size_header": int(cfg['font_size_header']),
            "font_size_body": int(cfg['font_size_body']),
        }
        return config

    @staticmethod
    def validate_config(parsed_config):

        errors = []
        
        if not (ExcavatorAPIProperties.RENDERTIME_MIN < parsed_config["render_time"] < ExcavatorAPIProperties.RENDERTIME_MAX):
            errors.append(f"render_time must be between {ExcavatorAPIProperties.RENDERTIME_MIN}-{ExcavatorAPIProperties.RENDERTIME_MAX}")
        if not (ExcavatorAPIProperties.FONTSIZE_MIN < parsed_config["font_size_header"] < ExcavatorAPIProperties.FONTSIZE_MAX):
            errors.append(f"font_size_body must be between {ExcavatorAPIProperties.FONTSIZE_MIN}-{ExcavatorAPIProperties.FONTSIZE_MAX}")
        if not (ExcavatorAPIProperties.FONTSIZE_MIN < parsed_config["font_size_body"] < ExcavatorAPIProperties.FONTSIZE_MAX):
            errors.append(f"font_size_body must be between {ExcavatorAPIProperties.FONTSIZE_MIN}-{ExcavatorAPIProperties.FONTSIZE_MAX}")

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(errors))
    
    @staticmethod
    def update_config(config):
        config_path = Path("/home") / "savonia" / "excavator" / "config" / ScreenManager.CONFIG_FILE_NAME
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file '{ScreenManager.CONFIG_FILE_NAME}' not found")
        with open(config_path, 'w') as f:
            yaml.safe_dump(config, f,default_flow_style=False)
    
# Example
# if __name__ == "__main__":
#     manager = ScreenManager()
#     manager.start()
#     sleep(5)
#     msg="This draws a horizontal line at y=14 (which makes sense as a separator). But in _render_default_view(), your line goes from y=19 to y=14, creating a diagonal instead of"
#     manager.add_to_renderq(RenderViewInfo("message", render_count=1, render_time=10, header="Hyvää Päivää!", body=msg))
#     sleep(16)
#     manager.shutdown()