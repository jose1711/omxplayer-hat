#!/usr/bin/env python3
'''
write text to LCD, then wait and turn it off

  arg1 = text to display (can be multiline)
[ arg2 = timeout (seconds) ]
[ arg3 = color ]

'''
import sys
from time import sleep
from PIL import Image, ImageDraw, ImageFont, ImageColor
import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config


def write(text, LCD):
    image = Image.new("RGB",
                     (LCD.width, LCD.height),
                     "BLACK")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('/usr/share/fonts/TTF/FreeSans.ttf', 10)
    _, _, textwidth, textheight = draw.textbbox((0, 0), text)
    x = (LCD.width - textwidth) / 2
    y = (LCD.height - textheight) / 2
    draw.text((x, y), text, fill=color, font=font)
    LCD.LCD_ShowImage(image,0,0)


if len(sys.argv) < 2:
    sys.exit()

# defaults
timeout = 5
color = 'yellow'

text = sys.argv[1]
if len(sys.argv) >= 3:
    timeout = int(sys.argv[2])

if len(sys.argv) >= 4:
    color = sys.argv[3]
    color = color.upper()

# print(f'Text to show: {text}, timeout: {timeout}')
LCD = LCD_1in44.LCD()
Lcd_ScanDir = LCD_1in44.SCAN_DIR_DFT  #SCAN_DIR_DFT = D2U_L2R
LCD.LCD_Init(Lcd_ScanDir)
# no need to clear the screen - we will overwrite it completely anyway
# LCD.LCD_Clear()

# Backlight pin
BL = 24
GPIO.setup(BL, GPIO.OUT)
pwm = GPIO.PWM(BL, 1000)
pwm.start(80)

write(text, LCD)
sleep(timeout)
