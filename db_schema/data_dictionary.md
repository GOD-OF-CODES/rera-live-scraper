# UP-RERA Data Dictionary

## A. `promoters`

| Column | PostgreSQL Type | Null? | Key | Source JSON | UI Label |
|---|---|---:|---|---|---|
| id | BIGINT GENERATED ALWAYS AS IDENTITY | No | PK | System | — |
| rera_promoter_id | VARCHAR(50) | Yes | UNIQUE | `promoter.promoter_id` | RERA Promoter ID |
| name | VARCHAR(255) | No | — | `promoter.name` | Promoter Name |
| created_at | TIMESTAMPTZ | No | — | System | — |
| updated_at | TIMESTAMPTZ | No | — | System | — |

## B. `projects`

| Column | Type | Null? | Key | Source JSON | UI Label |
|---|---|---:|---|---|---|
| id | BIGINT GENERATED ALWAYS AS IDENTITY | No | PK | System | — |
| registration_number | VARCHAR(50) | No | UNIQUE | top-level `registration_number` | RERA Registration Number |
| rera_project_id | VARCHAR(50) | Yes | — | `identification.project_id` | RERA Project ID |
| project_name | VARCHAR(255) | No | — | `identification.project_name` | Project Name |
| project_type | VARCHAR(100) | Yes | — | `search_result.project_type` | Project Type |
| district | VARCHAR(150) | Yes | — | `search_result.district` | District |
| approval_certificate | VARCHAR(255) | Yes | — | `search_result.approval_certificate` | Approval Certificate |
| registration_date | DATE | Yes | — | `identification.registration_date` | Registration Date |
| promoter_id | BIGINT | Yes | FK | derived from `promoter` | Promoter |
| source | VARCHAR(50) | No | — | `source` | Source |
| search_url | TEXT | Yes | — | `search_url` | Search Source |
| project_details_url | TEXT | Yes | — | `project_details_url` / `page.url` | RERA Project Page |
| documents_json | JSONB | Yes | — | `documents` (denormalized copy) | — |
| scraped_at | TIMESTAMPTZ | Yes | — | System | Last Scraped |

## C. `project_basic_details`

| Column | Type | Null? | Source JSON | UI Label |
|---|---|---:|---|---|
| id | BIGINT IDENTITY | No | System | — |
| project_id | BIGINT | No | Relationship | — |
| total_area_sq_m | NUMERIC(15,2) | Yes | `total_area_sq_m` | Total Area (sq. m) |
| district | VARCHAR(150) | Yes | `district` | District |
| tehsil | VARCHAR(150) | Yes | `tehsil` | Tehsil |
| original_start_date | DATE | Yes | `original_start_date` | Original Start Date |
| proposed_start_date | DATE | Yes | `proposed_start_date` | Proposed Start Date |
| sanctioning_competent_authority | VARCHAR(255) | Yes | `sanctioning_competent_authority` | Sanctioning Authority |
| project_cost_lakhs | NUMERIC(15,2) | Yes | `project_cost_lakhs` | Project Cost (₹ Lakhs) |
| proposed_completion_date | DATE | Yes | `proposed_completion_date` | Proposed Completion Date |

## D. `project_locations`

| Column | Type | Null? | Source JSON | UI Label |
|---|---|---:|---|---|
| id | BIGINT IDENTITY | No | System | — |
| project_id | BIGINT | No | Relationship | — |
| latitude_part_1 | VARCHAR(100) | Yes | `latitude_part_1` | Latitude Part 1 |
| latitude_part_2 | VARCHAR(100) | Yes | `latitude_part_2` | Latitude Part 2 |
| longitude_part_1 | VARCHAR(100) | Yes | `longitude_part_1` | Longitude Part 1 |
| longitude_part_2 | VARCHAR(100) | Yes | `longitude_part_2` | Longitude Part 2 |

## E. `project_professionals`

| Column | Type | Null? | Source JSON | UI Label |
|---|---|---:|---|---|
| id | BIGINT IDENTITY | No | System | — |
| project_id | BIGINT | No | Relationship | — |
| professional_type | VARCHAR(50) | No | object key: contractor/architect/structural_engineer | Role |
| name | VARCHAR(255) | Yes | `name` | Name |
| address | TEXT | Yes | `address` | Address |
| license_number | VARCHAR(100) | Yes | `license_number` | License Number |
| contact | VARCHAR(100) | Yes | future-compatible | Contact |
| email | VARCHAR(255) | Yes | future-compatible | Email |

## F. `project_bank_details`

| Column | Type | Null? | Source JSON | UI Label |
|---|---|---:|---|---|
| id | BIGINT IDENTITY | No | System | — |
| project_id | BIGINT | No | Relationship | — |
| account_number | VARCHAR(100) | Yes | `account_number` | Account Number (masked) |
| account_holder_name | VARCHAR(255) | Yes | `account_holder_name` | Account Holder |
| bank_name | VARCHAR(255) | Yes | `bank_name` | Bank |
| branch_address | TEXT | Yes | `branch_address` | Branch Address |
| branch_name | VARCHAR(255) | Yes | `branch_name` | Branch |
| ifsc_code | VARCHAR(20) | Yes | `ifsc_code` | IFSC |

## G. `project_documents`

| Column | Type | Null? | Source JSON | UI Label |
|---|---|---:|---|---|
| id | BIGINT IDENTITY | No | System | — |
| project_id | BIGINT | No | Relationship | — |
| serial_number | INTEGER | Yes | `serial_number` | Serial No. |
| document_name | VARCHAR(500) | Yes | `document_name` | Document |
| file_name | VARCHAR(500) | Yes | `file_name` | File Name |
| uploaded_date | DATE | Yes | `uploaded_date` | Uploaded Date |
| document_type | VARCHAR(50) | Yes | `document_type` | Type |
| document_url | TEXT | Yes | `download_url` | View Document |

## H. `project_progress_links`

| Column | Type | Null? | Source JSON | UI Label |
|---|---|---:|---|---|
| id | BIGINT IDENTITY | No | System | — |
| project_id | BIGINT | No | Relationship | — |
| name | VARCHAR(500) | Yes | `quarterly_progress.links[].name` | Progress Item |
| url | TEXT | Yes | `quarterly_progress.links[].url` | View |

## I. `project_extensions`

| Column | Type | Purpose |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| project_id | BIGINT | FK to project |
| section_name | VARCHAR(100) | Identifies the source section |
| data | JSONB | Original section payload |
| created_at | TIMESTAMPTZ | Audit timestamp |

Current `section_name` candidates:
- `plan_records`
- `unit_records`
- `villa_plot_records`
- `khasra_plot_details`
- `registry_agreement_details`
- `development_works`

These are intentionally not normalized until real non-empty examples are available.

## Security note

`account_number` should not be displayed in full on the UI. Store/access it with appropriate application-level security and mask it in presentation, e.g. `********5067`.
