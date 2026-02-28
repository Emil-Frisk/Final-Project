# Final Project
This project was built for the [Ai-MaSi](https://github.com/AI-MaSi) project. The purpose of this solution was to integrate many separate modules into one easy use case.

## Starting situation
There was miniature excavator which has Raspberry Pi 5 with [PWM signal chip](https://learn.adafruit.com/adafruit-16-channel-pwm-servo-hat-for-raspberry-pi/) that can output 16 different DC PWM signals.

![Miniature Excavator](./documentation/images/Pienoiskaivuri.jpg)

There was also a motion platform that can be controller with this [API](https://github.com/Emil-Frisk/Motion-Platform-).

![Miniature Excavator](./documentation/images/liikealusta.jpg)

The end goal was to install this [IMU](https://www.adafruit.com/product/4503) sensor on top of the excavator and mirror its orientation with the motion platform while remote driving it with the motion platforms controller.

You can see the final result [here](https://youtu.be/n0L2oRUeU-k).

# Advanced Branch
Advanced branch has implementation where UDPSocket has been done with c++ instead. BuildUDPSocket folder has build build details. C++ implementation is 100x faster ~110 microseconds.