#ifndef TIMER_H
#define TIMER_H
#include <Arduino.h>

class Timer {
private:
  unsigned long _prev, _interval;
  bool _fired = false;

public:
  explicit Timer(unsigned long intervalMs) : _prev(millis()), _interval(intervalMs) {}
  
  bool stateChanged() const { return _fired; }
  
  void update() {
    unsigned long now = millis();
    if (now - _prev >= _interval) { _prev += _interval; _fired = true; }
    else _fired = false;
  }
};

#endif