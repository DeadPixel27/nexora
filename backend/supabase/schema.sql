-- Nexora schema — run in Supabase SQL Editor (Dashboard → SQL → New query)

create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    email text not null default '',
    created_at timestamptz not null default now()
);

create table if not exists workflows (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    name text not null,
    description text not null default '',
    source text not null default 'planner',
    task_description text not null default '',
    parent_template_id text,
    current_template_version_id uuid,
    extraction_prompt text,
    default_email text,
    default_sheets_url text,
    default_sheet_name text,
    created_at timestamptz not null default now()
);

create table if not exists workflow_steps (
    id uuid primary key default gen_random_uuid(),
    workflow_id uuid not null references workflows(id) on delete cascade,
    step_order int not null,
    agent_type text not null,
    config jsonb not null default '{}',
    reason text not null default '',
    unique (workflow_id, step_order)
);

create table if not exists workflow_runs (
    id uuid primary key default gen_random_uuid(),
    workflow_id uuid references workflows(id) on delete set null,
    user_id uuid references users(id) on delete set null,
    upload_id text not null,
    document_ids jsonb not null default '[]',
    task_description text not null default '',
    status text not null,
    planned_steps jsonb not null default '[]',
    result jsonb,
    error_message text,
    parent_run_id uuid references workflow_runs(id) on delete set null,
    template_id text,
    current_template_version_id uuid,
    extraction_prompt text,
    cached_documents jsonb,
    refine_summary text,
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists workflow_step_runs (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references workflow_runs(id) on delete cascade,
    step_order int not null,
    agent_type text not null,
    status text not null,
    output jsonb not null default '{}',
    error_message text,
    unique (run_id, step_order)
);

create index if not exists idx_users_email on users(email);
create index if not exists idx_workflows_user_id on workflows(user_id);
create index if not exists idx_workflow_steps_workflow_id on workflow_steps(workflow_id);
create index if not exists idx_workflow_runs_workflow_id on workflow_runs(workflow_id);
create index if not exists idx_workflow_runs_user_id on workflow_runs(user_id);
create index if not exists idx_workflow_step_runs_run_id on workflow_step_runs(run_id);

-- Pipeline templates (editable catalog — seed via supabase/seed_templates.sql)
create table if not exists pipeline_templates (
    id text primary key,
    name text not null,
    description text not null default '',
    icon text not null default 'file-text',
    category text not null default 'general',
    default_task text not null,
    fields jsonb not null default '[]',
    extraction_instructions text not null default '',
    rules jsonb not null default '[]',
    output_format text not null default 'json',
    suggested_steps jsonb not null default '[]',
    example_output_fields jsonb not null default '[]',
    sort_order int not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_pipeline_templates_category on pipeline_templates(category);
create index if not exists idx_pipeline_templates_active_sort on pipeline_templates(is_active, sort_order);

create table if not exists user_template_versions (
    id uuid primary key,
    scope_type text not null check (scope_type in ('run', 'workflow')),
    scope_id uuid not null,
    parent_version_id uuid references user_template_versions(id) on delete set null,
    template_id text not null,
    storage_key text not null,
    refine_summary text not null default '',
    version_number int not null,
    created_at timestamptz not null default now(),
    unique (scope_type, scope_id, version_number)
);

create index if not exists idx_user_template_versions_scope
    on user_template_versions(scope_type, scope_id, version_number);

create table if not exists refinement_events (
    id uuid primary key default gen_random_uuid(),
    template_id text not null,
    scope_type text not null check (scope_type in ('run', 'workflow')),
    scope_id uuid not null,
    version_id uuid not null references user_template_versions(id) on delete cascade,
    parent_version_id uuid,
    user_message text not null default '',
    refine_summary text not null default '',
    created_at timestamptz not null default now()
);

create index if not exists idx_refinement_events_template
    on refinement_events(template_id, created_at desc);

-- V2: inbound email forwarding addresses (one per workflow)
create table if not exists inbound_addresses (
    address_id text primary key,
    full_address text not null unique,
    user_id uuid not null references users(id) on delete cascade,
    workflow_id uuid not null references workflows(id) on delete cascade,
    created_at timestamptz default now()
);

create index if not exists idx_inbound_addresses_user_id
    on inbound_addresses(user_id);

-- Launch: usage metering, waitlist, analytics, admin flag
create table if not exists usage_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    pages int not null default 1,
    template_id text,
    run_id uuid references workflow_runs(id) on delete set null,
    event_type text not null default 'extraction',
    created_at timestamptz not null default now()
);

create index if not exists idx_usage_events_user_month
    on usage_events(user_id, created_at);

create table if not exists waitlist (
    id uuid primary key default gen_random_uuid(),
    email text not null,
    name text not null default '',
    source text not null default 'normal',
    feedback text not null default '',
    created_at timestamptz not null default now()
);

create unique index if not exists idx_waitlist_email
    on waitlist(email);

create table if not exists analytics_events (
    id uuid primary key default gen_random_uuid(),
    event_type text not null,
    user_id uuid references users(id) on delete set null,
    template_id text,
    run_id uuid references workflow_runs(id) on delete set null,
    duration_ms int,
    page_count int,
    error text,
    metadata jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists idx_analytics_events_type_date
    on analytics_events(event_type, created_at);

create table if not exists audit_events (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    actor_user_id uuid references users(id) on delete set null,
    action text not null,
    resource_type text,
    resource_id text,
    request_id text,
    metadata jsonb not null default '{}'
);

create index if not exists idx_audit_events_actor_date
    on audit_events(actor_user_id, created_at);

create index if not exists idx_audit_events_action_date
    on audit_events(action, created_at);

alter table users add column if not exists is_admin boolean not null default false;

-- Uploads registry (owner binding for IDOR prevention)
create table if not exists uploads (
    id text primary key,
    user_id uuid not null references users(id) on delete cascade,
    created_at timestamptz not null default now()
);

create index if not exists idx_uploads_user_id on uploads(user_id);

-- RLS: backend-only access via service role (see migrations/017_enable_rls.sql)
alter table users enable row level security;
alter table workflows enable row level security;
alter table workflow_steps enable row level security;
alter table workflow_runs enable row level security;
alter table workflow_step_runs enable row level security;
alter table pipeline_templates enable row level security;
alter table user_template_versions enable row level security;
alter table refinement_events enable row level security;
alter table inbound_addresses enable row level security;
alter table usage_events enable row level security;
alter table waitlist enable row level security;
alter table analytics_events enable row level security;
alter table audit_events enable row level security;
alter table uploads enable row level security;

