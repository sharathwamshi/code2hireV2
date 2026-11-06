// Peer-to-peer video call for F2F rounds. Media goes browser to browser (WebRTC);
// Code2Hire only relays the signalling messages. The interviewer always makes the offer, so there are no collisions.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

export async function getMedia({ video = true, audio = true } = {}) {
  return navigator.mediaDevices.getUserMedia({
    video: video ? { width: { ideal: 1280 }, height: { ideal: 720 } } : false,
    audio: audio ? { echoCancellation: true, noiseSuppression: true, autoGainControl: true } : false,
  });
}

export function useCall({ attId, role, info, local, active, onMessage }) {
  const pc = useRef(null);
  const ice = useRef([]);
  const cursor = useRef(info?.cursor || 0);
  const stopped = useRef(false);
  const msg = useRef(onMessage);
  const session = useRef(Math.random().toString(36).slice(2, 8)); // offers from an older page never match
  const offerNo = useRef(0);      // every offer is numbered; stale answers are ignored
  const lastOffer = useRef(0);    // time of the last offer, to collapse join + ready bursts
  msg.current = onMessage;
  const [remote, setRemote] = useState(null);
  const [state, setState] = useState("waiting"); // waiting | connecting | connected | reconnecting | left | ended
  const [peerOnline, setPeerOnline] = useState(!!info?.peer_online);
  const [peerMedia, setPeerMedia] = useState({ mic: true, cam: true, screen: false });
  const [roundStatus, setRoundStatus] = useState(info?.status || null);
  const [peerAwaySince, setPeerAwaySince] = useState(info?.peer_online ? null : Date.now());

  const send = useCallback((kind, payload = {}) => api.post(`/call/${attId}/signal`, { kind, payload }).catch(() => {}), [attId]);

  const close = () => { try { pc.current?.close(); } catch { /* closed */ } pc.current = null; };
  const fresh = () => {
    close();
    const p = new RTCPeerConnection({ iceServers: info.ice_servers || [] });
    local?.getTracks().forEach((t) => p.addTrack(t, local));
    p.ontrack = (e) => setRemote(e.streams[0] || new MediaStream([e.track]));
    p.onicecandidate = (e) => e.candidate && send("ice", e.candidate.toJSON());
    p.onconnectionstatechange = () => {
      const s = p.connectionState;
      if (s === "connected") setState("connected");
      else if (s === "connecting" || s === "new") setState("connecting");
      else if (s === "disconnected") setState("reconnecting");
      else if (s === "failed") { setState("reconnecting"); if (role === "interviewer") setTimeout(() => offer(true), 800); }
    };
    pc.current = p;
    ice.current = [];
    return p;
  };
  const flush = async () => { for (const c of ice.current) { try { await pc.current.addIceCandidate(c); } catch { /* stale */ } } ice.current = []; };
  const offer = async (force = false) => {
    if (!force && Date.now() - lastOffer.current < 2500 && pc.current) return;
    lastOffer.current = Date.now();
    const n = `${session.current}-${++offerNo.current}`;
    const p = fresh();
    setState("connecting");
    const o = await p.createOffer();
    await p.setLocalDescription(o);
    send("offer", { type: o.type, sdp: o.sdp, n });
  };

  const handle = async (s) => {
    const k = s.kind, d = s.payload || {};
    if (k === "join") { setPeerOnline(true); if (role === "interviewer") await offer(true); else send("ready"); }
    else if (k === "ready" && role === "interviewer") await offer(false);
    else if (k === "offer" && role === "candidate") {
      const p = fresh(); setState("connecting");
      await p.setRemoteDescription({ type: d.type, sdp: d.sdp }); await flush();
      const a = await p.createAnswer(); await p.setLocalDescription(a);
      send("answer", { type: a.type, sdp: a.sdp, n: d.n });
    } else if (k === "answer" && role === "interviewer" && pc.current) {
      if (d.n !== `${session.current}-${offerNo.current}`) return;               // answer to an older offer
      if (pc.current.signalingState !== "have-local-offer") return;
      await pc.current.setRemoteDescription({ type: d.type, sdp: d.sdp }); await flush();
    }
    else if (k === "ice") { if (pc.current?.remoteDescription) { try { await pc.current.addIceCandidate(d); } catch { /* stale */ } } else ice.current.push(d); }
    else if (k === "bye") { close(); setRemote(null); setState(d.ended ? "ended" : "left"); setPeerOnline(false); }
    else if (k === "media") setPeerMedia((m) => ({ ...m, ...d }));
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
    return () => { stopped.current = true; send("bye"); close(); };
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
  return { remote, state, peerOnline, peerMedia, roundStatus, peerAwaySince, send, replaceVideo, replaceTrack, hangup };
}

// Recording moved to lib/recorder.js (chunked uploads, both sides, always on).
