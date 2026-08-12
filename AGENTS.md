# Project Delivery Rules

- Protect `main`; feature work stays on the current approved feature branch.
- Preserve user changes. Do not reset, clean, merge, or overwrite unrelated work.
- Small feature slices use focused tests. Run the full gate only for a major release or stable-branch integration.
- Never commit runtime media, household data, credentials, private addresses, or generated local settings.
- For macOS instructions, give only short copy-safe terminal commands.
- Put reusable or long scripts in this repository; do not require multiline terminal paste or heredocs.
- Repository shell scripts must be ASCII-only, UTF-8 with LF endings, compatible with macOS Bash 3.2 and BSD tools, and verified with `bash -n`.
- Avoid GNU-only flags, smart quotes, Chinese comments, and emoji in shell scripts.
