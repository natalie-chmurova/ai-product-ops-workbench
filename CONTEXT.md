# AI Product Ops Workbench

Turns one product meeting into work on a tracker board: it reads what was said, drafts tickets and summaries, checks every point against the board, and proposes a plan that a person applies.

## Language

### The meeting

**Transcript**:
The text of one meeting, typed or transcribed from a recording.
_Avoid_: notes

**Meeting context**:
The structured reading of one transcript that every artifact is built from: meeting decisions, action items, bugs, risks and sprint signals.
_Avoid_: summary, context (on its own)

**Action item**:
A piece of work someone must do, as the meeting stated it.
_Avoid_: todo

**Meeting decision**:
A position the team settled on that changes work already under way — its scope, its date or its priority. It never becomes new work of its own.
_Avoid_: decision (on its own)

**Change kind**:
Which of those a meeting decision changed: `scope_change`, `date_change`, `priority_change` or `other`. It is a meeting decision's own kind and never an effect kind; the two are read a few lines apart when the plan is rendered.
_Avoid_: kind (on its own), type

**Task**:
A tracker-ready ticket drafted from an action item or a bug, with a goal, context, steps and acceptance criteria.
_Avoid_: ticket, issue

**Artifact**:
A document built from one meeting context: tasks, the sprint summary, the bug triage, the per-speaker notes, and the report page that shows them beside the transcript.

### The board

**Board**:
The open tasks in the tracker list a run is checked against.
_Avoid_: backlog, list (for the set of tasks)

**Board row**:
One task on the board as the pipeline sees it: its id, name, status, owners and due date.
_Avoid_: card

**Scope**:
The one tracker list a run reads its board from and writes its plan to.
_Avoid_: target list, list id

**Board fixture**:
A board read from a file instead of the tracker, so a transcript can be checked against a board from its own world.

### Reconciling

**Point**:
Anything checked against the board — a task, an action item, a meeting decision or an eval entry. Every point has a name and a body.
_Avoid_: item

**Match**:
The agent's answer for one point: new work, or an update to a named board row, with a confidence and a reason.
_Avoid_: decision, verdict

**Gate**:
The confidence below which a match is not acted on without a person.
_Avoid_: threshold

**Escalation cause**:
Why a point went to a person: the agent doubted its match, its reply could not be read, or it named a row that is not on the board.

### The plan

**Plan**:
What a run proposes to do to its scope — one effect for every point — before anything is written. The Board plan tab is where it is shown.
_Avoid_: board plan (for the value itself)

**Effect**:
What happens to one point: create a task, comment on an existing one, or ask a person.
_Avoid_: action, outcome

**Effect kind**:
Which of those three an effect is: `create`, `comment` or `ask`. An intent is an effect kind too — the one the agent would have chosen with the gate ignored.
_Avoid_: kind (on its own), action

**Intent**:
The effect the agent would take if the gate were ignored.
_Avoid_: decision

**Verdict**:
A person's call on a point the agent asked about: approve, reject or redirect.
_Avoid_: decision, approval

**Apply**:
Writing a plan's effects to its scope after a person clicks, each effect at most once.
_Avoid_: send, push, sync

**Effect key**:
The fingerprint of one effect, computed identically by the app and the n8n workflow, that makes applying the same effect a second time write nothing.
_Avoid_: hash
