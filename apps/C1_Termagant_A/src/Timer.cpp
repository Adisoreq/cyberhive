#include "Timer.h"
#include <Arduino.h>

Timer::Timer(unsigned long intervalMs) 
    : _prev(millis()), _interval(intervalMs), _total(0) {}

bool Timer::stateChanged() const { 
    return _fired; 
}

unsigned long Timer::total() const { 
    return _total; 
}

unsigned long Timer::interval() const {
    return _interval;
}
  
void Timer::reset() { 
    _prev = millis(); 
    _total = 0; 
    _fired = false; 
}

void Timer::update() {
    unsigned long now = millis();

    if (now - _prev >= _interval) { 
        _prev += _interval; 
        _fired = true; 
        _total += _interval; 
    }

    else _fired = false;
}