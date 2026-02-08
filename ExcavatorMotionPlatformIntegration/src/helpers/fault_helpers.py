from utils.utils import is_nth_bit_on
from constants.fault_codes import CRITICAL_FAULTS, ABSOLUTE_FAULTS

def has_faulted(data):
    left, right = data
    return (is_nth_bit_on(3, left), is_nth_bit_on(3, right))

def is_critical_fault(data):
    left, right = data 
    if not left in CRITICAL_FAULTS and not right in CRITICAL_FAULTS:
        return False
    return True

def is_absolute_fault(data):
    left, right = data
    if not left in ABSOLUTE_FAULTS and not right in ABSOLUTE_FAULTS:
        return False
    return True


async def validate_fault_register(self, gui_socket) -> bool:
    """
    Check if the fault register have critical or absolute fault. Returns True if there's none.
    """
    vals = await self.check_fault_stauts(log=True)
    l_has_faulted, r_has_faulted = has_faulted(vals) 
    if (l_has_faulted or r_has_faulted):

        vals = await self.get_present_fault()

        if not vals:
            self.logger.error("Getting recent fault was not succesful")
            return False

        ### check if the fault is absolute
        if is_absolute_fault(vals):
            if gui_socket:
                await gui_socket.send(f"event=absolutefault|message=ABSOLUTE FAULT DETECTED: {ABSOLUTE_FAULTS[2048]}|")
            return False
        
        # Check that its not a critical fault
        if is_critical_fault(vals):
            if l_has_faulted:
                if gui_socket: 
                    await gui_socket.send(f"event=fault|message=CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[0]]}|")
                return False
            else:
                if gui_socket:
                    await gui_socket.send(f"event=fault|message=CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[1]]}|")
                self.logger.error(f"CRITICAL FAULT DETECTED: {CRITICAL_FAULTS[vals[1]]}")
                return False
    else:
        return True