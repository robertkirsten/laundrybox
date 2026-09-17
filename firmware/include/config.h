#pragma once
#include <Arduino.h>

#define HOST_SERIAL Serial     // USB serial to the Raspberry Pi
#define RFID_SERIAL Serial1    // RX1 = pin 0, TX1 = pin 1

constexpr unsigned long kHostBaud    = 115200;
constexpr unsigned long kRfidBaud    = 115200;
constexpr uint16_t      kRfidTxPower = 2600;   // dBm * 100 = 26.00 dBm
constexpr unsigned long kRfidWindowMs      = 100;  // ms spent polling RFID before weighing
constexpr uint32_t      kRfidPollTimeoutMs = 50;   // single pollOnce() timeout
constexpr uint32_t      kRfidCommandTimeoutMs = 200; // IDLE-mode command timeout
constexpr uint8_t       kRfidCommandRetries   = 3;
constexpr unsigned long kRfidStartupDelayMs   = 500; // U107 boot time after UART starts
constexpr unsigned long kRfidWakeDelayMs      = 20;  // RF circuitry startup before polling

constexpr uint8_t kNumLoadCells        = 4;
constexpr uint8_t kLoadcellDoutPins[]  = {2, 6, 10, 14};
constexpr uint8_t kLoadcellSckPins[]   = {3, 7, 11, 15};
constexpr float kLoadcellPolarities[]  = {1.0f, 1.0f, 1.0f, 1.0f};//, -1.0f};

// Per-corner gain calibration: raw counts/gram for each cell, in cell order.
// Runtime weight = sum_i (cellRaw[i] - offset[i]) * polarity[i] / kCalibrationFactors[i].
// PLACEHOLDER: these all equal the previous single combined factor, so the scale
// behaves exactly as it did before until you run the 4-corner calibration in
// firmware_hx711 and paste the four values it prints here.
constexpr float kCalibrationFactors[kNumLoadCells] = {202.455582f, 209.137711f, 197.145020f, 208.115631f};
static_assert(sizeof(kCalibrationFactors) / sizeof(kCalibrationFactors[0]) == kNumLoadCells,
              "kCalibrationFactors must have exactly kNumLoadCells entries");

// True only once every corner has a positive factor, i.e. the scale is
// calibrated. When false, weight is reported as null and taring is skipped.
constexpr bool factorsAllPositive() {
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    if (!(kCalibrationFactors[i] > 0.0f)) {
      return false;
    }
  }
  return true;
}
constexpr bool kScaleCalibrated = factorsAllPositive();

constexpr uint8_t kTareSamples       = 20;

// Re-zero the empty box after a real garment has been removed. The upper
// threshold stays below the backend's minimum accepted garment weight so a
// valid garment can never be treated as the empty baseline.
constexpr float   kAutoTareMaxResidualG        = 30.0f;
constexpr float   kAutoTareLoadedMinG          = 50.0f;
constexpr float   kAutoTareStabilityToleranceG = 2.0f;
constexpr uint8_t kAutoTareStableSamples       = 3;
static_assert(kAutoTareMaxResidualG < kAutoTareLoadedMinG,
              "auto-tare residual must remain below the minimum garment weight");
static_assert(kAutoTareStableSamples >= 2, "auto-tare requires multiple stable samples");

constexpr uint8_t       kWeightSamples      = 2;    // averaged ADC reads per measurement
// At the measured ~10.5 SPS, five discarded conversions put the first retained
// sample beyond the HX711's specified 400 ms settling interval. The first
// discard can be immediately ready because it was converted during RFID scan.
constexpr uint8_t       kSettleConversions  = 5;
constexpr unsigned long kMinCyclePeriodMs   = 250;  // minimum cycle time (floor, not fixed cadence)
constexpr uint32_t      kAdcReadyMs         = 200;  // max wait for an ADC sample

// Ferrous-metal detector
constexpr uint8_t kMetalPin            = A0;
constexpr int     kMetalAdcBits        = 12;    // analogReadResolution -> 0..4095
constexpr float   kMetalVref           = 3.3f;  // Teensy 4.1 ADC reference (V)
constexpr float   kMetalThresholdVolts = 0.8f;  // reading above this => metal
constexpr uint8_t kMetalSamples        = 4;     // averaged analog reads per report

constexpr uint8_t kMaxTagsPerReport = 8;
