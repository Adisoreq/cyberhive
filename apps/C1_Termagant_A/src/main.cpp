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


/*

void setup() {
  Serial.begin(115200);
  
  pinMode(LED_BLUE, OUTPUT);
  
  Motors::init();
  Serial.println("Device ready.");

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
  commandChar.setEventHandler(BLEWritten, [](BLEDevice, BLECharacteristic) {   Bluetooth::onCommand(); });

  Commands::onStatusChanged = Bluetooth::publishStatus;
  Bluetooth::publishStatus();
  BLE.advertise();
  Serial.println("Device ready, advertising.");
}

void loop() {
  BLE.poll();
  s_tmr.update();

  if (s_tmr.stateChanged()) {
    Bluetooth::publishStatus();

    
  }
  
  if (mode == MODE_AUTO) {
    m_tmr.update();

    if (m_tmr.stateChanged()) {
      sw.update(!sw.value());
    }

    Commands::applyMotion(sw.value() ? MODE_FWD : MODE_BWD);
  }
}

*/



// Attached RGB diode
const int PIN_RED = 7;
const int PIN_GREEN = 9;
const int PIN_BLUE = 10;

const int MIDDLE = 127;

bool red, green, blue;

bool inverted = true;

void setup() {
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BLUE, OUTPUT);
}

void setColor(bool r, bool g, bool b) {
  red = r;
  green = g;
  blue = b;
  
  digitalWrite(LED_RED, red ? HIGH : LOW);
  digitalWrite(PIN_RED, red ? HIGH : LOW);

  digitalWrite(LED_GREEN, green ? HIGH : LOW);
  digitalWrite(PIN_GREEN, green ? HIGH : LOW);
  
  digitalWrite(LED_BLUE, blue ? HIGH : LOW);
  digitalWrite(PIN_BLUE, blue ? HIGH : LOW);
}

void loop() {
  setColor(!inverted, inverted, inverted);
  delay(500);
  setColor(inverted, !inverted, inverted);
  delay(500);
  setColor(inverted, inverted, !inverted);
  delay(500);
}

