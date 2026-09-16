#pragma once
#include <Arduino.h>

#define HOST_SERIAL Serial     // USB serial to the Raspberry Pi
#define RFID_SERIAL Serial1    // RX1 = pin 0, TX1 = pin 1

constexpr unsigned long kHostBaud    = 115200;
constexpr unsigned long kRfidBaud    = 115200;
constexpr uint16_t      kRfidTxPower = 2600;   // dBm * 100 = 26.00 dBm

constexpr uint8_t kLoadcellDoutPin = 2;
constexpr uint8_t kLoadcellSckPin  = 3;

constexpr float   kCalibrationFactor = 0.0f;
constexpr uint8_t kTareSamples       = 20;

constexpr uint8_t       kWeightSamples  = 2;    // averaged ADC reads per message
constexpr unsigned long kReportPeriodMs = 250;  // JSON emit cadence
constexpr uint32_t      kAdcReadyMs     = 200;  // max wait for an ADC sample

constexpr uint8_t kMaxTagsPerReport = 8;
