#ifndef COMMANDS_H
#define COMMANDS_H

#include <Arduino.h>

#include "Motors.h"
#include "Pins.h"

enum Mode : uint8_t { MODE_STOP = 0, MODE_FWD = 1, MODE_BWD = 2, MODE_AUTO = 3 };

Mode    mode  = MODE_STOP;
uint8_t speed = 200;

namespace Commands {

    // Wywoływany po zmianie trybu/prędkości (ustawiany przez warstwę transportu, np. Bluetooth)
    void (*onStatusChanged)() = nullptr;

    void applyMotion(bool forward) {
        digitalWrite(PIN_BLUE, forward ? LOW : HIGH);
        if (forward) Motors::moveFwd(speed);
        else         Motors::moveBwd(speed);
    }

    void setMode(Mode m) {
        mode = m;
        if (m == MODE_STOP) {
            Motors::stop();
            digitalWrite(PIN_BLUE, HIGH);
        } 
        else if (m == MODE_FWD) {
            applyMotion(true);
        } 
        else if (m == MODE_BWD) {
            applyMotion(false);
        }
        if (onStatusChanged) onStatusChanged();
    }

    // Ramka: [0] = komenda (tryb), [1] = opcjonalna prędkość
    void process(const uint8_t* buf, int len) {
        if (len < 1) return;

        if (len >= 2) speed = buf[1];

        Serial.print("CMD: ");
        for (int i = 0; i < len; i++) { Serial.print(buf[i], HEX); Serial.print(' '); }
        Serial.println();

        switch (buf[0]) {
            case 0: setMode(MODE_STOP); break;
            case 1: setMode(MODE_FWD);  break;
            case 2: setMode(MODE_BWD);  break;
            case 3: setMode(MODE_AUTO); break;
            default: Serial.println("Nieznana komenda"); break;
        }
    }
}

#endif //COMMANDS_H
