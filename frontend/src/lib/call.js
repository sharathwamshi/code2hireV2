// Peer-to-peer video call for F2F rounds. Media goes browser to browser (WebRTC);
// Code2Hire only relays the signalling messages. The interviewer always makes the offer, so there are no collisions.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken } from "../api";

export async function getMedia({ video = true, audio = true } = {}) {
  return navigator.mediaDevices.getUserMedia({
    video: video ? { width: { ideal: 1280 }, height: { ideal: 720 } } : false,
    audio: audio ? { echoCancellation: true, noiseSuppression: true, autoGainControl: true } : false,
  });
}

/** V02.00.08: how the connection actually runs, from the browser's stats: direct (host/srflx) or through the relay. */
export async function connectionPath(pc) {
  try {
    const stats = await pc.getStats();
    let pair = null;
    stats.forEach((r) => { if (r.type === "transport" && r.selectedCandidatePairId) pair = stats.get(r.selectedCandidatePairId); });
    if (!pair) stats.forEach((r) => { if (r.type === "candidate-pair" && r.state === "succeeded" && (r.nominated || r.selected)) pair = pair || r; });
    if (!pair) return null;
    const l = stats.get(pair.localCandidateId) || {}, rm = stats.get(pair.remoteCandidateId) || {};
    const relay = l.candidateType === "relay" || rm.candidateType === "relay";
    return { path: relay ? "relay" : "direct", local: l.candidateType, remote: rm.candidateType,
      protocol: l.relayProtocol || l.protocol, rtt: pair.currentRoundTripTime };
  } catch { return null; }
}

const CONNECT_TIMEOUT = 15000;   // no media after this long: try again (V02.00.08)

export function useCall({ attId, role, info, local, active, onMessage }) {
  const pc = useRef(null);
  const curN = useRef(null);      // the offer number the current connection belongs to
  const pend = useRef({});        // ICE candidates that arrived before their offer/answer, by offer number
  const cursor = useRef(info?.cursor || 0);
  const stopped = useRef(false);
  const msg = useRef(onMessage);
  const session = useRef(Math.random().toString(36).slice(2, 8)); // offers from an older page never match
  const offerNo = useRef(0);      // every offer is numbered; stale answers and ICE are ignored
  const lastOffer = useRef(0);    // time of the last offer, to collapse join + ready bursts
  const chain = useRef(Promise.resolve()); // offer, answer and ICE leave in order, so ICE never overtakes its offer
  const watchdog = useRef(null);
  const tries = useRef(0);
  const relayOnly = useRef(false);
  msg.current = onMessage;
  const [remote, setRemote] = useState(null);
  const [state, setState] = useState("waiting"); // waiting | connecting | connected | reconnecting | failed | left | ended
  const [peerOnline, setPeerOnline] = useState(!!info?.peer_online);
  const [peerMedia, setPeerMedia] = useState({ mic: true, cam: true, screen: false });
  const [roundStatus, setRoundStatus] = useState(info?.status || null);
  const [peerAwaySince, setPeerAwaySince] = useState(info?.peer_online ? null : Date.now());
  const [path, setPath] = useState(null);       // {path: "direct" | "relay", local, remote, protocol}
  const [attempt, setAttempt] = useState(0);    // how many times the connection was retried
  const [connectingSince, setConnectingSince] = useState(null);

  const send = useCallback((kind, payload = {}) => api.post(`/call/${attId}/signal`, { kind, payload }).catch(() => {}), [attId]);
  const sendStrict = (kind, payload = {}) => api.post(`/call/${attId}/signal`, { kind, payload });  // rejects on failure (chat)
  const sendOrdered = (kind, payload) => { chain.current = chain.current.then(() => send(kind, payload)); return chain.current; };
  const report = (body) => api.post(`/call/${attId}/path`, body).catch(() => {});

  const clearWatch = () => { if (watchdog.current) clearTimeout(watchdog.current); watchdog.current = null; };
  const close = () => { clearWatch(); try { pc.current?.close(); } catch { /* closed */ } pc.current = null; };
  const servers = () => info.ice_servers || [];
  const fresh = (n) => {
    close();
    const p = new RTCPeerConnection({ iceServers: servers(), iceTransportPolicy: relayOnly.current && info.relay ? "relay" : "all" });
    local?.getTracks().forEach((t) => p.addTrack(t, local));
    p.ontrack = (e) => setRemote(e.streams[0] || new MediaStream([e.track]));
    p.onicecandidate = (e) => e.candidate && sendOrdered("ice", { ...e.candidate.toJSON(), n });
    p.onconnectionstatechange = () => {
      if (pc.current !== p) return;
      const s = p.connectionState;
      if (s === "connected") {
        clearWatch(); setState("connected"); setConnectingSince(null);
        connectionPath(p).then((x) => { setPath(x || { path: "unknown" }); report({ state: "connected", ...(x || { path: "unknown" }) }); });
        if (tries.current) { tries.current = 0; setAttempt(0); }
      } else if (s === "connecting" || s === "new") setState("connecting");
      else if (s === "disconnected") { setState("reconnecting"); arm(8000); }   // brief drops often recover by themselves
      else if (s === "failed") { setState("reconnecting"); retry("failed"); }
    };
    pc.current = p;
    curN.current = n;
    return p;
  };
  /** Not connected in time: the interviewer makes a new offer; the second retry goes through the relay only. The
   *  candidate asks the interviewer for a new offer. After three tries both sides show "couldn't connect". */
  const retry = (why) => {
    clearWatch();
    if (stopped.current) return;
    tries.current += 1;
    setAttempt(tries.current);
    if (tries.current >= 2 && info.relay && !relayOnly.current) { relayOnly.current = true; report({ state: "relay_only" }); }
    else report({ state: tries.current > 3 ? "failed" : "retry" });
    if (tries.current > 3) setState("failed");
    if (role === "interviewer") setTimeout(() => offer(true), 300);
    else send("ready", { again: true, relay: relayOnly.current });  // ask for a new offer; the count stays the interviewer's
  };
  const arm = (ms = CONNECT_TIMEOUT) => {
    clearWatch();
    watchdog.current = setTimeout(() => { if (pc.current && pc.current.connectionState !== "connected") retry("timeout"); },
      tries.current > 3 ? 30000 : ms);
  };
  const flush = async (n) => {
    const list = pend.current[n] || [];
    delete pend.current[n];
    for (const c of list) { try { await pc.current.addIceCandidate(c); } catch { /* stale */ } }
  };
  const offer = async (force = false) => {
    if (!force && Date.now() - lastOffer.current < 2500 && pc.current) return;
    lastOffer.current = Date.now();
    const n = `${session.current}-${++offerNo.current}`;
    const p = fresh(n);
    setState((s) => (s === "failed" ? s : "connecting"));
    setConnectingSince((t) => t || Date.now());
    const o = await p.createOffer();
    await p.setLocalDescription(o);
    sendOrdered("offer", { type: o.type, sdp: o.sdp, n, relay: relayOnly.current, t: tries.current });  // t: which try this is
    arm();
  };

  const handle = async (s) => {
    const k = s.kind, d = s.payload || {};
    if (k === "join") {
      setPeerOnline(true);
      if (role === "interviewer") { tries.current = 0; setAttempt(0); await offer(true); } else send("ready");
    } else if (k === "ready" && role === "interviewer") {
      if (d.relay && info.relay) relayOnly.current = true;
      if (d.retry) { tries.current = 1; setAttempt(1); setState("connecting"); setConnectingSince(Date.now()); }  // the candidate pressed Try again
      await offer(!!d.retry || !!d.again);
    } else if (k === "offer" && role === "candidate") {
      if (d.relay && info.relay) relayOnly.current = true;
      // the interviewer's side counts the tries; the candidate shows the same attempt, and "couldn't connect" after the last
      if (typeof d.t === "number") { tries.current = d.t; setAttempt(d.t); }
      const p = fresh(d.n); setState(d.t > 3 ? "failed" : "connecting");
      setConnectingSince((t) => t || Date.now());
      await p.setRemoteDescription({ type: d.type, sdp: d.sdp }); await flush(d.n);
      const a = await p.createAnswer(); await p.setLocalDescription(a);
      sendOrdered("answer", { type: a.type, sdp: a.sdp, n: d.n });
      arm(CONNECT_TIMEOUT + 5000);
    } else if (k === "answer" && role === "interviewer" && pc.current) {
      if (d.n !== `${session.current}-${offerNo.current}`) return;               // answer to an older offer
      if (pc.current.signalingState !== "have-local-offer") return;
      await pc.current.setRemoteDescription({ type: d.type, sdp: d.sdp }); await flush(d.n);
    } else if (k === "ice") {
      const { n, ...cand } = d;
      if (n && n !== curN.current) { (pend.current[n] = pend.current[n] || []).push(cand); }       // for an offer not here yet
      else if (pc.current?.remoteDescription) { try { await pc.current.addIceCandidate(cand); } catch { /* stale */ } }
      else (pend.current[n || curN.current] = pend.current[n || curN.current] || []).push(cand);
    } else if (k === "bye") {
      close(); setRemote(null); setPath(null); setState(d.ended ? "ended" : "left"); setPeerOnline(false);
      tries.current = 0; setAttempt(0); setConnectingSince(null);
    } else if (k === "media") setPeerMedia((m) => ({ ...m, ...d }));
    msg.current?.(s);
  };

  useEffect(() => {
    if (!active || !info || !local) return;
    stopped.current = false;
    cursor.current = info.cursor || 0;  // only signals from now on; never replay an old session
    send("join");
    (async () => {
      while (!stopped.current) {
        try {
          const r = await api.get(`/call/${attId}/signal`, { after: cursor.current, wait: 6 });
          cursor.current = r.cursor;
          setPeerOnline(r.peer_online);
          setPeerAwaySince((t) => (r.peer_online ? null : t || Date.now()));
          setRoundStatus(r.status);
          for (const s of r.signals) { if (stopped.current) break; await handle(s); }
          if (r.ended) { msg.current?.({ kind: "ended" }); }
        } catch { await new Promise((ok) => setTimeout(ok, 2000)); }
      }
    })();
    // gap 4 (V02.00.07): closing the tab or the browser counts as leaving at once, so the other side is told within a
    // second instead of watching a frozen picture
    const gone = () => {
      try {
        fetch(`${import.meta.env.VITE_API_BASE || ""}/api/call/${attId}/signal`, { method: "POST", keepalive: true,
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` }, body: JSON.stringify({ kind: "bye", payload: { closed: true } }) });
      } catch { /* the server's presence check will notice */ }
    };
    window.addEventListener("pagehide", gone);
    return () => { window.removeEventListener("pagehide", gone); stopped.current = true; send("bye"); close(); };
  }, [active, attId, local]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Swap the outgoing video track (screen share or camera) without renegotiating. */
  const replaceVideo = async (track) => {
    const sender = pc.current?.getSenders().find((x) => x.track?.kind === "video");
    if (sender) await sender.replaceTrack(track);
  };
  /** Swap an outgoing track of either kind (a repaired camera or microphone, V02.00.05). */
  const replaceTrack = async (kind, track) => {
    const sender = pc.current?.getSenders().find((x) => x.track?.kind === kind || (!x.track && kind));
    if (sender) await sender.replaceTrack(track).catch(() => {});
  };
  /** ended=false: only this side leaves (the other side waits and reconnects when it comes back). */
  const hangup = (ended = false) => { send("bye", { ended }); close(); setRemote(null); setState(ended ? "ended" : "self_left"); };
  /** "Try again" on either side: start the connection over (through the relay when one is set up). */
  const reconnect = () => {
    tries.current = 1; setAttempt(1); setState("connecting"); setConnectingSince(Date.now());
    if (info.relay) relayOnly.current = true;
    if (role === "interviewer") offer(true); else send("ready", { retry: tries.current, relay: relayOnly.current });
  };
  return { remote, state, peerOnline, peerMedia, roundStatus, peerAwaySince, send, sendStrict, replaceVideo, replaceTrack, hangup,
    path, attempt, connectingSince, reconnect, relay: !!info?.relay };
}

// Recording moved to lib/recorder.js (chunked uploads, both sides, always on).
