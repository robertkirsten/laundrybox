#pragma once
#include <Arduino.h>

#define HOST_SERIAL Serial     // USB serial to the Raspberry Pi
#define RFID_SERIAL Serial1    // RX1 = pin 0, TX1 = pin 1

constexpr unsigned long kHostBaud    = 115200;
constexpr unsigned long kRfidBaud    = 115200;
constexpr uint16_t      kRfidTxPower = 2600;   // dBm * 100 = 26.00 dBm

constexpr uint8_t kNumLoadCells        = 2;
constexpr uint8_t kLoadcellDoutPins[]  = {2, 4};
constexpr uint8_t kLoadcellSckPins[]   = {3, 5};

// TEMPORARY FIX: Cell 1 is mounted upside down, which causes its reading to be negative.
// We multiply its reading by -1 to flip it. Change this back to {1, 1} once it's remounted correctly!
constexpr float kLoadcellPolarities[]  = {1.0f, -1.0f};

constexpr float   kCalibrationFactor = 107.44f;
constexpr uint8_t kTareSamples       = 20;

constexpr uint8_t       kWeightSamples  = 2;    // averaged ADC reads per message
constexpr unsigned long kReportPeriodMs = 250;  // JSON emit cadence
constexpr uint32_t      kAdcReadyMs     = 200;  // max wait for an ADC sample

constexpr uint8_t kMaxTagsPerReport = 8;
