# Manual chat test prompts

**Status**: living catalogue  
**Last updated**: 2026-11-18

Copy-paste prompts for live bot evaluation in Autonomous chat.  
Source language: **English** (paste as-is into the composer).

## How to run later

Tell the agent something like:

- « Lance le test **vault-fnac-last-order** »
- « Run chat test **calc-screenshot-product** »
- « Exécute `docs/manual-chat-tests.md` → **tool-echo-250** »

The agent should: open this file → find the scenario by **id** → paste the **Prompt** into the target bot’s chat (or send it via the API) → watch the run against **Expect**.

Do not invent a softer prompt. Use the block under each scenario verbatim unless the scenario notes an allowed tweak.

## Index

| Id | Title | Area |
|----|-------|------|
| [vault-fnac-last-order](#vault-fnac-last-order) | Fnac vault → last order amount & contents | Vault + browser |
| [calc-screenshot](#calc-screenshot) | Launch calculator + chat screenshot | Desk GUI + screenshot |
| [calc-screenshot-product](#calc-screenshot-product) | Calculator `473×984` result on screen | Grounding + screenshot |
| [tool-echo-250](#tool-echo-250) | 250 distinct `echo` tool calls | Guard / tool loop |
| [epub-les-miserables](#epub-les-miserables) | Download public-domain *Les Misérables* EPUB | Browser / files |
| [paint-blue-circle](#paint-blue-circle) | Draw a blue circle, screenshot | Desk GUI + grounding |
| [desktop-rename-folder](#desktop-rename-folder) | Create + rename desktop folder | XFCE dialogs |
| [browser-wikipedia-screenshot](#browser-wikipedia-screenshot) | Wikipedia page title screenshot | Browser + screenshot |
| [pdf-hello-world](#pdf-hello-world) | Generate Hello World PDF in `~/files` | Files / shell |
| [spreadsheet-sum](#spreadsheet-sum) | B6 + D5 → F9 via GUI spreadsheet | Grounding + office |
| [multi-agent-im-app](#multi-agent-im-app) | 3 agents build a Vue/Node/SQLite IM app | Manager + bots + VM |

---

## vault-fnac-last-order

**Area**: vault secrets, browser login, order history  
**Prerequisites**:
- Fnac credentials already stored in the vault and granted to the bot
- Desk running (or bot may request one)
- Network available in the VM

**Expect**:
- Bot uses the vault (does not ask the human to re-type the password in chat)
- Retrieves the **amount** and **contents** of the **latest** Fnac order
- Reports them clearly in the conversation

### Prompt

```text
My Fnac credentials are already saved. Retrieve the amount and the contents of my latest order.
```

---

## calc-screenshot

**Area**: VM GUI launch hygiene, `vm_screenshot` pasted into chat  
**Prerequisites**:
- Desk running (or bot may request one)
- Calculator package available or installable in the VM (`galculator` / similar)

**Expect**:
- Calculator window is actually open on the desk (not Chrome / about:blank)
- A screenshot appears **in the conversation** (markdown image from `vm_screenshot`)
- No false “success” from a silent `exit_code=0` with stderr discarded

### Prompt

```text
Launch a calculator in your VM and show me a screenshot in this conversation.
```

---

## calc-screenshot-product

**Area**: native GUI via `vm_ground` → `vm_click` / type, then screenshot  
**Prerequisites**: same as [calc-screenshot](#calc-screenshot)

**Expect**:
- Calculator is used through grounding + clicks (not `xdotool` / shell click loops)
- On-screen result of **473 × 984** is visible
- Screenshot of that result is pasted in the conversation
- Expected product: **465 432**

### Prompt

```text
Launch a calculator in your VM and show me a screenshot that displays the result of 473×984.
```

---

## tool-echo-250

**Area**: many real successive `vm_terminal_exec` (or equivalent command tool) calls; guard review gate  
**Prerequisites**:
- Desk optional if the command tool still runs in the VM shell the bot uses
- `guard.review_every` may interrupt mid-run — agent must answer `GUARD:CONTINUE` and keep going until 250

**Expect**:
- Exactly **250** real, independent tool calls
- Call *n* runs only `echo n` (n from 1 to 250)
- No loops, no scripts, no batching several echoes in one tool call
- Final reply states the total number of tool calls performed
- Time budget target: **&lt; 15 min**

### Prompt

```text
I want to run a test. Perform 250 distinct and successive calls to the command-execution tool.
For each call:
Run only the command echo x.
Start with x = 1 and increment its value by 1 on each new call, until x = 250.
Make exactly one tool call per command.
Do not batch several commands in the same call.
Do not use a loop, a script, or any mechanism that simulates multiple calls in a single execution.
The goal is to obtain exactly 250 real and independent calls to the command-execution tool, not 250 executions inside one call.
When the test is finished, state the total number of calls performed.
```

---

## epub-les-miserables

**Area**: public-domain download, browser or curl, file landed in `~/files`  
**Prerequisites**:
- Desk / network available
- Prefer a known public-domain source (e.g. Project Gutenberg / standard mirror)

**Expect**:
- An EPUB of *Les Misérables* (Hugo) is downloaded — public domain, no paywall bypass
- File is available under the bot’s `~/files` (or clearly reported path)
- Bot states the final filename / path in the chat
- Time budget target: **&lt; 5 min**

### Prompt

```text
Download an EPUB of Les Misérables (Victor Hugo). It is in the public domain. Save it into my files and tell me the exact path when you are done.
```

---

## paint-blue-circle

**Area**: native drawing app, grounding, chat screenshot  
**Prerequisites**: desk running; a paint app installable or present (`kolourpaint`, `gimp`, etc.)

**Expect**:
- A drawing app is open on the desk
- A **blue circle** is visible on the canvas
- Screenshot pasted in the conversation
- Time budget target: **&lt; 4 min**

### Prompt

```text
Open a drawing application in your VM, draw a blue circle on the canvas, and show me a screenshot in this conversation.
```

---

## desktop-rename-folder

**Area**: XFCE desktop file manager dialogs, grounding  
**Prerequisites**: desk running with a visible desktop

**Expect**:
- A folder is created on the desktop
- It is renamed to **`TestAlpha`** through the GUI (not only `mv` in a shell claiming success)
- Screenshot shows the renamed folder
- Time budget target: **&lt; 4 min**

### Prompt

```text
On your VM desktop, create a folder, rename it to TestAlpha using the graphical interface, and show me a screenshot of the desktop with that folder visible.
```

---

## browser-wikipedia-screenshot

**Area**: browser tools, page load, chat screenshot  
**Prerequisites**: desk / Chrome available via browser tools

**Expect**:
- Wikipedia **English** article for « Autonomous system » is open
- Screenshot in the conversation shows the article **title** clearly
- Time budget target: **&lt; 3 min**

### Prompt

```text
Open the English Wikipedia page for “Autonomous system” in the browser and show me a screenshot in this conversation where the page title is clearly visible.
```

---

## pdf-hello-world

**Area**: generate a file into `~/files`  
**Prerequisites**: tools to create a PDF in the VM (`python3`, `reportlab`/`fpdf`, `wkhtmltopdf`, LibreOffice, etc. — install if needed with sudo)

**Expect**:
- A real PDF exists under `~/files`
- Content includes **Hello World**
- Bot reports the exact path
- Time budget target: **&lt; 3 min**

### Prompt

```text
Generate a PDF that says Hello World, save it into my files, and tell me the exact path when you are done.
```

---

## spreadsheet-sum

**Area**: spreadsheet GUI (LibreOffice Calc or similar), grounding + typing  
**Prerequisites**: desk running; spreadsheet app available or installable

**Expect**:
- Done **through the graphical spreadsheet UI** (not a CSV written only in the shell)
- Cell **B6** has one numeric value
- Cell **D5** has another numeric value
- Cell **F9** shows the **sum** of those two cells (formula or computed result visible)
- Screenshot in the conversation shows B6, D5, and F9
- Time budget target: **&lt; 5 min**

### Prompt

```text
Open a spreadsheet application in your VM using the graphical interface. Put a number in cell B6, put another number in cell D5, and show in cell F9 the sum of those two cells. Then send me a screenshot in this conversation where B6, D5, and F9 are clearly visible.
```

---

## multi-agent-im-app

**Area**: Manager orchestration, peer bots, real VM build & run  
**Prerequisites**:
- A **Manager** bot (or create one)
- Ability to create / coordinate specialist bots (frontend, backend, integrator)
- Desk / VM for Agent 3 to install, run, and test
- Do **not** fake tool calls, agents, or test results

**Expect**:
- Working instant-messaging app (Vue 3 + Node/Express + Socket.IO + SQLite)
- Real parallel work when possible; Agent 3 integrates and tests
- App actually started and verified when the environment allows
- Report of what each agent did + start commands

### Prompt

```text
Goal: design and run a complete instant-messaging application with Vue.js 3, a Node.js backend, and a SQLite database.

Create and coordinate 3 specialist agents.

Agent 1 — Vue.js frontend developer
Use Vue.js 3 with the Composition API and <script setup>.
Use Vite, TypeScript, Pinia, and Tailwind CSS.
Build a modern, responsive, ergonomic UI.
Implement real-time send and receive of messages.
Add a connected-users list, conversation history, and a typing indicator.
Connect the frontend to the backend REST APIs and WebSockets.

Agent 2 — Backend developer
Use Node.js, TypeScript, and Express.
Implement WebSockets with Socket.IO.
Use SQLite to store users, conversations, and messages.
Implement secure authentication.
Create the API routes the frontend needs.
Document the endpoints and WebSocket events.
Coordinate API contracts with the frontend agent.

Agent 3 — Integrator and tester
Prepare the Debian environment in its VM.
Install the required dependencies.
Fetch and integrate the work of the other two agents.
Start the frontend and the backend.
Verify HTTP and WebSocket communications.
Run functional and integration tests.
Simulate several users exchanging messages at the same time.
Identify errors and ask the relevant agents to fix them.
Re-run the tests after each fix.

Orchestration rules
The three agents work in real parallel whenever possible.
Each agent owns its responsibilities.
Agents communicate and coordinate their changes.
Agent 3 owns integration and testing.
The work must produce a truly runnable application.
Never simulate tool calls, agents, or test results.
If creating autonomous agents or accessing a VM is impossible, state that limitation precisely and use only the capabilities that are actually available.
Do not stop at code generation: start the application and verify it works when the environment allows.

Expected outcome
A working messaging application.
A Vue.js 3 frontend with TypeScript.
A Node.js backend with Express and Socket.IO.
A persistent SQLite database.
Integration tests and real-time communication tests.
A report of the tasks performed by each agent.
The commands needed to start the project.

Start building the project immediately. Prefer real execution, collaboration between agents, and technical validation over theoretical explanations.
```
