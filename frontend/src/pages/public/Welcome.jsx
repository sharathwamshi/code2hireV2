import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Disha } from "../../components/Mascot";
import { Btn, Spinner } from "../../components/ui";

/** The candidate's personal link. Opens their portal straight away; they set a password inside. */
export default function Welcome() {
  const { token } = useParams();
  const nav = useNavigate();
  const { useToken } = useAuth();
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    (async () => {
      try {
        const p = await api.get(`/auth/invite/${token}`);
        setInfo(p);
        const o = await api.post(`/auth/invite/${token}/open`);
        await useToken(o.token);
        try { o.require_password ? localStorage.setItem("c2h_must_pw", "1") : localStorage.removeItem("c2h_must_pw"); } catch { /* private mode */ }
        setTimeout(() => nav(o.home === "/me" ? "/me?welcome=1" : o.home + "?welcome=1", { replace: true }), 1300);
      } catch (e) { setErr(e.message); }
    })();
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="welcome">
      <div className="welcome-card">
        <div className="logo" style={{ fontSize: 26 }}>Code<b>2</b>Hire</div>
        <Disha size={110} mood={err ? "think" : "happy"} />
        {err ? <>
          <h2>{err}</h2>
          <p className="muted">If you've already set a password, sign in with your email.</p>
          <div className="row"><Link className="btn primary" to="/login">Sign in</Link></div>
        </> : !info ? <Spinner /> : <>
          <h2>Welcome, {info.name.split(" ")[0]}!</h2>
          <p style={{ fontSize: 16 }}>{info.added_by ? `${info.added_by}${info.company ? ` from ${info.company}` : ""}` : info.company || "A hiring team"} added you on Code2Hire{info.job ? <> for <b>{info.job}</b></> : ""}.</p>
          <div className="row muted small"><Spinner /> Opening your portal…</div>
          <p className="small muted">You'll set your own password inside. Your link works until {new Date(info.expires_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} or until you set it.</p>
        </>}
        <div className="tiny faint">Powered by AcknowledgerFirst</div>
      </div>
    </div>
  );
}
