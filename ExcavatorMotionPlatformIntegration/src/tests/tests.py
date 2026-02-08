from helpers.motor_api_helper import clamp_target_revs
from settings.motors_config import MotorConfig
from services.MotorApi import MotorApi
from ModbusClients import ModbusClients
from settings.config import Config
from utils.setup_logging import setup_logging
import asyncio

def test_urev_clamp():
    ### In range
    assert clamp_target_revs(20.0, 20.0, config) == [[0, 20], [0, 20]]
    assert clamp_target_revs(21.0, 19.0, config) == [[0, 21], [0, 19]]
    assert clamp_target_revs(21.5, 19.25, config) == [[32768, 21], [16384, 19]]
    assert clamp_target_revs(21.25, 19.5, config) == [[16384, 21], [32768, 19]]
    assert clamp_target_revs(21.75, 19.5, config) == [[16384+32768, 21], [32768, 19]]
    assert clamp_target_revs(21.99999999999, 19.5, config) == [[65535, 21], [32768, 19]]
    assert clamp_target_revs(21.99999999999, 19.99999999999, config) == [[65535, 21], [65535, 19]]
    assert clamp_target_revs(21.0, 19.99999999999, config) == [[0, 21], [65535, 19]]
    assert clamp_target_revs(21, 16, config) == [[0, 21], [0, 16]]
    
    ### Overshoot
    assert clamp_target_revs(300.99999999999, 20.5, config) == [[61406, 28], [32768, 20]]
    assert clamp_target_revs(300.25, 20.5, config) == [[16384, 28], [32768, 20]]
    assert clamp_target_revs(300.99999999999, 20.25, config) == [[61406, 28], [16384, 20]]
    assert clamp_target_revs(300.99999999999, 28.99999999999, config) == [[61406, 28], [61406, 28]]
    assert clamp_target_revs(16.25, 300.50, config) == [[16384, 16], [32768, 28]]
    assert clamp_target_revs(16.25, 300.99999999999, config) == [[16384, 16], [61406, 28]]
    
    ### Undershoot
    assert clamp_target_revs(-300.01, 0.01, config) == [[25801, 0], [25801, 0]]
    assert clamp_target_revs(-300.01, 10.0, config) == [[25801, 0], [0, 10]]
    assert clamp_target_revs(-300.01, 28.0, config) == [[25801, 0], [0, 28]]
    assert clamp_target_revs(-300.01, 28.99999999999, config) == [[25801, 0], [61406, 28]]
    assert clamp_target_revs(20.25, -300.01, config) == [[16384, 20], [25801, 0]]
    assert clamp_target_revs(28.25, -300.01, config) == [[16384, 28], [25801, 0]]
    assert clamp_target_revs(29.25, -300.01, config) == [[16384, 28], [25801, 0]]
    assert clamp_target_revs(29.99999999999, -300.01, config) == [[61406, 28], [25801, 0]]
    assert clamp_target_revs(29.99999999999, -300.5, config) == [[61406, 28], [32768, 0]]
    

# async def _test_analog_velocity():
#     logger = setup_logging(name="tests", filename="tests.log", extensive_logging=False, log_to_file=False)
#     motor_config = MotorConfig()
#     config = Config()
#     modbus_clinets = ModbusClients(config=config)
#     await modbus_clinets.connect()
#     motor_api = MotorApi(modbus_clients=modbus_clinets,config=motor_config)
#     await motor_api.set_analog_vel_max(left_motor=True,left_vals=[0,0] ,both_motors=False)

# # [[left_Decimal[[28], [r_decimal, r_whole]] = clamp_target_revs(29.99999999999, -300.5, config)
# a = 10

# if __name__ == "__main__":
#     asyncio.run(_test_analog_velocity())