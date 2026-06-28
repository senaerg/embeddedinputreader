"""
MicroPython control logic for the embedded input reader.

Features:
- Reads four slide switches through a chained 4:1 mux (GPIO27/28 select, GPIO26 input).
- Debounced button interrupts on GPIO16-18 mapping to keys 0, 1, 2.
- Converts switch binary value to decimal and prints on startup and when it changes.
- Checks the last three button presses against passcode 0-2-1 and toggles LEDs D0-D8 (GPIO7-15).
"""

import machine
from utime import sleep, sleep_ms, sleep_us, ticks_diff, ticks_ms

# GPIO assignments from the provided schematic
LED_PINS = [7, 8, 9, 10, 11, 12, 13, 14, 15]  # D0 (rightmost) -> D8 (leftmost)
BUTTON_PINS = [16, 17, 18]  # B0 -> B2

MUX_S0_PIN = 27  # lower-level select (shared by first-level muxes)
MUX_S1_PIN = 28  # upper-level select (second level)
MUX_OUT_PIN = 26  # mux output back to MCU

# Behavior tuning
DEBOUNCE_MS = 200
INACTIVITY_CLEAR_MS = 3000
POLL_DELAY_MS = 40
PASSCODE = [0, 2, 1]


def bits_to_decimal(bits):
    """Convert list of bits [SW0, SW1, SW2, SW3] to decimal, SW0 is LSB."""
    value = 0
    for idx, bit in enumerate(bits):
        value |= (bit & 1) << idx
    return value


class InputReader:
    def __init__(self):
        # Outputs
        self.leds = [machine.Pin(pin, machine.Pin.OUT, value=0) for pin in LED_PINS]

        # Mux control
        self.mux_s0 = machine.Pin(MUX_S0_PIN, machine.Pin.OUT, value=0)
        self.mux_s1 = machine.Pin(MUX_S1_PIN, machine.Pin.OUT, value=0)
        self.mux_out = machine.Pin(MUX_OUT_PIN, machine.Pin.IN)

        # Button handling
        self.button_value_by_pin = {pin_no: idx for idx, pin_no in enumerate(BUTTON_PINS)}
        self.last_press_times = {pin_no: 0 for pin_no in BUTTON_PINS}
        self.event_queue = []
        self.pressed_keys = []
        self.last_key_time = 0

        for pin_no in BUTTON_PINS:
            pin = machine.Pin(pin_no, machine.Pin.IN, machine.Pin.PULL_DOWN)
            # Capture pin number in default arg to avoid late binding
            pin.irq(trigger=machine.Pin.IRQ_RISING, handler=lambda _p, n=pin_no: self._interrupt_callback(n))

        # Switch tracking
        self.last_switch_value = None

    # ----- Switch reading -----
    def _read_switch_bits(self):
        bits = []
        for idx in range(4):
            # idx maps: 0 -> SW0 (rightmost, LSB), 1 -> SW1, 2 -> SW2, 3 -> SW3
            self.mux_s1.value(1 if idx >= 2 else 0)  # select left/right mux group
            self.mux_s0.value(idx & 1)  # select within the pair
            sleep_us(50)  # allow mux output to settle
            bits.append(self.mux_out.value())
        return bits

    def read_switch_decimal(self):
        return bits_to_decimal(self._read_switch_bits())

    def poll_switches(self):
        current = self.read_switch_decimal()
        if current != self.last_switch_value:
            self.last_switch_value = current
            print(f"selected output: {current}")

    # ----- Button interrupt handling -----
    def _interrupt_callback(self, pin_no):
        now = ticks_ms()
        last = self.last_press_times.get(pin_no, 0)
        if ticks_diff(now, last) < DEBOUNCE_MS:
            return
        self.last_press_times[pin_no] = now
        key_val = self.button_value_by_pin.get(pin_no)
        if key_val is None:
            return
        # Queue event for main loop to handle (avoid heavy work in IRQ)
        self.event_queue.append((now, key_val))

    def _handle_keypress(self, event_time, key_val):
        self.last_key_time = event_time
        self.pressed_keys.append(key_val)
        print(f"key press: {key_val}")

        if len(self.pressed_keys) == 3:
            self._evaluate_passcode()
            self.pressed_keys.clear()

    def _evaluate_passcode(self):
        if self.pressed_keys != PASSCODE:
            print("incorrect passcode")
            return

        selected = self.read_switch_decimal()
        print(f"selected output: {selected}")

        if 0 <= selected < len(self.leds):
            led = self.leds[selected]
            next_state = 0 if led.value() else 1
            led.value(next_state)
            state_label = "on" if next_state else "off"
            print(f"correct passcode, toggling LED {selected} -> {state_label}")
        else:
            print(f"selected output: {selected}, valid range: 0-{len(self.leds)-1}, doing nothing")

    def _check_inactivity_clear(self, now_ms):
        if self.pressed_keys and ticks_diff(now_ms, self.last_key_time) > INACTIVITY_CLEAR_MS:
            self.pressed_keys.clear()
            print("no key press for 3s, clearing key buffer")

    # ----- Main loop -----
    def run(self):
        sleep(0.01)
        print("Program starting")

        # Print initial switch state
        initial = self.read_switch_decimal()
        self.last_switch_value = initial
        print(f"selected output: {initial}")

        while True:
            # Drain queued keypress events
            while self.event_queue:
                event_time, key_val = self.event_queue.pop(0)
                self._handle_keypress(event_time, key_val)

            # Clear stale key sequences if inactive
            self._check_inactivity_clear(ticks_ms())

            # Poll switch mux
            self.poll_switches()

            sleep_ms(POLL_DELAY_MS)


def main():
    reader = InputReader()
    reader.run()


if __name__ == "__main__":
    main()
