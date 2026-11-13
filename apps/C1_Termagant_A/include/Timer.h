#ifndef TIMER_H
#define TIMER_H

class Timer {
private:
  unsigned long _prev, _interval, _total;
  bool _fired = false;

public:
  explicit Timer(unsigned long intervalMs);

  bool stateChanged() const;
  unsigned long total() const;
  unsigned long interval() const;

  void reset();
  void update();
};

#endif