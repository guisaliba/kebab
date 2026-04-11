## Phase Approval Workflow

When a phase is explicitly approved by the user, execute this sequence:

1. Ensure a phase branch exists; if creating a new branch, always branch from `main`.
2. Commit approved phase changes using Conventional Commits.
3. Push commits and ensure the branch is published to remote.
4. Open a PR to `main`.
5. After PR creation, provide the next phase plan before implementation.

Constraints:

- Keep trust boundaries intact: no direct automated writes to `wiki/`.
- Keep retrieval/editorial automation staging-only unless explicitly changed by approved phase scope.
- Keep phase PRs focused, but include explicitly requested unrelated files when the user asks.
