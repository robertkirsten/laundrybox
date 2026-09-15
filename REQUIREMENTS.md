# ARGUS Scan Technical Baseline

**Status:** Draft for Tech Coaching  
**Last updated:** 2026-09-14

Contains function model and the Must-have/Nice-to-have
requirements list.

## 1. system scope

The system evaluates one returned garment at a time and tells the operator
whether it should be checked manually for a foreign object.

The system scope starts with recording a clean reference weight linked to a
garment identifier. The same physical scale may be used for reference and
return measurements. The scope ends when the operator receives a two-state
decision:

- **PASS (GREEN light):** no manual inspection indicated.
- **CHECK (RED light):** manual inspection required.

The system does not remove foreign objects, process garments in bulk, track
wearers, or integrate with a production ERP system.

## 2. Must-have requirements

These are additional technical constraints for the requirements slide, rather
than a repetition of the function sequence.

| ID | Requirement |
|---|---|
| M-01 | The system must evaluate exactly one garment per cycle. |
| M-02 | A sytem cycle must require only placing and removing the garment into/from the box, without manual identifier entry. |
| M-03 | The garment identification method must be RFID. |
| M-04 | The system must support retrieving a clean reference weight for each garment. |
| M-05 | The system must operate over a garment weight range of 50 g to 1000 g. |
| M-06 | The system must produce its decision within 10 seconds of a correctly presented garment. |
| M-07 | The system must provide exactly two unambiguous results: PASS (green light) and CHECK (red light). |
| M-08 | The objects detected by the system must include pens as the smallest target class and screwdrivers or heavier metallic objects. |
| M-09 | The decision method must target a false-negative rate of no more than 10%. |
| M-10 | Decision thresholds must prioritize sensitivity over specificity. |
| M-11 | Garment-contact surfaces must not snag or damage garments and must be wipe-cleanable. |
| M-12 | The system must distinguish the added mass of the lightest target object reliably within this range. |
| M-13 | Missing identity or reference data, invalid measurements, or other uncertainty must produce CHECK. |

## 3. Nice-to-have requirements

| ID | Requirement |
|---|---|
| N-01 | The system should produce its decision within 3 seconds of a correctly presented garment. |
| N-02 | The decision method should target a false-negative rate of no more than 2%. |
| N-03 | The system should use electromagnetic metal sensing as an additional channel for detecting ferromagnetic objects. |
| N-04 | The operator should be able to record whether a manual check found an object, allowing false positives and false negatives to be evaluated. |
| N-05 | PASS and CHECK should remain distinguishable without relying on colour alone, for example through text or symbols. |
| N-06 | The system should learn the expected contamination of each individual garment from its return weight history. |
| N-07 | The system should not be affected by vibrations. |
