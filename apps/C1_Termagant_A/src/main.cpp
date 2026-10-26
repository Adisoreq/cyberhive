#define ID      "C1_Termagant_A"
#define NAME    "Termagant A"
#define BOARD   "Seeed XIAO nRF52840"

#include <Arduino.h>
#include <ArduinoBLE.h>

#include "Bluetooth.h"
#include "Pins.h"
#include "Motors.h"
#include "Switch.h"
#include "Timer.h"

Timer tmr(200.0);
Switch sw(false);

void setup() {
  Serial.begin(115200);
  
  pinMode(PIN_BLUE, OUTPUT);
  
  Motors::init();
  Serial.println("Device ready.");

  Bluetooth::setMode(MODE_STOP);

  if (!BLE.begin()) {
    Serial.println("BLE.begin() nie powiodlo sie");
    while (true) { digitalWrite(PIN_BLUE, !digitalRead(PIN_BLUE)); delay(100); }
  }

  BLE.setLocalName(DEVICE_NAME);
  BLE.setDeviceName(DEVICE_NAME);
  BLE.setAdvertisedService(service);

  service.addCharacteristic(commandChar);
  service.addCharacteristic(statusChar);
  BLE.addService(service);

  BLE.setEventHandler(BLEConnected, Bluetooth::onConnected);
  BLE.setEventHandler(BLEDisconnected, Bluetooth::onDisconnected);
  commandChar.setEventHandler(BLEWritten, [](BLEDevice, BLECharacteristic) { Bluetooth::onCommand(); });

  Bluetooth::publishStatus();
  BLE.advertise();
  Serial.println("Device ready, advertising.");
}

void loop() {
  BLE.poll();

  if (mode == MODE_AUTO) {
    tmr.update();
    if (tmr.stateChanged()) sw.update(!sw.value());
    Bluetooth::applyMotion(sw.value());
  }
}
