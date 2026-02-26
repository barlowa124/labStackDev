# Data Classification Policy

This repository is open-source for software code, but lab data must be classified before sharing.

## Allowed in public repo

- Synthetic sample data generated for testing
- Fully de-identified data that has documented approval for public release
- Non-sensitive metadata that cannot identify participants, sponsors, or proprietary processes

## Not allowed in public repo

- Human-subject data with direct or indirect identifiers
- PHI, HIPAA-regulated data, or patient-linked records
- FERPA-protected student records
- Sponsor-restricted, NDA-covered, or proprietary partner data
- Export-controlled data or methods
- Raw instrument captures unless explicitly approved for public release

## Classification levels

- `PUBLIC`: approved for open release
- `INTERNAL`: lab-internal use only
- `RESTRICTED`: controlled-access only, requires PI and/or compliance approval

## Minimum labeling expectation

For any dataset artifact, include:

- Source and date range
- De-identification status
- Classification level (`PUBLIC`, `INTERNAL`, `RESTRICTED`)
- Approval reference (if applicable)

## Operational rule

If classification is unknown, treat data as `RESTRICTED` by default and do not commit it.
