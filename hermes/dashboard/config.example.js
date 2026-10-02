// Copy to config.js and fill in. ONLY the anon/publishable key goes here —
// it is safe to expose IF AND ONLY IF RLS is enabled with read-only policies
// (which 01_hermes_monitoring.sql does). NEVER put the service_role/secret key
// in this file or anywhere client-side.
window.HERMES_DASHBOARD_CONFIG = {
  SUPABASE_URL: "https://YOUR_PROJECT_REF.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_...",
  REFRESH_SECONDS: 15,
};
