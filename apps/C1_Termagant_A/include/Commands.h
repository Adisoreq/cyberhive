#ifndef COMMANDS_H
#define COMMANDS_H

#include <Arduino.h>

#include "Motors.h"
#include "Pins.h"

enum Mode : uint8_t { MODE_STOP = 0, MODE_FWD = 1, MODE_BWD = 2, MODE_LEFT = 3, MODE_RIGHT = 4, MODE_AUTO = 5 };

Mode    mode  = MODE_STOP;
uint8_t speed = 200;

namespace Commands {
    void (*onStatusChanged)() = nullptr;

    void applyMotion(Mode m) {
        bool forward = (m == MODE_FWD);
        digitalWrite(LED_BLUE, forward ? LOW : HIGH);

        switch (m) {
            case MODE_FWD:   Motors::moveFwd(speed); break;
            case MODE_BWD:   Motors::moveBwd(speed); break;
            case MODE_LEFT:  Motors::turnLeft(speed); break;
            case MODE_RIGHT: Motors::turnRight(speed); break;
            default:         Motors::stop(); break;
        }
    }

    void setMode(Mode m) {
        mode = m;
        applyMotion(m);
        if (onStatusChanged) onStatusChanged();
    }

    // Ramka: [0] = komenda (tryb), [1] = opcjonalna prędkość
    void process(const uint8_t* buf, int len) {
        if (len < 1) return;

        Serial.print("CMD: ");
        for (int i = 0; i < len; i++) { Serial.print(buf[i], HEX); Serial.print(' '); }
        Serial.println();

        if (buf[0] > MODE_AUTO) {
            Serial.println("Nieznana komenda");
            return;
        }

        if (len >= 2) speed = buf[1];

        switch (buf[0]) {
            case 0: setMode(MODE_STOP); break;
            case 1: setMode(MODE_FWD);  break;
            case 2: setMode(MODE_BWD);  break;
            case 3: setMode(MODE_LEFT); break;
            case 4: setMode(MODE_RIGHT); break;
            case 5: setMode(MODE_AUTO); break;
        }
    }
}

#endif //COMMANDS_H
