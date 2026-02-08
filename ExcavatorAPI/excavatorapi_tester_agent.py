from tcp_client import TCPClient
from PCA9685_controller import PumpConfig, ChannelConfig
from dataclasses import asdict
import copy
from time import sleep

test_count=0

"""
Agent that tests all excavatorAPI:s public actions 
"""

def wait_for_signal(tester_agent, test_name,timeout=25):
    global test_count
    for _ in range(timeout):
        if tester_agent.test_continuation_signal.is_set():
            tester_agent.test_continuation_signal.clear()
            test_count+=1
            return True
        sleep(1)
    tester_agent.test_continuation_signal.clear()
    raise RuntimeError(f"Test {test_name} timeout while waiting for servers response. {test_count} tests succeeded")

def validate_config(config_name, new_config, updated_config):
    if new_config is None:
        raise RuntimeError(f"New config is none")
    
    for property, expected_val in new_config.items():
        if updated_config[property] != expected_val:
            print(f"Config {config_name} did not update as expected. Property: {property} - expected_val: {expected_val} - actual val {updated_config[property]}")
            raise RuntimeError(f"Config {config_name} did not update as expected. Property: {property} - expected_val: {expected_val}")

def check_errors(tester_agent, expected_errors):
    if tester_agent.errors_counter != expected_errors:
        raise RuntimeError("Some unepexted errors occured?")
if __name__ == "__main__":
    try:
        # tester_agent = TCPClient(testing_enabled=True)
        tester_agent = TCPClient(testing_enabled=True, srv_ip="10.214.33.27")
        expected_errors=0
        if tester_agent.start():
            print("Tester agent awekens")
            ######## SCREEN ################
            # tester_agent.stop_screen()
            # result=wait_for_signal(tester_agent=tester_agent, test_name="stop_screen")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.start_screen()
            # wait_for_signal(tester_agent=tester_agent, test_name="start_screen")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)

            # tester_agent.get_screen_status()
            # result=wait_for_signal(tester_agent=tester_agent, test_name="get_screen_status")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.send_screen_message("Test header", body="LOng body... LOng body... LOng body... LOng body... LOng body... LOng body... ")
            # wait_for_signal(tester_agent=tester_agent, test_name="send_screen_message")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            # ########### MIRRORING ################
            # tester_agent.start_mirroring()
            # wait_for_signal(tester_agent=tester_agent, test_name="start_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.get_orientation_tracker_status()
            # result=wait_for_signal(tester_agent=tester_agent, test_name="get_orientation_tracker_status")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.get_mirroring_status()
            # result=wait_for_signal(tester_agent=tester_agent, test_name="get_mirroring_status")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # sleep(3)
            
            # expected_errors+=1
            # tester_agent.start_mirroring()
            # wait_for_signal(tester_agent=tester_agent, test_name="start_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.stop_mirroring()
            # wait_for_signal(tester_agent=tester_agent, test_name="stop_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)


            
            
            
            
            
            
            
            
            
            
            # ########## DRIVING ################
            # tester_agent.start_driving(["lift_boom"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            # sleep(3)
            
            # expected_errors+=1
            # tester_agent.start_driving(["lift_boom"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)

            # tester_agent.stop_driving()
            # wait_for_signal(tester_agent=tester_agent, test_name="stop_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # sleep(3)

            # expected_errors+=1
            # tester_agent.start_driving(["heheheheh"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # expected_errors+=1
            # tester_agent.start_driving(["lift_boom","lowl"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.start_driving(["lift_boom","tilt_boom", "scoop", "rotate"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            # sleep(3)
            
            # expected_errors+=1
            # tester_agent.start_driving(["pump"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.stop_driving()
            # wait_for_signal(tester_agent=tester_agent, test_name="stop_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            # ########## DRIVING AND MIRRORING ################
            # tester_agent.start_driving_and_mirroring(channel_names=["lift_boom"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            # sleep(3)
            
            # expected_errors+=1
            # tester_agent.start_driving_and_mirroring(channel_names=["lift_boom"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)

            # tester_agent.stop_driving_and_mirroring()
            # wait_for_signal(tester_agent=tester_agent, test_name="stop_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # expected_errors+=1
            # tester_agent.start_driving_and_mirroring(channel_names=["heheheheh"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # expected_errors+=1
            # tester_agent.start_driving_and_mirroring(channel_names=["lift_boom","lowl"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # # Some problem w this?
            # tester_agent.start_driving_and_mirroring(channel_names=["lift_boom","tilt_boom", "scoop", "rotate"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            # sleep(3)
            
            # expected_errors+=1
            # tester_agent.start_driving_and_mirroring(channel_names=["pump"])
            # wait_for_signal(tester_agent=tester_agent, test_name="start_driving")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # expected_errors+=1
            # tester_agent.start_driving_and_mirroring(channel_names=["lift_boom"], orientation_send_rate="HAHAHAHAH")
            # wait_for_signal(tester_agent=tester_agent, test_name="start_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # expected_errors+=1
            # tester_agent.start_driving_and_mirroring(channel_names=["lift_boom"], orientation_send_rate=1200)
            # wait_for_signal(tester_agent=tester_agent, test_name="start_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # tester_agent.stop_driving_and_mirroring()
            # wait_for_signal(tester_agent=tester_agent, test_name="stop_driving_and_mirroring")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            
            
            
            
            
            
            
            
            
            
            
            



            ######### CONFIGURE EXCAVATOR ################
            # tester_agent.get_excavator_config()
            # wait_for_signal(tester_agent=tester_agent, test_name="get_excavator_config")
            # original_cfg=copy.deepcopy(tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)

            # new_config={"has_screen": not original_cfg["has_screen"]}
            # tester_agent.configure_excavator(has_screen=new_config["has_screen"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_screen")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)

            # # Back to original
            # tester_agent.configure_excavator(has_screen=original_cfg["has_screen"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_screen")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
















            
            # ######### CONFIGURE SCREEN ################
            # tester_agent.get_screen_config()
            # wait_for_signal(tester_agent=tester_agent, test_name="get_screen_config")
            # original_cfg=copy.deepcopy(tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # expected_errors+=1
            # new_config={"render_time": 36,"font_size_body":31,"font_size_header":17}
            # tester_agent.configure_screen(default_render_time=new_config["render_time"], font_size_header=new_config["font_size_header"], font_size_body=new_config["font_size_body"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_screen")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # new_config={"render_time": 3,"font_size_body":5,"font_size_header":17}
            # print(f"Original config: {original_cfg} - type {type(original_cfg)}")
            # new_config["render_time"] = original_cfg["render_time"]+1
            # tester_agent.configure_screen(default_render_time=new_config["render_time"], font_size_header=new_config["font_size_header"], font_size_body=new_config["font_size_body"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_screen")
            # validate_config(config_name="screen_config", new_config=new_config, updated_config=tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # # Put the original config back
            # tester_agent.configure_screen(default_render_time=original_cfg["render_time"], font_size_header=original_cfg["font_size_header"], font_size_body=original_cfg["font_size_body"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_screen")
            # validate_config(config_name="screen_config", new_config=original_cfg, updated_config=tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            # ######### CONFIGURE ORIENTATION_TRACKER ################
            # tester_agent.get_orientation_tracker_config()
            # wait_for_signal(tester_agent=tester_agent, test_name="get_orientation_tracker_config")
            # original_cfg=copy.deepcopy(tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # new_config = {"gyro_data_rate": 104, "accel_data_rate": 104, "gyro_range": 250, "accel_range": 4, "enable_lpf2": True, "enable_simple_lpf": True, "alpha": 0.09, "tracking_rate": 100}
            # new_config["tracking_rate"]=original_cfg["tracking_rate"]+1
            # tester_agent.configure_orientation_tracker(gyro_data_rate=new_config["gyro_data_rate"], accel_data_rate=new_config["accel_data_rate"], gyro_range=new_config["gyro_range"], accel_range=new_config["accel_range"], enable_lpf2=new_config["enable_lpf2"], enable_simple_lpf=new_config["enable_simple_lpf"], alpha=new_config["alpha"], tracking_rate=new_config["tracking_rate"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_orientation_tracker")
            # validate_config(config_name="configure_orientation_tracker", new_config=new_config, updated_config=tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # new_config["gyro_data_rate"]=208
            # tester_agent.configure_orientation_tracker(gyro_data_rate=new_config["gyro_data_rate"], accel_data_rate=new_config["accel_data_rate"], gyro_range=new_config["gyro_range"], accel_range=new_config["accel_range"], enable_lpf2=new_config["enable_lpf2"], enable_simple_lpf=new_config["enable_simple_lpf"], alpha=new_config["alpha"], tracking_rate=new_config["tracking_rate"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_orientation_tracker")
            # validate_config(config_name="configure_orientation_tracker", new_config=new_config, updated_config=tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # new_config["gyro_data_rate"]=300
            # expected_errors+=1
            # tester_agent.configure_orientation_tracker(gyro_data_rate=new_config["gyro_data_rate"], accel_data_rate=new_config["accel_data_rate"], gyro_range=new_config["gyro_range"], accel_range=new_config["accel_range"], enable_lpf2=new_config["enable_lpf2"], enable_simple_lpf=new_config["enable_simple_lpf"], alpha=new_config["alpha"], tracking_rate=new_config["tracking_rate"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_orientation_tracker")
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            # Put original cfg back
            # tester_agent.configure_orientation_tracker(gyro_data_rate=original_cfg["gyro_data_rate"], accel_data_rate=original_cfg["accel_data_rate"], gyro_range=original_cfg["gyro_range"], accel_range=original_cfg["accel_range"], enable_lpf2=original_cfg["enable_lpf2"], enable_simple_lpf=original_cfg["enable_simple_lpf"], alpha=original_cfg["alpha"], tracking_rate=original_cfg["tracking_rate"])
            # wait_for_signal(tester_agent=tester_agent, test_name="configure_orientation_tracker")
            # validate_config(config_name="configure_orientation_tracker", new_config=original_cfg, updated_config=tester_agent.recent_config)
            # check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            # ########### CONFIGURE PWM_CONTROLLER ################
            tester_agent.get_pwm_config()
            wait_for_signal(tester_agent=tester_agent, test_name="get_pwm_config")
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            original_cfg=copy.deepcopy(tester_agent.recent_config)
            original_pump=original_cfg["CHANNEL_CONFIGS"]["pump"].copy()
            original_tilt_boom=original_cfg["CHANNEL_CONFIGS"]["tilt_boom"].copy()
            
            chan_cfg=ChannelConfig(output_channel=12,pulse_min=1100,pulse_max=2345,direction=1)
            channel_name="new_channel"
            new_config=asdict(chan_cfg)


            ### PUMP ALONE
            new_pump=original_pump.copy()
            new_pump["pulse_min"] = original_pump["pulse_min"]+1
            
            tester_agent.configure_pwm_controller(pump=new_pump)
            wait_for_signal(tester_agent=tester_agent, test_name="configure_pwm_controller")
            updated_cfg=tester_agent.recent_config["CHANNEL_CONFIGS"]["pump"]
            validate_config(config_name="pwm_channel", new_config=new_pump, updated_config=updated_cfg)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            ### Set back to original
            tester_agent.configure_pwm_controller(pump=original_pump)
            wait_for_signal(tester_agent=tester_agent, test_name="configure_pwm_controller")
            updated_cfg=tester_agent.recent_config["CHANNEL_CONFIGS"]["pump"]
            validate_config(config_name="pwm_channel", new_config=original_pump, updated_config=updated_cfg)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            ### --- ###
            
            
            ### CHANNEL CONFIG ALONE
            new_tilt_boom=original_tilt_boom.copy()
            old_dir=original_tilt_boom["direction"]
            new_dir=0
            
            new_dir = -1 if old_dir > 0 else 1
            new_tilt_boom["direction"]=new_dir
            channel_configs={"tilt_boom":new_tilt_boom}
            
            tester_agent.configure_pwm_controller(channel_configs=channel_configs)
            wait_for_signal(tester_agent=tester_agent, test_name="configure_pwm_controller")
            updated_cfg=tester_agent.recent_config["CHANNEL_CONFIGS"]["tilt_boom"]
            validate_config(config_name="pwm_channel", new_config=new_tilt_boom, updated_config=updated_cfg)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            
            ### Set back to original
            sleep(3)
            tester_agent.configure_pwm_controller(channel_configs={"tilt_boom":original_tilt_boom})
            wait_for_signal(tester_agent=tester_agent, test_name="configure_pwm_controller")
            updated_cfg=tester_agent.recent_config["CHANNEL_CONFIGS"]["tilt_boom"]
            validate_config(config_name="pwm_channel", new_config=original_tilt_boom, updated_config=updated_cfg)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            ### --- ###
            
            ### CHANNEL CONFIG AND PUMP UPDATE AT THE SAME TIME
            new_pump["pulse_max"] = original_pump["pulse_max"]+300
            new_pump["pulse_min"] = 606
            channel_configs["tilt_boom"]["deadzone"] = original_tilt_boom["deadzone"] + 0.1
            
            
            tester_agent.configure_pwm_controller(pump=new_pump,channel_configs=channel_configs)
            wait_for_signal(tester_agent=tester_agent, test_name="configure_pwm_controller")
            updated_tilt_boom=tester_agent.recent_config["CHANNEL_CONFIGS"]["tilt_boom"]
            updated_pump=tester_agent.recent_config["CHANNEL_CONFIGS"]["pump"]
            validate_config(config_name="pwm_channel", new_config=new_pump, updated_config=updated_pump)
            validate_config(config_name="pwm_channel", new_config=channel_configs["tilt_boom"], updated_config=updated_tilt_boom)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)

            ### Set back to original
            tester_agent.configure_pwm_controller(pump=original_pump, channel_configs={"tilt_boom":original_tilt_boom})
            wait_for_signal(tester_agent=tester_agent, test_name="configure_pwm_controller")
            updated_tilt_boom=tester_agent.recent_config["CHANNEL_CONFIGS"]["tilt_boom"]
            updated_pump=tester_agent.recent_config["CHANNEL_CONFIGS"]["pump"]
            validate_config(config_name="pwm_channel", new_config=original_tilt_boom, updated_config=updated_tilt_boom)
            validate_config(config_name="pwm_channel", new_config=original_pump, updated_config=updated_pump)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            ### --- ###

            ## ADD PWM CHANNEL
            tester_agent.add_pwm_channel(channel_name=channel_name, channel_type="channel_config",config=new_config)
            wait_for_signal(tester_agent=tester_agent, test_name="add_pwm_channel")
            updated_cfg=tester_agent.recent_config["CHANNEL_CONFIGS"][channel_name]
            validate_config(config_name="pwm_channel", new_config=new_config, updated_config=updated_cfg)
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            ## --- ###
            
            ## REMOVE PWM CHANNEL
            tester_agent.remove_pwm_channel(channel_name=channel_name)
            wait_for_signal(tester_agent=tester_agent, test_name="remove_pwm_channel")
            updated_cfg=tester_agent.recent_config["CHANNEL_CONFIGS"].get(channel_name)
            if updated_cfg is not None:
                raise RuntimeError(f"Removing PWM Channel {channel_name} failed")
            check_errors(tester_agent=tester_agent,expected_errors=expected_errors)
            # --- ###
            
            tester_agent.shutdown()
            
            print(f"All of {test_count} tests succeeded!")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Tester agent error: {e}")
    