from dataclasses import dataclass

@dataclass
class Config:
    WEBSOCKET_SRV_PORT = 7000
    
    ### SERVER CONFIG
    SERVER_IP_LEFT: str = '192.168.0.211'  
    SERVER_IP_RIGHT: str = '192.168.0.212'
    SERVER_PORT: int = 502  
    WEB_SERVER_PORT: int = 5001

    ### USEFUL MAX VALUES
    UINT32_MAX = 65535

    ### 
    MODULE_NAME = None
    POLLING_TIME_INTERVAL: int = 5
    POS_UPDATE_HZ: int = 1
    START_TID: int = 10001 # first TID will be startTID + 1
    LAST_TID: int = 20000
    CONNECTION_TRY_COUNT = 5

    #Motorapi rate limit
    RATELIMIT = 60