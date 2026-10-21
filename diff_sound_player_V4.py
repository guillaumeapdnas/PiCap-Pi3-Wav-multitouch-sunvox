#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CapTouch Sound Mapper V4 — PiCap Bare Conductive / Raspberry Pi 3
===================================================================
Tout ce que fait la V3 (calibration du silence, plages, thème sombre,
plein écran kiosk, rejeu réglable...) PLUS un MOTEUR SUNVOX :

  MOTEUR AUDIO (nouvelle zone rose dans la barre d'outils)
  - « SunVox » : le moteur de synthé modulaire de SunVox (C, ultra léger
    pour le Pi 3) remplace Pygame. Le projet SunVox est GÉNÉRÉ PAR CODE
    au lancement — aucun fichier .sunvox à préparer.
  - « Pygame » : le lecteur .wav classique de la V3 (repli automatique
    si SunVox n'est pas installé).

  MODE SUNVOX « Synthé (généré) »
  - Un module Generator (synthé analogique) polyphonique : 12 pistes =
    12 électrodes, une note différente par électrode (gamme pentatonique
    mineure par défaut, modifiable dans config.json → "notes").
  - Chaîne Generator → Filtre → Echo → Output.
  - La vélocité de chaque note est indexée sur la valeur capacitive.
  - Le niveau capacitif pilote EN CONTINU la fréquence de coupure du
    filtre (effet wah-wah expressif « simili-Ableton »).

  MODE SUNVOX « Sampler (.wav) »
  - Les .wav de tracks/E{e}/{iii}.wav sont chargés dans des modules
    Sampler créés à la demande (1 module par couple électrode/son).
  - La position dans la plage déforme la hauteur du sample en temps réel
    (pitch bend continu de 0 à 12 demi-tons).

  INSTALLATION SUNVOX (une seule fois, sur le Pi — pip exige Python 3.9,
  on copie donc directement le dossier, qui est du pur Python + la
  bibliothèque compilée pour ARM 32 bits) :
      cd /home/admin/PiCapExamples/Python/PiCap-Pi3-Wav-multitouch-multison-V2
      git clone --depth 1 https://github.com/metrasynth/sunvox-dll-python.git
      cp -r sunvox-dll-python/sunvox .
      rm -rf sunvox-dll-python
  Le dossier 'sunvox' doit rester À CÔTÉ de ce script.
  Lancement : sudo python3 diff_sound_player_V4.py
"""

import json
import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pygame
from pygame.mixer import Sound

# ---------------------------------------------------------------------------
# SunVox — optionnel : bibliothèque 'sunvox' (copiée à côté du script).
# Si elle est absente, l'application démarre en moteur Pygame, sans crash.
# ---------------------------------------------------------------------------
sv = None
SV_OK = False
SV_ERROR = ""
try:
    import sunvox.dll as sv          # charge aussi sunvox.so (ARM 32 bits)
    SV_OK = True
except Exception as exc:
    SV_ERROR = str(exc)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.path.join(APP_DIR, "config.json")
TRACKS_DIR = os.path.join(APP_DIR, "tracks")

NUM_ELECTRODES = 12
NUM_SOUNDS = 12
NUM_COLS = NUM_SOUNDS * 2          # une colonne min + une colonne max par son
POLL_MS = 100                      # période de lecture capteur / rafraîchissement
DEFAULT_TOUCH_THRESHOLD = 40
DEFAULT_RELEASE_THRESHOLD = 20
DEFAULT_RETRIGGER_DELAY = 1.0      # secondes avant de rejouer la même plage
DEFAULT_SPREAD_MAX = 60            # valeur max pour le bouton « Répartir »
DIFF_DISPLAY_MAX = 120             # échelle des barres de niveau
KIOSK_MODE = True                 # plein écran au démarrage (Échap pour sortir)
CALIB_DURATION = 3.0              # secondes de calibration du silence
CALIB_MARGIN = 2                  # marge de sécurité ajoutée au bruit mesuré

# --- moteur SunVox ----------------------------------------------------------
SV_SLOT = 0
SV_MODE_SYNTH = "Synthé (généré)"
SV_MODE_SAMPLER = "Sampler (.wav)"
SV_MODES = (SV_MODE_SYNTH, SV_MODE_SAMPLER)
SV_NOTE_OFF = 128                  # NOTECMD_NOTE_OFF
SV_ALL_NOTES_OFF = 129             # NOTECMD_ALL_NOTES_OFF
SV_SET_PITCH = 133                 # NOTECMD_SET_PITCH
SV_MAX_VEL = 129                    # vélocité max SunVox
SV_SAMPLER_NOTE = 49                # note de déclenchement des samplers (C4)
# gamme pentatonique mineure de Do3 à Mi b5 : 1 note par électrode.
# Valeurs SunVox : 1 = Do0, chaque octave = +12. 37 = Do3.
DEFAULT_SV_NOTES = [37, 40, 42, 44, 46, 49, 52, 55, 58, 61, 63, 67]

# --- Thème sombre : une couleur par zone -----------------------------------
BG_ROOT = "#12121a"                  # fond général
BG_ROW_EVEN = "#1d1d2c"              # lignes électrodes (alternées)
BG_ROW_ODD = "#171722"
BG_HEADER_S0 = "#26263c"             # en-têtes colonnes sons (alternés)
BG_HEADER_S1 = "#1c1c2e"
FG_MAIN = "#e6e6f0"                  # texte principal
FG_MUTED = "#8f96ad"                 # texte secondaire

ZONE_SEUILS = "#2a2015"              # orange  : seuils, répartition, calibration
ACCENT_SEUILS = "#e8a33d"
ZONE_LECTURE = "#14261a"             # vert    : play/stop, rejeu
ACCENT_LECTURE = "#43c05a"
ZONE_VOLUME = "#0f2230"              # bleu    : volume
ACCENT_VOLUME = "#3fb7d8"
ZONE_FICHIERS = "#221830"            # violet  : charger / sauver / reset
ACCENT_FICHIERS = "#a48ad0"
ZONE_MOTEUR = "#2a1522"              # rose    : moteur audio SunVox/Pygame
ACCENT_MOTEUR = "#e08ab0"
ACCENT_ELECTRODES = "#3fb7d8"        # cyan    : noms E, barres de niveau
COL_DIFF = "#ffb454"                 # valeur diff en orange vif

COL_EVEN = BG_ROW_EVEN               # couleur de base des cellules (lignes paires)
COL_ODD = BG_ROW_ODD
COL_ACTIVE = "#1f7a34"               # plage en cours (vert)
COL_DISABLED = "#101018"             # min == max : désactivée
COL_INVALID = "#8a3030"              # min > max (rouge)

# ---------------------------------------------------------------------------
# Capteur MPR121 — module fourni par le paquet picap de Bare Conductive
# (bibliothèque wiringpi-mpr121, installée au niveau du système) :
# "import MPR121" le trouve automatiquement, comme dans les anciennes versions.
# S'il est absent, l'application démarre en MODE DÉMO (sans crash).
# ---------------------------------------------------------------------------
sensor = None
sensor_error = ""
try:
    import MPR121
    sensor = MPR121.begin()
    sensor.set_touch_threshold(DEFAULT_TOUCH_THRESHOLD)
    sensor.set_release_threshold(DEFAULT_RELEASE_THRESHOLD)
    SENSOR_OK = True
except Exception as exc:            # capteur absent, I2C HS, lib manquante...
    sensor_error = str(exc)
    SENSOR_OK = False


# ---------------------------------------------------------------------------
# Moteur SunVox
# ---------------------------------------------------------------------------
class SunVoxEngine:
    """Synthé modulaire SunVox piloté par les électrodes capacitives.

    Le projet SunVox est construit par code au lancement :
      - mode Synthé  : Generator (12 pistes) -> Filtre -> Echo -> Output ;
      - mode Sampler : modules Sampler créés à la demande avec les .wav
        de tracks/E{e}/{iii}.wav, un par couple (électrode, son).
    Tous les appels se font depuis le thread principal Tk (root.after),
    SunVox rendant le reste en interne.
    """

    def __init__(self, mode, notes, volume=100):
        self.mode = mode
        self.notes = list(notes)
        self.volume = max(0, min(100, int(volume)))
        self.note_on = [False] * NUM_ELECTRODES
        self._last_pitch = [None] * NUM_ELECTRODES
        self._samplers = {}            # (électrode, son) -> numéro de module
        self._gen = None               # module Generator (mode synthé)
        self._filter = None            # module Filtre (mode synthé)
        self._cutoff_ctl = None        # n° du contrôleur "Cutoff (Hz)"
        self._cutoff_lo = 0
        self._cutoff_hi = 1
        self._last_cutoff = -1
        self._vol_ctl = None           # contrôleur "Volume" du module Output
        self._vol_lo = 0
        self._vol_hi = 1

        sv.init(None, 44100, 2, 0)     # config auto (ALSA sur le Pi)
        sv.open_slot(SV_SLOT)
        self._build()
        self.set_volume(self.volume)

    # ------------------------------------------------------------ projet
    def _build(self):
        sv.lock_slot(SV_SLOT)
        try:
            if self.mode == SV_MODE_SYNTH:
                self._gen = sv.new_module(SV_SLOT, b"Generator",
                                          b"SynthCap", 0, 0, 0)
                self._filter = sv.new_module(SV_SLOT, b"Filter",
                                             b"Filtre", 220, 0, 0)
                echo = sv.new_module(SV_SLOT, b"Echo", b"Echo", 440, 0, 0)
                # module 0 = Output (présent dans tout projet SunVox)
                sv.connect_module(SV_SLOT, self._gen, self._filter)
                sv.connect_module(SV_SLOT, self._filter, echo)
                sv.connect_module(SV_SLOT, echo, 0)
            if self._filter is not None:
                self._cutoff_ctl = self._find_ctl(self._filter, "Cutoff (Hz)")
                if self._cutoff_ctl is not None:
                    self._cutoff_lo = sv.get_module_ctl_min(
                        SV_SLOT, self._filter, self._cutoff_ctl, 0)
                    self._cutoff_hi = sv.get_module_ctl_max(
                        SV_SLOT, self._filter, self._cutoff_ctl, 0)
            self._vol_ctl = self._find_ctl(0, "Volume")
            if self._vol_ctl is not None:
                self._vol_lo = sv.get_module_ctl_min(
                    SV_SLOT, 0, self._vol_ctl, 0)
                self._vol_hi = sv.get_module_ctl_max(
                    SV_SLOT, 0, self._vol_ctl, 0)
        finally:
            sv.unlock_slot(SV_SLOT)

    @staticmethod
    def _find_ctl(mod, wanted):
        """Retourne le numéro du contrôleur 'wanted' du module (ou None)."""
        try:
            for n in range(sv.get_number_of_module_ctls(SV_SLOT, mod)):
                raw = sv.get_module_ctl_name(SV_SLOT, mod, n)
                if raw and raw.decode("utf-8", "ignore").strip() == wanted:
                    return n
        except Exception:
            pass
        return None

    # -------------------------------------------------------- samplers
    def _get_sampler(self, electrode, sound):
        """Crée (une seule fois) le module Sampler pour (électrode, son)."""
        key = (electrode, sound)
        if key in self._samplers:
            return self._samplers[key]
        path = os.path.join(TRACKS_DIR, "E%d" % electrode, "%03d.wav" % sound)
        if not os.path.exists(path):
            return None
        try:
            sv.lock_slot(SV_SLOT)
            try:
                mod = sv.new_module(
                    SV_SLOT, b"Sampler",
                    ("S%d_%d" % (electrode, sound)).encode(),
                    100 + 40 * sound, 100 + 60 * electrode, 0)
                sv.sampler_load(SV_SLOT, mod, path.encode(), -1)
                sv.connect_module(SV_SLOT, mod, 0)
            finally:
                sv.unlock_slot(SV_SLOT)
        except Exception:
            return None
        self._samplers[key] = mod
        return mod

    # ---------------------------------------------------------- jeu
    @staticmethod
    def _velocity(diff):
        """Vélocité 1..129 indexée sur le niveau capacitif."""
        t = max(0.0, min(1.0, diff / float(DIFF_DISPLAY_MAX)))
        return max(1, min(SV_MAX_VEL, int(40 + 89 * t)))

    def note_on(self, electrode, sound, diff):
        vel = self._velocity(diff)
        try:
            if self.mode == SV_MODE_SYNTH:
                note = max(1, min(120, int(self.notes[electrode])))
                sv.send_event(SV_SLOT, electrode, note, vel,
                              self._gen + 1, 0, 0)
            else:
                mod = self._get_sampler(electrode, sound)
                if mod is None:
                    return
                sv.send_event(SV_SLOT, electrode, SV_SAMPLER_NOTE, vel,
                              mod + 1, 0, 0)
            self.note_on[electrode] = True
        except Exception:
            pass

    def note_off(self, electrode):
        if not self.note_on[electrode]:
            return
        try:
            sv.send_event(SV_SLOT, electrode, SV_NOTE_OFF, 0, 0, 0, 0)
        except Exception:
            pass
        self.note_on[electrode] = False
        self._last_pitch[electrode] = None

    def all_off(self):
        for e in range(NUM_ELECTRODES):
            self.note_off(e)
        try:
            sv.send_event(SV_SLOT, 0, SV_ALL_NOTES_OFF, 0, 0, 0, 0)
        except Exception:
            pass

    def bend(self, electrode, semitones):
        """Pitch bend continu (demi-tons vers l'aigu) de la note tenue."""
        if not self.note_on[electrode]:
            return
        if self.mode == SV_MODE_SYNTH:
            n = max(1, min(120, int(self.notes[electrode])))
            pitch = 0x7800 - (n - 1) * 0x100       # 0x7800 = Do0
        else:
            pitch = 0x4800                          # Do4 = note de trigger
        k = int(max(0.0, min(24.0, float(semitones))))
        pitch = max(0, pitch - k * 0x100)
        if pitch != self._last_pitch[electrode]:
            try:
                # module 0 = dernier module utilisé sur cette piste
                sv.send_event(SV_SLOT, electrode, SV_SET_PITCH, 0, 0, 0, pitch)
                self._last_pitch[electrode] = pitch
            except Exception:
                pass

    # -------------------------------------------------- contrôle continu
    def continuous(self, diffs):
        """Cutoff du filtre piloté par l'électrode la plus active (mode synthé)."""
        if self._filter is None or self._cutoff_ctl is None:
            return
        peak = 0
        for d in diffs:
            if d > peak:
                peak = d
        t = max(0.0, min(1.0, peak / float(DIFF_DISPLAY_MAX)))
        val = int(self._cutoff_lo
                  + (self._cutoff_hi - self._cutoff_lo) * (t * t))
        if val != self._last_cutoff:
            try:
                sv.set_module_ctl_value(SV_SLOT, self._filter,
                                         self._cutoff_ctl, val, 0)
                self._last_cutoff = val
            except Exception:
                pass

    def set_volume(self, percent):
        """Volume général : contrôleur 'Volume' du module Output."""
        pct = max(0, min(100, int(percent)))
        self.volume = pct
        if self._vol_ctl is None:
            return
        try:
            val = self._vol_lo + (self._vol_hi - self._vol_lo) * pct // 100
            sv.set_module_ctl_value(SV_SLOT, 0, self._vol_ctl, val, 0)
        except Exception:
            pass

    def close(self):
        try:
            self.all_off()
            sv.close_slot(SV_SLOT)
        except Exception:
            pass
        try:
            sv.deinit()
        except Exception:
            pass


def get_int(var, default=0):
    """Lecture sûre d'une IntVar (l'utilisateur peut être en train de taper)."""
    try:
        return int(var.get())
    except (tk.TclError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
class CapTouchApp:
    def __init__(self, root):
        self.root = root
        root.title("CapTouch Sound Mapper V4 — PiCap + SunVox")
        root.geometry("1280x640")
        root.minsize(900, 480)
        if KIOSK_MODE:
            root.attributes("-fullscreen", True)

        # --- thème sombre global -------------------------------------------
        root.configure(bg=BG_ROOT)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG_ROOT, foreground=FG_MAIN)
        style.configure("TFrame", background=BG_ROOT)
        style.configure("TLabel", background=BG_ROOT, foreground=FG_MAIN)
        style.configure("TButton", background="#2b2b3e", foreground=FG_MAIN,
                         borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", "#3d3d55")])
        style.configure("TEntry", fieldbackground="#26263a", foreground=FG_MAIN,
                        insertcolor=FG_MAIN, bordercolor="#3a3a52")
        style.configure("TSpinbox", fieldbackground="#26263a", foreground=FG_MAIN,
                        insertcolor=FG_MAIN, arrowcolor=FG_MAIN,
                        bordercolor="#3a3a52", background="#2b2b3e",
                        buttonbackground="#2b2b3e")
        style.configure("TCombobox", fieldbackground="#26263a",
                        foreground=FG_MAIN, background="#2b2b3e",
                        arrowcolor=FG_MAIN, bordercolor="#3a3a52")
        style.configure("Horizontal.TScrollbar", troughcolor="#1b1b28",
                        background="#33334a", bordercolor=BG_ROOT,
                        arrowcolor=FG_MAIN)
        self.style = style

        # --- état ---------------------------------------------------------
        self.touch_var = tk.IntVar(value=DEFAULT_TOUCH_THRESHOLD)
        self.release_var = tk.IntVar(value=DEFAULT_RELEASE_THRESHOLD)
        self.volume_var = tk.IntVar(value=100)
        self.retrigger_var = tk.DoubleVar(value=DEFAULT_RETRIGGER_DELAY)
        self.spread_max_var = tk.IntVar(value=DEFAULT_SPREAD_MAX)

        # moteur audio : SunVox par défaut s'il est disponible
        self.engine_var = tk.StringVar(
            value=("SunVox" if SV_OK else "Pygame"))
        self.sv_mode_var = tk.StringVar(value=SV_MODE_SYNTH)
        self.sv_notes = list(DEFAULT_SV_NOTES)
        self.audio_engine = None        # None / "pygame" / "sunvox"
        self.sv_engine = None           # instance SunVoxEngine
        self.pg_sounds = [[None] * NUM_SOUNDS
                          for _ in range(NUM_ELECTRODES)]

        # plages[e][2i] = min du son i, plages[e][2i+1] = max du son i
        # par défaut tout est désactivé (min == max == 0) => silence.
        self.plages = [[tk.IntVar(value=0) for _ in range(NUM_COLS)]
                       for _ in range(NUM_ELECTRODES)]

        # synchronisation : une case par SON (sync min + max ensemble)
        self.sync_vars = [tk.BooleanVar(value=False) for _ in range(NUM_SOUNDS)]

        self.diff_labels = [tk.StringVar(value="0") for _ in range(NUM_ELECTRODES)]
        self.entry_widgets = [[None] * NUM_COLS for _ in range(NUM_ELECTRODES)]
        self.entry_colors = {}          # cache : évite de reconfigurer 288 widgets
        self.bars = []
        self.bar_rects = []

        self.active_range = [None] * NUM_ELECTRODES
        self.last_play_time = [0.0] * NUM_ELECTRODES

        self.running = False
        self._syncing = False

        # calibration du silence (bruit de repos mesuré par électrode)
        self.noise_floor = [0] * NUM_ELECTRODES
        self._calibrating = False
        self._calib_end = 0.0
        self._calib_samples = [0] * NUM_ELECTRODES
        self._calib_was_running = False

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

        # synchronisation temps réel des colonnes
        for e in range(NUM_ELECTRODES):
            for c in range(NUM_COLS):
                self.plages[e][c].trace_add(
                    "write", lambda *_a, e=e, c=c: self._on_range_change(e, c))

        # raccourcis
        root.bind_all("<space>", self._on_space)
        root.bind_all("<Escape>", self._exit_fullscreen)
        root.bind_all("<F11>", self._toggle_fullscreen)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.load_config(DEFAULT_CONFIG_FILE, quiet=True)
        self.switch_engine()            # démarre le moteur configuré
        self.set_volume(self.volume_var.get())

        self._poll()
        self.toggle_running()          # démarre en lecture

        # NB : le message est placé APRÈS toggle_running pour ne pas être écrasé
        if SENSOR_OK:
            # calibration automatique du silence ~0,6 s après l'ouverture
            # (laisse le temps aux lignes I2C de se stabiliser)
            self.root.after(600, self.start_calibration)
        else:
            root.title("CapTouch Sound Mapper V4 — MODE DÉMO (capteur indisponible)")
            self.set_status(f"Mode démo — capteur indisponible : {sensor_error}")

    # ------------------------------------------------------------------ UI
    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BG_ROOT)
        bar.pack(side="top", fill="x", padx=10, pady=(10, 2))

        row1 = tk.Frame(bar, bg=BG_ROOT)
        row1.pack(side="top", fill="x")
        row2 = tk.Frame(bar, bg=BG_ROOT)
        row2.pack(side="top", fill="x", pady=(6, 2))

        def zone(parent, title, bg, accent):
            z = tk.Frame(parent, bg=bg, padx=12, pady=7)
            z.pack(side="left", fill="y", padx=(0, 10))
            tk.Label(z, text=title, bg=bg, fg=accent,
                     font=("TkDefaultFont", 8, "bold")).pack(side="top", anchor="w")
            inner = tk.Frame(z, bg=bg)
            inner.pack(side="top", anchor="w", pady=(4, 0))
            return inner

        def mklabel(parent, text, bg, fg=FG_MAIN):
            return tk.Label(parent, text=text, bg=bg, fg=fg)

        def mkentry(parent, var):
            return tk.Entry(parent, textvariable=var, width=4, justify="center",
                            bg="#26263a", fg=FG_MAIN, insertbackground=FG_MAIN,
                            relief="flat", highlightthickness=1,
                            highlightbackground="#3a3a52")

        def mkbtn(parent, text, cmd, bg, fg, bg_active, padx=8, bold=False):
            font = ("TkDefaultFont", 10, "bold") if bold else "TkDefaultFont"
            return tk.Button(parent, text=text, command=cmd, bd=0, relief="flat",
                             bg=bg, fg=fg, activebackground=bg_active,
                             activeforeground=fg, padx=padx, pady=3,
                             cursor="hand2", font=font)

        # --- zone ORANGE : seuils & configuration -------------------------
        seuils = zone(row1, "SEUILS / CONFIG", ZONE_SEUILS, ACCENT_SEUILS)
        mklabel(seuils, "Touch:", ZONE_SEUILS).pack(side="left")
        mkentry(seuils, self.touch_var).pack(side="left", padx=(3, 8))
        mklabel(seuils, "Release:", ZONE_SEUILS).pack(side="left")
        mkentry(seuils, self.release_var).pack(side="left", padx=(3, 8))
        mkbtn(seuils, "Appliquer", self.apply_thresholds,
              "#3d2f1c", "#ffcb7a", "#54401f").pack(side="left", padx=(0, 10))
        mklabel(seuils, "Répartir jusqu'à:", ZONE_SEUILS).pack(side="left")
        mkentry(seuils, self.spread_max_var).pack(side="left", padx=(3, 3))
        mkbtn(seuils, "Répartir", self.spread_ranges,
              "#3d2f1c", "#ffcb7a", "#54401f").pack(side="left", padx=(0, 10))
        mkbtn(seuils, "Calibrer silence", self.start_calibration,
              "#7a5a1e", "#ffe9bd", "#96722a").pack(side="left")

        # --- zone VERTE : lecture --------------------------------------------
        lecture = zone(row1, "LECTURE", ZONE_LECTURE, ACCENT_LECTURE)
        self.playstop_btn = mkbtn(lecture, "■ Stop", self.toggle_running,
                                  "#b23a31", "#ffffff", "#d04c40",
                                  padx=18, bold=True)
        self.playstop_btn.pack(side="left", padx=(0, 12))
        mklabel(lecture, "Rejeu (s):", ZONE_LECTURE).pack(side="left")
        ttk.Spinbox(lecture, from_=0.1, to=10.0, increment=0.1, width=5,
                    textvariable=self.retrigger_var).pack(side="left", padx=(3, 0))

        # --- zone ROSE : moteur audio (NOUVEAU V4) ---------------------------
        moteur = zone(row2, "MOTEUR AUDIO", ZONE_MOTEUR, ACCENT_MOTEUR)
        engines = ("SunVox", "Pygame") if SV_OK else ("Pygame",)
        self.engine_combo = ttk.Combobox(moteur, textvariable=self.engine_var,
                                         values=engines, state="readonly",
                                         width=8)
        self.engine_combo.pack(side="left")
        self.engine_combo.bind("<<ComboboxSelected>>", self.switch_engine)
        mklabel(moteur, "Mode SunVox:", ZONE_MOTEUR).pack(side="left", padx=(10, 0))
        self.sv_mode_combo = ttk.Combobox(moteur, textvariable=self.sv_mode_var,
                                          values=SV_MODES, state="readonly",
                                          width=13)
        self.sv_mode_combo.pack(side="left", padx=(3, 0))
        self.sv_mode_combo.bind("<<ComboboxSelected>>", self.switch_sv_mode)
        if not SV_OK:
            self.sv_mode_combo.state(["disabled"])
            mklabel(moteur, "(dossier « sunvox » requis)",
                    ZONE_MOTEUR, FG_MUTED).pack(side="left", padx=(8, 0))

        # --- zone BLEUE : volume ---------------------------------------------
        vol = zone(row2, "VOLUME", ZONE_VOLUME, ACCENT_VOLUME)
        self.volume_scale = tk.Scale(vol, from_=0, to=100, orient="horizontal",
                                     length=160, showvalue=0, bg=ZONE_VOLUME,
                                     fg=FG_MAIN, troughcolor="#0a1822",
                                     highlightthickness=0,
                                     highlightbackground=ZONE_VOLUME,
                                     activebackground=ACCENT_VOLUME,
                                     command=self.set_volume)
        self.volume_scale.set(100)
        self.volume_scale.pack(side="left")
        self.volume_label = mklabel(vol, "100%", ZONE_VOLUME, ACCENT_VOLUME)
        self.volume_label.pack(side="left", padx=(8, 0))

        # --- zone VIOLETTE : fichiers -----------------------------------------
        fichiers = zone(row2, "FICHIERS", ZONE_FICHIERS, ACCENT_FICHIERS)
        for text, cmd in (("Charger…", lambda: self.load_config(None)),
                          ("Sauver", self.save_config),
                          ("Sauver sous…", self.save_config_as),
                          ("Réinitialiser", self.reset_all)):
            mkbtn(fichiers, text, cmd, "#322748", "#d8c9f5", "#443561"
                  ).pack(side="left", padx=(0, 6))
        mkbtn(fichiers, "✕ Quitter", self.on_close,
              "#7a2430", "#ffd9de", "#9a3040", padx=12).pack(side="left")

    def _build_table(self):
        container = tk.Frame(self.root, bg=BG_ROOT)
        container.pack(side="top", fill="both", expand=True)

        tk.Label(container, text="ÉLECTRODES", bg=BG_ROOT, fg=ACCENT_ELECTRODES,
                 font=("TkDefaultFont", 9, "bold")
                 ).pack(side="top", anchor="w", padx=14, pady=(8, 0))

        self.canvas = tk.Canvas(container, highlightthickness=0, bg=BG_ROOT)
        hscroll = ttk.Scrollbar(container, orient="horizontal",
                                command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=hscroll.set)
        self.canvas.pack(side="top", fill="both", expand=True)
        hscroll.pack(side="bottom", fill="x")

        frame = tk.Frame(self.canvas, bg=BG_ROOT)
        self.canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>",
                   lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # molette horizontale (X11 : boutons 6/7) — tous les systèmes ne
        # gèrent pas ces boutons (TclError "specified keysym ... for
        # non-key event" sur certains Tk 8.6 / Raspbian) : si le bind est
        # refusé, on l'ignore et la barre de défilement reste utilisable.
        for seq, units in (("<Button-6>", 2), ("<Button-7>", -2)):
            try:
                self.canvas.bind_all(
                    seq,
                    lambda e, u=units: self.canvas.xview_scroll(u, "units"))
            except tk.TclError:
                pass

        # --- en-tête -------------------------------------------------------
        for col, txt in ((0, "Test"), (1, "E"), (2, "Diff"), (3, "Niveau")):
            tk.Label(frame, text=txt, width=5, bg="#101018", fg=FG_MUTED,
                     font=("TkDefaultFont", 9, "bold")).grid(
                         row=0, column=col, sticky="nsew")
        for i in range(NUM_SOUNDS):
            bg = BG_HEADER_S0 if i % 2 == 0 else BG_HEADER_S1
            tk.Label(frame, text=f"S{i}\nmin", bg=bg, width=4, fg=FG_MAIN,
                     font=("TkDefaultFont", 9, "bold")).grid(
                         row=0, column=4 + 2 * i, sticky="nsew")
            tk.Label(frame, text=f"S{i}\nmax", bg=bg, width=4, fg=FG_MAIN,
                     font=("TkDefaultFont", 9, "bold")).grid(
                         row=0, column=5 + 2 * i, sticky="nsew")

        # --- lignes électrodes ---------------------------------------------
        for e in range(NUM_ELECTRODES):
            row = e + 1
            color = COL_EVEN if e % 2 == 0 else COL_ODD
            tk.Button(frame, text="▶", width=2, relief="flat", bd=0,
                      bg="#23232e", fg=ACCENT_VOLUME, activebackground="#3a3a52",
                      activeforeground=ACCENT_VOLUME, cursor="hand2",
                      command=lambda e=e: self.test_electrode(e)
                      ).grid(row=row, column=0, sticky="nsew")
            tk.Label(frame, text=f"E{e}", width=4, bg=color,
                     fg=ACCENT_ELECTRODES,
                     font=("TkDefaultFont", 9, "bold")).grid(
                         row=row, column=1, sticky="nsew")
            tk.Label(frame, textvariable=self.diff_labels[e], width=5,
                     fg=COL_DIFF, bg=color).grid(row=row, column=2, sticky="nsew")

            bar = tk.Canvas(frame, width=96, height=16, bg="#0d0d15",
                            highlightthickness=0)
            bar.grid(row=row, column=3, sticky="nsew", padx=2, pady=2)
            self.bars.append(bar)
            self.bar_rects.append(None)

            for i in range(NUM_SOUNDS):
                cmin, cmax = 4 + 2 * i, 5 + 2 * i
                wmin = tk.Entry(frame, textvariable=self.plages[e][2 * i],
                                width=4, justify="center", bg=color, fg=FG_MAIN,
                                insertbackground=FG_MAIN, relief="flat",
                                highlightthickness=1,
                                highlightbackground="#31314a")
                wmin.grid(row=row, column=cmin)
                wmax = tk.Entry(frame, textvariable=self.plages[e][2 * i + 1],
                                width=4, justify="center", bg=color, fg=FG_MAIN,
                                insertbackground=FG_MAIN, relief="flat",
                                highlightthickness=1,
                                highlightbackground="#31314a")
                wmax.grid(row=row, column=cmax)
                self.entry_widgets[e][2 * i] = wmin
                self.entry_widgets[e][2 * i + 1] = wmax

        # --- ligne « Sync » (une case par son) ------------------------------
        tk.Label(frame, text="Sync", fg=FG_MUTED, bg=BG_ROOT).grid(
            row=NUM_ELECTRODES + 2, column=0, columnspan=4, sticky="e")
        for i in range(NUM_SOUNDS):
            tk.Checkbutton(frame, variable=self.sync_vars[i], bg=BG_ROOT,
                           fg=FG_MAIN, selectcolor="#26263a",
                           activebackground=BG_ROOT, activeforeground=FG_MAIN
                           ).grid(row=NUM_ELECTRODES + 2, column=4 + 2 * i,
                                  columnspan=2, sticky="nsew")

        # --- légende --------------------------------------------------------
        tk.Label(frame,
                 text="vert = plage active   ·   gris foncé = désactivée (min = max)   ·   "
                      "rouge = min > max   ·   Sync = copie min & max de la colonne "
                      "sur toutes les électrodes",
                 fg=FG_MUTED, bg=BG_ROOT).grid(
                     row=NUM_ELECTRODES + 3, column=0,
                     columnspan=4 + NUM_COLS, sticky="w", pady=(6, 0))

    def _build_statusbar(self):
        self.status_label = tk.Label(self.root, text="", bg="#0c0c13",
                                     fg=FG_MUTED, anchor="w", padx=10, pady=3)
        self.status_label.pack(side="bottom", fill="x")

    def set_status(self, msg):
        self.status_label.config(text=msg)

    # ------------------------------------------------------------- capteur
    def read_diffs(self):
        diffs = [0] * NUM_ELECTRODES
        if SENSOR_OK and sensor is not None:
            try:
                sensor.update_baseline_data()
                sensor.update_filtered_data()
                for e in range(NUM_ELECTRODES):
                    diffs[e] = (sensor.get_baseline_data(e)
                                - sensor.get_filtered_data(e))
            except Exception as exc:
                self.set_status(f"Erreur capteur : {exc}")
        return diffs

    # ------------------------------------------------------------ boucle
    def _poll(self):
        raw_diffs = self.read_diffs()
        now = time.monotonic()
        retrigger = self.retrigger_var.get()
        diffs = [0] * NUM_ELECTRODES

        # --- calibration du silence en cours ------------------------------
        if self._calibrating:
            remaining = self._calib_end - now
            if remaining > 0:
                for e in range(NUM_ELECTRODES):
                    self._calib_samples[e] = max(self._calib_samples[e],
                                                  raw_diffs[e])
                self.set_status(f"Calibration du silence… {remaining:.1f}s "
                                f"— NE TOUCHEZ PAS les électrodes")
                self.root.after(POLL_MS, self._poll)
                return
            self._finish_calibration()

        for e in range(NUM_ELECTRODES):
            # diff calibré : bruit de repos propre à l'électrode (matière,
            # longueur de fil/capuchon) soustrait -> 0 = silence garanti
            diff = max(0, raw_diffs[e] - self.noise_floor[e])
            diffs[e] = diff
            self.diff_labels[e].set(str(diff))
            self._update_bar(e, diff)

            # détection de la plage active (première plage valide qui contient diff)
            active = None
            for i in range(NUM_SOUNDS):
                mn = get_int(self.plages[e][2 * i])
                mx = get_int(self.plages[e][2 * i + 1])
                if mx > mn and mn <= diff <= mx:
                    active = i
                    break

            prev = self.active_range[e]

            # SunVox : couper la note tenue dès qu'on quitte la plage
            if self.audio_engine == "sunvox" and self.sv_engine is not None:
                if prev is not None and active != prev:
                    self.sv_engine.note_off(e)

            # rejeu immédiat à l'entrée dans une nouvelle plage
            can_play = False
            if active is not None:
                if self.audio_engine == "sunvox":
                    can_play = self.sv_engine is not None
                elif self.audio_engine == "pygame":
                    can_play = self.pg_sounds[e][active] is not None
            if (self.running and active is not None and can_play
                    and (prev != active
                         or now - self.last_play_time[e] >= retrigger)):
                self._trigger(e, active, diff)
                self.last_play_time[e] = now

            # SunVox : pitch bend continu selon la position dans la plage
            if (self.audio_engine == "sunvox" and self.sv_engine is not None
                    and active is not None):
                mn = get_int(self.plages[e][2 * active])
                mx = get_int(self.plages[e][2 * active + 1])
                span = max(1, mx - mn)
                self.sv_engine.bend(e, 12.0 * (diff - mn) / span)

            self.active_range[e] = active
            self._refresh_entry_colors(e, active)

        # SunVox : filtre (cutoff) piloté en continu par l'électrode la plus active
        if self.audio_engine == "sunvox" and self.sv_engine is not None:
            self.sv_engine.continuous(diffs)

        self.root.after(POLL_MS, self._poll)

    def _update_bar(self, e, diff):
        bar = self.bars[e]
        w = max(20, bar.winfo_width())
        length = max(0, min(1.0, diff / float(DIFF_DISPLAY_MAX))) * (w - 2)
        fill = ACCENT_LECTURE if self.active_range[e] is not None else ACCENT_ELECTRODES
        if self.bar_rects[e] is None:
            self.bar_rects[e] = bar.create_rectangle(1, 1, 1 + length, 15, fill=fill)
        else:
            bar.coords(self.bar_rects[e], 1, 1, 1 + length, 15)
            bar.itemconfig(self.bar_rects[e], fill=fill)

    def _refresh_entry_colors(self, e, active):
        base = COL_EVEN if e % 2 == 0 else COL_ODD
        for i in range(NUM_SOUNDS):
            mn = get_int(self.plages[e][2 * i])
            mx = get_int(self.plages[e][2 * i + 1])
            if mn > mx:
                color = COL_INVALID
            elif mx == mn:
                color = COL_DISABLED
            elif i == active:
                color = COL_ACTIVE
            else:
                color = base
            for c in (2 * i, 2 * i + 1):
                widget = self.entry_widgets[e][c]
                if self.entry_colors.get(id(widget)) != color:
                    widget.configure(bg=color)
                    self.entry_colors[id(widget)] = color

    # -------------------------------------------------- moteurs audio
    def switch_engine(self, *_args):
        """Bascule le moteur audio (appelé par la combobox ou au démarrage)."""
        wanted = self.engine_var.get()
        if wanted == "SunVox" and not SV_OK:
            self.set_status("SunVox indisponible (%s) — moteur Pygame utilisé. "
                            "Copiez le dossier « sunvox » à côté du script."
                            % (SV_ERROR or "bibliothèque absente"))
            self.engine_var.set("Pygame")
            wanted = "Pygame"
        target = "sunvox" if wanted == "SunVox" else "pygame"
        if self.audio_engine == target:
            return
        if target == "sunvox":
            self._start_sunvox()
        else:
            self._start_pygame()
        self.set_volume(self.volume_var.get())

    def switch_sv_mode(self, *_args):
        """Changement de mode SunVox : reconstruit le projet."""
        if self.audio_engine == "sunvox":
            self._stop_sunvox()
            self._start_sunvox()
            self.set_volume(self.volume_var.get())

    def _start_pygame(self):
        if self.audio_engine == "pygame":
            return
        if self.audio_engine == "sunvox":
            self._stop_sunvox()
        try:
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2,
                                 buffer=512)
            pygame.init()
            pygame.mixer.set_num_channels(64)
            found = 0
            for e in range(NUM_ELECTRODES):
                folder = os.path.join(TRACKS_DIR, "E%d" % e)
                for i in range(NUM_SOUNDS):
                    path = os.path.join(folder, "%03d.wav" % i)
                    self.pg_sounds[e][i] = None
                    if os.path.exists(path):
                        try:
                            self.pg_sounds[e][i] = Sound(path)
                            found += 1
                        except Exception:
                            pass
            self.audio_engine = "pygame"
            self.set_status(f"Moteur Pygame : {found} son(s) chargé(s) "
                            f"depuis tracks/.")
        except Exception as exc:
            self.set_status(f"Erreur moteur Pygame : {exc}")

    def _start_sunvox(self):
        if self.audio_engine == "sunvox":
            return
        if self.audio_engine == "pygame":
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            self.audio_engine = None
        try:
            self.sv_engine = SunVoxEngine(self.sv_mode_var.get(),
                                          self.sv_notes,
                                          self.volume_var.get())
        except Exception as exc:
            self.set_status(f"SunVox : échec d'initialisation ({exc}) — "
                            f"retour au moteur Pygame.")
            self.engine_var.set("Pygame")
            self.sv_engine = None
            self._start_pygame()
            return
        self.audio_engine = "sunvox"
        if self.sv_engine.mode == SV_MODE_SYNTH:
            detail = "synthé Generator 12 pistes + Filtre + Echo, gamme " \
                     "pentatonique par électrode"
        else:
            detail = "samplers .wav chargés à la demande depuis tracks/"
        self.set_status(f"Moteur SunVox actif : {detail}.")

    def _stop_sunvox(self):
        if self.sv_engine is not None:
            try:
                self.sv_engine.close()
            except Exception:
                pass
        self.sv_engine = None
        self.audio_engine = None

    def _trigger(self, e, sound, diff):
        """Déclenche le son (électrode e, son S{sound}) sur le moteur actif."""
        if self.audio_engine == "sunvox" and self.sv_engine is not None:
            self.sv_engine.note_on(e, sound, diff)
        elif self.audio_engine == "pygame":
            s = self.pg_sounds[e][sound]
            if s is not None:
                s.play()

    # ------------------------------------------------------------- actions
    def toggle_running(self):
        self.running = not self.running
        suffix = "   [MODE DÉMO]" if not SENSOR_OK else ""
        if self.running:
            self.playstop_btn.config(text="■ Stop", bg="#b23a31",
                                     activebackground="#d04c40")
            self.set_status("Lecture : ON" + suffix)
        else:
            self.playstop_btn.config(text="▶ Play", bg="#2e7d38",
                                     activebackground="#3f9c4a")
            if self.audio_engine == "sunvox" and self.sv_engine is not None:
                self.sv_engine.all_off()      # coupe les notes tenues
            self.set_status("Lecture : OFF" + suffix)

    # -------------------------------------------------- plein écran
    def _toggle_fullscreen(self, _event=None):
        self.root.attributes("-fullscreen",
                             not self.root.attributes("-fullscreen"))

    def _exit_fullscreen(self, _event=None):
        self.root.attributes("-fullscreen", False)

    # -------------------------------------------------- calibration silence
    def start_calibration(self, duration=CALIB_DURATION):
        """Mesure le bruit capacitif de repos de chaque électrode.
        À lancer sans rien toucher : le max observé par électrode (matière,
        longueur du câble...) devient le zéro de référence."""
        if self._calibrating:
            return
        if not SENSOR_OK:
            self.set_status("Calibration impossible : capteur indisponible.")
            return
        self._calibrating = True
        self._calib_end = time.monotonic() + duration
        self._calib_samples = [0] * NUM_ELECTRODES
        self._calib_was_running = self.running
        self.running = False            # aucun son pendant la mesure

    def _finish_calibration(self):
        self._calibrating = False
        self.noise_floor = [s + CALIB_MARGIN for s in self._calib_samples]
        self.running = self._calib_was_running
        floors = ", ".join(f"E{e}:{self.noise_floor[e]}"
                           for e in range(NUM_ELECTRODES))
        self.set_status(f"Silence calibré (bruit/câble/matière par "
                        f"électrode) : {floors}")

    def _on_space(self, _event):
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return                       # ne pas voler la barre d'espace
        self.toggle_running()

    def set_volume(self, val):
        try:
            volume = float(val) / 100.0
        except (TypeError, ValueError):
            return
        self.volume_var.set(int(round(volume * 100)))
        self.volume_label.config(text=f"{int(round(volume * 100))}%")
        if self.audio_engine == "sunvox" and self.sv_engine is not None:
            self.sv_engine.set_volume(self.volume_var.get())
        else:
            for e in range(NUM_ELECTRODES):
                for i in range(NUM_SOUNDS):
                    if self.pg_sounds[e][i] is not None:
                        self.pg_sounds[e][i].set_volume(volume)

    def apply_thresholds(self):
        touch = get_int(self.touch_var, DEFAULT_TOUCH_THRESHOLD)
        release = get_int(self.release_var, DEFAULT_RELEASE_THRESHOLD)
        if SENSOR_OK and sensor is not None:
            try:
                sensor.set_touch_threshold(touch)
                sensor.set_release_threshold(release)
                self.set_status(f"Seuils appliqués : Touch={touch} / Release={release}")
            except Exception as exc:
                self.set_status(f"Erreur seuils : {exc}")
        else:
            self.set_status("Seuils enregistrés (capteur indisponible).")

    def test_electrode(self, e):
        """Bouton Test ▶ : joue la note synthé / le sampler sans toucher."""
        if self.audio_engine == "sunvox" and self.sv_engine is not None:
            if self.sv_engine.mode == SV_MODE_SYNTH:
                self.sv_engine.note_on(e, 0, 100)
                self.set_status(f"Test E{e} → note synthé (piste {e})")
            else:
                for i in range(NUM_SOUNDS):
                    path = os.path.join(TRACKS_DIR, "E%d" % e, "%03d.wav" % i)
                    if os.path.exists(path):
                        self.sv_engine.note_on(e, i, 100)
                        self.set_status(f"Test E{e} → sampler S{i}")
                        break
                else:
                    self.set_status(f"Aucun .wav pour E{e} "
                                    f"(tracks/E{e}/xxx.wav)")
            self.root.after(
                500, lambda: self.sv_engine and self.sv_engine.note_off(e))
            return
        for i in range(NUM_SOUNDS):
            if self.pg_sounds[e][i] is not None:
                self.pg_sounds[e][i].play()
                self.set_status(f"Test E{e} → son S{i}")
                return
        self.set_status(f"Aucun son trouvé pour E{e} (tracks/E{e}/xxx.wav)")

    def spread_ranges(self):
        """Génère NUM_SOUNDS plages contiguës de 1 à spread_max (0 = silence)."""
        spread_max = get_int(self.spread_max_var, DEFAULT_SPREAD_MAX)
        if spread_max < NUM_SOUNDS:
            self.set_status("Valeur trop petite pour répartir 12 plages.")
            return
        step = spread_max / float(NUM_SOUNDS)
        for e in range(NUM_ELECTRODES):
            for i in range(NUM_SOUNDS):
                lo = int(i * step) + (1 if i == 0 else 2)
                hi = int((i + 1) * step) + 1
                self.plages[e][2 * i].set(lo)
                self.plages[e][2 * i + 1].set(hi)
        self.set_status(f"Plages réparties de 1 à {spread_max} sur toutes "
                        f"les électrodes (0 = silence).")

    def reset_all(self):
        if not messagebox.askyesno("Confirmation",
                                   "Réinitialiser seuils et plages ?"):
            return
        self.touch_var.set(DEFAULT_TOUCH_THRESHOLD)
        self.release_var.set(DEFAULT_RELEASE_THRESHOLD)
        for e in range(NUM_ELECTRODES):
            for c in range(NUM_COLS):
                self.plages[e][c].set(0)
        self.apply_thresholds()
        self.set_status("Configuration réinitialisée (plages désactivées).")

    # ------------------------------------------------------- sync colonnes
    def _on_range_change(self, e, c):
        """Toute édition d'une case avec Sync actif propage la valeur."""
        if self._syncing:
            return
        sound_idx = c // 2
        if not self.sync_vars[sound_idx].get():
            return
        self._syncing = True
        try:
            value = get_int(self.plages[e][c])
            for other in range(NUM_ELECTRODES):
                if other != e:
                    self.plages[other][c].set(value)
        finally:
            self._syncing = False

    # ----------------------------------------------------------- config IO
    def _config_dict(self):
        return {
            "touch_threshold": get_int(self.touch_var, DEFAULT_TOUCH_THRESHOLD),
            "release_threshold": get_int(self.release_var, DEFAULT_RELEASE_THRESHOLD),
            "volume": self.volume_var.get(),
            "retrigger_delay": self.retrigger_var.get(),
            "spread_max": get_int(self.spread_max_var, DEFAULT_SPREAD_MAX),
            "engine": self.engine_var.get(),
            "sv_mode": self.sv_mode_var.get(),
            "notes": list(self.sv_notes),
            "noise_floor": list(self.noise_floor),
            "plages": [[get_int(v) for v in row] for row in self.plages],
        }

    def save_config(self):
        self._write_config(DEFAULT_CONFIG_FILE)
        self.set_status(f"Configuration sauvegardée : {DEFAULT_CONFIG_FILE}")

    def save_config_as(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")],
            initialdir=APP_DIR)
        if filepath:
            self._write_config(filepath)
            self.set_status(f"Configuration sauvegardée : {filepath}")

    def _write_config(self, filepath):
        with open(filepath, "w") as f:
            json.dump(self._config_dict(), f, indent=4)

    def load_config(self, filepath=None, quiet=False):
        if filepath is None:
            filepath = filedialog.askopenfilename(
                filetypes=[("JSON files", "*.json")], initialdir=APP_DIR)
        if not filepath or not os.path.exists(filepath):
            return
        try:
            with open(filepath, "r") as f:
                config = json.load(f)

            self._syncing = True          # éviter les propagations en cascade
            try:
                self.touch_var.set(config.get("touch_threshold",
                                              DEFAULT_TOUCH_THRESHOLD))
                self.release_var.set(config.get("release_threshold",
                                                 DEFAULT_RELEASE_THRESHOLD))
                self.retrigger_var.set(config.get("retrigger_delay",
                                                  DEFAULT_RETRIGGER_DELAY))
                nf = config.get("noise_floor", [])
                for e in range(NUM_ELECTRODES):
                    self.noise_floor[e] = int(nf[e]) if e < len(nf) else 0
                if "volume" in config:
                    self.set_volume(config["volume"])

                # --- moteur audio (NOUVEAU V4) --------------------------
                if config.get("engine") in ("SunVox", "Pygame"):
                    self.engine_var.set(config["engine"])
                if config.get("sv_mode") in SV_MODES:
                    self.sv_mode_var.set(config["sv_mode"])
                notes = config.get("notes", [])
                for e in range(NUM_ELECTRODES):
                    if e < len(notes):
                        try:
                            n = int(notes[e])
                        except (TypeError, ValueError):
                            continue
                        if 1 <= n <= 120:
                            self.sv_notes[e] = n

                plages = config.get("plages", [])
                for e in range(NUM_ELECTRODES):
                    if e < len(plages):
                        row = plages[e]
                        for c in range(NUM_COLS):
                            if c < len(row):
                                self.plages[e][c].set(row[c])
            finally:
                self._syncing = False

            self.apply_thresholds()
            if not quiet:
                self.set_status(f"Configuration chargée : {filepath}")
        except Exception as exc:
            if not quiet:
                messagebox.showerror("Erreur", f"Chargement impossible : {exc}")

    # ------------------------------------------------------------- fermeture
    def on_close(self):
        self.running = False
        if self.sv_engine is not None:
            try:
                self.sv_engine.close()
            except Exception:
                pass
        try:
            pygame.mixer.quit()
            pygame.quit()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    CapTouchApp(root)
    root.mainloop()
