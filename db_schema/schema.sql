-- UP-RERA Database Schema Design
-- Implemented and tested — see db/init_db.py to apply, db/loader.py to insert data.
-- PostgreSQL

CREATE TABLE promoters (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rera_promoter_id VARCHAR(50) UNIQUE,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    registration_number VARCHAR(50) NOT NULL UNIQUE,
    rera_project_id VARCHAR(50),
    project_name VARCHAR(255) NOT NULL,
    project_type VARCHAR(100),
    district VARCHAR(150),
    approval_certificate VARCHAR(255),
    registration_date DATE,
    promoter_id BIGINT REFERENCES promoters(id),
    source VARCHAR(50) NOT NULL DEFAULT 'UP-RERA',
    search_url TEXT,
    project_details_url TEXT,
    documents_json JSONB,
    scraped_at TIMESTAMPTZ
);

CREATE INDEX idx_projects_promoter_id ON projects(promoter_id);
CREATE INDEX idx_projects_district ON projects(district);
CREATE INDEX idx_projects_project_type ON projects(project_type);

CREATE TABLE project_basic_details (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL UNIQUE
        REFERENCES projects(id) ON DELETE CASCADE,
    total_area_sq_m NUMERIC(15,2),
    district VARCHAR(150),
    tehsil VARCHAR(150),
    original_start_date DATE,
    proposed_start_date DATE,
    sanctioning_competent_authority VARCHAR(255),
    project_cost_lakhs NUMERIC(15,2),
    proposed_completion_date DATE
);

CREATE TABLE project_locations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL UNIQUE
        REFERENCES projects(id) ON DELETE CASCADE,
    latitude_part_1 VARCHAR(100),
    latitude_part_2 VARCHAR(100),
    longitude_part_1 VARCHAR(100),
    longitude_part_2 VARCHAR(100)
);

CREATE TABLE project_professionals (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL
        REFERENCES projects(id) ON DELETE CASCADE,
    professional_type VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    address TEXT,
    license_number VARCHAR(100),
    contact VARCHAR(100),
    email VARCHAR(255)
);

CREATE INDEX idx_project_professionals_project_id
    ON project_professionals(project_id);

CREATE TABLE project_bank_details (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL UNIQUE
        REFERENCES projects(id) ON DELETE CASCADE,
    account_number VARCHAR(100),
    account_holder_name VARCHAR(255),
    bank_name VARCHAR(255),
    branch_address TEXT,
    branch_name VARCHAR(255),
    ifsc_code VARCHAR(20)
);

CREATE TABLE project_documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL
        REFERENCES projects(id) ON DELETE CASCADE,
    serial_number INTEGER,
    document_name VARCHAR(500),
    file_name VARCHAR(500),
    uploaded_date DATE,
    document_type VARCHAR(50),
    document_url TEXT
);

CREATE INDEX idx_project_documents_project_id
    ON project_documents(project_id);

CREATE TABLE project_progress_links (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL
        REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(500),
    url TEXT
);

CREATE INDEX idx_project_progress_project_id
    ON project_progress_links(project_id);

CREATE TABLE project_extensions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id BIGINT NOT NULL
        REFERENCES projects(id) ON DELETE CASCADE,
    section_name VARCHAR(100) NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_project_extensions_project_id
    ON project_extensions(project_id);

CREATE INDEX idx_project_extensions_data
    ON project_extensions USING GIN(data);

-- Candidate section_name values:
-- plan_records
-- unit_records
-- villa_plot_records
-- khasra_plot_details
-- registry_agreement_details
-- development_works

-- NOTE:
-- Full account_number should be protected and should never be
-- displayed directly in the UI. Mask it at presentation time.

-- =========================================================
-- Project Documents section (see db/migrations/002_project_documents_view.sql)
-- =========================================================

CREATE OR REPLACE VIEW project_documents_view AS
SELECT
    pr.id                    AS project_id,
    pr.registration_number,
    pr.project_name,
    pd.serial_number,
    pd.document_name,
    pd.file_name,
    pd.document_type,
    pd.uploaded_date,
    pd.document_url
FROM projects pr
JOIN project_documents pd ON pd.project_id = pr.id
ORDER BY pr.registration_number, pd.serial_number;

COMMENT ON VIEW project_documents_view IS
    'One row per document, joined with its project. Browse this in pgAdmin (Views) to see document_name and document_url per project without writing a join yourself.';
