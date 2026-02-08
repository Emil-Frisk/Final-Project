import argparse
from settings.config import Config
from settings.motors_config import MotorConfig
import sys

def handle_launch_params(b_motor_config=False):
    module_name = sys.argv[0]
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, help="port number")
    parser.add_argument("--server_left", type=str, help="left side motor ip")
    parser.add_argument("--server_right", type=str, help="right side motor ip")
    parser.add_argument("--vel", type=int, help="max rpm velocity")
    parser.add_argument("--acc", type=int, help="max rpm acceleration")
    parser.add_argument("--slaveid", type=int, help="drivers slave id")
    parser.add_argument("--polling_time_interval", type=int, help="polling time interval")
    parser.add_argument("--start_tid", type=int, help="start tid")
    parser.add_argument("--end_tid", type=int, help="end tid")
    parser.add_argument("--web_server_port", type=int, help="end tid")

    config = Config()
    motor_config =  MotorConfig()
    config.MODULE_NAME = module_name

    if ("fault_poller.py" in module_name):
        config.START_TID = 30000
        config.LAST_TID = 40000
    elif (module_name in "palvelin.py"):
        config.START_TID = 1
        config.LAST_TID = 10000

    args = parser.parse_known_args()
    args = args[0]
    if (args.port):
        config.SERVER_PORT = args.port
    if (args.acc):
        motor_config.MAX_ACC = args.acc
    if (args.vel):
        motor_config.MAX_VEL = args.vel
    if (args.server_left):
        config.SERVER_IP_LEFT = args.server_left
    if (args.server_right):
        config.SERVER_IP_RIGHT = args.server_right
    if (args.slaveid):
        config.SLAVE_ID = args.slaveid
    if (args.polling_time_interval):
        config.POLLING_TIME_INTERVAL = args.time_interval
    if (args.start_tid):
        config.START_TID = args.start_tid
    if (args.end_tid):
        config.LAST_TID = args.end_tid
    if (args.web_server_port):
        config.WEB_SERVER_PORT = args.web_server_port
    if b_motor_config == True:
        return config,motor_config
    return config