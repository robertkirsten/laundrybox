# LaundryBox Technical Baseline

**Status:** Draft for Tech Coaching  
**Last updated:** 2026-09-13  
**Prototype time remaining when agreed:** 5 days

This Markdown file is the source for the two graded content slides in the TMS
submission template: the function model and the Must-have/Nice-to-have
requirements list. Component choices are included only when the team has made a
deliberate constraint or contingency decision.

## 1. Product scope

The prototype evaluates one returned garment at a time and tells the operator
whether it should be checked manually for a foreign object.

The prototype scope starts with recording a clean reference weight linked to a
garment identifier. The same physical scale may be used for reference and
return measurements. The scope ends when the operator receives a two-state
decision:

- **PASS:** no manual inspection indicated.
- **CHECK:** manual inspection required.

The prototype does not remove foreign objects, process garments in bulk, track
wearers, or integrate with a production ERP system.

## 2. Function-model content

This section contains functions and states for the function-model slide. They
should not be repeated verbatim as additional requirements on the requirements
slide.

```text
(Clean garment available)
  -> Record garment reference
  -> (Reference record available)

(Returned garment presented)
  -> Identify garment
  -> (Identity status known)
  -> Obtain reference record
  -> (Reference status known)
  -> Measure returned garment
  -> (Return weight available or invalid)
  -> Account for expected contamination                 [challenge]
  -> (Comparable weight difference available)
  -> Evaluate inspection need                           [crucial] [challenge]
  -> (PASS or CHECK decision available)
  -> Communicate decision
  -> (Operator informed)
```

An optional branch may add another evidence source:

```text
(Returned garment presented)
  -> Detect evidence of damaging material               [challenge]
  -> (Additional evidence available or invalid)
  -> Evaluate inspection need
```

In the submitted diagram, mark “Evaluate inspection need” with the blue crucial
dot. Mark contamination handling, decision performance, and the optional
additional detection function with red challenge dots. Keep the function names
solution-neutral; RFID, scales, and electromagnets belong in the requirements
or component discussion.

## 3. Requirement sources

| ID | Source |
|---|---|
| S-01 | Team decisions recorded on 2026-09-13. |
| S-02 | Customer interviews and observations of the actual laundry workflow. Interview names and dates must be added before submission where cited. |
| S-03 | Prototype constraint: five days remaining and a 20 kg load cell already ordered. |
| S-04 | Team risk assessment: missed damaging objects matter more than unnecessary manual checks. |

## 4. Must-have requirements

These are additional technical constraints for the requirements slide, rather
than a repetition of the function sequence.

| ID | Requirement | Source |
|---|---|---|
| M-01 | The prototype must evaluate exactly one garment per cycle. | S-01, S-02 |
| M-02 | The primary identification method must be RFID. If RFID proves technically infeasible during the prototype feasibility test, the team may use a barcode and must document the change. | S-01 |
| M-03 | The prototype must support recording and retrieving a clean reference weight for each test garment. It may use the same scale for reference and return measurements. | S-01, S-03 |
| M-04 | The prototype must operate over a garment test range of 50 g to 1,000 g. The selected scale must distinguish the added mass of the lightest test object reliably within this range. | S-01, S-03 |
| M-05 | The prototype must produce its decision within 10 seconds of a correctly presented garment. Any revision must be documented and justified before final evaluation. | S-01, S-02 |
| M-06 | The prototype must provide exactly two unambiguous results: PASS and CHECK. Missing identity or reference data, invalid measurements, or other uncertainty must produce CHECK. | S-01, S-04 |
| M-07 | The agreed evaluation set must include pens as the smallest target class and screwdrivers or heavier metallic objects as representative machine-damage risks. | S-01, S-02 |
| M-08 | The decision method must target a false-negative rate of no more than 1%, equivalent to sensitivity of at least 99%, on the agreed target-object definition. Prototype results must report observed counts and sample size rather than claim population-level performance from a small test set. | S-01, S-04 |
| M-09 | Decision thresholds must prioritize sensitivity over specificity. The team must measure and report specificity, but no minimum specificity is fixed until the object prevalence and acceptable manual-check workload are known. | S-01, S-02, S-04 |
| M-10 | For the prototype, contamination compensation must use either no correction or one documented, configurable fixed offset. The selected method and value must be stored with the results. | S-01, S-03 |
| M-11 | Each test cycle must retain the garment identifier, reference and return weights, applied offset, decision threshold, result, and timestamp so the decision can be reconstructed. | S-01 |
| M-12 | Garment-contact surfaces must not snag or damage garments and must be wipe-cleanable. | S-02 |
| M-13 | The prototype must not store or display wearer identity. | S-01 |

## 5. Nice-to-have requirements

| ID | Requirement | Source |
|---|---|---|
| N-01 | The prototype should use magnetic or electromagnetic sensing as an additional channel for damaging ferromagnetic objects if the current feasibility test succeeds. | S-01, S-03 |
| N-02 | If the optional electromagnetic subsystem is fitted, it must de-energize safely after a timeout or control failure and must include suitable electrical, inductive-load, thermal, and magnetic-field protection. | S-04 |
| N-03 | A normal cycle should require only placing and removing the garment, without manual identifier entry. | S-01, S-02 |
| N-04 | The operator should be able to record whether a manual check found an object, allowing false positives and false negatives to be evaluated. | S-02, S-04 |
| N-05 | PASS and CHECK should remain distinguishable without relying on colour alone, for example through text or symbols. | S-04 |
| N-06 | A future product should learn the expected contamination of each individual garment from its return history instead of relying on one fixed offset. | S-01 |

## 6. Open checks before submission

1. Add the dates or identifiers of the customer interviews and workflow
   observations used as sources.
2. Test whether the ordered 20 kg load cell has enough repeatability in the
   50-1,000 g working range, especially for the selected pen.
3. Fix the exact test objects, number of trials, and placement method before
   evaluating the 1% false-negative target.
4. Choose zero correction or a fixed configurable contamination offset for the
   demonstration.
5. Record a go/no-go decision for RFID and, separately, for the optional
   electromagnetic channel.
6. Confirm whether the 10-second cycle time remains a Must-have after the first
   end-to-end prototype test.

The linked Moodle “rubric” is a general explanation of academic rubrics, not a
course-specific scoring scheme. The submission template and Tech Coaching
instructions therefore remain the operative formatting guidance available to
the team.
