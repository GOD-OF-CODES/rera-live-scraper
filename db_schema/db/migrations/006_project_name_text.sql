-- Preserve complete published names, including names longer than 255 characters.
-- Safe to apply again; no values are truncated and existing rows are retained.
-- PostgreSQL requires rebuilding the view that selects this column. Preserve its
-- definition, comment, owner and explicit grants. Do not CASCADE: unexpected
-- downstream dependencies must fail the transaction rather than be removed.
DO $$
DECLARE
    view_oid oid := to_regclass('project_documents_view');
    view_definition text;
    view_comment text;
    view_owner text;
    view_grants jsonb;
    grant_row record;
BEGIN
    IF view_oid IS NOT NULL THEN
        SELECT pg_get_viewdef(view_oid, true), obj_description(view_oid, 'pg_class'),
               pg_get_userbyid(relowner)
        INTO view_definition, view_comment, view_owner
        FROM pg_class WHERE oid = view_oid;
        SELECT jsonb_agg(jsonb_build_object(
                   'grantee', CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                   'privilege', a.privilege_type, 'grantable', a.is_grantable))
        INTO view_grants
        FROM pg_class c, LATERAL aclexplode(c.relacl) a WHERE c.oid = view_oid;
        DROP VIEW project_documents_view;
    END IF;

    ALTER TABLE projects ALTER COLUMN project_name TYPE TEXT;

    IF view_definition IS NOT NULL THEN
        EXECUTE 'CREATE VIEW project_documents_view AS ' || view_definition;
        EXECUTE format('COMMENT ON VIEW project_documents_view IS %L', view_comment);
        FOR grant_row IN SELECT * FROM jsonb_to_recordset(view_grants)
            AS x(grantee text, privilege text, grantable boolean)
        LOOP
            EXECUTE format('GRANT %s ON project_documents_view TO %s%s',
                grant_row.privilege,
                CASE WHEN grant_row.grantee = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(grant_row.grantee) END,
                CASE WHEN grant_row.grantable THEN ' WITH GRANT OPTION' ELSE '' END);
        END LOOP;
        EXECUTE format('ALTER VIEW project_documents_view OWNER TO %I', view_owner);
    END IF;
END $$;
