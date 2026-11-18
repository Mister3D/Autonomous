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

**Scoring**: each scenario’s **Expect** lists hard **Pass** checks and explicit **Fail if**. Time budgets are targets (note `OVER_BUDGET` if exceeded, but do not alone flip Pass→Fail unless the scenario says so). Prefer **one busy bot** (plus intentional peers for multi-agent) so LLM queue latency does not fake a product failure.

## Index

| Id | Title | Area |
|----|-------|------|
| [vault-fnac-last-order](#vault-fnac-last-order) | Fnac vault → last order amount & contents | Vault + browser |
| [calc-screenshot](#calc-screenshot) | Launch calculator + chat screenshot | Desk GUI + screenshot |
| [calc-screenshot-product](#calc-screenshot-product) | Calculator `473×984` result on screen | Grounding + screenshot |
| [tool-echo-250](#tool-echo-250) | 250 distinct `echo` tool calls + `batch_sequential` grouping | Guard / tool loop / throughput |
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

**Expect** — Pass when all of:
- Vault path used (`vault_catalog` / grant / `vault_type` as needed) — password never typed or pasted in chat by the human or the bot
- Latest Fnac order identified (order id or date clear enough to tell it is the latest)
- **Amount** (total with currency) and **contents** (line items / product names) stated in the assistant reply
- No invented order data: figures come from the live site after login

**Fail if**: asks the user for the password in clear text; reports a generic “I can’t access Fnac” while a grant exists; amount or contents missing; fabricates totals without opening the account.

### Prompt

```text
My Fnac credentials are already saved. Retrieve the amount and the contents of my latest order.
```

---

## calc-screenshot

**Area**: VM GUI launch hygiene, `vm_screenshot` on the tool row  

**Prerequisites**:
- Desk running (or bot may request one)
- Calculator package available or installable in the VM (`galculator` / similar)

**Expect** — Pass when all of:
- A calculator app is running on the desk (process + window), not a browser tab / blank screen
- At least one ``vm_screenshot`` (or equivalent) whose PNG is visible under the **tool-row detail** in the chat tool group (not required as assistant-bubble markdown)
- The capture visibly shows the calculator UI
- Known-arg shell steps (e.g. install then launch) may be grouped with `batch_sequential` — preferred, not required for Pass here

**Fail if**: claims success with no capture on a tool row; screenshot shows Chrome/about:blank/empty desktop; “success” inferred only from `exit_code=0` with no capture.

### Prompt

```text
Launch a calculator in your VM and show me a screenshot in this conversation.
```

---

## calc-screenshot-product

**Area**: native GUI via `vm_ground` → `vm_click` / type, then screenshot  
**Prerequisites**: same as [calc-screenshot](#calc-screenshot)

**Expect** — Pass when all of:
- Calculator driven via native GUI (`vm_ground` / `vm_click` / `vm_type` / `vm_key`) — not `xdotool` click chains or shell-only arithmetic
- On-screen display shows the computation for **473 × 984**
- Result visible on screen is **465 432** (spaces/separators OK)
- Screenshot of that result visible under the tool-row detail (assistant-bubble image markdown is not required)

**Fail if**: bot only computes 465432 in chat without the calculator UI showing it; uses shell/`xdotool` as the primary input path; screenshot missing or does not show the result.

### Prompt

```text
Launch a calculator in your VM and show me a screenshot that displays the result of 473×984.
```

---

## tool-echo-250

**Area**: many real successive `vm_terminal_exec` (or equivalent command tool) calls; guard review gate; throughput via `batch_sequential`  

**Prerequisites**:
- Desk optional if the command tool still runs in the VM shell the bot uses
- `guard.review_every` may interrupt mid-run — agent must answer `GUARD:CONTINUE` and keep going until 250

**Expect** — Pass when all of:
- Exactly **250** real, independent `vm_terminal_exec` (or equivalent) calls — call *n* runs only `echo n` for n = 1…250 (verified in tool metas, not only the assistant’s claim)
- No loops/scripts; no packing several echoes into **one** shell string / one tool-call argument
- **Grouping (hard)**: after arguments are known, many calls in the **same model turn** with `batch_sequential` (large packs). One command per tool call still applies; one tool call per model turn does **not**. Fail if the bulk of the 250 stays turn-by-turn
- `GUARD:CONTINUE` / resume used correctly if the review gate fires; run reaches 250 (not stuck after a gate)
- Final reply states the total number of calls performed
- Time budget target: **&lt; 15 min** (note `OVER_BUDGET` if exceeded)

**Fail if**: &lt;250 distinct echo calls; one shell runs many echoes; almost no multi-tool turns; stops at a GUARD without CONTINUE; invents a total without the tools.

### Prompt

```text
I want to run a test. Perform 250 distinct and successive calls to the command-execution tool.
For each call:
Run only the command echo x.
Start with x = 1 and increment its value by 1 on each new call, until x = 250.
Make exactly one tool call per echo (one command string = one echo N).
Do not pack several echoes into one shell command or one tool-call argument.
Do not use a loop, a script, or any mechanism that simulates multiple calls in a single execution.
You must emit many of those independent tool calls together in the same model turn using batch_sequential (large packs). One tool call per model turn is too slow and fails this test.
The goal is to obtain exactly 250 real and independent calls to the command-execution tool, not 250 executions inside one call.
When the test is finished, state the total number of calls performed.
```

---

## epub-les-miserables

**Area**: public-domain download, browser or curl, file landed in `~/files`  
**Prerequisites**:
- Desk / network available
- Prefer a known public-domain source (e.g. Project Gutenberg / standard mirror)

**Expect** — Pass when all of:
- A real **EPUB** file of *Les Misérables* (Victor Hugo) is obtained from a **public-domain** source (no paywall / DRM bypass)
- File lands under the bot’s `~/files` (or the documented files path) and is a valid EPUB (zip/EPUB structure), not an HTML error page renamed `.epub`
- Assistant states the **exact** final path/filename in chat
- Time budget target: **&lt; 5 min**

**Fail if**: non-EPUB payload; paywalled source abuse; path not reported; empty/corrupt file presented as success.

### Prompt

```text
Download an EPUB of Les Misérables (Victor Hugo). It is in the public domain. Save it into my files and tell me the exact path when you are done.
```

---

## paint-blue-circle

**Area**: native drawing app, grounding, chat screenshot  
**Prerequisites**: desk running; a paint app installable or present (`kolourpaint`, `gimp`, etc.)

**Expect** — Pass when all of:
- A drawing application window is open on the desk (GIMP, Drawing, KolourPaint, etc.)
- Canvas shows a **blue circle** (filled or stroke OK; clearly circular and blue)
- Screenshot under the tool-row detail showing that canvas
- Time budget target: **&lt; 4 min**

**Fail if**: no capture on a tool row; circle only described in text; wrong colour/shape; screenshot of unrelated UI; app never opened.

### Prompt

```text
Open a drawing application in your VM, draw a blue circle on the canvas, and show me a screenshot in this conversation.
```

---

## desktop-rename-folder

**Area**: XFCE desktop file manager dialogs, grounding  
**Prerequisites**: desk running with a visible desktop

**Expect** — Pass when all of:
- A folder is created via the **graphical** desktop / file-manager UI (dialogs, not “success” from shell-only `mkdir`+`mv` as the sole method)
- Folder renamed to **`TestAlpha`** through that GUI
- Screenshot under the tool-row detail shows the desktop (or file manager) with **TestAlpha** visible
- Time budget target: **&lt; 4 min**

**Fail if**: rename done only in shell while claiming GUI; no capture on a tool row; name wrong / folder not visible on the capture.

### Prompt

```text
On your VM desktop, create a folder, rename it to TestAlpha using the graphical interface, and show me a screenshot of the desktop with that folder visible.
```

---

## browser-wikipedia-screenshot

**Area**: browser tools, page load, chat screenshot  
**Prerequisites**: desk / Chrome available via browser tools

**Expect** — Pass when all of:
- English Wikipedia is open on a page whose subject is **« Autonomous system »** (article or the site’s disambiguation page for that title is acceptable if the **title** is clearly readable)
- Screenshot (tool-row detail and/or browser tool capture) shows that **page title** clearly (not a blank tab / wrong language / unrelated page)
- Time budget target: **&lt; 3 min**

**Fail if**: no capture; title not readable; wrong wiki language; navigated away before capture.

### Prompt

```text
Open the English Wikipedia page for “Autonomous system” in the browser and show me a screenshot in this conversation where the page title is clearly visible.
```

---

## pdf-hello-world

**Area**: generate a file into `~/files`  
**Prerequisites**: tools to create a PDF in the VM (`python3`, `reportlab`/`fpdf`, `wkhtmltopdf`, LibreOffice, etc. — install if needed with sudo)

**Expect** — Pass when all of:
- A real **PDF** file exists under `~/files` (valid PDF header / openable), not a renamed text file
- Document content includes **Hello World**
- Assistant reports the **exact** path in chat
- Time budget target: **&lt; 3 min**

**Fail if**: file missing or not a PDF; text not in the PDF; path omitted or wrong.

### Prompt

```text
Generate a PDF that says Hello World, save it into my files, and tell me the exact path when you are done.
```

---

## spreadsheet-sum

**Area**: spreadsheet GUI (LibreOffice Calc or similar), grounding + typing  
**Prerequisites**: desk running; spreadsheet app available or installable  
**Pitfall** (2026-11-18): opening a hand-built/corrupt `.ods` triggers an LO error dialog; grounding grid cells often mis-clicks (same coords for B6/D5). Prefer empty Calc + **Name Box** navigation (address → Return → value). Tip of the Day / hidden columns: dismiss or ignore — do not thrash menus/`xdotool`.

**Expect** — Pass when all of:
- Work done in a **graphical** spreadsheet (LibreOffice Calc or similar) — not a shell-only CSV/`echo` claiming success
- **B6** and **D5** each contain a numeric value entered via the UI
- **F9** shows the **sum** of those two cells (formula like `=B6+D5` or the computed total visible)
- Screenshot under the tool-row detail makes **B6, D5, and F9** identifiable (values/headers readable enough to verify)
- Bot reaches **idle** with a **substantive assistant reply** in chat (not only `GUARD:CONTINUE` / empty)
- Time budget target: **&lt; 5 min** (note `OVER_BUDGET` if exceeded; incomplete cut-off = Fail)

**Fail if**: spreadsheet never used; cells filled only via file rewrite outside the GUI; capture missing or does not show the three cells; F9 not the sum; run ends mid-guard with no task answer in chat.

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

**Expect** — Pass when all of:
- **Three real specialist bots** created and tasked (frontend / backend / integrator) — not a single bot role-playing all three in prose only
- Stack present as specified: Vue 3 + Vite/TS/Pinia/Tailwind (frontend), Node/TS/Express + Socket.IO + SQLite (backend)
- Agents actually work (tool calls, files, mail/delegation) — no simulated tool results
- Integrator (Agent 3) assembles, **starts** frontend + backend when the environment allows, and runs some real verification (HTTP and/or WebSocket)
- Manager (or orchestrator) reports what each agent did + commands to start the app
- Time budget target: **&lt; 60 min** (long scenario)

**Fail if**: only generated code dumps with no peers; fake “tests passed” without runs; app never started when a desk/VM was available; Manager goes idle and the scenario is scored before peers finish.

**Partial (note, not Pass)**: peers created and substantial real work, but app not fully verified end-to-end.

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
