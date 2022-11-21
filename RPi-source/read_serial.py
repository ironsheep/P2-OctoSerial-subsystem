#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
UART communication on Raspberry Pi using Python
http://www.electronicwings.com
'''
import serial
from time import sleep

"""
ser = serial.Serial ("/dev/serial0", 2000000)    #Open port with baud rate & timeout
while True:
    received_data = ser.read()              #read serial port
    print (received_data)                   #print received data
    #sleep(0.03)
    data_left = ser.inWaiting()             #check for remaining byte
    received_data += ser.read(data_left)
    print (received_data)                   #print received data
    #ser.write(received_data)
"""

log_file  =  open('f1', 'w')
ser = serial.Serial ("/dev/serial0", 2000000, timeout=1)    #Open port with baud rate & timeout
while True:
    received_data = ser.readline()              #read serial port
    line = received_data.decode('utf-8').rstrip()
    if len(line) > 0:
        print ('- [{}]'.format(line))                   #print received data
        print ('{}'.format(line), file=log_file)                   #print received data
