#ifndef MOTORS_H
#define MOTORS_H

#include "Pins.h"

class Motors {
public:
  static void init() {
    // Motor A
    pinMode(OUT_A1, OUTPUT);
    pinMode(OUT_A2, OUTPUT);

    // Motor B
    pinMode(OUT_B1, OUTPUT);
    pinMode(OUT_B2, OUTPUT);
  }

  static void moveFwd(const uint8_t& speed = 200) {
    // Motor A
    analogWrite(OUT_A1, speed);
    analogWrite(OUT_B1, speed);

    // Motor B
    analogWrite(OUT_A2, 0);
    analogWrite(OUT_B2, 0);
  }

  static void moveBwd(const uint8_t& speed = 200) {
    // Motor A
    analogWrite(OUT_A1, 0);
    analogWrite(OUT_B1, 0);

    // Motor B
    analogWrite(OUT_A2, speed);
    analogWrite(OUT_B2, speed);
  }

  static void stop() {
    analogWrite(OUT_A1, 0);
    analogWrite(OUT_B1, 0);

    analogWrite(OUT_A2, 0);
    analogWrite(OUT_B2, 0);
  }

  static void turnLeft(const uint8_t& speed = 200) {
    // Motor A
    analogWrite(OUT_A1, 0);
    analogWrite(OUT_B1, speed);

    // Motor B
    analogWrite(OUT_A2, 0);
    analogWrite(OUT_B2, speed);
  }

  static void turnRight(const uint8_t& speed = 200) {
    // Motor A
    analogWrite(OUT_A1, speed);
    analogWrite(OUT_B1, 0);

    // Motor B
    analogWrite(OUT_A2, speed);
    analogWrite(OUT_B2, 0);
  }
};

#endif //MOTORS_H