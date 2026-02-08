from utils.setup_logging import setup_logging
from ModbusClients import ModbusClients
from services.MotorApi import MotorApi
from utils.launch_params import handle_launch_params
import asyncio
from utils.utils import  extract_part
from helpers.fault_helpers import has_faulted, is_critical_fault, is_absolute_fault
from constants.fault_codes import ABSOLUTE_FAULTS, CRITICAL_FAULTS
from services.WebSocketClient import WebSocketClient
from settings.motors_config import MotorConfig

class FaultPoller():
    def __init__(self):
        self.has_faulted = False
        self.wsclient = None

    def on_message(self, msg):
        event = extract_part("event=", msg)
        message = extract_part("message=", msg)
        if not event:
            self.logger.error("wsclient message does not have event specified in it.")
            return
        
        if not message:
            self.logger.error("server did not specify message part")
            return
        
        if event == "error":
            self.logger.error(message)

        ### Lets fault poller continue the loop again
        if event == "faultcleared":
            self.has_faulted = False
            self.logger.info("Fault has cleared starting polling loop again")

    async def main(self):
        self.logger = setup_logging("faul_poller", "faul_poller.log", extensive_logging=True)
        config = handle_launch_params()
        motor_config = MotorConfig()
        clients = ModbusClients(config=config, logger=self.logger)
        connected = await clients.connect()
        if (not connected):
            return
        
        motor_api = MotorApi(logger=self.logger, modbus_clients=clients)
        wsclient = WebSocketClient(identity="fault poller", logger=self.logger, on_message=self.on_message)
        self.wsclient = wsclient
        await wsclient.connect()

        self.logger.info(f"Starting polling loop with polling time interval: {config.POLLING_TIME_INTERVAL}")
        try:
            counter = 0
            while(True):
                counter += 1
                await asyncio.sleep(config.POLLING_TIME_INTERVAL)
                if self.has_faulted:
                    await asyncio.sleep(5)
                    continue

                ### simulated critical fault situation
                # if counter == 3:
                #     await wsclient.send(f"event=fault|action=message|message=CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[2]}|receiver=GUI|")
                #     self.logger.error(f"CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[2]}")
                #     self.has_faulted = True
                #     continue
                # await asyncio.sleep(1)

                vals = await motor_api.check_fault_stauts(log=False)

                if not vals: ### something went wrong
                    self.logger.error("something went wrong while checkigng fault status")
                    continue

                l_has_faulted, r_has_faulted = has_faulted(vals)
                if (l_has_faulted or r_has_faulted):
                    vals = await motor_api.get_present_fault()

                    if not vals:
                        self.logger.error("Getting recent fault was not succesful")
                        continue

                    ## check if the fault is absolute
                    if is_absolute_fault(vals):
                        await wsclient.send(f"event=fault|action=absolutefault|message=ABSOLUTE FAULT DETECTED: {ABSOLUTE_FAULTS[2048]}|receiver=GUI|")
                        self.logger.error(f"absolutefault DETECTED: {ABSOLUTE_FAULTS[2048]}")
                        self.logger.error(f"Stopping polling...")
                        self.has_faulted = True
                        continue

                    # Check that its not a critical fault
                    if is_critical_fault(vals):
                        if l_has_faulted:
                            await wsclient.send(f"event=fault|action=message|message=CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[0]]}|receiver=GUI|")
                            self.logger.error(f"CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[0]]}")
                        else:
                            await wsclient.send(f"event=fault|action=message|message=CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[1]]}|receiver=GUI|")
                            self.logger.error(f"CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[1]]}")
                        self.has_faulted = True
                    else:
                        ### raise reset fault bit and reset the register to 0
                        await motor_api.set_ieg_mode(motor_config.RESET_FAULT_VALUE)
                        await motor_api.set_ieg_mode(0)
                        self.logger.info("Fault cleared")
        except KeyboardInterrupt:
            self.logger.info("Polling stopped by user")
        except Exception as e:
            self.logger.error(f"Unexpected error in polling loop: {str(e)}")
        finally:
            clients.cleanup()
            self.logger.info("Fault poller has been closed")
            self.wsclient.close()

if __name__ == "__main__":
    fault_poller = FaultPoller()
    asyncio.run(fault_poller.main())