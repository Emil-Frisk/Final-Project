import socket
import threading
import logging
import sys

class TCPSocketClient():
    def __init__(self, port=7001, host="localhost", logger=None, on_message_received=None):
        self.host = host
        self.port = port
        self.is_running = False
        self.client_socket = None
        self.logger= self._setup_logger(logger)
        self.on_message_received = on_message_received

    def _start_thread(self, f, *args):
        thread = threading.Thread(
                        args=args,
                        target=f
                    )
        thread.daemon = True
        thread.start()

    def _setup_logger(self, logger):
        """Set up logger with sensible defaults"""
        if logger:
            return logger
        
        # Create default logger
        logger_name = f"TCPClient-{self.host}:{self.port}"
        default_logger = logging.getLogger(logger_name)
        
        # Only configure if not already configured
        if not default_logger.handlers:
            default_logger.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
            console_handler.setFormatter(formatter)
            default_logger.addHandler(console_handler)
        
        return default_logger
    
    def connect(self):
        self.client_socket = self._create_client()
        if self.client_socket:
            self._start_thread(self._listen)

    def send_message(self, msg):
        try:
            if self.is_running and self.client_socket:
                if isinstance(msg, str):
                    data = msg.encode("utf-8")
                elif isinstance(msg, bytes):
                    data = msg
                elif isinstance(msg, (dict, list, tuple)):
                    import json
                    data = json.dumps(msg).encode("utf-8")
                else:
                    data = str(msg).encode("utf-8")
                    
                self.client_socket.send(data)
                self.logger.info(f"Sent {len(data)} bytes")
        except Exception as e:
            self.logger.error(f"Failed to send a message: {e}") 

    def _create_client(self):
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((self.host, self.port))
            self.logger.info(f"Client connected to server: {self.host}:{self.port}")
            self.is_running = True
            return client_socket
        except Exception as e:
            self.logger.error(f"Failed to create client: {e}") 
            return None

    def _listen(self):
        try:
            self.client_socket.settimeout(1.0)
            self.logger.info("Starting to listen...")
            while self.is_running:
                try:
                    data = self.client_socket.recv(1024) 
                    if data:
                        msg = data.decode("utf-8")
                        self.logger.info(f"Data received: {msg}")
                        if self.on_message_received:
                            self.on_message_received(msg)
                    else:
                        self.logger.info("Client disconnected from the server")
                except socket.timeout:
                    continue

            self.logger.info("Client is not listening for messages anymore")
        except Exception as e:
            self.logger.error(f"Something went wrong while listening for messages. Context: {e}")

    def close(self):
        try:
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None
                self.is_running = False
                self.logger.info("Cleaned up client")
        except Exception as e:
            self.logger.error(f"Something went wrong while closing the socket server. {e}")