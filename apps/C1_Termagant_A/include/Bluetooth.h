#ifndef BLUETOOTH_H
#define BLUETOOTH_H

#include <ArduinoBLE.h>

#include "Pins.h"
#include "Motors.h"
#include "Commands.h"

#define DEVICE_NAME "Termagant A"

#define UUID_SERVICE "6cced000-f280-4439-b11e-4f40ae081441"
#define UUID_COMMAND "6cced001-f280-4439-b11e-4f40ae081441"
#define UUID_STATUS  "6cced002-f280-4439-b11e-4f40ae081441"

static BLEService service(UUID_SERVICE);
static BLECharacteristic commandChar(UUID_COMMAND, BLEWrite | BLEWriteWithoutResponse, 20);
static BLECharacteristic statusChar(UUID_STATUS, BLERead | BLENotify, 2);

namespace Bluetooth {
    
    void publishStatus() {
        uint8_t st[2] = { (uint8_t)mode, speed };
        statusChar.writeValue(st, sizeof(st));
    }

    void onCommand() {
        uint8_t buf[20];
        int len = commandChar.readValue(buf, sizeof(buf));
        Commands::process(buf, len);
    }

    void onConnected(BLEDevice central) {
        Serial.print("Polaczono: ");
        Serial.println(central.address());
    }

    void onDisconnected(BLEDevice central) {
        Serial.println("Rozlaczono");
        Commands::setMode(MODE_STOP);      // bezpieczeństwo: stop po utracie połączenia
        BLE.advertise();         // wznów reklamowanie
    }
}

#endif //BLUETOOTH_H