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
          for (const s of r.signals) { if (stopped.current) break; await handle(s); }
          if (r.status === "completed" || r.status === "reviewed") { msg.current?.({ kind: "ended" }); }
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
  const hangup = (ended = false) => { send("bye", { ended }); close(); setRemote(null); setState(ended ? "ended" : "left"); };
  return { remote, state, peerOnline, peerMedia, send, replaceVideo, hangup };
}

/** Records the call: the other person's video with both voices mixed. Resolves to a webm Blob. */
export function startRecorder(remote, local) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const dest = ctx.createMediaStreamDestination();
  [remote, local].forEach((s) => { if (s?.getAudioTracks().length) ctx.createMediaStreamSource(new MediaStream(s.getAudioTracks())).connect(dest); });
  const tracks = [...(remote?.getVideoTracks() || []).slice(0, 1), ...dest.stream.getAudioTracks()];
  const type = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((t) => window.MediaRecorder?.isTypeSupported(t));
  if (!type) return null;
  const rec = new MediaRecorder(new MediaStream(tracks), { mimeType: type, videoBitsPerSecond: 900_000 });
  const chunks = [];
  const started = Date.now();
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.start(5000);
  return {
    seconds: () => Math.round((Date.now() - started) / 1000),
    stop: () => new Promise((ok) => { rec.onstop = () => { ctx.close(); ok(new Blob(chunks, { type: "video/webm" })); }; try { rec.stop(); } catch { ok(new Blob(chunks, { type: "video/webm" })); } }),
  };
}

export async function uploadRecording(attId, blob, seconds, part = 0) {
  const fd = new FormData();
  fd.append("file", blob, `attempt-${attId}.webm`);
  fd.append("seconds", String(seconds));
  fd.append("part", String(part));
  return api.post(`/call/${attId}/recording`, fd);
}
