import { useEffect, useState } from "react";

// The three agents, drawn as the approved mascots: Hira (a blue gem), Isha (a golden firefly), Disha (a compass).
// mood: idle | talk | think | happy. Clicking makes them react.

function useMood(mood) {
  const [m, setM] = useState(mood);
  useEffect(() => setM(mood), [mood]);
  return [m, setM];
}

export function Hira({ size = 64, mood = "idle", onClick, title = "Hira" }) {
  const [m, setM] = useMood(mood);
  const [hop, setHop] = useState(0);
  const mouth = m === "talk" ? "M186 232 Q200 250 214 232 Q200 240 186 232" : m === "think" ? "M188 238 L212 236" : "M184 232 Q200 252 216 232";
  return (
    <svg className={"mascot" + (hop ? " m-hop" : "") + (m === "think" ? " m-think" : "")} key={hop} width={size} height={size} viewBox="30 40 340 330"
      role="img" aria-label={title} onClick={() => { setHop(hop + 1); onClick?.(); if (mood === "idle") { setM("happy"); setTimeout(() => setM("idle"), 1400); } }}>
      <path className={m === "happy" ? "m-wave" : ""} d="M314 200 q 32 -8 42 -46" fill="none" stroke="#2F6FED" strokeWidth="11" strokeLinecap="round" />
      <path d="M84 205 q -30 10 -36 44" fill="none" stroke="#2F6FED" strokeWidth="11" strokeLinecap="round" />
      <ellipse cx="184" cy="350" rx="13" ry="7" fill="#1E3F8A" /><ellipse cx="216" cy="350" rx="13" ry="7" fill="#1E3F8A" />
      <g stroke="#1E3F8A" strokeWidth="3" strokeLinejoin="round">
        <polygon points="120,110 165,110 140,170 60,170" fill="#A9C4FF" /><polygon points="165,110 235,110 260,170 140,170" fill="#DCE7FF" />
        <polygon points="235,110 280,110 340,170 260,170" fill="#7FA6F7" /><polygon points="60,170 140,170 200,345" fill="#5B8FF5" />
        <polygon points="140,170 260,170 200,345" fill="#86AAF8" /><polygon points="260,170 340,170 200,345" fill="#2F6FED" />
      </g>
      <path d="M176 122 l10 0 l-14 30 l-10 0z" fill="#fff" fillOpacity=".8" />
      <circle cx="178" cy="212" r="13" fill="#fff" stroke="#12213F" strokeWidth="3" /><circle cx="222" cy="212" r="13" fill="#fff" stroke="#12213F" strokeWidth="3" />
      <g transform={m === "think" ? "translate(3,-4)" : ""}><circle cx="178" cy="212" r="6.5" fill="#12213F" /><circle cx="222" cy="212" r="6.5" fill="#12213F" /></g>
      <path d={mouth} fill={m === "talk" ? "#12213F" : "none"} stroke="#12213F" strokeWidth="5" strokeLinecap="round" />
      <ellipse cx="166" cy="236" rx="7" ry="4" fill="#FF9DB0" fillOpacity=".75" /><ellipse cx="234" cy="236" rx="7" ry="4" fill="#FF9DB0" fillOpacity=".75" />
      {m === "happy" && <path d="M330 70 l6 14 l14 6 l-14 6 l-6 14 l-6 -14 l-14 -6 l14 -6z" fill="#FFC94A" className="m-glow" />}
    </svg>
  );
}

export function Isha({ size = 64, mood = "idle", onClick, title = "Isha" }) {
  const [m, setM] = useMood(mood);
  const [hop, setHop] = useState(0);
  return (
    <svg className={"mascot" + (hop ? " m-hop" : "") + (m === "think" ? " m-think" : "")} key={hop} width={size} height={size} viewBox="60 60 280 280" role="img" aria-label={title}
      onClick={() => { setHop(hop + 1); onClick?.(); if (mood === "idle") { setM("happy"); setTimeout(() => setM("idle"), 1400); } }}>
      <circle className="m-glow" cx="200" cy="200" r="120" fill="#FFD27A" fillOpacity=".3" />
      <ellipse className={m === "talk" || m === "happy" ? "m-flap" : ""} cx="150" cy="148" rx="34" ry="20" transform="rotate(-35 150 148)" fill="#fff" fillOpacity=".9" stroke="#E3A92B" strokeWidth="4" />
      <ellipse className={m === "talk" || m === "happy" ? "m-flap" : ""} cx="250" cy="148" rx="34" ry="20" transform="rotate(35 250 148)" fill="#fff" fillOpacity=".9" stroke="#E3A92B" strokeWidth="4" />
      <path d="M200 128 C210 170 230 190 272 200 C230 210 210 230 200 272 C190 230 170 210 128 200 C170 190 190 170 200 128Z" fill="#FFC94A" stroke="#E3A92B" strokeWidth="4" />
      <circle cx="200" cy="200" r="40" fill="#FFC94A" />
      <g transform={m === "think" ? "translate(3,-3)" : ""}><circle cx="186" cy="196" r="6" fill="#5A3B00" /><circle cx="214" cy="196" r="6" fill="#5A3B00" /></g>
      <path d={m === "talk" ? "M192 210 Q200 222 208 210 Q200 214 192 210" : "M192 211 Q200 218 208 211"} fill={m === "talk" ? "#5A3B00" : "none"} stroke="#5A3B00" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Disha({ size = 64, mood = "idle", onClick, title = "Disha" }) {
  const [m, setM] = useMood(mood);
  const [hop, setHop] = useState(0);
  return (
    <svg className={"mascot" + (hop ? " m-hop" : "")} key={hop} width={size} height={size * 1.08} viewBox="30 10 340 370" role="img" aria-label={title}
      onClick={() => { setHop(hop + 1); onClick?.(); if (mood === "idle") { setM("happy"); setTimeout(() => setM("idle"), 1400); } }}>
      <path d="M88 214 q -36 -8 -46 -52" fill="none" stroke="#E07B1A" strokeWidth="13" strokeLinecap="round" />
      <path className={m === "happy" || m === "talk" ? "m-wave" : ""} d="M312 226 q 30 18 30 54" fill="none" stroke="#E07B1A" strokeWidth="13" strokeLinecap="round" />
      <ellipse cx="168" cy="346" rx="20" ry="10" fill="#1F8A84" /><ellipse cx="232" cy="346" rx="20" ry="10" fill="#1F8A84" />
      <g className="m-needle"><polygon points="203,92 226,58 274,18 240,72" fill="#E07B1A" stroke="#173C3A" strokeWidth="3" strokeLinejoin="round" />
        <polygon points="203,92 240,72 226,58" fill="#1F8A84" stroke="#173C3A" strokeWidth="3" strokeLinejoin="round" /></g>
      <circle cx="200" cy="215" r="122" fill="#FFF4E6" stroke="#E07B1A" strokeWidth="14" />
      <circle cx="200" cy="215" r="100" fill="none" stroke="#1F8A84" strokeWidth="2" strokeDasharray="3 9" />
      <circle cx="203" cy="92" r="9" fill="#1F8A84" stroke="#173C3A" strokeWidth="3" />
      <circle cx="168" cy="205" r="15" fill="#fff" stroke="#173C3A" strokeWidth="3" /><circle cx="232" cy="205" r="15" fill="#fff" stroke="#173C3A" strokeWidth="3" />
      <g transform={m === "think" ? "translate(4,-4)" : ""}><circle cx="168" cy="205" r="8" fill="#173C3A" /><circle cx="232" cy="205" r="8" fill="#173C3A" /></g>
      <path d={m === "talk" ? "M174 246 Q200 272 226 246 Q200 256 174 246" : "M170 248 Q200 276 230 248"} fill={m === "talk" ? "#173C3A" : "none"} stroke="#173C3A" strokeWidth="6" strokeLinecap="round" />
    </svg>
  );
}

export function AgentNote({ agent = "hira", title, children, action, mood }) {
  const M = { hira: Hira, isha: Isha, disha: Disha }[agent];
  return (
    <div className={"agent " + agent}>
      <M size={44} mood={mood} />
      <div className="grow col" style={{ gap: 4 }}>
        {title && <b style={{ color: agent === "hira" ? "var(--hira)" : agent === "isha" ? "var(--isha)" : "var(--disha)" }}>{title}</b>}
        <div style={{ color: "var(--ink-2)" }}>{children}</div>
        {action && <div className="row wrap" style={{ marginTop: 4 }}>{action}</div>}
      </div>
    </div>
  );
}
