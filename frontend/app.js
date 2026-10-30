/* ==========================================================================
   Bug Buster - app.js

   STAGE 2 (design only): this file intentionally contains no behaviour yet.
   Stage 3 adds uploads, preview and loading states. Stage 4 connects the
   real backend.

   The page is built so JavaScript only has to flip a few attributes:

   - #conn-pill[data-status]      checking | online | degraded | offline
   - #upload-wrap[data-has-file]  "true" | "false"
   - #results[data-state]         idle | loading | error | insufficient | success
   - #submit-btn.is-loading       shows the spinner and elapsed timer

   Backend contract (read from backend/main.py, do not change):
   - GET  {API}/health
   - POST {API}/analyze-bug   multipart/form-data: image, repo_path, issue_hint (optional)
   ========================================================================== */

"use strict";

// Default backend address. Stage 3 lets the user change it in the settings dialog.
const DEFAULT_API_URL = "http://localhost:8000";
