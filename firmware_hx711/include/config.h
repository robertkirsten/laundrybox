#pragma once
#include <Arduino.h>

constexpr uint8_t kNumLoadCells        = 1;
constexpr uint8_t kLoadcellDoutPins[]  = {2};//{4, 6, 8};
constexpr uint8_t kLoadcellSckPins[]   = {3};//{5, 7, 9};
constexpr float kLoadcellPolarities[]  = {1.0f};//, 1.0f, 1.0f};//, -1.0f};

constexpr uint8_t kTareSamples        = 20;
constexpr uint8_t kCalibrationSamples = 20;

// Minimum tared ADC counts from the reference mass to accept as valid.
// Guards against wiring errors or an empty-scale measurement.
constexpr float kMinReferenceSignalCounts = 100.0f;
