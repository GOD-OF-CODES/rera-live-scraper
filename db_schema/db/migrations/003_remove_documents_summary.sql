-- Migration 003: remove projects.documents_summary
--
-- This column (added in migration 002) turned out not to be
-- wanted. project_documents_view remains the recommended way to
-- browse documents per project in pgAdmin - it wasn't touched by
-- this migration.
--
-- Safe to run multiple times.

ALTER TABLE projects
    DROP COLUMN IF EXISTS documents_summary;
