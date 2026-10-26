#ifndef SWITCH_H
#define SWITCH_H

class Switch {
private:
  bool _sw = false;
  bool _ch = false;

public:
  Switch(bool initialValue) { 
    _sw = initialValue;
  }

  bool value() const {
    return _sw;
  }

  void update(bool value) {
    _ch = (_sw != value);
    _sw = value;
  }

  bool stateChanged() const {
    return _ch;
  }
};

#endif // SWITCH_H