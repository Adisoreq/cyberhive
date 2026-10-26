# CyberHive

Robotics project


## Description

Robotic hive reacting to the hive mind's commands.

Consists of server with camera that registers user's hand gestures and mini robots that receive signals through Bluetooth and react to them.


## Components

### Serwer (Python)

- Hardware: Radxa Dragon Q6A
- Camera: Raspberry Pi AI 3
- Rozpoznawanie gestow: MediaPipe Tasks

### Klient (Seeed XIAO nRF52840)

- Aplikacja PlatformIO: `apps/C1_Termagant_A`
- Płytka: Seeed XIAO nRF52840

## Jak zacząć

### Uruchomienie klienta

Zainstaluj [PlatformIO Core](https://platformio.org/install/cli), a następnie z katalogu `apps/C1_Termagant_A` uruchom:

```powershell
pio run
```

Aby wgrać program na podłączoną płytkę:

```powershell
pio run --target upload
```

### Uruchomienie serwera

Przejdź [**tutaj**](docs/setup.md), aby uzyskać więcej informacji.

## Profile zaleznosci

- `requirements.txt` - bazowe zaleznosci runtime
- `requirements-dev.txt` - zaleznosci developerskie (bazowe + narzedzia)
- `requirements-prod.txt` - zaleznosci pod wdrozenie (bazowe, wersje do walidacji na Raspberry Pi)

## Raspberry Pi (prod)

Przykladowy plik uslugi systemd znajduje sie w `scripts/systemd/remote-droids-server.service`.
Szczegoly konfiguracji i uruchomienia: [docs/setup.md](docs/setup.md).

## Wymagania

- **Serwer**
  - Python (3.13+)
  - pip
- **Klient**
  - PlatformIO Core
  - Seeed XIAO nRF52840