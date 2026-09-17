#pragma once
#include <Arduino.h>

constexpr uint8_t kNumLoadCells        = 4;
constexpr uint8_t kLoadcellDoutPins[]  = {2, 4, 6, 8};
constexpr uint8_t kLoadcellSckPins[]   = {3, 5, 7, 9};

// TEMPORARY FIX: Cell 1 is mounted upside down, which causes its reading to be negative.
// We multiply its reading by -1 to flip it. Change this back to {1, 1} once it's remounted correctly!
constexpr float kLoadcellPolarities[]  = {1.0f, 1.0f, 1.0f, 1.0f};//, -1.0f};

constexpr uint8_t kTareSamples        = 20;
constexpr uint8_t kCalibrationSamples = 20;

// Minimum tared ADC counts from the reference mass to accept as valid.
// Guards against wiring errors or an empty-scale measurement.
constexpr float kMinReferenceSignalCounts = 100.0f;
