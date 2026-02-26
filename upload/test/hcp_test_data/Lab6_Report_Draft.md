# SDS-PAGE and Western Blot Analysis of E. coli Lysates: Sample Preparation, Gel Issues, and Deviation Impacts (Lab 6)

Angus Barlow  
BEC 425 (Group 5)  
Date: February 2026

---

## Abstract

This study utilized SDS-PAGE and Western blotting to evaluate the expression of the target scFv protein in *E. coli* lysates. Samples were prepared via mechanical disruption (bead beating) and separated by electrophoresis to visualize total protein profiles and specifically detect the target antigen. The experiment was impacted by several significant procedural deviations, including sample identity confusion during aliquoting, buffer leakage during electrophoresis, and physical damage (tearing) to the gels during staining and transfer. While the total protein stain provided limited data due to gel integrity issues, the Western blot yielded no visible bands. These negative results highlight the critical importance of upstream sample handling, careful gel manipulation, and strict adherence to blocking and washing protocols in verifying recombinant protein expression.

---

## Introduction

Verifying protein expression is a critical quality control step in biomanufacturing. Sodium Dodecyl Sulfate Polyacrylamide Gel Electrophoresis (SDS-PAGE) separates proteins based on molecular weight, allowing for the visualization of the entire proteome. Western blotting adds a layer of specificity by transferring these proteins to a membrane and probing them with antibodies specific to the target product. Together, these methods distinguish between general biomass accumulation and specific product formation.

**Study Question:** Can the scFv13R4 protein be detected and distinguished from host cell proteins in induced lysates using SDS-PAGE and Western blot analysis under the current experimental conditions?

---

## Materials and Methods

**Sample Preparation (Bead Beating)**
Frozen cell pellets from the expression cultures were thawed and resuspended. Lysis was achieved by mechanical disruption using glass beads ("bead beating"). An 800 µL aliquot of each sample was combined with 200 µL of glass beads and subjected to high-speed agitation to disrupt the cell wall and release intracellular proteins. The lysate was clarified by centrifugation, and the supernatant was collected for analysis.

**SDS-PAGE Setup**
Lysates were mixed with loading buffer and heated to denature proteins. Samples were loaded into a polyacrylamide gel along with a molecular weight ladder and a positive control. Electrophoresis was conducted in a vertical tank filled with running buffer at constant voltage until the dye front reached the bottom of the gel.

**Western Blot and Staining**
Two replicate gels were run. The first was stained with Coomassie Blue (or Acqua Stain) to visualize total protein. The second was used for Western blotting. The proteins were transferred from the gel to a membrane using a wet transfer cassette. The membrane was blocked with a BSA-based blocking buffer to prevent non-specific binding, washed with PBS-T, and incubated with primary and secondary antibodies. Detection was performed using a colorimetric substrate.

---

## Results

**Sample Handling Observations**
During the sample preparation phase, traceability was compromised for the first four tubes due to unclear labeling during the initial draw. Additionally, excessive foaming/bubbles occurred during pipetting of the lysates, which likely introduced variability in the actual volume of protein loaded into the gel.

**Electrophoresis Performance**
The electrophoresis run was complicated by a significant leak in the running buffer reservoir, attributed to overfilling the apparatus. This required monitoring to ensuring electrical continuity. Additionally, the loading of the positive control lane was interrupted when buffer back-flowed into the pipette tip, potentially resulting in an under-loaded control.

**Visualization Outcomes**
*   **SDS-PAGE (Total Protein):** The gel designated for staining was physically torn during handling and imaging. While some lane separation was visible, the structural damage made it difficult to confidently assign bands to specific molecular weights or samples.
*   **Western Blot:** The final developed membrane showed **no visible bands** in any lane, including the positive control. Deviations noted during this process included the gel tearing during transfer assembly and an incorrect sequence of wash steps (blocking buffer was added when PBS-T was intended, though this was quickly corrected).

| Lane | Intended Sample Type | Expected Outcome | Observed Outcome | Interpretation |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Molecular weight ladder | Distinct marker bands | Ladder visibility limited by gel damage | Molecular-weight assignment confidence reduced |
| 2 | Positive control | Clear band at known target size | No visible band | Control lane likely underloaded or transfer/detection failure |
| 3-6 | Experimental lysates | Total protein smear and/or target-associated region | Faint/ambiguous separation, no definitive target signal | Sample loading and gel integrity issues prevented robust interpretation |
| Blot (all lanes) | Membrane transfer product | Detectable immunoreactive signal in control and positive lysates | No visible bands in any lane | System-level failure likely at transfer/handling/detection stages |

*Table 1: Lane-level expectation versus observation summary for SDS-PAGE and Western blot outputs.*

| Deviation | Where It Occurred | Likely Technical Effect | Downstream Impact on Data Quality | Corrective Action for Next Run |
| :--- | :--- | :--- | :--- | :--- |
| Tube/source ambiguity | Sample prep and aliquoting | Potential misassignment and non-equivalent loading | Lane identity confidence reduced | Pre-label tubes before lysis; verify with two-person check |
| Excessive bubbles during loading | Gel loading | Inaccurate delivered volume and uneven well fill | Increased lane-to-lane variability | Slow pipetting; brief spin-down before loading |
| Running buffer leak | Electrophoresis setup | Potential unstable electric field and migration inconsistency | Compromised band sharpness/reproducibility | Fill to marked level only; verify gasket and seal before run |
| Gel tearing | Staining/transfer handling | Physical discontinuity in protein migration/transfer path | Major loss of interpretability | Keep gels hydrated; use support film/spatula and two-person transfer setup |
| Wash/block sequence confusion | Western blot wash steps | Altered membrane chemistry and nonspecific behavior | Possible weak/no signal or high background risk | Bench checklist with step-by-step tick marks and reagent labels |

*Table 2: Deviation-impact matrix linking observed execution issues to data risk and corrective actions.*

![Figure 1. Gel image (Group 5). Insert lane labels/expected band sizes in the caption after you confirm the lane map.](figures/group5_gel.png)

![Figure 2. Lab 6 workflow and deviation map (summary).](figures/lab6_workflow_deviation_map.png)

---

## Discussion

**Analysis of Negative Results**
The complete absence of bands on the Western blot indicates a systemic failure rather than a lack of expression alone. The most probable causes, ranked by likelihood, are:
1.  **Transfer Failure:** The physical tearing of the gel before/during transfer likely prevented proper contact between the gel and membrane, stopping proteins from moving onto the blot.
2.  **Sample Loading/Identity:** The confusion regarding tube identity and the "bubbling" during pipetting means that some lanes may have been empty or contained only buffer, while others may have been overloaded or misidentified.
3.  **Positive Control Failure:** The aborted loading of the positive control removed the primary reference point. Without a visible positive control, it is impossible to verify if the antibodies and detection reagents were working.

**Impact of Deviations**
The buffer leak during the run may have caused uneven heating or migration, but the lack of bands is more likely due to the downstream transfer and handling issues. The confusion between the rocker (for blocking) and rotator (for washing) steps, along with the reagent swap (adding blocker instead of wash), introduced process variability that could have raised the background noise or washed away weak signals, though the total absence of signal points back to the transfer step.

**Future Improvements**
To correct these issues in future runs, three specific changes should be implemented:
1.  **Strict Sample Labeling:** Tubes must be clearly labeled *before* bead beating to prevent the "unclear source" issue.
2.  **Gel Handling Technique:** Use a "blot roller" gently and keep gels hydrated to prevent tearing. The transfer stack should be assembled by two people to ensure alignment without damage.
3.  **Reagent Checklist:** A printed checklist at the bench would prevent mixing up Blocking Buffer and PBS-T, ensuring the chemical environment on the membrane is correct for antibody binding.

---

## Conclusion

This experiment attempted to characterize protein expression but was inconclusive due to procedural deviations. The lack of bands on the Western blot and the physical damage to the SDS-PAGE gel prevent a definitive statement on scFv production. However, the operational learnings regarding gel handling, sample traceability, and buffer management are critical for ensuring the success of future verification experiments.

---

## References

1.  *BEC 425/525 Course Manual*, Spring 2026. NC State University BTEC.
