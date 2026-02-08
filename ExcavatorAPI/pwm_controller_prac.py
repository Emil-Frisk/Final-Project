from time import sleep
from PCA9685_controller import PWMController

if __name__ == "__main__":
    try:
        pwm_controller = PWMController(log_level="DEBUG")
        for _ in range(5):
                if _ % 2 == 0:
                pwm_controller.update_named(commands={"lift_boom": 0.7})
            elif _ % 7 == 0:
                # pwm_controller.reset(True)
                print("Pööö")
            else:
                pwm_controller.update_named(commands={"lift_boom": -0.2})
            sleep(2)
        pwm_controller._simple_cleanup()
    except Exception as e:
        print(f"Fail: {e}")
    
