# UP-RERA Database Schema Design

## 1. Central idea

The scraper JSON is a nested document. A relational database should not be one huge `projects` table.

The main project becomes the parent record and repeating/independent sections become related tables.

```text
PROMOTER
   |
   | 1:N
   v
PROJECT
   |
   +-- 1:1 PROJECT_BASIC_DETAILS
   +-- 1:1 PROJECT_LOCATION
   +-- 1:N PROJECT_PROFESSIONALS
   +-- 1:1 PROJECT_BANK_DETAILS
   +-- 1:N PROJECT_DOCUMENTS
   +-- 1:N PROJECT_PROGRESS_LINKS
   +-- 1:1 PROJECT_EXTENSIONS
```

## 2. Tables

### `promoters`
Stores the UP-RERA promoter identity. One promoter can have multiple projects.

### `projects`
Main project record. This contains project identity, registration, type, district and source URLs.

### `project_basic_details`
Stores area, tehsil, start/completion dates, project cost and sanctioning authority.

### `project_locations`
Stores the latitude/longitude values exactly as extracted. They are kept as text because the three samples contain different representations.

Example:
- `11`, `13`, `12`, `14`
- `27`, `203718`, `77`, `972437`
- DMS-like strings such as `28'28’50.12” N`

Do not convert these values without first confirming UP-RERA's coordinate format.

### `project_professionals`
Stores contractor, architect, structural engineer and similar roles. This is a child table because a project may have several professional roles and some projects have missing roles.

### `project_bank_details`
Stores project bank-account metadata. Account numbers should be protected/masked at the UI layer.

### `project_documents`
Stores every document row. One project can have many documents. The PDF itself is not stored by this schema; the UP-RERA URL is stored.

### `project_progress_links`
Stores quarterly progress/certificate links.

### `project_extensions`
Stores source sections whose internal shape is not known yet:
- plan records
- unit records
- villa/plot records
- khasra/plot details
- registry/agreement details
- development works

This avoids inventing columns that are not supported by the current JSON samples.

## 3. Common vs optional data

The three samples show that fields can be missing depending on the project.

Examples:

- `tehsil` exists in some projects but not all.
- `original_start_date` and `sanctioning_competent_authority` occur in The Hemisphere sample but not the other two.
- architect and structural-engineer details are populated in some projects and empty in others.
- document counts vary substantially.
- project type can be Residential or Commercial.

Therefore, most source-derived fields are nullable unless they are fundamental identifiers.

## 4. Primary keys

Each database table has its own internal `BIGSERIAL`/identity primary key.

UP-RERA identifiers are also retained:

- project: `rera_project_id` / `registration_number`
- promoter: `rera_promoter_id`

This prevents the database's internal ID from being confused with the government/source identifier.

## 5. Foreign-key relationships

- `projects.promoter_id -> promoters.id`
- child project tables use `project_id -> projects.id`
- child rows use `ON DELETE CASCADE`

## 6. Source/provenance

The schema preserves:

- source
- search URL
- project details URL
- document URL
- progress URL

This is important for future property due-diligence because a UI/AI result should be traceable back to UP-RERA.

## 7. Why JSONB is used for currently unknown structures

The current samples contain empty arrays/objects for some sections. A schema should not invent fields without source evidence.

For those sections, `project_extensions` stores JSONB payloads until actual records are observed.

Later:

```text
JSONB extension
      |
      v
inspect real records
      |
      v
define exact columns
      |
      v
normalize into dedicated child table
```
