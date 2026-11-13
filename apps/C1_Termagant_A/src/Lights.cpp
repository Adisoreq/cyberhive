#include <Arduino.h>
#include "Pins.h"
#include "Lights.h"

void Lights::init() {
    pinMode(LIGHT_RED, OUTPUT);
    pinMode(LIGHT_GREEN, OUTPUT);
    pinMode(LIGHT_BLUE, OUTPUT);
}

void Lights::set(RGB colors, bool state) {
    if (colors & RED) {
        digitalWrite(LIGHT_RED, state ? HIGH : LOW);
    }
    if (colors & GREEN) {
        digitalWrite(LIGHT_GREEN, state ? HIGH : LOW);
    }
    if (colors & BLUE) {
        digitalWrite(LIGHT_BLUE, state ? HIGH : LOW);
    }
}

void Lights::set(RGB colors, uint8_t intensity) {
    if (colors & RED) {
        analogWrite(LIGHT_RED, intensity);
    }
    if (colors & GREEN) {
        analogWrite(LIGHT_GREEN, intensity);
    }
    if (colors & BLUE) {
        analogWrite(LIGHT_BLUE, intensity);
    }
}
