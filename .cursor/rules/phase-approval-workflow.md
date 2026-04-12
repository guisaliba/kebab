## Phase Approval Workflow

When a phase is explicitly approved by the user, execute this sequence:

1. Ensure a phase branch exists; if creating a new branch, always branch from `main`.
2. Commit approved phase changes using Conventional Commits.
3. Push commits and ensure the branch is published to remote.
4. Open a PR to `main`.
5. After PR creation, provide the next phase plan before implementation.
6. Before requesting phase closure, provide a full verification package with:
   - exact files changed and one-line purpose per file
   - exact commands run (index/tests/eval/phase-specific commands)
   - concrete generated artifact samples from a real run
   - contract/path/grounding proofs
   - rerun and safety proofs
   - retrieval guardrail metrics and benchmark-change evidence
   - known limitations and recommended next phase

Constraints:

- Keep trust boundaries intact: no direct automated writes to `wiki/`.
- Keep retrieval/editorial automation staging-only unless explicitly changed by approved phase scope.
- Keep phase PRs focused, but include explicitly requested unrelated files when the user asks.
- Do not mark a phase as complete from summaries alone; closure requires the verification package.
