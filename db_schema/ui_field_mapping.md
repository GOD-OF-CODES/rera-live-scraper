# UP-RERA UI Field Mapping

This document describes the proposed fields/screens. It is a UI design reference, not a frontend implementation.

## 1. Project Overview

| UI Section | UI Field | DB Source | Component |
|---|---|---|---|
| Project | Project Name | `projects.project_name` | Heading |
| Project | RERA Registration Number | `projects.registration_number` | Text |
| Project | RERA Project ID | `projects.rera_project_id` | Text |
| Project | Project Type | `projects.project_type` | Badge |
| Project | District | `projects.district` | Text |
| Project | Approval Certificate | `projects.approval_certificate` | Text |
| Project | Registration Date | `projects.registration_date` | Date |
| Project | Promoter | `promoters.name` | Linked text |
| Project | RERA Project Page | `projects.project_details_url` | View Source button |

## 2. Basic Details

- Total Project Area
- District
- Tehsil
- Original Start Date
- Proposed Start Date
- Sanctioning Competent Authority
- Project Cost
- Proposed Completion Date

## 3. Location

Show the extracted coordinate values. Do not label them as a standard decimal GPS coordinate until their source format has been confirmed.

## 4. Promoter

- Promoter Name
- RERA Promoter ID

## 5. Professionals

Display only roles for which data exists:

- Contractor
- Architect
- Structural Engineer
- Project Coordinator Mobile

For architect/engineer:
- Name
- Address
- License Number where available

## 6. Bank Details

Display:
- Bank
- Account Holder
- Branch
- Branch Address
- IFSC
- Masked Account Number

Do NOT show the full account number.

## 7. Documents

Table:

| Serial | Document | Type | Uploaded Date | Action |
|---|---|---|---|---|
| 1 | Registry Document... | Old | 17-12-2017 | View |
| 2 | Details of Encumbrances | New | 03-07-2018 | View |

The `View` action uses `project_documents.document_url`.

## 8. Quarterly Progress

Display each link as an action:

- Form REG 1
- Form REG 2
- Form REG 3
- Form REG 4
- Form REG 4A
- Form REG 5
- View Physical and Financial Progress
- View Quarterly Progress Certificates
- Order For CA, Architect, Engineer Certificate

## 9. Sections not yet finalized

The following should not be given invented UI columns yet:

- Plan records
- Unit records
- Villa/plot records
- Khasra/plot details
- Registry/agreement details
- Development works

Once a project JSON contains real records, the fields can be added to the data dictionary and UI mapping.
