

def validate_pitch_and_roll_values(pitch,roll):
    try:
        pitch = float(pitch)
        roll = float(roll)
        return True
    except:
        raise
        
        
    
def validate_message(self,receiver, message):
    
    if not message:
        return (False, None, "event=error|message=Action message given, but no actual message found, example: message=<message>|")
    
    if not receiver:
        return (False, None, "event=error|message=No receiver given in the message, example: receiver=<receiver>|")

    for client, info in self.wsclients.items():
        if info["identity"] == receiver:
            return (True, client, message)
        
    return (False, None, "event=error|message=No receiver was found in the server with this identity|")

