from time import sleep
import socket
import threading
from dataclass_types import ExcavatorAPIProperties

class ServiceListener:
    def __init__(self, ip, port, service_name, cleanup_cb=None):
        """
        Initialize the ServiceListener.
        
        Args:
            ip (str): IP address to bind to
            port (int): Port number to listen on
            service_name (str): Name of the service
        """
        self.ip = ip
        self.port = port
        self.cleanup_cb=cleanup_cb
        self.service_name = service_name
        self.stop_event = threading.Event()
        self.running=False
        self.socket = None
        self.client_socket = None
        self.client_address = None 
        self.listener_thread=None
    
    def wait_for_ready(self, n=9):
        """Polls ready for n seconds"""
        for _ in range(n):
            if self.running is True:
                return True
            sleep(1)
        return False
    
    def start(self):
        """
        Start the service listener. Creates a TCP socket, binds to the
        specified IP and port, listens for a client connection, then enters
        a message receiving loop until stop_event is set.
        """
        self.listener_thread=threading.current_thread()
        
        # Create TCP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.ip, self.port))
        
        # Listen for incoming connection
        self.socket.listen(1)
        print(f"[Service Manger - {self.service_name}] Listening on {self.ip}:{self.port}")
        self.running=True
        # Accept a single client connection
        self.client_socket, self.client_address = self.socket.accept()
        print(f"[Service Manger - {self.service_name}] Client connected from {self.client_address}")
        
        # Message receiving loop
        while not self.stop_event.is_set():
            try:
                # Set a timeout to allow checking stop_event periodically
                self.client_socket.settimeout(1.0)
                message = self.client_socket.recv(1024)
                
                if message:
                    print(f"[Service Manger - {self.service_name}] Received: {message.decode('utf-8', errors='ignore')}")
                else:
                    # Empty message means client disconnected
                    print(f"[Service Manger - {self.service_name}] Client disconnected")
                    break
                    
            except socket.timeout:
                # Timeout is expected, just continue checking stop_event
                continue
            except Exception as e:
                print(f"[Service Manger - {self.service_name}] Error while listening for service: {self.service_name} - e: {e}")
                if self.cleanup_cb is not None:
                    self.cleanup_cb()
                break
        
    
    def close(self, calling_thread):
        """
        Clean up all resources. Sets the stop event and closes all sockets.
        """
        print(f"[Service Manger - {self.service_name}] Closing service listener")
        self.stop_event.set()
        
        if self.client_socket:
            try:
                if self.listener_thread != calling_thread and self.listener_thread.is_alive():
                    self.listener_thread.join(ExcavatorAPIProperties.SHUTDOWN_GRACE_PERIOD)
                self.client_socket.close()
            except:
                pass
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        
        self.running=False
        self.socket=None
        self.stop_event.clear()
        self.client_address=None
        self.client_address=None
        print(f"[Service Manger - {self.service_name}] Service listener closed")
        
if __name__ == "__main__":
    try:
        sl=ServiceListener(ip="0.0.0.0", port=7123, service_name="udp_socket")
        thr=threading.Thread(target=sl.start,daemon=True)
        thr.start()
        while True:
            sleep(1)
    except KeyboardInterrupt:
        sl.close()
        thr.join(5)