#include <Arduino.h>
#include <math.h>

#include "HX711.h"

namespace {

constexpr uint8_t LOADCELL_DOUT_PIN = 2;
constexpr uint8_t LOADCELL_SCK_PIN = 3;

// The plate and box remain installed throughout calibration. Place this known
// mass inside the empty box when prompted, then remove it when prompted.
constexpr float CALIBRATION_MASS_G = 557.4f;

// Temporary prototype target: one Argus. Replace after weighing the garment.
constexpr float CLEAN_GARMENT_WEIGHT_G = 601.4f; //557.4f;
constexpr float WEIGHT_THRESHOLD_G = 3.0f;

constexpr uint8_t TARE_SAMPLES = 20;
constexpr uint8_t CALIBRATION_SAMPLES = 20;
constexpr uint8_t MEASUREMENT_SAMPLES = 10;
constexpr unsigned long PLACEMENT_TIME_MS = 5000;

HX711 scale;

void haltWithError(const char *message) {
  Serial.print("ERROR: ");
  Serial.println(message);

  while (true) {
    delay(1000);
  }
}

void calibrateWithInstalledAssembly() {
  scale.set_scale(1.0f);

  Serial.println("Calibration step 1/3");
  Serial.println("Leave the plate and empty box installed.");
  Serial.println("Remove all garments and calibration objects.");
  Serial.println("Taring the empty assembly in 5 seconds...");
  delay(PLACEMENT_TIME_MS);
  scale.tare(TARE_SAMPLES);

  Serial.println("Calibration step 2/3");
  Serial.print("Place the calibration mass in the box (mass: ");
  Serial.print(CALIBRATION_MASS_G, 1);
  Serial.println(" g). Keep it still and ensure it touches only the box.");
  Serial.println("Measuring the reference mass in 5 seconds...");
  delay(PLACEMENT_TIME_MS);

  const float rawReferenceCounts = scale.get_value(CALIBRATION_SAMPLES);
  if (!isfinite(rawReferenceCounts) || fabsf(rawReferenceCounts) < 100.0f) {
    haltWithError(
        "Reference signal is too small. Check mounting and calibration sequence.");
  }

  const float calibrationFactor =
      rawReferenceCounts / CALIBRATION_MASS_G;
  scale.set_scale(calibrationFactor);

  Serial.print("Calibration factor: ");
  Serial.print(calibrationFactor, 6);
  Serial.println(" raw counts/g");

  Serial.println("Calibration step 3/3");
  Serial.println("Remove the calibration mass. Leave the plate and box installed.");
  Serial.println("Taring the empty assembly again in 5 seconds...");
  delay(PLACEMENT_TIME_MS);
  scale.tare(TARE_SAMPLES);
  Serial.println("Ready. Add a garment for PASS/CHECK testing.");
}

void printMeasurement(float weightG) {
  const float differenceG = fabsf(weightG - CLEAN_GARMENT_WEIGHT_G);
  const bool passes = differenceG <= WEIGHT_THRESHOLD_G;

  Serial.print("Weight: ");
  Serial.print(weightG, 1);
  Serial.print(" g | Target: ");
  Serial.print(CLEAN_GARMENT_WEIGHT_G, 1);
  Serial.print(" g | Difference: ");
  Serial.print(differenceG, 1);
  Serial.print(" g | ");
  Serial.println(passes ? "PASS" : "CHECK");
}

}  // namespace

void setup() {
  Serial.begin(57600);

  const unsigned long serialWaitStartedMs = millis();
  while (!Serial && millis() - serialWaitStartedMs < 3000) {
    // Give the USB serial monitor a short opportunity to connect.
  }

  if (CALIBRATION_MASS_G <= 0.0f) {
    haltWithError("CALIBRATION_MASS_G must be positive.");
  }
  if (CLEAN_GARMENT_WEIGHT_G <= 0.0f) {
    haltWithError("Set CLEAN_GARMENT_WEIGHT_G in main.cpp.");
  }
  if (WEIGHT_THRESHOLD_G < 0.0f) {
    haltWithError("WEIGHT_THRESHOLD_G cannot be negative.");
  }

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  if (!scale.wait_ready_timeout(3000)) {
    haltWithError("HX711 not found. Check power and wiring.");
  }

  calibrateWithInstalledAssembly();
}

void loop() {
  if (!scale.wait_ready_timeout(1000)) {
    Serial.println("ERROR: HX711 not ready.");
    delay(1000);
    return;
  }

  printMeasurement(scale.get_units(MEASUREMENT_SAMPLES));
  delay(1000);
}
