# Guardian Event Dashboard Implementation Plan

1. Add focused RED tests for the read-only query and closed response projection.
2. Implement `GuardianEventQueryService` with SQLite read-only/query-only access.
3. Inject the service from centralized `app.data_dir` and expose an authenticated,
   no-store API with one stable unavailable result.
4. Add Dashboard presenter/rendering tests for immediate load, 15-second refresh,
   unresolved emphasis, five evidence states and stale-list retention.
5. Serve the script through the existing authentication boundary and add the media-free
   event section to the Dashboard.
6. Run focused tests, full Python and Node suites, compilation, dry-run, diff and
   privacy/security scans; update project status documents and publish only the
   approved feature branch.
