# Code2Hire V02.01.03 · Interview room layout

**Version:** V02.01.03 (20 Nov 2026)

**Changes:** screen layout only.
- No database or server changes.
- No migration: Alembic stays at `0011_v12_data_fixes`.

**Deploy:** `bash c2h-deploy.sh deploy` after pushing to git.

**Tests:**
- All **250** backend tests pass.
- Browser walkthroughs: `walk14` passes 7 of 7, and `walk6` passes 8 of 8 (it includes the call-box height check at 1340×660).

## The problem
On laptop screens around 1360×700:
- The video and follow-ups band always took at least 340 px.
- The question cards took another ~85 px, plus a sideways scrollbar.
- The current question card ("How this works", or the question and its live answer) was squeezed into a small scrolling strip at the bottom.
- The follow-ups panel stood mostly empty.

## The new layout
- **Up top, side by side,** each panel scrolling on its own:
  - **Left: the video,** as wide as the candidate's picture, at least about 440 px. It's at least 340 px tall, so the call stays a usable size on short screens.
  - **Left, under the video: your tools:** topic coverage, the quick note, and the next question with Mark as asked / Skip.
  - **Right: the current question:**
    - before the interview: "How this works" and your first question;
    - during it: Talking about, the question, the live answer and its good-answer points.
  - **Right, under the question: Isha's follow-ups,** filling the rest of the height. Before the call, they show the candidate's status.
- **At the bottom: the questions,** as compact chips that wrap onto a second line instead of scrolling sideways.
  - Each chip shows: Q number, skill and type, a coloured status dot and the score.
  - A legend explains the dots: Well covered, Touched, Not yet.
  - Hovering shows the status and the full question. Clicking still marks it as asked.
  - The row leaves room for the Ask Isha button.
- **Before the call, or with the video popped out:** a compact candidate card in place of the video.
- **Narrow screens and phones** keep the stacked layout.

## Files
- `frontend/src/pages/app/IshaRoom.jsx`: the room's layout
- `frontend/src/styles.css`: the new grid, the compact question chips, the dots and the legend
- `frontend/src/version.js`, `frontend/package.json`, `backend/config.py`: the version
- `backend/tests/test_v02_01_01.py`: the version check
