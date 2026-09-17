#pragma once
#include <Arduino.h>

constexpr uint8_t kNumLoadCells        = 4;
constexpr uint8_t kLoadcellDoutPins[]  = {2, 6, 10, 14};
constexpr uint8_t kLoadcellSckPins[]   = {3, 7, 11, 15};
constexpr float kLoadcellPolarities[]  = {1.0f, 1.0f, 1.0f, 1.0f};//, -1.0f};

constexpr uint8_t kTareSamples        = 20;
constexpr uint8_t kCalibrationSamples = 20;

// Minimum tared ADC counts (summed across all cells) at a single placement to
// accept as valid. Guards against a forgotten mass or a wiring error.
constexpr float kMinReferenceSignalCounts = 100.0f;
