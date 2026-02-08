# fault_codes.py
CRITICAL_FAULTS = {
    1: "Current in the actuator was too large.",
    2: "Continuous current in the actuator was too large",
    16: "Low bus voltage",
    32: "High DC Bus Voltage, voltage was too large: decrease the acceleration",
    64: "Following error: this should not happen",
    128: "Board temperature is too high",
    256: "Servo motor has reached too high temperature"
}

ABSOLUTE_FAULTS = {
    4: "ABSOLUTE FAULT: Position tracking error. Motors need to be repaired", 
    2048: "ABSOLUTE FAULT: Something is seriously wrong with the DC bus wirings. DO NOT use this system anymore it needs repair"
}
