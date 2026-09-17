#pragma once
#include <Arduino.h>

constexpr uint8_t kNumLoadCells        = 4;
// One HX711 per corner. The 4th cell is assumed to continue the pin pattern;
// verify DOUT=10 / SCK=11 against the actual wiring before calibrating.
constexpr uint8_t kLoadcellDoutPins[]  = {3, 5, 7, 9};
constexpr uint8_t kLoadcellSckPins[]   = {4, 6, 8, 10};

// All four corners read positive under a downward load.
constexpr float kLoadcellPolarities[]  = {1.0f, 1.0f, 1.0f, 1.0f};

constexpr uint8_t kTareSamples        = 20;
constexpr uint8_t kCalibrationSamples = 20;

// Minimum tared ADC counts (summed across all cells) at a single placement to
// accept as valid. Guards against a forgotten mass or a wiring error.
constexpr float kMinReferenceSignalCounts = 100.0f;
