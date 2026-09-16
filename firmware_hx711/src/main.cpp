#include <Arduino.h>
#include <math.h>
#include <stdlib.h>

#include "HX711.h"
#include <config.h>

static_assert(sizeof(kLoadcellDoutPins) / sizeof(kLoadcellDoutPins[0]) == kNumLoadCells,
              "kLoadcellDoutPins must have exactly kNumLoadCells entries");
static_assert(sizeof(kLoadcellSckPins) / sizeof(kLoadcellSckPins[0]) == kNumLoadCells,
              "kLoadcellSckPins must have exactly kNumLoadCells entries");
static_assert(sizeof(kLoadcellPolarities) / sizeof(kLoadcellPolarities[0]) == kNumLoadCells,
              "kLoadcellPolarities must have exactly kNumLoadCells entries");

namespace {

HX711 gCells[kNumLoadCells];

void haltWithError(const char *message) {
  Serial.print("ERROR: ");
  Serial.println(message);

  while (true) {
    delay(1000);
  }
}

String readSerialLine() {
  String line;

  while (true) {
    while (Serial.available() > 0) {
      const char character = static_cast<char>(Serial.read());

      if (character == '\r' || character == '\n') {
        // A serial monitor commonly sends CR+LF. Consume the second line-ending
        // character so it cannot accidentally acknowledge the next prompt.
        delay(2);
        while (Serial.available() > 0) {
          const int nextCharacter = Serial.peek();
          if (nextCharacter != '\r' && nextCharacter != '\n') {
            break;
          }
          Serial.read();
        }
        return line;
      }

      line += character;
    }

    delay(1);
  }
}

void waitForEnter() {
  readSerialLine();
}

float readCalibrationMassG() {
  while (true) {
    Serial.println();
    Serial.println("Enter the calibration object's mass in grams, then press Enter:");

    String input = readSerialLine();
    input.trim();

    char *end = nullptr;
    const float massG = strtof(input.c_str(), &end);
    const bool parsedEntireInput =
        end != input.c_str() && end != nullptr && *end == '\0';

    if (parsedEntireInput && isfinite(massG) && massG > 0.0f) {
      Serial.print("Calibration mass: ");
      Serial.print(massG, 3);
      Serial.println(" g");
      return massG;
    }

    Serial.println("Invalid mass. Enter a positive number, for example: 557.4");
  }
}

void runCalibration(float calibrationMassG) {
  Serial.println();
  Serial.println("Step 1/2: Prepare the empty scale");
  Serial.println("Leave the plate/box installed and remove every loose object.");
  Serial.println("Press Enter when the scale is empty and stable.");
  waitForEnter();

  // Tare every cell
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    // A scale factor of 1 makes get_value() return tared raw ADC counts.
    gCells[i].set_scale(1.0f);

    if (!gCells[i].wait_ready_timeout(3000)) {
      Serial.print("ERROR: HX711 cell ");
      Serial.print(i);
      Serial.println(" not ready. Calibration cancelled.");
      return;
    }

    Serial.print("Taring cell ");
    Serial.print(i);
    Serial.print(" ... ");
    gCells[i].tare(kTareSamples);
    Serial.println("done");
  }

  Serial.println();
  Serial.println("Step 2/2: Measure the reference object");
  Serial.print("Place the ");
  Serial.print(calibrationMassG, 3);
  Serial.println(" g object on the scale and keep it still.");
  Serial.println("Press Enter when the reading is stable.");
  waitForEnter();

  // Read tared counts from every cell and sum them
  float combinedCounts = 0.0f;
  float cellReadings[kNumLoadCells];
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    if (!gCells[i].wait_ready_timeout(3000)) {
      Serial.print("ERROR: HX711 cell ");
      Serial.print(i);
      Serial.println(" not ready. Calibration cancelled.");
      return;
    }

    Serial.print("Sampling cell ");
    Serial.print(i);
    Serial.print(" ... ");
    const float cellCounts = gCells[i].get_value(kCalibrationSamples) * kLoadcellPolarities[i];
    Serial.println(cellCounts, 3);
    cellReadings[i] = cellCounts;
    combinedCounts += cellCounts;
  }

  if (!isfinite(combinedCounts) ||
      fabsf(combinedCounts) < kMinReferenceSignalCounts) {
    Serial.println(
        "ERROR: Combined reference signal is too small. "
        "Check the wiring, mounting, and sequence.");
    return;
  }

  const float calibrationFactor = combinedCounts / calibrationMassG;

  Serial.println();
  Serial.println("Calibration complete");
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    Serial.print("  Cell ");
    Serial.print(i);
    Serial.print(" tared reading: ");
    Serial.println(cellReadings[i], 3);
  }
  Serial.print("  Combined tared reading: ");
  Serial.println(combinedCounts, 3);
  Serial.print("  Calibration factor: ");
  Serial.print(calibrationFactor, 6);
  Serial.println(" raw counts/gram");

  Serial.println();
  Serial.println("Copy this into firmware/include/config.h:");
  Serial.print("  constexpr float kCalibrationFactor = ");
  Serial.print(calibrationFactor, 6);
  Serial.println("f;");

  Serial.println();
  Serial.println("Remove the object. A new calibration can now be started.");
}

}  // namespace

void setup() {
  Serial.begin(57600);

  const unsigned long serialWaitStartedMs = millis();
  while (!Serial && millis() - serialWaitStartedMs < 3000) {
    // Give the USB serial monitor a short opportunity to connect.
  }

  Serial.println();
  Serial.print("HX711 multi-cell calibration firmware (");
  Serial.print(kNumLoadCells);
  Serial.println(" load cells)");
  Serial.println("Serial speed: 57600 baud");
  Serial.println("Configure the serial monitor to send a line ending.");

  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    gCells[i].begin(kLoadcellDoutPins[i], kLoadcellSckPins[i]);
    if (!gCells[i].wait_ready_timeout(3000)) {
      Serial.print("HX711 cell ");
      Serial.print(i);
      Serial.print(" not found (DOUT=");
      Serial.print(kLoadcellDoutPins[i]);
      Serial.print(", SCK=");
      Serial.print(kLoadcellSckPins[i]);
      Serial.println("). Check power and wiring.");
      haltWithError("HX711 initialisation failed.");
    }
    Serial.print("Cell ");
    Serial.print(i);
    Serial.println(" ready");
  }
}

void loop() {
  const float calibrationMassG = readCalibrationMassG();
  runCalibration(calibrationMassG);
}
