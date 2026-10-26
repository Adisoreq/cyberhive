#ifndef BLUETOOTH_H
#define BLUETOOTH_H

#include <ArduinoBLE.h>

#include "Pins.h"
#include "Motors.h"

#define DEVICE_NAME "Termagant A"

#define UUID_SERVICE "6cced000-f280-4439-b11e-4f40ae081441"
#define UUID_COMMAND "6cced001-f280-4439-b11e-4f40ae081441"
#define UUID_STATUS  "6cced002-f280-4439-b11e-4f40ae081441"

enum Mode : uint8_t { MODE_STOP = 0, MODE_FWD = 1, MODE_BWD = 2, MODE_AUTO = 3 };

Mode    mode  = MODE_STOP;
uint8_t speed = 200;

static BLEService service(UUID_SERVICE);
static BLECharacteristic commandChar(UUID_COMMAND, BLEWrite | BLEWriteWithoutResponse, 20);
static BLECharacteristic statusChar(UUID_STATUS, BLERead | BLENotify, 2);

namespace Bluetooth {
    
    void publishStatus() {
        uint8_t st[2] = { (uint8_t)mode, speed };
        statusChar.writeValue(st, sizeof(st));
    }

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
        publishStatus();
    }

    void onCommand() {
        uint8_t buf[20];
        int len = commandChar.readValue(buf, sizeof(buf));
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

    void onConnected(BLEDevice central) {
        Serial.print("Polaczono: ");
        Serial.println(central.address());
    }

    void onDisconnected(BLEDevice central) {
        Serial.println("Rozlaczono");
        setMode(MODE_STOP);      // bezpieczeństwo: stop po utracie połączenia
        BLE.advertise();         // wznów reklamowanie
    }
}

#endif //BLUETOOTH_H