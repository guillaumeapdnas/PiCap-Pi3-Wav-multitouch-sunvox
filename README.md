# PiCap-Pi3-Wav-multitouch-sunvox

Instrument interactif « simili-Ableton » : les 12 électrodes capacitives du
PiCap (Bare Conductive / MPR121) sur Raspberry Pi 3 pilotent en temps réel
un synthé modulaire **SunVox** (avec repli Pygame .wav).

- `diff_sound_player_V4.py` : interface Tkinter (plages, calibration du
  silence, plein écran, thème sombre) + moteur SunVox (synthé généré ou
  samplers .wav), sélectionnables à chaud.
- `tracks/E{0..11}/{000..011}.wav` : sons (non inclus dans le dépôt).
- `sunvox/` : bibliothèque SunVox Python (copiée sur le Pi, pas dans le dépôt).

## Installation (une fois)
1. Cloner ce dépôt sur le Pi.
2. Copier `tracks/` depuis l'ancien projet.
3. git clone --depth 1 https://github.com/metrasynth/sunvox-dll-python.git
   cp -r sunvox-dll-python/sunvox .
   rm -rf sunvox-dll-python

## Lancement
sudo python3 diff_sound_player_V4.py
