#!/usr/bin/env bash
# AI-Native Project Bootstrap Script
# This script scaffolds the ideal file tree and core AI directives for a new repository.

set -e

echo "🚀 Bootstrapping AI-Native Project Structure..."

# 1. Create Directories
mkdir -p .gemini
mkdir -p .agents/rules
mkdir -p tasks

# 2. Create .gemini/GEMINI.md (The Prime Directive)
cat << 'EOF' > .gemini/GEMINI.md
# 🧠 AI Architectural Mandate & Workflow Orchestration

## Agent Intelligence & Behavioral Constraints

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions).
- If something goes sideways, STOP and re-plan immediately - don't keep pushing.
- Use plan mode for verification steps, not just building.
- Write detailed specs upfront to reduce ambiguity.

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean.
- Offload research, exploration, and parallel analysis to subagents.
- For complex problems, throw more compute at it via subagents.
- One task per subagent for focused execution.

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern.
- Write rules for yourself that prevent the same mistake.
- Ruthlessly iterate on these lessons until mistake rate drops.
- Review lessons at session start.

### 4. Verification Before Done
- Never mark a task complete without proving it works.
- Diff behavior between main and your changes when relevant.
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness.

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer.
- Challenge your own work before presenting it.

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding.
- Point at logs, errors, failing tests - then resolve them.
- Zero context switching required from the user.
- Go fix failing CI tests without being told how.
- After EVERY git push, you MUST actively monitor the CI/CD pipeline status (e.g., using `gh run list` and `gh run view`). If the pipeline fails, diagnose the trace logs and resolve all issues autonomously until the build is perfectly green.

## Task Management & Organization

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items.
2. **Verify Plan**: Check in before starting implementation.
3. **Track Progress**: Mark items complete as you go.
4. **Explain Changes**: High-level summary at each step.
5. **Document Results**: Add review section to `tasks/todo.md`.
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections.

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
EOF

# 3. Create .cursorrules (The Router)
cat << 'EOF' > .cursorrules
# AI System Instructions

Whenever you successfully implement a feature or fix and commit it to the repository, you MUST update the `CHANGELOG.md` file located at the root of the project. Detail what was added, changed, deprecated, removed, or fixed. 

CRITICAL: The core operational constraints for all agents are defined centrally in `.gemini/GEMINI.md`. You MUST adhere strictly to its rules on Plan Mode, Verification tracking, and Autonomous behavior.

Additionally, maintain `tasks/todo.md` by checking off completed tasks and adding new ones for future features or technical debt. After any significant correction from the user, you MUST proactively synthesize the rule to avoid the mistake and dump it into `tasks/lessons.md`.
EOF

# 4. Create .agents/rules/changelog_rule.md (Modular Subagent Rules)
cat << 'EOF' > .agents/rules/changelog_rule.md
---
description: Maintain the CHANGELOG and TODO list
---

# Persistent Memory & Changelog Rule

As an AI assistant working on this project, you MUST adhere to the following rule:

For **every successful implementation** of a feature or fix that is committed to the repository, you **MUST**:
1. Create an entry in `CHANGELOG.md` at the root of the project detailing what was added, changed, fixed, or removed.
2. If applicable, update the `tasks/todo.md` tracker to check off completed features or fixes, and add any new technical debt or planned features.
3. Obey the overarching project constraints, plan modes, and logging heuristics strictly defined within `.gemini/GEMINI.md`. Update `tasks/lessons.md` after correcting behavior.

Do not ask the user for permission to do this—do it proactively as part of the commit/wrap-up process.
EOF

# 5. Create Execution Tracker Files
cat << 'EOF' > tasks/todo.md
# AI Execution Planner & Checklists

### Features
- [ ] Initialize project scaffolding and setup local environment

### Fixes
- [ ] Review security policies and environment variables
EOF

cat << 'EOF' > tasks/lessons.md
# AI System Lessons Learned

_Every time the user corrects a mistake, documents a bug, or provides a new paradigm, log the behavioral pattern to avoid in this file._

## Ongoing Rules
- **Simple Over Complex**: Senior developer standards. Minimal Impact.
- **Self-Sufficiency**: When given a bug report: just fix it. Don't ask for hand-holding.
- **Proof Over Promises**: Never mark a task complete without proving it works. Run tests, check logs.
EOF

# 6. Create universal log
if [ ! -f CHANGELOG.md ]; then
cat << 'EOF' > CHANGELOG.md
# CHANGELOG

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- Initialized core repository using AI-Native Blueprint.
EOF
fi

echo "✅ Scaffold Complete! Your AI-Native repository template is ready."
echo "Created: .gemini/GEMINI.md, .cursorrules, .agents/rules/changelog_rule.md, tasks/todo.md, tasks/lessons.md, and CHANGELOG.md"
