-- Enable Row Level Security on all application tables.
--
-- Nexora talks to Postgres only via the FastAPI backend (service role key).
-- The frontend never uses the Supabase client. With RLS on and no permissive
-- policies for anon/authenticated, PostgREST denies direct client access.
-- The service role bypasses RLS and is unaffected.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_step_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_template_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE refinement_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE uploads ENABLE ROW LEVEL SECURITY;
