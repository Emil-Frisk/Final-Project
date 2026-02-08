import time
import board
from adafruit_lsm6ds.lsm6ds3 import LSM6DS3
from adafruit_lsm6ds import AccelRange, Rate, GyroRange
from smbus2 import SMBus

bus = SMBus(1)  # I2C bus 1
addr = 0x6A

accel_prev_values = None
gyro_prev_values = None
lpf_enabled = False
N = 1000

i2c = board.I2C()
sensor = LSM6DS3(i2c)
alpha = 0.1
# print(dir(sensor))

SAMPLE_RATE = 100

sample_ratemap= {
    0: "1.6 HZ",
    1: "12.5 HZ",
    2: "26 HZ",
    3: "52 HZ",
    4: "104 HZ",
    5: "208 HZ",
    6: "416 HZ",
    7: "833 HZ",
    8: "1 66K HZ",
    9: "3 33K HZ",
    10: "6 66K HZ"
}

accel_rangemap = {
    0: "2G",
    1: "4G",
    2: "8G",
    3: "16G"
}

gyro_rangemap = {
    0: "250 DPS",
    1: "500 DPS",
    2: "1000 DPS",
    3: "2000 DPS"
}

samplerates = [Rate.RATE_1_6_HZ, Rate.RATE_12_5_HZ, Rate.RATE_26_HZ, Rate.RATE_52_HZ, Rate.RATE_104_HZ, Rate.RATE_208_HZ, Rate.RATE_416_HZ, Rate.RATE_833_HZ, Rate.RATE_1_66K_HZ, Rate.RATE_3_33K_HZ, Rate.RATE_6_66K_HZ]
accel_ranges = [AccelRange.RANGE_2G, AccelRange.RANGE_4G, AccelRange.RANGE_8G, AccelRange.RANGE_16G]
gyro_ranges = [GyroRange.RANGE_250_DPS, GyroRange.RANGE_500_DPS, GyroRange.RANGE_1000_DPS, GyroRange.RANGE_2000_DPS]

def init_lsm6ds(i2c):
    return LSM6DS3(i2c)

def apply_lpf(values, sensor=1):
    global accel_prev_values
    global gyro_prev_values
    if sensor: # accel
        
        if not accel_prev_values:
            accel_prev_values = values
            return accel_prev_values
        
        accel_prev_values[0] = (1-alpha) * accel_prev_values[0] + values[0] * alpha
        accel_prev_values[1] = (1-alpha) * accel_prev_values[1] + values[1] * alpha
        accel_prev_values[2] = (1-alpha) * accel_prev_values[2] + values[2] * alpha
        return accel_prev_values.copy()
    
    else: #gyro
        if not gyro_prev_values:
            gyro_prev_values = values
            return gyro_prev_values
        
        gyro_prev_values[0] = (1-alpha) * gyro_prev_values[0] + values[0] * alpha
        gyro_prev_values[1] = (1-alpha) * gyro_prev_values[1] + values[1] * alpha
        gyro_prev_values[2] = (1-alpha) * gyro_prev_values[2] + values[2] * alpha
        return gyro_prev_values.copy()
    

def take_samples(n, sensor):
    results = []
    iteration_duration=1/SAMPLE_RATE
    
    for _ in range(n):
        desired_next = time.perf_counter() + iteration_duration
        
        accel_x, accel_y, accel_z = sensor.acceleration
        result = [accel_x, accel_y, accel_z]
        if lpf_enabled:
            result = apply_lpf(list((accel_x, accel_y, accel_z)), sensor=1)
        
        results.append(result)
        
        sleep_time = desired_next - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)
        
    return results

def take_gyro_samples(n, sensor):
    results = []
    iteration_duration=1/SAMPLE_RATE
    
    for _ in range(n):
        desired_next = time.perf_counter() + iteration_duration
        
        gyro_x, gyro_y, gyro_z = sensor.gyro
        result = [gyro_x, gyro_y, gyro_z]
        if lpf_enabled:
            result = apply_lpf(list((gyro_x, gyro_y, gyro_z)), sensor=0)
        
        results.append(result)
        
        sleep_time = desired_next - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)
        
    return results

def calculate_fluctuations(samples):
    fluctuations = []
    index = 0
    for sample in range(len(samples)-1):
        fluctuation_x = abs(samples[index+1][0] - samples[index][0])
        fluctuation_y = abs(samples[index+1][1] - samples[index][1])
        fluctuation_z = abs(samples[index+1][2] - samples[index][2])
        fluctuations.append([fluctuation_x, fluctuation_y, fluctuation_z])
        index += 1    
    return fluctuations

def calculate_fluctuations_avg(fluctuations):
    fluctuations_x = []
    fluctuations_y = []
    fluctuations_z = []
    
    i = 0
    for sample in fluctuations:
        fluctuations_x.append(sample[0])
        fluctuations_y.append(sample[1])
        fluctuations_z.append(sample[2])
        i += 1
    
    return [sum(fluctuations_x)/len(fluctuations), sum(fluctuations_y)/len(fluctuations), sum(fluctuations_z)/len(fluctuations)]

def benchmark_accel_ranges(sensor, file):
    range_index = 0
    for accel_range in accel_ranges:
        sensor.accelerometer_range = accel_range
        samples = take_samples(10000, sensor)
        fluctuations = calculate_fluctuations(samples)
        avgs = calculate_fluctuations_avg(fluctuations)
        
        file.write(f"Accel Range: {accel_rangemap[range_index]} || Avg fluctuation x: {avgs[0]}; y: {avgs[1]}; z: {avgs[2]}\n")
        print(f"Accel range: {accel_rangemap[range_index]} benchmarked...")
        range_index += 1

def benchmark_gyro_ranges(sensor, file):
    range_index = 0
    for gyro_range in gyro_ranges:
        sensor.gyro_range = gyro_range
        samples = take_gyro_samples(10000, sensor)
        fluctuations = calculate_fluctuations(samples)
        avgs = calculate_fluctuations_avg(fluctuations)
        
        file.write(f"Gyro Range: {gyro_rangemap[range_index]} || Avg fluctuation x: {avgs[0]}; y: {avgs[1]}; z: {avgs[2]}\n")
        print(f"Gyro range: {gyro_rangemap[range_index]} benchmarked...")
        range_index += 1

def benchmark_gyro_odrs(sensor, file):
    rate_index = 0
    for rate in samplerates:
        sensor.gyro_data_rate = rate
        samples = take_gyro_samples(N, sensor)
        fluctuations = calculate_fluctuations(samples)
        avgs = calculate_fluctuations_avg(fluctuations)
        
        file.write(f"Gyro sample rate: {sample_ratemap[rate_index]} || Avg fluctuation x: {avgs[0]}; y: {avgs[1]}; z: {avgs[2]}\n")
        print(f"Gyro sample rate: {sample_ratemap[rate_index]} benchmarked...")
        rate_index += 1

def benchmark_accel_odrs(sensor, file):
    rate_index = 0
    for rate in samplerates:
        sensor.accelerometer_data_rate = rate
        print(f"Accel rate: {sample_ratemap[rate_index]} benchmarked started")
        samples = take_samples(N, sensor)
        fluctuations = calculate_fluctuations(samples)
        avgs = calculate_fluctuations_avg(fluctuations)
        
        file.write(f"Accel rate: {sample_ratemap[rate_index]} || Avg fluctuation x: {avgs[0]}; y: {avgs[1]}; z: {avgs[2]}\n")
        print(f"Accel rate: {sample_ratemap[rate_index]} benchmarked...")
        rate_index += 1

def benchmark_accel_lpf(sensor, file):
    samples = take_samples(10000, sensor)
    fluctuations = calculate_fluctuations(samples)
    avgs = calculate_fluctuations_avg(fluctuations)
    file.write(f"{avgs[0]},{avgs[1]},{avgs[2]}")
    
def benchmark_gyro_lpf(sensor, file):
    samples = take_gyro_samples(10000, sensor)
    fluctuations = calculate_fluctuations(samples)
    avgs = calculate_fluctuations_avg(fluctuations)
    file.write(f"{avgs[0]},{avgs[1]},{avgs[2]}")

if __name__ == "__main__":
    try:
        file = open("lsm6ds_benchmark_odrs.txt", "a")
        # i2c = board.I2C()  # uses board.SCL and board.SDA
        # sensor = init_lsm6ds(i2c)
        
        addr = 0x6A
        print("enabling lpf2")
        # bus.write_byte_data(addr,0x17, 128) ## LPF2 on on accelerometer
        
        print(f"17h registers value before: {bus.read_byte_data(addr, 0x17)}")
        sensor.accelerometer_data_rate = Rate.RATE_104_HZ
        sensor.accelerometer_range = AccelRange.RANGE_2G
        sensor.gyro_range = GyroRange.RANGE_250_DPS
        print(f"17h registers value after: {bus.read_byte_data(addr, 0x17)}\n")
        print(f"acc range: {sensor.gyro_range}")
        
        ### Double check LPF 2 (integrated)
        # bus.write_byte_data(addr,0x17, 128) ## LPF2 on on accelerometer
        
        # benchmark_accel_odrs(sensor, file)
        # file.write("=== ACCELEROMETER ODR BENCHMARK ===\n")
        # benchmark_accel_odrs(sensor, file)
        
        # file.write("\n=== GYRO ODR BENCHMARK ===\n")
        # benchmark_gyro_odrs(sensor, file)
    finally:        
        file.close()