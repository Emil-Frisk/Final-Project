import socket
import struct
import threading
import time
import crcmod
from typing import Optional, List
from utils.utils import setup_logging
from utils.utils import ExcavatorAPIProperties

send_types = [
    'b', # Signed byte
    'B', # Unsigned byte
    'h', # Signed 2 bytes
    'H', # Unsigned 2 bytes
    'i', # Signed 4 bytes
    'I', # Unsigned 4 bytes
    'q', # Signed 8 bytes
    'Q', # Unsgined 8 bytes
    'f', # 4 byte float 
    'd', # 8 byte float
]

# NOTE: ExcavatorAPI is responsible for cleaning up with cleanup_callback
# on unexpected thread crashes
class UDPSocket:
    """
    UDP socket with heartbeat safety mechanism.
    - Returns None if data is too old
    - Configurable timeout for safety
    """
    # Common CRC for networking with small packets 
    # 0x11021 (CRC-16-CCITT) is the polynomial we are dividing with
    crc16 = crcmod.mkCrcFun(0x11021, initCrc=0xFFFF)

    def __init__(self, cleanup_callback=None, local_id=0, max_age_seconds=1, delay_tracking=False, send_type = 'f', flushing_treshold=0.5, operation="unknown", socket_timeout=1,logging_level="INFO", tcp_server=None):
        # ExcavatorAPI actions
        self.cleanup_callback = cleanup_callback
        self.logger=setup_logging(logging_level=logging_level)
        self.stop_event = threading.Event()
        
        self.socket = None
        self.remote_addr = None
        self.tcp_server=tcp_server
        # NOTE: this validation is important to guarantee that threads will have time to see a stop event and not be left hanging in the background
        if socket_timeout < ExcavatorAPIProperties.MIN_RATE:
            raise RuntimeError(f"socket_timeout is smaller the {ExcavatorAPIProperties.MIN_RATE} minimum allowed rate")
        self.socket_timeout = socket_timeout
        
        # max age ms will be used to stop the udp transfer
        # operation if data stops flowing unexpectedly
        self.remote_max_age_ms = None
        self.local_id = local_id
        self.num_inputs = 0
        self.num_outputs = 0
        self.max_age_seconds = max_age_seconds
        self.heartbeat_thread = None
        # This will be sent in the handshake operation and can be used by the client
        self.operation = operation

        # Sending data
        self.send_type = send_type

        # For receiving data
        self.latest_data = None
        self.latest_timestamp = time.time()
        self.data_lock = threading.Lock()
        self.recv_thread = None
        self.running = False
        self.receive_type = None
        self.flushing_treshold = flushing_treshold

        # Statistics
        self.packets_received = 0
        self.packets_sent=0
        self.packets_expired = 0
        self.packets_shape_invalid = 0
        self.packets_corrupted = 0
        self.last_packet_time = 0.0
        
        
        # network delay stats
        self._delay_tracking = delay_tracking
        self._delay_mean = 0.0
        self._delay_m2 = 0.0
        self._delay_min = float("inf")
        self._delay_max = float("-inf")
        self._delay_n = 0.0

        # Pre-computed format strings (filled after handshake)
        self.send_format = None
        self.recv_format = None

    def setup(self, host, port, num_inputs, num_outputs, is_server=False):
        """Set up UDP socket with heartbeat protocol."""
        self.num_inputs = num_inputs
        self.num_outputs = num_outputs

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(1.0)

        if is_server:
            self.socket.bind((host, port))
            self.logger.info(f"UDP Server listening on {host}:{port}")
        else:
            self.remote_addr = (host, port)
            self.logger.info(f"UDP Client ready to send to {host}:{port}")

        # Format: data (N bytes)
        # the recv type will be defined by the sender in the handshake 
        self.send_format = f'<{self.num_outputs}{self.send_type}'
        self.recv_format = f'<{self.num_inputs}'

        return True
    
    @staticmethod
    def _validate_crc(data: bytes, checksum) -> bool:
        return UDPSocket.crc16(data) == checksum
    
    def handshake(self, client_tcp_socket=None, timeout=5.0):
        """Enhanced handshake that includes max_age_seconds."""
        # Pack: [id, num_outputs, num_inputs, max_age_ms] as 4 bytes + 2 bytes
        max_age_ms = int(self.max_age_seconds * 1000)
        handshake_format="<3HsH"
        handshake_size=struct.calcsize(handshake_format)
        our_info = struct.pack(handshake_format,
                               self.local_id,
                               self.num_outputs,
                               self.num_inputs,
                               self.send_type.encode(),
                               max_age_ms)

        self.socket.settimeout(timeout)
        if self.remote_addr:  # Client mode
            self.socket.sendto(our_info, self.remote_addr)
            try:
                data, addr = self.socket.recvfrom(handshake_size)
                self.remote_addr = addr
            except socket.timeout:
                self.logger.error("Handshake timeout!")
                return False
        else:  # Server mode
            self.logger.info("Waiting for handshake...")
            try:
                # Inform possible tcp client that server is ready for hanshake
                if client_tcp_socket:
                    self.tcp_server.send_response(websocket=client_tcp_socket,data={"event": "handshake", "operation": self.operation})
                data, addr = self.socket.recvfrom(handshake_size)
                self.remote_addr = addr
                self.socket.sendto(our_info, self.remote_addr)
            except socket.timeout:
                self.logger.error("Handshake timeout!")
                return False

        # Verify match
        remote_id, remote_outputs, remote_inputs, remote_send_type, self.remote_max_age_ms = struct.unpack(handshake_format, data)
        remote_send_type = remote_send_type.decode()

        if remote_inputs != self.num_outputs:
            self.logger.error(f"Mismatch: They expect {remote_inputs} inputs, we send {self.num_outputs}")
            return False
        if remote_outputs != self.num_inputs:
            self.logger.error(f"Mismatch: They send {remote_outputs} outputs, we expect {self.num_inputs}")
            return False

        self.logger.info(f"Handshake OK with device ID {remote_id} (max_age: {self.remote_max_age_ms}ms)")
        
        # Specify the receive type based on remote send type
        if not remote_send_type in send_types:
            self.logger.error(f"Invalid send type: {remote_send_type}; Here are the possible types {','.join(send_types)}")
            return False
        
        with self.data_lock:
            self.receive_type = remote_send_type
            self.recv_format = f"<{self.num_inputs}{self.receive_type}"
        
        self.logger.info(f"Send format: {self.send_format}")
        self.logger.info(f"Receive format: {self.recv_format}")
        self.socket.settimeout(1.0)
        return True

    def send(self, values):
        """Send values with timestamp."""
        if not self.remote_addr:
            self.logger.warning("No remote address set!")
            return False

        if len(values) != self.num_outputs:
            self.logger.error(f"Expected {self.num_outputs} values, got {len(values)}")
            return False
        
        data_wo_crc = struct.pack(self.send_format, *values)

        # Combine -> data + crc and send
        data = data_wo_crc+struct.pack("<H", UDPSocket.crc16(data_wo_crc))
        self.socket.sendto(data, self.remote_addr)
        self.packets_sent+=1
        return True

    def get_latest(self) -> Optional[List[int]]:
        """
        Get latest data only if it's fresh enough.
        Returns None if data is too old or no data received.
        """
        if not self.running: return False
        
        with self.data_lock:
            if self.latest_data is None:
                return None

            # Check if data is too old
            age = time.time() - self.latest_timestamp
            if age > self.max_age_seconds:
                self.packets_expired += 1
                return None

            data = self.latest_data.copy()
            self.latest_data=None
            return data
        
    def get_status(self) -> dict:
        """Get connection statistics for monitoring."""
        with self.data_lock:
            current_time = time.time()
            age = current_time - self.latest_timestamp if self.latest_timestamp > 0 else None
            time_since_last = current_time - self.last_packet_time if self.last_packet_time > 0 else None

            return {
                'running': self.running,
                'packets_received': self.packets_received,
                'packets_sent': self.packets_sent,
                'packets_expired': self.packets_expired,
                'packets_corrupted': self.packets_corrupted,
                'packets_shape_invalid':self.packets_shape_invalid,
                'data_age_seconds': age,
                'time_since_last_packet': time_since_last,
                'has_data': self.latest_data is not None,
                'receive_type':self.receive_type,
                'send_type':self.send_type,
                'num_inputs':self.num_inputs,
                'num_outputs':self.num_outputs
            }

    def start(self):
        if self.running: return
        if not self._start_receiving():
            raise RuntimeError("Failed to start receiving")
        self.latest_timestamp = time.time()
        # Only start heartbeat monitor if we are actually expecting something
        if self.num_inputs > 0:
            if not self._start_heartbeat():
                raise RuntimeError("Failed to start heartbeat monitoring")
        self.logger.info("UDPSocket service has been started")
        return True

    def _start_heartbeat(self):
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        self.logger.info("Started heartbeat thread")
        return True

    def _start_receiving(self):
        """Start the receive thread."""
        if not self.recv_thread or not self.recv_thread.is_alive():
            self.running = True
            self.recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.recv_thread.start()
            self.logger.info("Started receive thread")
            return True

    def _heartbeat_loop(self):
        """Will cleanup the operation if data stops flowing"""
        try:
            while not self.stop_event.is_set():
                with self.data_lock:
                    age = time.time() - self.latest_timestamp
                    if age > 30:
                        raise RuntimeError("_heartbeat_loop: Connection has timed out")
                time.sleep(2)
        except Exception as e:
            self.logger.error(f"Error occured in _heartbeat_loop: {e}")
            if self.cleanup_callback:
                self.cleanup_callback()
        self.logger.info(f"_heartbeat_loop: has been closed")
            
    def _stop_receiving(self, current_thread):
        """Stop the receive thread."""
        if self.recv_thread and self.recv_thread.is_alive():
            if self.recv_thread != current_thread:
                self.recv_thread.join(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
                self.logger.info("Stopped receive thread")

    def _stop_heartbeat(self, current_thread):
        """Stop the receive thread."""
        self.running = False
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            if current_thread != self.heartbeat_thread:
                self.heartbeat_thread.join(timeout=ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
                self.logger.info("Stopped heartbeat thread")

    def close_connection(self):
        """Sends an empty byte to close connection"""
        if not self.remote_addr: return
        try:
            self.socket.sendall(b'', self.remote_addr)
        except Exception:
            pass

    def _receive_loop(self):
        """Background thread to continuously receive data with timestamps."""
        expected_size = struct.calcsize(self.receive_type)*self.num_inputs + 2

        while not self.stop_event.is_set():
            try:
                data, addr = self.socket.recvfrom(expected_size)
                # Force a copy RIGHT HERE
                data = bytes(data)  # Detach from actuall socket buffer
                if not self.remote_addr:
                    self.remote_addr = addr
                
                if data == b'':
                    self.logger.info(f"Client: {self.remote_addr} has disconnected.")
                    break
                
                if len(data) == expected_size:
                    arrival_time = time.time()
                    # Unpack crc and validate it
                    
                    values_data = data[:-2]
                    received_crc = struct.unpack("<H", data[-2:])[0]
                    
                    if not UDPSocket._validate_crc(values_data, received_crc):
                        self.packets_corrupted += 1
                        continue # just silenty drop the corrupted packet

                    values = list(struct.unpack(self.recv_format, values_data))
                        
                    if self._delay_tracking and self.last_packet_time:
                        interval = max(0.0, arrival_time - self.last_packet_time)
                        self._delay_n += 1
                        delta = interval - self._delay_mean
                        self._delay_mean += delta / self._delay_n
                        self._delay_m2 += delta * (interval - self._delay_mean)
                        self._delay_min = min(self._delay_min, interval)
                        self._delay_max = max(self._delay_max, interval)
                        
                    with self.data_lock:
                        self.latest_data = values.copy()
                        self.latest_timestamp = arrival_time
                        self.packets_received += 1
                        self.last_packet_time = arrival_time
                else:
                    self.logger.warning(f"Wrong packet size: expected {expected_size}, got {len(data)}")
                    self.packets_shape_invalid += 1
                
            except socket.timeout:
                continue  # Normal timeout, keep trying
            except Exception as e:
                self.logger.error(f"Error occured in receive loop: {e}")
                print(f"struct.calcsize(self.recv_format) AGAIN: {struct.calcsize(self.recv_format)}")
                print(f"self.recv_format value AGAIN: {repr(self.recv_format)}")
                print(f"id(self.recv_format): {id(self.recv_format)}")
                self.close_connection()
                if self.cleanup_callback:
                    self.cleanup_callback()
                break
        self.logger.info("Receive thread has been closed")

    def print_packet_stats(self) -> None:
        self.logger.info("="*5+" UDP PACKET STATS "+ "="*5)
        self.logger.info(f"Packets received: {self.packets_received}")
        self.logger.info(f"Packets expired: {self.packets_expired}")
        self.logger.info(f"Packets shape invalid: {self.packets_shape_invalid}")
        self.logger.info(f"Packets corrupted: {self.packets_corrupted}")
        self.logger.info(f"Last packet timestamp: {self.last_packet_time}")
    
    def print_delay_stats(self):
        self.logger.info("="*5+" UDP PACKET NETWORK DELAY STATS "+ "="*5)
        self.logger.info(f"Delay mean: {self._delay_mean * 1000} ms")
        self.logger.info(f"Delay m2: {self._delay_m2}")
        self.logger.info(f"Delay min: {self._delay_min * 1000} ms")
        self.logger.info(f"Delay max: {self._delay_max * 1000} ms")
        if self._delay_n > 1: 
            variance = self._delay_m2 / (self._delay_n - 1) 
            std_dev = variance ** 0.5
            self.logger.info(f"Delay std dev: {std_dev*1000:.2f} ms")

    def _stop_threads(self):
        current_thread=threading.current_thread()
        self._stop_receiving(current_thread)
        self._stop_heartbeat(current_thread)
        return True

    def close(self):
        """Clean shutdown."""
        if not self.running: return
        self.running = False
        self.stop_event.set()
        self._stop_threads()
        if self.socket:
            self.socket.close()
        self.logger.info("UDPSocket service has been shutdown")
        return True
            
# Note: Removed NetworkSafePWMController to keep this module focused on UDP.