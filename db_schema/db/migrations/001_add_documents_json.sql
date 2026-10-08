-- Migration 001: add a denormalized documents_json column to
-- projects.
--
-- WHY: project_documents already stores one row per document
-- (correctly normalized), but that means seeing "all documents
-- for this project" in pgAdmin requires a join/filter. This
-- column keeps a plain JSON copy of the same documents array
-- directly on the project row, so you can see it at a glance
-- without leaving the projects table.
--
-- This does not replace project_documents - that table is still
-- the source of truth and is what you should query/join against.
-- This column is a convenience mirror of the same data.
--
-- Safe to run multiple times (IF NOT EXISTS).

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS documents_json JSONB;

COMMENT ON COLUMN projects.documents_json IS
    'Denormalized copy of this project''s documents (same data as project_documents), for quick viewing in pgAdmin without a join.';
