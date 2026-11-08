# Raspberry Pi Pico FAST Calculator V3 - Proteus 8 MicroPython
# LCD: I2C-16X2 PCF8574, 0x3F, GP0 SDA / GP1 SCL
# Rows A-D: GP2 GP3 GP4 GP5; Columns 1-4: GP6 GP7 GP8 GP9
# Keypad rows: [7,8,9,/], [4,5,6,*], [1,2,3,-], [C,0,=,+]
from machine import Pin, I2C
from time import ticks_ms, ticks_diff, sleep_ms

LCD_ADDR = 0x3F
I2C_FREQUENCY = 100000  # Stable default. Try 400000 only if Proteus I2C supports it.
KEY_DEBOUNCE_MS = 18
MAX_DIGITS = 12
PRINT_KEYS = False       # True enables debug output; False is faster.

class LCD1602:
    BL = 0x08
    EN = 0x04
    RS = 0x01

    def __init__(self, bus, addr):
        self.bus = bus
        self.addr = addr
        self.old = [' ' * 16, ' ' * 16]
        sleep_ms(50)
        self._nibble(0x30)
        sleep_ms(5)
        self._nibble(0x30)
        sleep_ms(2)
        self._nibble(0x30)
        sleep_ms(2)
        self._nibble(0x20)
        sleep_ms(2)
        self.command(0x28)  # 4-bit mode, two lines
        self.command(0x08)  # display off
        self.command(0x01)  # clear once at startup
        sleep_ms(3)
        self.command(0x06)
        self.command(0x0C)

    def _nibble(self, upper, rs=0):
        b = (upper & 0xF0) | self.BL | rs
        self.bus.writeto(self.addr, bytes((b | self.EN, b)))

    def command(self, v):
        self._nibble(v & 0xF0)
        self._nibble((v << 4) & 0xF0)

    def line(self, row, text):
        text = str(text)[:16]
        while len(text) < 16:
            text += ' '
        old = self.old[row]
        if text == old:
            return
        # Update only the changed span instead of all 16 characters.
        start = 0
        while start < 16 and text[start] == old[start]:
            start += 1
        end = 15
        while end >= start and text[end] == old[end]:
            end -= 1
        self.command((0x80 if row == 0 else 0xC0) + start)
        length = end - start + 1
        data = bytearray(length * 4)
        p = 0
        for i in range(start, end + 1):
            value = ord(text[i])
            hi = (value & 0xF0) | self.BL | self.RS
            lo = ((value << 4) & 0xF0) | self.BL | self.RS
            data[p] = hi | self.EN
            data[p + 1] = hi
            data[p + 2] = lo | self.EN
            data[p + 3] = lo
            p += 4
        self.bus.writeto(self.addr, data)
        self.old[row] = text

ROWS = [Pin(i, Pin.OUT, value=1) for i in (2, 3, 4, 5)]
COLS = [Pin(i, Pin.IN, Pin.PULL_UP) for i in (6, 7, 8, 9)]
KEYS = (
    ('7', '8', '9', '/'),
    ('4', '5', '6', '*'),
    ('1', '2', '3', '-'),
    ('C', '0', '=', '+')
)

def scan_key():
    # No 1 ms per-row delay: key response is limited by debounce, not scanning.
    for r in range(4):
        ROWS[r].value(0)
        for c in range(4):
            if COLS[c].value() == 0:
                ROWS[r].value(1)
                return KEYS[r][c]
        ROWS[r].value(1)
    return None

def show_number(value):
    if value != value or abs(value) > 999999999999:
        return 'OVERFLOW'
    negative = value < 0
    magnitude = abs(value)
    scaled = int(magnitude * 10000 + 0.5)
    integer_part = scaled // 10000
    decimal_part = scaled % 10000
    out = str(integer_part)
    if decimal_part:
        decimal_text = str(decimal_part)
        while len(decimal_text) < 4:
            decimal_text = '0' + decimal_text
        while decimal_text[-1] == '0':
            decimal_text = decimal_text[:-1]
        out += '.' + decimal_text
    if negative and scaled:
        out = '-' + out
    return out

def calculate(a, op, b):
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        if b == 0:
            return None
        return a / b
    return b

class Calculator:
    def __init__(self):
        self.clear()

    def clear(self):
        self.first = None
        self.operator = None
        self.entry = '0'
        self.new_entry = False
        self.result_shown = False
        self.error = False

    def display(self):
        if self.error:
            return ('MATH ERROR', 'PRESS C TO CLEAR')
        if self.result_shown:
            return ('RESULT', self.entry)
        if self.first is None or self.operator is None:
            return ('PICO CALCULATOR', self.entry)
        if self.new_entry:
            # Show the pending operation until the next digit is pressed.
            return (show_number(self.first) + self.operator, '0')
        # Immediately remove the previous operand/expression once a new
        # number is entered. Only the current number remains visible.
        return ('ENTER NUMBER', self.entry)

    def key(self, k):
        if k == 'C':
            self.clear()
            return True
        if self.error:
            return False
        if '0' <= k <= '9':
            if self.result_shown:
                self.clear()
                self.entry = k
            elif self.new_entry:
                self.entry = k
                self.new_entry = False
            elif (len(self.entry) - (1 if self.entry[0] == '-' else 0)) < MAX_DIGITS:
                if self.entry == '0':
                    self.entry = k
                else:
                    self.entry += k
            return True
        if k in ('+', '-', '*', '/'):
            if self.first is None or self.result_shown:
                self.first = float(self.entry)
            elif not self.new_entry:
                result = calculate(self.first, self.operator, float(self.entry))
                if result is None or show_number(result) == 'OVERFLOW':
                    self.error = True
                    return True
                self.first = result
                self.entry = show_number(result)
            self.operator = k
            self.new_entry = True
            self.result_shown = False
            return True
        if k == '=':
            if self.first is None or self.operator is None or self.new_entry:
                return False
            result = calculate(self.first, self.operator, float(self.entry))
            if result is None or show_number(result) == 'OVERFLOW':
                self.error = True
                return True
            self.entry = show_number(result)
            self.first = None
            self.operator = None
            self.new_entry = False
            self.result_shown = True
            return True
        return False

# LCD initialization only once; leave keypad usable if LCD is absent.
bus = I2C(0, sda=Pin(0), scl=Pin(1), freq=I2C_FREQUENCY)
lcd = None
try:
    if LCD_ADDR in bus.scan():
        lcd = LCD1602(bus, LCD_ADDR)
    else:
        print('LCD address 0x3F not detected')
except Exception as exc:
    print('LCD startup error:', exc)
    lcd = None

calc = Calculator()
last_raw = None
stable = None
changed_at = ticks_ms()
dirty = True
print('FAST CALCULATOR V3 READY')

while True:
    now = ticks_ms()
    raw = scan_key()
    if raw != last_raw:
        last_raw = raw
        changed_at = now
    if raw != stable and ticks_diff(now, changed_at) >= KEY_DEBOUNCE_MS:
        stable = raw
        if stable is not None:
            if PRINT_KEYS:
                print('KEY', stable)
            if calc.key(stable):
                dirty = True
    if dirty:
        dirty = False
        a, b = calc.display()
        if lcd is not None:
            try:
                lcd.line(0, a)
                lcd.line(1, b)
            except Exception as exc:
                print('LCD error:', exc)
                lcd = None
    sleep_ms(1)
