#define ID      "C1_Termagant_A"
#define NAME    "Termagant A"
#define BOARD   "Seeed XIAO nRF52840"

#include <Arduino.h>
#include <ArduinoBLE.h>

#include "Bluetooth.h"
#include "Commands.h"
#include "Pins.h"
#include "Motors.h"
#include "Switch.h"
#include "Timer.h"

Timer m_tmr(200.0);
Timer s_tmr(1000.0);
Switch sw(false);

void setup() {
  Serial.begin(115200);
  
  pinMode(PIN_BLUE, OUTPUT);
  
  Motors::init();
  Serial.println("Device ready.");

  Commands::setMode(MODE_STOP);

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
  commandChar.setEventHandler(BLEWritten, [](BLEDevice, BLECharacteristic) {   Bluetooth::onCommand(); });

  Commands::onStatusChanged = Bluetooth::publishStatus;
  Bluetooth::publishStatus();
  BLE.advertise();
  Serial.println("Device ready, advertising.");
}

void loop() {
  BLE.poll();
  s_tmr.update();

  if (s_tmr.stateChanged())
    Bluetooth::publishStatus();

  if (mode == MODE_AUTO) {
    m_tmr.update();

    if (m_tmr.stateChanged()) 
      sw.update(!sw.value());
    
    Commands::applyMotion(sw.value());
  }
}
