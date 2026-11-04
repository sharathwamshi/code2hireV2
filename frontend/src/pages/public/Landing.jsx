import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Disha, Hira, Isha } from "../../components/Mascot";

const ASKS = [
  { q: "What can you do?", a: "I post jobs, shortlist applicants, run MCQ and AI interviews, and write reports with evidence." },
  { q: "Are you fair?", a: "I score against your rubric and show the quote behind every score. A person always decides." },
  { q: "Do a trick", a: "Ta-da! Now type any role and watch me build a plan in five seconds." },
  { q: "Who are your friends?", a: "Isha coaches interviewers and Disha helps candidates. Let’s watch our story!", watch: true },
];
const SCENES = [
  { cap: "Meet Priya. She needs a senior Java engineer, fast.", show: "jd", h: [70, 1], i: [112, 0], d: [-14, 0] },
  { cap: "Hira reads the job and drafts the whole hiring plan in seconds.", show: "plan", h: [70, 1], i: [112, 0], d: [-14, 0], think: true },
  { cap: "240 applicants. Hira ranks every one, with reasons, and shortlists 18.", show: "res", h: [72, 1], i: [112, 0], d: [-14, 0] },
  { cap: "Rahul from HR runs the interview. Isha quietly suggests the next question.", show: "iv", h: [90, .5], i: [70, 1], d: [-14, 0] },
  { cap: "Every candidate gets feedback and a learning path from Disha.", show: "path", h: [92, .45], i: [82, .55], d: [68, 1] },
  { cap: "One hire. Every round, with evidence. That’s Code2Hire.", show: "end", h: [24, 1], i: [48, 1], d: [72, 1] },
];
const SCENE_MS = 4200;
const BEATS = [
  { t: "We moved our order services to Kubernetes last year, and I owned the scaling setup.", tag: "+ Claim: owned the scaling setup", k: "claim", sc: 2.5, cov: [] },
  { t: "I set up the Horizontal Pod Autoscaler on CPU at 70 percent.", tag: "✓ Strong: names the autoscaler and metric", k: "good", sc: 3.3, cov: [0] },
  { t: "Later we switched to a custom metric on queue length, because CPU lagged behind traffic.", tag: "✓ Strong: explains why", k: "good", sc: 4.0, cov: [0] },
  { t: "Honestly, the load testing was done by another team.", tag: "! Check: resume says he led load testing", k: "flag", sc: 3.8, cov: [0, 2] },
  { t: "Requests and limits we set mostly by trial and error.", tag: "~ Vague: no sizing method", k: "vague", sc: 3.6, cov: [0, 1, 2] },
];
const NEXT = [
  { type: "Move on", q: "Let’s switch to messaging. What delivery guarantee does Kafka give you?", why: "Messaging is not covered yet" },
  { type: "Move on", q: "Let’s switch to messaging. What delivery guarantee does Kafka give you?", why: "Messaging is not covered yet" },
  { type: "Go deeper", q: "What queue length triggered a scale-up, and how did you choose it?", why: "Strong answer: test real depth" },
  { type: "Go deeper", q: "What queue length triggered a scale-up, and how did you choose it?", why: "Strong answer: test real depth" },
  { type: "Clarify", q: "Your resume says you led load testing. What exactly was your part?", why: "Contradicts the resume" },
  { type: "Clarify", q: "Your resume says you led load testing. What exactly was your part?", why: "Contradicts the resume, and sizing was vague" },
];
const RUB = ["Autoscaler and the metric used", "Sizing of requests and limits", "Tested under real load"];
const EVID = [
  { name: "Java and JVM", score: 4.6, quote: "In my last project the latency spike was an N+1 query from a new JPA relation; we caught it in the slow query log.", time: "Answer at 04:30", rubric: "diagnoses from evidence, not guesses" },
  { name: "Databases and SQL", score: 4.5, quote: "I’d read the EXPLAIN plan, add a composite index on customer and date, then consider partitioning by month.", time: "Answer at 14:05", rubric: "reads the plan; right index order" },
  { name: "System design", score: 4.0, quote: "Update the cache when the price service publishes a change, with a one-minute TTL as a safety net.", time: "Answer at 22:05", rubric: "invalidation plus safety net" },
  { name: "Messaging", score: 3.2, quote: "Kafka is at least once, so messages can come again; we just made sure processing was fast.", time: "Answer at 19:30", rubric: "duplicates not handled: partial" },
];
const SEGS = [
  { label: "Employers", problem: "Senior interviewers are booked for weeks, so good candidates wait and drop out.", how: "Hira runs the early rounds; Isha lets any trained team member run the F2F with expert questions.", get: "Interviews in days, consistent scoring across interviewers, and a hiring packet for every finalist." },
  { label: "Staffing agencies", problem: "Clients reject candidates the agency could not screen deeply enough.", how: "White-label AI interviews and Isha-coached screens under your brand, with client-ready reports.", get: "Better shortlists, branded reports with salary hidden, and a client view of only what you share." },
  { label: "Campus", problem: "Thousands of freshers, a handful of panelists and a two-week window.", how: "Bulk MCQ and AI interviews, prep tracks with Disha before the drive, and templates per role.", get: "A ranked shortlist with evidence, and students who arrive prepared." },
  { label: "GCCs", problem: "Hiring at scale across many teams, each with its own bar.", how: "Team templates, policies, panels with calibration reports, and full audit.", get: "One standard across teams, and data on which interviewers and questions work." },
];
const ROLES = [
  { label: "Recruiter", before: ["A spreadsheet of 240 resumes", "14 emails to find one interview slot", "Interviewer asks: “what should I ask?”", "Chasing feedback for five days"], after: ["A ranked shortlist, with reasons", "Candidates book their own slots", "Isha plans every question", "Scorecards in on the same day"] },
  { label: "Interviewer", before: ["Reads the JD five minutes before", "Asks the same five questions to everyone", "Notes on paper, lost by Friday", "Can’t judge a Kafka answer"], after: ["Isha’s brief: 6 areas, 2 gaps to probe", "Follow-ups based on what was just said", "A tagged transcript, saved", "Rubric ticked live as they answer"] },
  { label: "Candidate", before: ["Applies to 50 jobs, hears from 2", "Never learns what went wrong", "Prepares from random videos", "Takes the same test for every company"], after: ["Matched on verified skills", "Feedback after every round", "Mock interviews with Disha", "Badges that can waive repeat tests"] },
  { label: "Manager", before: ["Decides on gut feel", "No idea which interviewer is strict", "Hiring status lives in someone’s head", "Agencies send 40 CVs at once"], after: ["A hiring packet with evidence", "Interviewer calibration reports", "A live funnel for every job", "Client-ready shortlists"] },
];
const STATIONS = [
  { day: "Day 0", name: "Post the job", who: "Hira", title: "Paste a JD. Hira drafts the rest.", body: "Skills, levels, rounds, pass rules and first questions, in seconds. Publish it public, private or internal.", ui: [["Skills found", "5 must-haves"], ["Template", "MCQ → AI → F2F"], ["Visibility", "Public"]] },
  { day: "Day 1", name: "Shortlist", who: "Hira", title: "Every applicant read and ranked.", body: "Each resume is scored against the JD with plain reasons. Verified badges are flagged. You decide who moves on.", ui: [["Applicants", "240"], ["Shortlisted", "18"], ["Top reason", "5 of 7 must-haves"]] },
  { day: "Day 2", name: "MCQ screen", who: "Hira", title: "A fair skill test, scored instantly.", body: "Questions from your JD, integrity checks on, and pass rules that advance or hold candidates automatically.", ui: [["Java", "86%"], ["SQL", "79%"], ["Integrity", "All clear"]] },
  { day: "Day 3", name: "AI interview", who: "Hira", title: "A real conversation, any time of day.", body: "Hira asks, listens and follows up by voice. The report links every score to the answer behind it.", ui: [["Overall", "4.4 / 5"], ["Strongest", "Databases"], ["To probe", "Kafka"]] },
  { day: "Day 5", name: "F2F with Isha", who: "Isha", title: "Any interviewer, expert questions.", body: "Isha reads every sentence, tags claims and gaps, and suggests the next question. The interviewer stays in charge.", ui: [["Tag", "Check: contradicts resume"], ["Suggests", "Clarify load testing"], ["Coverage", "4 of 5 areas"]] },
  { day: "Day 6", name: "Decision", who: "Manager", title: "One page, every round, one decision.", body: "The hiring packet shows MCQ, AI interview and F2F side by side, with disagreements flagged. A named person decides.", ui: [["Rounds", "3 of 3 done"], ["Disagreement", "None"], ["Verdict", "Proceed · Priya S"]] },
  { day: "Day 7", name: "Offer and feedback", who: "Disha", title: "The offer goes out. Everyone learns.", body: "The chosen candidate gets an offer; everyone else gets real feedback and a learning path from Disha.", ui: [["Offer", "Sent"], ["Feedback", "Shared with 17"], ["Learning paths", "Started by 9"]] },
];
const WHO = { Hira: "#2F6FED", Isha: "#B45309", Manager: "#5B3FFF", Disha: "#E07B1A" };
const FAQ = [
  ["Does the AI decide who gets hired?", "No. Hira and Isha score and suggest; a named person on your team makes every decision."],
  ["How is a score calculated?", "Against your rubric, answer by answer. Every score links to the exact quote and rubric line."],
  ["Does the candidate know Isha is helping?", "Candidates are told the interview is recorded and AI-assisted and give consent. Isha's panel is visible only to the interviewer."],
  ["How do you handle cheating?", "Clear rules, warnings that explain themselves, and an automatic pause for your review. You set the rules per round."],
  ["Which AI and voice do you use?", "Anthropic Claude does all the reasoning. Azure Speech gives Hira a natural voice, with Indian English, Hindi, Tamil, Telugu and more to choose from."],
  ["Where is our data stored?", "In India, with retention periods you choose. Candidates can download or delete their own data."],
  ["Is it free for candidates?", "Yes. Practice, skill checks and applying are free. Some company certifications may have a fee."],
];

const CSS = `
.lp{font-family:Inter,system-ui,sans-serif;color:#14213D;background:#F4F2EC;overflow-x:hidden}
.lp a{text-decoration:none}
.lp .wrap{max-width:1200px;margin:0 auto;padding:0 24px}
.lp nav.lp-top{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:20px;padding:14px 28px;background:rgba(18,16,48,.82);backdrop-filter:blur(10px);color:#fff}
.lp nav.lp-top a{color:#D9D4FF;font-weight:600;font-size:14px}.lp nav.lp-top a:hover{color:#fff}
.lp .hero{position:relative;background:radial-gradient(900px 500px at 15% 0%,#3B2BB8 0%,transparent 60%),radial-gradient(800px 500px at 100% 30%,#0E6F8C 0%,transparent 55%),linear-gradient(160deg,#120F3A,#1B1458 60%,#0D2346);color:#fff;padding:56px 0 90px;overflow:hidden}
.lp .blob{position:absolute;border-radius:50%;filter:blur(50px);opacity:.45;animation:lpblob 14s ease-in-out infinite}
@keyframes lpblob{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(40px,-30px) scale(1.08)}66%{transform:translate(-30px,20px) scale(.95)}}
.lp .hero h1{font-size:clamp(40px,6vw,74px);font-weight:900;letter-spacing:-.04em;line-height:1.02;color:#fff}
.lp .uline{background:linear-gradient(transparent 62%,#FFC94A 62%);color:#fff;padding:0 4px;-webkit-box-decoration-break:clone;box-decoration-break:clone;background-size:100% 100%}
.lp .hero-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:40px;align-items:center}
.lp .door{display:inline-flex;background:rgba(255,255,255,.1);border-radius:12px;padding:4px;gap:4px}
.lp .door button{border:0;background:none;color:#D9D4FF;font-weight:700;padding:9px 16px;border-radius:9px;cursor:pointer}
.lp .door button.on{background:#fff;color:#1B1458}
.lp .try{display:flex;align-items:stretch;gap:8px;background:#fff;border-radius:14px;padding:6px;box-shadow:0 20px 50px rgba(0,0,0,.3)}
.lp .try input{flex:1;border:0;outline:none;padding:0 12px;font-size:16px;color:#14213D;min-width:0;background:none;height:48px}
.lp .try .cta{height:48px;display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;flex:none;padding:0 20px}
@media (max-width:520px){.lp .try{flex-direction:column}.lp .try input{height:44px}.lp .try .cta{width:100%}}
.lp .cta{border:0;border-radius:11px;padding:12px 18px;font-weight:800;cursor:pointer;font-size:15px}
.lp .cta.gold{background:#FFC94A;color:#14213D}.lp .cta.dark{background:#14213D;color:#fff}.lp .cta.white{background:#fff;color:#14213D}.lp .cta.ghost{background:rgba(255,255,255,.12);color:#fff}
.lp .stage{position:relative;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);border-radius:22px;min-height:440px;padding:22px;backdrop-filter:blur(4px)}
.lp .plan-row{display:grid;grid-template-columns:110px 1fr;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.1);animation:lppop .45s ease-out both}
@keyframes lppop{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.lp .bubble{background:#fff;color:#14213D;border-radius:14px;padding:10px 14px;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.2);max-width:300px;animation:lppop .3s}
.lp .chips button{border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.08);color:#fff;border-radius:99px;padding:6px 12px;font-weight:600;cursor:pointer;font-size:13px}
.lp .chips button:hover{background:rgba(255,255,255,.18)}
.lp .film{position:relative;height:330px;border-radius:16px;background:linear-gradient(180deg,#221B66,#141046);overflow:hidden}
.lp .actor{position:absolute;top:110px;transition:left 1s cubic-bezier(.5,0,.2,1),opacity .8s,transform 1s}
.lp .prop{position:absolute;left:6%;top:24px;width:56%;background:#fff;color:#14213D;border-radius:12px;padding:12px;font-size:13px;box-shadow:0 10px 30px rgba(0,0,0,.3);animation:lppop .5s}
.lp .scrub{display:flex;align-items:center;gap:10px;margin-top:10px}
.lp .scrub .track{flex:1;height:6px;background:rgba(255,255,255,.15);border-radius:6px;position:relative;cursor:pointer}
.lp .scrub .track i{position:absolute;inset:0 auto 0 0;background:#FFC94A;border-radius:6px}
.lp .marquee{background:#14213D;color:#fff;overflow:hidden;white-space:nowrap;padding:14px 0}
.lp .marquee > div{display:inline-flex;gap:40px;animation:lpmq 38s linear infinite;padding-left:40px}
@keyframes lpmq{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.lp .board{border-radius:28px;margin:22px auto;max-width:1240px;padding:64px 48px;position:relative;overflow:hidden}
.lp .board.white{background:#fff}.lp .board.black{background:#0E0E14;color:#fff}.lp .board.violet{background:linear-gradient(140deg,#5B3FFF,#3A23C9);color:#fff}
.lp .board.gold{background:#FFC94A}.lp .board.mint{background:#DDF5EC}.lp .board.peach{background:#FFE9D6}.lp .board.sky{background:#E3EDFF}
.lp .kicker{font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;opacity:.7}
.lp h2.big{font-size:clamp(30px,4.2vw,52px);font-weight:900;letter-spacing:-.035em;line-height:1.05;margin:8px 0 18px}
.lp .reveal{opacity:0;transform:translateY(24px);transition:opacity .7s,transform .7s}.lp .reveal.in{opacity:1;transform:none}
.lp .tabs2{display:inline-flex;gap:6px;flex-wrap:wrap}.lp .tabs2 button{border:1.5px solid currentColor;background:none;border-radius:99px;padding:7px 14px;font-weight:700;cursor:pointer;color:inherit;opacity:.65}
.lp .tabs2 button.on{opacity:1;background:#14213D;color:#fff;border-color:#14213D}
.lp .board.black .tabs2 button.on{background:#fff;color:#0E0E14;border-color:#fff}
.lp .xf{position:relative;margin-top:26px;user-select:none}
.lp .xf-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:12px}
.lp .xf-card{border-radius:14px;padding:16px 18px;font-weight:650;font-size:16px;transition:all .45s}
.lp .xf-card.before{background:#1E1E2A;color:#BFC3D6}.lp .xf-card.after{background:#12382A;color:#B9F1D2}
.lp .xf-card.dim{opacity:.28;filter:grayscale(1)}.lp .xf-card.lit{box-shadow:0 0 0 2px #8EE3B5}
.lp .slider{position:relative;height:56px;margin:12px 0 22px;background:linear-gradient(90deg,#12382A,#1E1E2A);border-radius:99px;cursor:grab}
.lp .slider .knob{position:absolute;top:-14px;width:84px;height:84px;margin-left:-42px;touch-action:none;cursor:grab}
.lp .flow{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:20px}
.lp .flow button{border:0;background:#fff;border-radius:14px;padding:12px 10px;text-align:left;cursor:pointer;transition:all .3s;color:#14213D}
.lp .flow button.on{background:#14213D;color:#fff;transform:translateY(-4px);box-shadow:0 12px 30px rgba(20,33,61,.25)}
.lp .screen{background:#14213D;color:#fff;border-radius:18px;padding:22px;margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:20px;animation:lppop .4s}
.lp .agents{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.lp .agent-card{border-radius:22px;padding:26px;position:relative;min-height:340px;display:flex;flex-direction:column;gap:12px;transition:transform .3s}
.lp .agent-card:hover{transform:translateY(-6px) rotate(-.5deg)}
.lp .live{display:grid;grid-template-columns:1.3fr 1fr;gap:18px;margin-top:20px}
.lp .panel{background:#16162A;border-radius:16px;padding:18px}
.lp .tag{display:inline-block;border-radius:8px;padding:3px 8px;font-size:12px;font-weight:700;margin-top:4px}
.lp .tag.claim{background:#1C2A4F;color:#A9C4FF}.lp .tag.good{background:#12382A;color:#8EE3B5}.lp .tag.flag{background:#3A1A22;color:#FFB4B4}.lp .tag.vague{background:#3A2E10;color:#FFD27A}
.lp .rounds{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:20px}
.lp .round{border-radius:18px;padding:20px;min-height:200px;display:flex;flex-direction:column;gap:10px}
.lp .pill{display:inline-flex;align-items:center;gap:6px;border-radius:99px;padding:6px 12px;font-weight:700;font-size:13px;background:rgba(20,33,61,.08)}
.lp .ev{display:grid;grid-template-columns:1fr 1.2fr;gap:18px;margin-top:20px}
.lp .ev button{display:flex;justify-content:space-between;width:100%;border:0;border-radius:12px;padding:14px 16px;margin-bottom:8px;cursor:pointer;font-weight:700;background:#F4F2EC;color:#14213D;font-size:15px}
.lp .ev button.on{background:#14213D;color:#fff}
.lp .price{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:20px}
.lp .price > div{background:#fff;border-radius:18px;padding:22px;display:flex;flex-direction:column;gap:10px;border:1px solid #E6E2D6}
.lp details{background:#fff;border-radius:14px;padding:16px 18px;margin-bottom:10px}.lp summary{font-weight:750;font-size:16px;cursor:pointer}
.lp footer{background:#0E0E14;color:#9BA1B5;padding:48px 0 30px;margin-top:22px}
.lp footer a{color:#C9CDDA;display:block;margin:6px 0;font-size:14px}
@media(max-width:980px){.lp .hero-grid,.lp .live,.lp .ev,.lp .screen{grid-template-columns:1fr}.lp .agents,.lp .rounds,.lp .price{grid-template-columns:1fr 1fr}.lp .flow{grid-template-columns:repeat(4,1fr)}.lp .board{padding:40px 22px;border-radius:20px;margin:14px}.lp nav.lp-top .hide-m{display:none}}
@media(max-width:620px){.lp .agents,.lp .rounds,.lp .price,.lp .xf-row{grid-template-columns:1fr}.lp .flow{grid-template-columns:repeat(2,1fr)}}
@media (prefers-reduced-motion: reduce){.lp *{animation:none!important;transition:none!important}}
`;

function useReveal() {
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && e.target.classList.add("in")), { threshold: .15 });
    document.querySelectorAll(".lp .reveal").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

function Hero() {
  const nav = useNavigate();
  const [door, setDoor] = useState("hire");
  const [mode, setMode] = useState("try");
  const [role, setRole] = useState("Senior Java Engineer");
  const [plan, setPlan] = useState(null);
  const [shown, setShown] = useState(0);
  const [ask, setAsk] = useState(-1);
  const [mood, setMood] = useState("idle");
  const [goal, setGoal] = useState("Backend developer");
  const [scene, setScene] = useState(0);
  const [ms, setMs] = useState(0);
  const [playing, setPlaying] = useState(true);
  useEffect(() => {
    if (!plan || shown >= plan.length) return;
    const t = setTimeout(() => { setShown(shown + 1); if (shown + 1 === plan.length) { setMood("happy"); setTimeout(() => setMood("idle"), 1400); } }, 420);
    return () => clearTimeout(t);
  }, [plan, shown]);
  useEffect(() => {
    if (mode !== "watch" || !playing) return;
    const t = setInterval(() => setMs((m) => {
      const n = m + 100;
      if (n >= SCENES.length * SCENE_MS) { setPlaying(false); return SCENES.length * SCENE_MS - 1; }
      setScene(Math.floor(n / SCENE_MS));
      return n;
    }), 100);
    return () => clearInterval(t);
  }, [mode, playing]);
  const [planFor, setPlanFor] = useState("");
  const [planBusy, setPlanBusy] = useState(false);
  // Hira drafts a plan for ANY title (not three fixed templates). If the server can't be reached, she says so.
  const build = async (title = role) => {
    const t = (title || "").trim();
    if (t.length < 2 || planBusy) return;
    setMood("think"); setPlan(null); setShown(0); setPlanBusy(true); setPlanFor(t);
    try {
      const p = await api.post("/public/hiring-plan", { title: t });
      const rows = [];
      if (p.skills?.length) rows.push(["Skills", p.skills.map((s) => `${s.name} L${s.level}${s.must ? "" : " (nice to have)"}`).join(" · ")]);
      rows.push(["Level", p.level]);
      if (p.rounds?.length) rows.push(["Rounds", p.rounds.map((r) => r.name).join(" → ")]);
      if (p.questions?.[0]) rows.push(["First question", p.questions[0]]);
      setPlanFor(p.title || t); setPlan(rows); setMood("talk");
    } catch (e) {
      setPlan([["Hmm", e.status === 429 ? e.message : "I couldn't draft that just now. Please try again in a moment."]]); setMood("idle");
    } finally { setPlanBusy(false); }
  };
  const s = SCENES[scene];
  const total = SCENES.length * SCENE_MS;
  const seek = (e) => { const r = e.currentTarget.getBoundingClientRect(); const v = Math.max(0, Math.min(total - 1, ((e.clientX - r.left) / r.width) * total)); setMs(v); setScene(Math.floor(v / SCENE_MS)); };
  return (
    <section className="hero">
      <div className="blob" style={{ width: 380, height: 380, background: "#7A5CFF", left: -80, top: 40 }} />
      <div className="blob" style={{ width: 300, height: 300, background: "#1FB6C9", right: -60, top: 220, animationDelay: "-5s" }} />
      <div className="wrap hero-grid" style={{ position: "relative" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <span className="kicker" style={{ color: "#FFC94A" }}>AI agents for every side of hiring</span>
          <h1>Every interview,<br /><span className="uline">expert-level.</span></h1>
          <p style={{ fontSize: 19, color: "#D9D4FF", maxWidth: 520 }}>Hira screens and interviews. Isha coaches your interviewers live. Disha helps candidates prove their skills. One platform, every round.</p>
          <div className="door" role="tablist"><button className={door === "hire" ? "on" : ""} onClick={() => setDoor("hire")}>I'm hiring</button><button className={door === "cand" ? "on" : ""} onClick={() => setDoor("cand")}>I'm a candidate</button></div>
          {door === "hire" ? (
            <>
              <form className="try" onSubmit={(e) => { e.preventDefault(); setMode("try"); build(); }}>
                <input aria-label="Job title" value={role} maxLength={120} onChange={(e) => setRole(e.target.value)} placeholder="Job title, e.g. Cloud Architect" />
                <button className="cta gold" type="submit" disabled={planBusy || role.trim().length < 2} style={planBusy || role.trim().length < 2 ? { opacity: .6, cursor: "not-allowed" } : undefined}>{planBusy ? "Drafting…" : "Build my plan"}</button>
              </form>
              <div className="chips" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}><span style={{ color: "#B9B2F0", fontSize: 13 }}>Try:</span>
                {["Senior Java Engineer", "Inside Sales Associate", "Data Analyst"].map((r) => <button key={r} onClick={() => { setRole(r); setMode("try"); build(r); }}>{r}</button>)}</div>
            </>
          ) : (
            <>
              <form className="try" onSubmit={(e) => { e.preventDefault(); nav("/signup"); }}>
                <input aria-label="Role you are preparing for" value={goal} onChange={(e) => setGoal(e.target.value)} />
                <button className="cta gold" type="submit">Show my path</button>
              </form>
              <span style={{ color: "#B9B2F0", fontSize: 13 }}>Free for candidates. Practice results stay private.</span>
            </>
          )}
          <div style={{ color: "#9F98DA", fontSize: 13 }}>No credit card · Data stored in India · A person makes every final decision</div>
        </div>
        <div className="stage">
          <div className="row" style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            <button className={"cta " + (mode === "try" ? "white" : "ghost")} style={{ padding: "8px 14px", fontSize: 13 }} onClick={() => setMode("try")}>Try it</button>
            <button className={"cta " + (mode === "watch" ? "white" : "ghost")} style={{ padding: "8px 14px", fontSize: 13 }} onClick={() => { setMode("watch"); setMs(0); setScene(0); setPlaying(true); }}>▶ Watch the story</button>
          </div>
          {mode === "try" ? (
            door === "hire" ? (
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "start" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 6 }}>Hira's hiring plan{plan && planFor ? `: ${planFor}` : ""}</div>
                  {!plan && <p style={{ color: "#C9C3F5" }}>{planBusy ? "Hira is drafting your plan…" : "Type a role on the left. Hira drafts the skills, levels, rounds and first questions here in about five seconds."}</p>}
                  {plan && plan.slice(0, shown).map(([k, v]) => <div key={k} className="plan-row"><b style={{ color: "#FFC94A", fontSize: 13 }}>{k}</b><span>{v}</span></div>)}
                  {plan && shown >= plan.length && <div style={{ display: "flex", gap: 8, marginTop: 14 }}><Link className="cta gold" to="/login">Save this plan, start free</Link><a className="cta ghost" href="#cta">Book a demo</a></div>}
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, width: 120, padding: "6px 4px", overflow: "visible" }}>
                  <Hira size={104} mood={mood} onClick={() => setAsk((ask + 1) % ASKS.length)} />
                  {ask >= 0 && <div className="bubble" style={{ fontSize: 13 }}>{ASKS[ask].a}</div>}
                </div>
                <div className="chips" style={{ gridColumn: "1 / -1", display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {ASKS.map((a, i) => <button key={a.q} onClick={() => { setAsk(i); setMood("talk"); setTimeout(() => setMood("idle"), 1600); if (a.watch) setTimeout(() => { setMode("watch"); setMs(0); setScene(0); setPlaying(true); }, 1200); }}>{a.q}</button>)}
                </div>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 120px", gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 800, fontSize: 18 }}>Disha's path for you: {goal}</div>
                  {[["Find your level", "Short skill checks show where you stand, L1 to L5."], ["Close the gaps", `A learning path and mock interviews for ${goal}.`], ["Prove it and apply", "Verified badges, then jobs that match them."]].map(([t, d], i) =>
                    <div key={t} className="plan-row" style={{ animationDelay: i * .2 + "s" }}><b style={{ color: "#FFC94A" }}>Step {i + 1}</b><span><b>{t}.</b> {d}</span></div>)}
                  <Link className="cta gold" to="/signup" style={{ display: "inline-block", marginTop: 14 }}>Practise an interview free</Link>
                </div>
                <Disha size={110} mood="happy" />
              </div>
            )
          ) : (
            <div>
              <div className="film">
                <div className="actor" style={{ left: s.h[0] + "%", opacity: s.h[1], transform: `scale(${s.h[1] < 1 ? .6 : 1})` }}><Hira size={110} mood={s.think ? "think" : "talk"} /></div>
                <div className="actor" style={{ left: s.i[0] + "%", opacity: s.i[1] }}><Isha size={100} mood="talk" /></div>
                <div className="actor" style={{ left: s.d[0] + "%", opacity: s.d[1] }}><Disha size={100} mood="talk" /></div>
                {s.show === "jd" && <div className="prop" key="jd"><b>JOB DESCRIPTION</b><div style={{ fontSize: 16, fontWeight: 800 }}>Senior Java Engineer</div><div>Java · Spring · SQL · Kubernetes</div></div>}
                {s.show === "plan" && <div className="prop" key="plan"><b>Hira's plan</b><div>Skills: Java L4 · Spring L3 · SQL L3</div><div>MCQ → AI interview → F2F + Isha</div><div>3 first questions drafted</div></div>}
                {s.show === "res" && <div className="prop" key="res"><b>Aarav M. · 91% match</b><div>5 of 7 must-haves</div><div style={{ fontSize: 20, fontWeight: 900 }}>240 → 18 shortlisted</div></div>}
                {s.show === "iv" && <div className="prop" key="iv"><b>Rahul · HR ↔ Aarav</b><div style={{ background: "#FFF4D6", borderRadius: 8, padding: 6, marginTop: 4 }}>Isha: “Ask what his part in load testing was.”</div><div>✓ Strong  ! Check</div></div>}
                {s.show === "path" && <div className="prop" key="path"><b>Feedback: strong on databases</b><div>Path: Kafka for Backend · 4 h</div><div>Badge earned: Java L4</div></div>}
                {s.show === "end" && <div className="prop" key="end" style={{ textAlign: "center", left: "20%", width: "60%" }}><div style={{ fontSize: 26, fontWeight: 900 }}>Code<span style={{ color: "#5B3FFF" }}>2</span>Hire</div><div>Every interview, expert-level.</div></div>}
                <div style={{ position: "absolute", left: 16, right: 16, bottom: 14, background: "rgba(0,0,0,.55)", borderRadius: 10, padding: "8px 12px", fontWeight: 650 }}>{s.cap}</div>
              </div>
              <div className="scrub">
                <button className="cta ghost" style={{ padding: "6px 12px" }} aria-label={playing ? "Pause" : "Play"} onClick={() => { if (!playing && ms >= total - 1) { setMs(0); setScene(0); } setPlaying(!playing); }}>{playing ? "❚❚" : "▶"}</button>
                <div className="track" onClick={seek} role="slider" aria-label="Story position" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(100 * ms / total)}><i style={{ width: (100 * ms / total) + "%" }} /></div>
                <span style={{ fontSize: 12, color: "#C9C3F5" }}>{scene + 1} / {SCENES.length}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function Transformation() {
  const [role, setRole] = useState(0);
  const [cmp, setCmp] = useState(100);
  const [drag, setDrag] = useState(false);
  const ref = useRef();
  const auto = useRef(true);
  useEffect(() => {
    // Plays once on its own so the fixes are visible without dragging; any touch hands control to the reader.
    if (!auto.current) return;
    let v = 100;
    const t = setInterval(() => { if (!auto.current) return clearInterval(t); v -= 2; setCmp(v); if (v <= 0) clearInterval(t); }, 40);
    return () => clearInterval(t);
  }, [role]);
  const move = (x) => { const r = ref.current.getBoundingClientRect(); setCmp(Math.max(0, Math.min(100, ((x - r.left) / r.width) * 100))); };
  const R = ROLES[role];
  const flipped = R.before.map((_, i) => cmp <= 100 - ((i + 1) * 100) / (R.before.length + 1));
  return (
    <section className="board black" aria-label="Before and after">
      <div className="kicker" style={{ color: "#FFC94A" }}>The transformation</div>
      <h2 className="big reveal">Drag Hira across. Watch hiring change.</h2>
      <div className="tabs2">{ROLES.map((r, i) => <button key={r.label} className={i === role ? "on" : ""} onClick={() => { setRole(i); auto.current = true; }}>{r.label}</button>)}</div>
      <div className="slider" ref={ref}
        onPointerDown={(e) => { auto.current = false; setDrag(true); move(e.clientX); e.currentTarget.setPointerCapture(e.pointerId); }}
        onPointerMove={(e) => drag && move(e.clientX)} onPointerUp={() => setDrag(false)}
        onKeyDown={(e) => { auto.current = false; if (e.key === "ArrowLeft") setCmp(Math.max(0, cmp - 10)); if (e.key === "ArrowRight") setCmp(Math.min(100, cmp + 10)); }}
        tabIndex={0} role="slider" aria-label="Before and after" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(100 - cmp)}>
        <div style={{ position: "absolute", left: 20, top: 17, color: "#8EE3B5", fontWeight: 800, fontSize: 13 }}>WITH CODE2HIRE</div>
        <div style={{ position: "absolute", right: 20, top: 17, color: "#BFC3D6", fontWeight: 800, fontSize: 13 }}>TODAY</div>
        <div className="knob" style={{ left: cmp + "%" }}><Hira size={84} mood={drag ? "talk" : "idle"} /></div>
      </div>
      <div className="xf">
        <div className="xf-row" style={{ fontWeight: 800, opacity: .6, fontSize: 13 }}><span>TODAY</span><span>WITH CODE2HIRE</span></div>
        {R.before.map((b, i) => (
          <div className="xf-row" key={b}>
            <div className={"xf-card before " + (flipped[i] ? "dim" : "")}>✗ {b}</div>
            <div className={"xf-card after " + (flipped[i] ? "lit" : "dim")}>✓ {R.after[i]}</div>
          </div>
        ))}
      </div>
      <p style={{ color: "#9BA1B5" }}>Drag Hira from right to left, or use the arrow keys: each problem flips into how Code2Hire solves it. Switch roles to see what changes for each person.</p>
    </section>
  );
}

function Flow() {
  const [fs, setFs] = useState(0);
  const [on, setOn] = useState(true);
  useEffect(() => { if (!on) return; const t = setInterval(() => setFs((x) => (x + 1) % STATIONS.length), 3200); return () => clearInterval(t); }, [on]);
  const st = STATIONS[fs];
  const M = st.who === "Isha" ? Isha : st.who === "Disha" ? Disha : Hira;
  return (
    <section className="board white" aria-label="How a hire flows">
      <div className="kicker">How it flows</div>
      <h2 className="big reveal">From job post to offer, with an agent at every step.</h2>
      <div className="flow">{STATIONS.map((s, i) => (
        <button key={s.name} className={i === fs ? "on" : ""} onClick={() => { setFs(i); setOn(false); }}>
          <div style={{ fontSize: 11, fontWeight: 800, opacity: .6 }}>{s.day}</div><div style={{ fontWeight: 800 }}>{s.name}</div>
          <div style={{ fontSize: 12, fontWeight: 700, color: i === fs ? "#FFC94A" : WHO[s.who] }}>{s.who}</div>
        </button>
      ))}</div>
      <div className="screen" key={fs}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <M size={70} mood="talk" />
          <h3 style={{ fontSize: 24, color: "#fff" }}>{st.title}</h3><p style={{ color: "#C9CDDA" }}>{st.body}</p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="kicker" style={{ color: "#9BA1B5" }}>On screen</div>
          {st.ui.map(([k, v]) => <div key={k} style={{ display: "flex", justifyContent: "space-between", background: "rgba(255,255,255,.07)", borderRadius: 10, padding: "12px 14px" }}><span style={{ color: "#9BA1B5" }}>{k}</span><b style={{ color: "#FFC94A" }}>{v}</b></div>)}
          <button className="cta ghost" style={{ alignSelf: "flex-start", fontSize: 13 }} onClick={() => setOn(!on)}>{on ? "❚❚ Pause tour" : "▶ Play tour"}</button>
        </div>
      </div>
      <p style={{ color: "#5B6478", marginTop: 12, fontSize: 13 }}>Example timeline. You choose the rounds, their order and the pass rules for every job.</p>
    </section>
  );
}

function Agents() {
  const [hello, setHello] = useState({});
  const cards = [
    ["Hira", "Recruiter agent", "#E3EDFF", Hira, "Drafts jobs, shortlists with reasons, runs MCQ and voice AI interviews, writes evidence-linked reports, answers “Ask Hira”.", "Hi! Give me a JD and a coffee. I’ll do the rest."],
    ["Isha", "Live interview copilot", "#FFF3D1", Isha, "Listens to every sentence, tags claims and gaps, keeps the rubric ticked and suggests the next best question, privately.", "I’ll whisper the right question. You stay in charge."],
    ["Disha", "Candidate agent", "#FFEEDB", Disha, "Finds the candidate’s level, builds learning paths and mock interviews, turns feedback into next steps and matches on verified skills.", "Every “no” comes with a path forward. Let’s grow."],
  ];
  return (
    <section className="board" style={{ background: "#F4F2EC" }} aria-label="Meet your agents">
      <div className="kicker">Meet your agents</div>
      <h2 className="big reveal">Three agents. One for each side of hiring.</h2>
      <p style={{ marginBottom: 20, color: "#5B6478" }}>Click a mascot to say hello.</p>
      <div className="agents">{cards.map(([n, r, bg, M, d, hi]) => (
        <div key={n} className="agent-card" style={{ background: bg }}>
          <M size={110} mood={hello[n] ? "happy" : "idle"} onClick={() => setHello({ ...hello, [n]: !hello[n] })} />
          <div><h3 style={{ fontSize: 28, fontWeight: 900 }}>{n}</h3><div style={{ fontWeight: 700, color: WHO[n] }}>{r}</div></div>
          <p>{d}</p>
          {hello[n] && <div className="bubble" style={{ alignSelf: "flex-start" }}>{hi}</div>}
        </div>
      ))}</div>
    </section>
  );
}

function LiveRoom() {
  const [beat, setBeat] = useState(2);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { if (!playing) return; const t = setInterval(() => setBeat((b) => { if (b >= 5) { setPlaying(false); return 5; } return b + 1; }), 1800); return () => clearInterval(t); }, [playing]);
  const said = BEATS.slice(0, beat);
  const score = beat ? BEATS[beat - 1].sc : 0;
  const cov = beat ? BEATS[beat - 1].cov : [];
  const nx = NEXT[beat];
  return (
    <section className="board black" aria-label="The live room">
      <div className="kicker" style={{ color: "#FFC94A" }}>Isha · live interview copilot</div>
      <h2 className="big reveal">Your HR lead runs a senior Java interview. Isha makes sure nothing is missed.</h2>
      <div className="live">
        <div className="panel">
          <div style={{ color: "#9BA1B5", fontSize: 13, marginBottom: 8 }}><b style={{ color: "#fff" }}>Interviewer:</b> You led the Kubernetes migration. How did you decide when pods should scale up?</div>
          <div style={{ minHeight: 260, display: "flex", flexDirection: "column", gap: 10 }}>
            {!said.length && <span style={{ color: "#9BA1B5" }}>Press Play or drag the slider to watch the answer arrive.</span>}
            {said.map((b, i) => <div key={i} style={{ animation: "lppop .35s" }}><div>“{b.t}”</div><span className={"tag " + b.k}>{b.tag}</span></div>)}
          </div>
          <div className="scrub">
            <button className="cta ghost" style={{ padding: "6px 12px" }} onClick={() => { if (beat >= 5) setBeat(0); setPlaying(!playing); }}>{playing ? "❚❚" : "▶"}</button>
            <input type="range" min={0} max={5} value={beat} onChange={(e) => { setPlaying(false); setBeat(+e.target.value); }} style={{ flex: 1, accentColor: "#FFC94A" }} aria-label="Scrub through the answer" />
            <span style={{ fontSize: 12, color: "#9BA1B5" }}>Sentence {beat} of 5</span>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}><Isha size={54} mood={playing ? "talk" : "idle"} /><div><div style={{ color: "#9BA1B5", fontSize: 12, fontWeight: 700 }}>ANSWER SCORE, LIVE</div><div style={{ fontSize: 34, fontWeight: 900, color: "#FFC94A" }}>{score ? score.toFixed(1) : "—"}<span style={{ fontSize: 16, color: "#9BA1B5" }}> / 5</span></div></div></div>
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>{RUB.map((r, i) => <div key={r} style={{ display: "flex", gap: 8, color: cov.includes(i) ? "#8EE3B5" : "#6C7290" }}>{cov.includes(i) ? "●" : "○"} {r}</div>)}</div>
          </div>
          {nx && <div className="panel" key={beat} style={{ border: "1px solid #FFC94A", animation: "lppop .35s" }}>
            <div style={{ color: "#FFC94A", fontSize: 12, fontWeight: 800 }}>ISHA SUGGESTS ASKING NEXT · {nx.type.toUpperCase()}</div>
            <div style={{ fontSize: 17, fontWeight: 700, margin: "6px 0" }}>“{nx.q}”</div><div style={{ color: "#9BA1B5", fontSize: 13 }}>{nx.why}</div>
          </div>}
        </div>
      </div>
      <p style={{ color: "#9BA1B5", marginTop: 14, fontSize: 13 }}>The candidate sees a normal video call and a notice that the interview is recorded and AI-assisted. Isha's panel is visible only to the interviewer, and the final decision is always theirs.</p>
    </section>
  );
}

function Rest() {
  const [ev, setEv] = useState(0);
  const [seg, setSeg] = useState(0);
  const [code, setCode] = useState("");
  const [cert, setCert] = useState(null);
  const [plans, setPlans] = useState(null);
  useEffect(() => { api.get("/public/plans").then(setPlans).catch(() => {}); }, []);
  const verify = async () => {
    const v = code.trim().toUpperCase();
    if (!v) return;
    if (!/^C2H-[A-Z0-9#+.]{1,4}-\d{6}$/.test(v)) { setCert({ ok: false, t: "Check the ID", b: "A verification ID looks like C2H-PYT3-482910." }); return; }
    try { const r = await api.get(`/public/verify/${encodeURIComponent(v)}`); setCert({ ok: r.state === "valid", t: `${r.state === "valid" ? "Valid" : r.state} · ${r.title}`, b: `${r.holder} · ${r.issuer}${r.grade ? " · " + r.grade : ""}` }); }
    catch (e) { setCert({ ok: false, t: "Not found", b: e.message }); }
  };
  const E = EVID[ev];
  return (
    <>
      <section className="board violet" aria-label="Statement" style={{ textAlign: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 10 }}><Isha size={90} mood="happy" /></div>
        <h2 className="big reveal" style={{ fontSize: "clamp(34px,5vw,64px)" }}>Your interviewer doesn't know Kafka.<br /><span style={{ color: "#FFC94A" }}>Isha does.</span></h2>
        <Link className="cta gold" to="/login" style={{ display: "inline-block" }}>See Isha in a real interview</Link>
      </section>

      <section className="board white" aria-label="Every round">
        <div className="kicker">One platform</div>
        <h2 className="big reveal">Every round, in any order.</h2>
        <div className="rounds">
          <div className="round" style={{ background: "#E3EDFF" }}><b className="kicker">MCQ screening</b><h3>Questions from your JD, scored instantly</h3><span className="pill">Java 86% · SQL 79%</span></div>
          <div className="round" style={{ background: "#14213D", color: "#fff" }}><b className="kicker" style={{ color: "#A9C4FF" }}>AI interview · Hira</b><h3>Voice or text, with real follow-ups</h3><p style={{ color: "#C9CDDA" }}>“You mentioned the slow query log. What would make you suspect an N+1 query?”</p></div>
          <div className="round" style={{ background: "#FFF3D1" }}><b className="kicker">F2F with Isha</b><h3>Any interviewer, expert questions</h3><span className="pill">Clarify · contradicts resume</span><span className="pill">Probe · vague on sizing</span></div>
          <div className="round" style={{ background: "#DDF5EC" }}><b className="kicker">Human F2F</b><h3>Structured scorecards for final rounds</h3><span className="pill">System design · 4 / 5</span><span className="pill">Collaboration · 4 / 5</span></div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18 }}>{["Hiring templates", "Scheduling and reminders", "Public, private and internal jobs", "Hiring packet and compare", "Report builder", "Certifications", "Voice choice per job", "Policies and approvals"].map((x) => <span key={x} className="pill">{x}</span>)}</div>
      </section>

      <section className="board gold" aria-label="Evidence">
        <div className="kicker">No black boxes</div>
        <h2 className="big reveal">Every score shows its working.</h2>
        <p style={{ maxWidth: 620 }}>Click any score to see the exact answer, the moment in the recording and the rubric line behind it. Hira recommends; a named person decides.</p>
        <div className="ev">
          <div>{EVID.map((e, i) => <button key={e.name} className={i === ev ? "on" : ""} onClick={() => setEv(i)}><span>{e.name}</span><span>{e.score} / 5</span></button>)}</div>
          <div style={{ background: "#fff", borderRadius: 18, padding: 22 }} key={ev}>
            <div className="kicker">Candidate A · AI interview report · awaiting your review</div>
            <h3 style={{ fontSize: 22, margin: "10px 0" }}>{E.name}: {E.score} / 5</h3>
            <div style={{ borderLeft: "4px solid #5B3FFF", padding: "8px 14px", background: "#F4F2EC", borderRadius: "0 10px 10px 0", fontStyle: "italic" }}>“{E.quote}”</div>
            <div style={{ marginTop: 10, color: "#5B6478", fontSize: 14 }}>{E.time} · Rubric: {E.rubric}</div>
          </div>
        </div>
      </section>

      <section className="board black" aria-label="Integrity">
        <div className="kicker" style={{ color: "#FFC94A" }}>Integrity</div>
        <h2 className="big reveal">Fair to honest candidates. Firm on cheating.</h2>
        <p style={{ color: "#C9CDDA", maxWidth: 680 }}>Rules up front, warnings that explain themselves, two warnings allowed, and the third pauses for your review. A dropped connection never counts against anyone.</p>
        <div style={{ display: "flex", gap: 14, alignItems: "center", background: "#4A3A10", color: "#FFE6A3", borderRadius: 14, padding: 16, marginTop: 18, maxWidth: 640 }}>
          <b style={{ fontSize: 26 }}>!</b><div><b>You switched tabs</b><div>Please stay on this screen until the interview ends. Warning 1 of 2.</div></div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>{["Fullscreen", "Face presence", "One person on camera", "Paste blocked", "Developer tools", "Configurable per round"].map((x) => <span key={x} className="pill" style={{ background: "rgba(255,255,255,.1)", color: "#fff" }}>{x}</span>)}</div>
      </section>

      <section className="board peach" aria-label="For candidates">
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 20, alignItems: "center" }}>
          <div>
            <div className="kicker">For candidates · with Disha</div>
            <h2 className="big reveal">Learn. Prove it.<br />Get matched.</h2>
            <p style={{ maxWidth: 560 }}>Practise with mock interviews, earn proctored badges from L1 to L5, and get matched on what you can actually do.</p>
            <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>{[["Learn", "Paths and mocks"], ["Prove", "Badges, certificates"], ["Get matched", "Verified skills"]].map(([a, b]) => <div key={a} style={{ background: "#fff", borderRadius: 14, padding: "12px 16px" }}><b>{a}</b><div style={{ fontSize: 13, color: "#5B6478" }}>{b}</div></div>)}</div>
            <div style={{ background: "#fff", borderRadius: 16, padding: 16, marginTop: 18, maxWidth: 520 }}>
              <b>Verify a Code2Hire certificate</b>
              <form style={{ display: "flex", gap: 8, marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); verify(); }}>
                <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="C2H-PYT3-000000" aria-label="Verification ID" style={{ flex: 1, border: "1px solid #CDD3E0", borderRadius: 10, padding: "0 12px", height: 42 }} />
                <button className="cta dark" type="submit" disabled={!code.trim()} style={!code.trim() ? { opacity: .55, cursor: "not-allowed" } : undefined}>Verify</button>
              </form>
              {cert && <div style={{ marginTop: 10, borderRadius: 10, padding: 10, background: cert.ok ? "#DDF5E8" : "#FDE7EA" }}><b>{cert.t}</b><div style={{ fontSize: 13 }}>{cert.b}</div></div>}
            </div>
          </div>
          <Disha size={200} mood="happy" />
        </div>
      </section>

      <section className="board white" aria-label="Built for how you hire">
        <div className="kicker">Solutions</div>
        <h2 className="big reveal">Built for how you hire.</h2>
        <div className="tabs2">{SEGS.map((s, i) => <button key={s.label} className={i === seg ? "on" : ""} onClick={() => setSeg(i)}>{s.label}</button>)}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 14, marginTop: 18 }} key={seg}>
          {[["The problem", SEGS[seg].problem, "#FDE7EA"], ["How Code2Hire helps", SEGS[seg].how, "#E3EDFF"], ["What you get", SEGS[seg].get, "#DDF5EC"]].map(([k, v, bg]) => <div key={k} style={{ background: bg, borderRadius: 16, padding: 20, animation: "lppop .4s" }}><div className="kicker">{k}</div><p style={{ fontSize: 17, fontWeight: 600, marginTop: 8 }}>{v}</p></div>)}
        </div>
      </section>

      <section className="board sky" aria-label="Trust">
        <div className="kicker">Design partner programme</div>
        <h2 className="big reveal">Help shape Code2Hire. Use it free while we build it with you.</h2>
        <p>For staffing agencies, IT services firms and GCCs that interview every week.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 12, marginTop: 18 }}>
          {[["Roles and permissions", "One person can be manager, recruiter and interviewer"], ["Policies", "Approvals, retention and limits, set once"], ["Audit log", "Who viewed, exported or changed what"], ["Consent built in", "Clear notice before every recorded round"], ["Data in India", "Retention you control"], ["Everything configurable", "Platform → company → team → job → round"]].map(([a, b]) => <div key={a} style={{ background: "#fff", borderRadius: 14, padding: 16 }}><b>{a}</b><div style={{ fontSize: 14, color: "#5B6478" }}>{b}</div></div>)}
        </div>
      </section>

      <section className="board" style={{ background: "#F4F2EC" }} aria-label="Pricing">
        <h2 className="big reveal">Simple pricing in rupees.</h2><span className="pill">1 credit ≈ 1 AI interview minute</span>
        <div className="price">
          {(plans ? Object.entries(plans) : []).map(([k, p]) => (
            <div key={k} style={k === "employer" ? { border: "2px solid #5B3FFF" } : undefined}>
              {k === "employer" && <span className="pill" style={{ alignSelf: "flex-start", background: "#EFEBFF", color: "#3F2BD9" }}>Most teams</span>}
              <h3 style={{ fontSize: 20 }}>{p.label}</h3>
              <div style={{ fontSize: 26, fontWeight: 900 }}>{p.credits.toLocaleString("en-IN")} <span style={{ fontSize: 14, color: "#5B6478" }}>credits</span></div>
              <div style={{ fontSize: 14, color: "#5B6478" }}>{p.limits.seats} seats · {p.limits.active_jobs} active jobs · {p.limits.isha_hours} Isha hours · {p.limits.storage_days}-day retention</div>
              <Link className={"cta " + (k === "employer" ? "gold" : "dark")} to={k === "enterprise" || k === "agency" ? "#cta" : "/login"} style={{ textAlign: "center", marginTop: "auto" }}>{k === "enterprise" || k === "agency" ? "Talk to us" : "Start free"}</Link>
            </div>
          ))}
        </div>
      </section>

      <section className="board white" aria-label="Frequently asked questions">
        <h2 className="big reveal">Straight answers.</h2>
        {FAQ.map(([q, a]) => <details key={q}><summary>{q}</summary><p style={{ marginTop: 8, color: "#33405C" }}>{a}</p></details>)}
      </section>

      <section id="cta" className="board violet" aria-label="Get started">
        <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 6 }}><Hira size={90} mood="happy" /><Isha size={80} mood="happy" /><Disha size={80} mood="happy" /></div>
          <div style={{ flex: 1, minWidth: 260 }}><h2 className="big" style={{ margin: 0 }}>Run your next interview with Isha.</h2><p>Set up a job in minutes. Your first AI interviews are on us.</p></div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}><Link className="cta gold" to="/login">I'm hiring · start free</Link><Link className="cta white" to="/signup">I'm a candidate · practise free</Link></div>
        </div>
      </section>
    </>
  );
}

export default function Landing() {
  const { me } = useAuth();
  useReveal();
  const ticker = useMemo(() => ["Java L4 · verified", "Isha: ask a follow-up", "Score 4.4 · evidence attached", "240 → 18 shortlisted", "Badge earned: SQL L3", "Feedback shared with 17", "Voice: Neerja · Indian English", "Policy: offer needs 2 approvals"], []);
  return (
    <div className="lp">
      <style>{CSS}</style>
      <nav className="lp-top">
        <Link to="/" style={{ color: "#fff", fontWeight: 900, fontSize: 22, letterSpacing: "-.5px" }}>Code<span style={{ color: "#FFC94A" }}>2</span>Hire</Link>
        <span className="hide-m" style={{ color: "#9F98DA", fontSize: 12 }}>Powered by AcknowledgerFirst</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 18, alignItems: "center" }}>
          <a className="hide-m" href="#how">Product</a><Link className="hide-m" to="/jobs">Jobs</Link><Link className="hide-m" to="/verify">Verify</Link>
          {me ? <Link className="cta gold" style={{ padding: "8px 14px", fontSize: 14 }} to={me.home}>Open app</Link>
            : <><Link to="/login">Sign in</Link><Link className="cta gold" style={{ padding: "8px 14px", fontSize: 14 }} to="/signup">Get started</Link></>}
        </div>
      </nav>
      <Hero />
      <div className="marquee" aria-label="A day with Code2Hire"><div>{[...ticker, ...ticker].map((t, i) => <span key={i}>✦ {t}</span>)}</div></div>
      <div id="how" />
      <Transformation />
      <Flow />
      <Agents />
      <LiveRoom />
      <Rest />
      <footer>
        <div className="wrap" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 20 }}>
          <div><div style={{ color: "#fff", fontWeight: 900, fontSize: 22 }}>Code<span style={{ color: "#FFC94A" }}>2</span>Hire</div><p>Every interview, expert-level.</p></div>
          <div><b style={{ color: "#fff" }}>Product</b><a href="#how">Hira</a><a href="#how">Isha</a><a href="#how">Disha</a><Link to="/verify">Certifications</Link></div>
          <div><b style={{ color: "#fff" }}>For</b><a href="#how">Employers</a><a href="#how">Staffing agencies</a><a href="#how">Campus hiring</a><a href="#how">GCCs</a></div>
          <div><b style={{ color: "#fff" }}>Resources</b><Link to="/jobs">Open jobs</Link><Link to="/verify">Verify a certificate</Link><a href="#cta">Contact</a></div>
        </div>
        <div className="wrap" style={{ marginTop: 30, fontSize: 13 }}>© {new Date().getFullYear()} Code2Hire · Powered by AcknowledgerFirst</div>
      </footer>
    </div>
  );
}
