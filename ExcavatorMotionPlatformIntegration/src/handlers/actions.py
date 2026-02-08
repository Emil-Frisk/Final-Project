
from utils.utils import convert_acc_rpm_revs, convert_to_revs, convert_vel_rpm_revs,format_response
from helpers import communication_hub_helpers as helpers
import math
from time import time
async def write(self, pitch, roll, wsclient):
    try:
        result = helpers.validate_pitch_and_roll_values(pitch,roll)
        if result:
            await self.motor_api.rotate(pitch, roll)
    except ValueError:
        
        await wsclient.send(format_response(event="error", message="message=No identity was given, example action=identify|identity=<identity>|"))
    except Exception as e:
        self.logger.error(f"Something went wrong in validating pitch and roll values: {e}")
        
async def identify(self, identity, wsclient):
    try:
        if identity:
            # Check if there is already client with the same identity, if so remove the old one

            identity = identity.lower()
            for client_socket, client_info in self.wsclients.items():
                if identity == client_info["identity"]:
                    self.logger.warning("Found an already existing client removing it...")
                    self.logger.info("?")
                    await client_socket.close()
                    del self.wsclients[client_socket]

            self.wsclients[wsclient]["identity"] = identity.lower()
            self.logger.info(f"Updated identity for {wsclient.remote_address}: {identity}")
        else:
            await wsclient.send("event=error|message=No identity was given, example action=identify|identity=<identity>|")
        if identity and identity == "gui":
            self.logger.info("Gui has been identified")
            if not self.motors_initialized:
                self.logger.info("Starting to initialize the motors")
                await self.init(wsclient)
    except Exception as e:
        self.logger.error(f"Something went wrong in identify action: {e}")

async def rotate(self, pitch, roll, wsclient):
    try:
        result = helpers.validate_pitch_and_roll_values(pitch, roll)
        if result:
            (pitch, roll) = result
            await self.motor_api.rotate(pitch,roll)
            # self.ow_file.write(f"{time() - self.start_time}\n")
            # self.ow_file.flush()

    except ValueError as e:
        self.logger.error(f"pitch and roll were not numbers: {e}")
        await wsclient.send("event=error|message=pitch and roll were not numbers. Please give integers|")
    except Exception as e:
        self.logger.error(f"Error while setting values: {e}")
        await wsclient.send("event=error|message=Something went wrong check logs server.log|")

async def clear_fault(self, wsclient):
    try:
        if not await self.motor_api.set_ieg_mode(self.motor_config.RESET_FAULT_VALUE):
            self.logger.error("Error clearing motors faults!")
            await wsclient.send("event=error|message=Error clearing motors faults!|")
        else:
            ### success case -> inform gui and fault poller
            succes_response = "event=faultcleared|message=Fault cleared succesfully!|"
            fault_poller_found = False
            await wsclient.send(succes_response) # Sending to GUI
            for sckt, info in self.wsclients.items():
                if info["identity"] == "fault poller":
                    await sckt.send(succes_response)
                    fault_poller_found = True
                    break
            if not fault_poller_found:
                self.logger.error("Fault poller not found from wsclients list at server")

            ### if motors have not been initialized -> initialize them
            if not self.motors_initialized:
                self.logger.warning("Motors have not been initialized, starting to initialize...")
                await self.init(wsclient)
    except Exception as e:
        self.logger.error("Error clearing motors faults!")
        await wsclient.send(f"event=error|message=Error clearing motors faults {e}!|")

async def message(self, receiver, wsclient, message):
    try:
        (success, receiver_client, msg) = helpers.validate_message(self,receiver,message)
        if success:
            await receiver_client.send(msg)
        else:
            await wsclient.send(msg)
    except Exception as e:
        self.logger.error(f"Something went wrong while trying to send a message {e}")

async def demo_control(self, pitch, roll):
    MODBUSCTRL_MAX = self.config
    if (pitch == "+"): # forward
        response = await self.motor_api.get_modbuscntrl_val()
        if not response:
            self.logger.error("Failed to get modbuscntrl ")

        (position_client_left, position_client_right) = response
        position_client_left = math.floor(position_client_left + (MODBUSCTRL_MAX * 0.15)) 
        position_client_right = math.floor(position_client_right + (MODBUSCTRL_MAX* 0.15)) 

        position_client_right = min(MODBUSCTRL_MAX, position_client_right)
        position_client_left = min(MODBUSCTRL_MAX, position_client_left)

        await self.motor_api.set_analog_modbus_cntrl((position_client_left, position_client_right))
    elif (pitch == "-"): #backward
        response = await self.motor_api.get_modbuscntrl_val()
        if not response:
            self.logger.error("Failed to get modbuscntrl val")
        (position_client_left, position_client_right) = response

        position_client_left = math.floor(position_client_left - (MODBUSCTRL_MAX* 0.15)) 
        position_client_right = math.floor(position_client_right - (MODBUSCTRL_MAX* 0.15)) 

        position_client_right = max(0, position_client_right)
        position_client_left = max(0, position_client_left)

        await self.motor_api.set_analog_modbus_cntrl((position_client_left, position_client_right))
    elif (roll == "-"):# left
        response = await self.motor_api.get_modbuscntrl_val()
        if not response:
            self.logger.error("Failed to get modbuscntrl val")
        (position_client_left, position_client_right) = response
        position_client_left = math.floor(position_client_left - (MODBUSCTRL_MAX* 0.08)) 
        position_client_right = math.floor(position_client_right + (MODBUSCTRL_MAX* 0.08)) 

        position_client_right = min(MODBUSCTRL_MAX, position_client_right)
        position_client_left = max(0, position_client_left)
        
        await self.motor_api.set_analog_modbus_cntrl((position_client_left, position_client_right))
    elif (roll == "+"):
        response = await self.motor_api.get_modbuscntrl_val()
        if not response:
            self.logger.error("Failed to get modbuscntrl val")
        (position_client_left, position_client_right) = response

        position_client_left = math.floor(position_client_left + (MODBUSCTRL_MAX* 0.20)) 
        position_client_right = math.floor(position_client_right - (MODBUSCTRL_MAX* 0.20)) 

        position_client_left = min(MODBUSCTRL_MAX, position_client_left)
        position_client_right = max(0, position_client_right)

        await self.motor_api.set_analog_modbus_cntrl((position_client_left, position_client_right))
    else:
        self.logger.error("Wrong parameter use direction (l | r)")
async def set_modbusvalues(self, modbus_left,modbus_right):
    try:
        modbus_left = int(float(modbus_left))
        modbus_right = int(float(modbus_right))
        await self.motor_api.set_analog_modbus_cntrl((modbus_right,modbus_left))
    except Exception as e:
        self.logger.error(f"Something went wrong while setting modbusvalues. e :{e}")
async def stop_motors(self):
    try:
        success = await self.motor_api.stop()
        if not success:
            pass # do something crazy :O
    except Exception as e:
        self.logger.error("Failed to stop motors?") # Mitäs sitten :D

async def continue_motors(self):
    try:
        success = await self.motor_api.continue_motors()
        if not success:
            pass 
    except Exception as e:
        self.logger.error("Failed to stop motors?")

async def update_input_values(self,acceleration,velocity):
    try:
        values = {"acceleration": int(acceleration), "velocity": int(velocity)}        
        if 'velocity' in values:
            (velocity_decimal, velocity_whole) = convert_vel_rpm_revs(values["velocity"])
            if not await self.motor_api.set_analog_vel_max(left_vals=(velocity_decimal, velocity_whole)):
                print("Velocity not uptaded successfully")
        if 'acceleration' in values:
            (acc_decimal, acc_whole) = convert_acc_rpm_revs(values["acceleration"])
            if not await self.motor_api.set_analog_acc_max(acc_decimal, acc_whole):
                self.logger.error("Acceleration not uptaded successfully")

        return {"status":"success"}
    except ValueError as e:
        return {"status": "error", "message": "Velocity and Acceleration has to be positive integers"}
    except Exception as e:
        self.logger.error(f"Error while updating motors values: {e}")
        return {"status": "error", "message": "Unexpected error while trying to update motors values"}
    
async def absolutefault(self):
    try:
        ### inform all processes that absolute fault has occured -> cleanup
        for client in self.wsclients:
            await client.send("event=absolutefault|message=Motors have gotten absolute fault, something very wrong has happened, they can't be operated with any longer they need repair!|")
        await self.shutdown_server()
    except Exception as e:
        self.logger.error(f"Something went wrong in absolute fault action: {e}")

async def read_telemetry(self, wsclient):
    try:
        data = await self.motor_api.get_telemetry_data()
        if not data:
            await wsclient.send(f"event=error|message=Something went wrong while reading telemetry data|")
            return False
        await wsclient.send(f"event=telemetrydata|message=boardtemp:{data[0]}*actuatortemp:{data[1]}*IC:{data[2]}*VBUS:{data[3]}*|")
    except Exception as e:
        self.logger.error(f"Something went wrong while reading telemetry data: {e}")
        await wsclient.send(f"event=error|message=Something went wrong while reading telemetry data|")
        