// V02.00.08: one wording for the video connection on both sides, so "waiting" never shows while the other person
// is already there, a slow connection says so, and a failed one says what to do.
import { useEffect, useState } from "react";

/** Re-render every second while something is counting. */
export function useTick(on) {
  const [, set] = useState(0);
  useEffect(() => { if (!on) return undefined; const t = setInterval(() => set((x) => x + 1), 1000); return () => clearInterval(t); }, [on]);
}

/**
 * call: the useCall() result. peer: "interviewer" or "candidate" (the other person). everConnected: connected at least once.
 * Returns {key, title, text, chip, tone, slow, failed}.
 */
export function describeCall(call, peer, everConnected) {
  const name = peer === "interviewer" ? "The interviewer" : "The candidate";
  const secs = call.connectingSince ? Math.round((Date.now() - call.connectingSince) / 1000) : 0;
  const away = call.state === "left" || (!call.peerOnline && everConnected && call.state !== "connected");
  if (call.state === "connected") return { key: "connected", title: "", text: "", chip: "● Connected", tone: "good" };
  if (call.state === "ended") return { key: "ended", title: "The interview has ended", text: "", chip: "Ended", tone: "" };
  if (away) return { key: "away", title: peer === "interviewer" ? "The interviewer has left the meeting" : "The candidate has left the call",
    text: peer === "interviewer" ? "Stay on this page. You'll be reconnected as soon as they come back. Your interview is still open."
      : "They'll be reconnected as soon as they come back.", chip: peer === "interviewer" ? "Interviewer left" : "Candidate left", tone: "warn" };
  if (call.state === "failed") return { key: "failed", failed: true, title: "We couldn't connect the video",
    text: `${name} is here, and chat and captions still work, but the video can't get through this network. Try again, or follow the steps below.`,
    chip: "Video not connected", tone: "bad" };
  if (!call.peerOnline && !everConnected) return { key: "waiting", title: `Waiting for ${peer === "interviewer" ? "the interviewer" : "the candidate"}`,
    text: "Stay on this page. You'll be connected as soon as they join.", chip: `Waiting for ${peer === "interviewer" ? "the interviewer" : "the candidate"}`, tone: "warn" };
  const slow = secs >= 10;
  const retrying = call.attempt > 0;
  return { key: "connecting", slow,
    title: call.state === "reconnecting" ? "Connection lost. Reconnecting…" : `${name} is here. Connecting the video…`,
    text: retrying ? `Trying again${call.relay && call.attempt >= 2 ? " through the Code2Hire relay" : ""} (attempt ${call.attempt + 1})…`
      : slow ? "This is taking longer than usual. It usually connects within a few seconds." : "This usually takes a few seconds.",
    chip: retrying ? `Connecting (attempt ${call.attempt + 1})` : call.state === "reconnecting" ? "Reconnecting" : "Connecting…", tone: "warn" };
}

/** What to try when the video can't connect. */
export function ConnectHelp({ onRetry, dark, compact }) {
  if (compact) {  // the interviewer's docked video is small: one line of advice to pass on, and the button
    return (
      <div className="col" style={{ gap: 6, alignItems: "center", maxWidth: 440, fontSize: 13 }}>
        <span>Ask the candidate to turn off any VPN or switch to a mobile hotspot, then try again. Chat and captions still work.</span>
        {onRetry && <button className="btn sm primary" onClick={onRetry}>Try again</button>}
      </div>
    );
  }
  return (
    <div className="col" style={{ gap: 6, textAlign: "left", maxWidth: 480, fontSize: 14, opacity: dark ? .92 : 1 }}>
      <ol style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 4 }}>
        <li>Turn off any VPN, proxy or security app that filters traffic.</li>
        <li>On office or college Wi-Fi, switch to a mobile hotspot or home Wi-Fi. Some networks block video calls.</li>
        <li>Close other video apps (Zoom, Teams, Meet) and other tabs using the camera.</li>
        <li>Use the latest Chrome or Edge.</li>
      </ol>
      {onRetry && <div><button className="btn primary" onClick={onRetry}>Try again</button></div>}
    </div>
  );
}
