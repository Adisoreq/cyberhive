#define ID      "C1_Termagant_A"
#define NAME    "Termagant A"

#include <Arduino.h>
#include <ArduinoBLE.h>

#include "Bluetooth.h"
#include "Commands.h"
#include "Motors.h"
#include "Pins.h"
#include "Switch.h"
#include "Timer.h"

Timer motionTimer(200);
Timer statusTimer(1000);
Switch autoDirection(false);

void setup() {
  Serial.begin(115200);

  pinMode(LED_BLUE, OUTPUT);
  pinMode(LED_RED, OUTPUT);

  Motors::init();
  Commands::setMode(MODE_STOP);

  if (!BLE.begin()) {
    Serial.println("BLE.begin() nie powiodlo sie");
    while (true) {
      digitalWrite(LED_RED, LOW);
      delay(100);
      digitalWrite(LED_RED, HIGH);
      delay(100);
    }
  }

  BLE.setLocalName(DEVICE_NAME);
  BLE.setDeviceName(DEVICE_NAME);
  BLE.setAdvertisedService(service);

  service.addCharacteristic(commandChar);
  service.addCharacteristic(statusChar);
  BLE.addService(service);

  BLE.setEventHandler(BLEConnected, Bluetooth::onConnected);
  BLE.setEventHandler(BLEDisconnected, Bluetooth::onDisconnected);
  commandChar.setEventHandler(
      BLEWritten, [](BLEDevice, BLECharacteristic) { Bluetooth::onCommand(); });

  Commands::onStatusChanged = Bluetooth::publishStatus;
  Bluetooth::publishStatus();
  BLE.advertise();
  Serial.println("Device ready, advertising.");
}

void loop() {
  BLE.poll();
  statusTimer.update();

  if (statusTimer.stateChanged()) {
    Bluetooth::publishStatus();
  }

  if (mode == MODE_AUTO) {
    motionTimer.update();

    if (motionTimer.stateChanged()) {
      autoDirection.update(!autoDirection.value());
      Commands::applyMotion(autoDirection.value() ? MODE_FWD : MODE_BWD);
    }
  }
}
