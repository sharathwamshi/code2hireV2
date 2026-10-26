import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { AgentNote, Hira } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Empty, Loading, useAsync } from "../../components/ui";

const KIND = { approval: ["Approve", "warn"], interview: ["Interview", "isha"], review: ["Review", "brand"], paused: ["Paused", "bad"],
  shortlist: ["Shortlist", "info"], decision: ["Decide", "gold"], credits: ["Credits", "bad"], platform: ["Platform", "dark"] };

export default function Today() {
  const { me } = useAuth();
  const nav = useNavigate();
  const { data, loading } = useAsync(() => api.get("/inbox/today"), []);
  const hour = new Date().getHours();
  const hi = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const cards = data?.cards || [];
  const groups = {};
  cards.forEach((c) => (groups[c.kind] ||= []).push(c));
  return (
    <>
      <PageHead title={`${hi}, ${me.user.name.split(" ")[0]}`} sub="Everything that needs you today, across all your roles, in one list."
        actions={<><Btn onClick={() => nav("/app/jobs/new")} kind="primary">New job with Hira</Btn><Btn onClick={() => nav("/app/jobs")}>All jobs</Btn></>} />
      <AgentNote agent="hira" title={cards.length ? `${cards.length} things need you` : "You're all caught up"}>
        {cards.length ? "Most urgent first. Paused candidates and approvals are at the top because someone is waiting." : "Nothing is waiting on you. Create a job or check reports when they come in."}
      </AgentNote>
      {loading && <Loading />}
      {!loading && !cards.length && <Empty title="Inbox zero" mascot={<Hira size={90} mood="happy" />} text="New applicants, reviews, interviews and approvals will appear here." />}
      <div className="grid g2">
        {Object.entries(groups).map(([k, list]) => (
          <div className="card" key={k}>
            <div className="card-h"><Chip kind={KIND[k]?.[1]}>{KIND[k]?.[0] || k}</Chip><b>{list.length}</b></div>
            {list.slice(0, 8).map((c, i) => (
              <div key={i} className="list-row">
                <div className="grow"><div className="b">{c.title}</div><div className="small muted">{c.body}</div></div>
                <Btn size="sm" kind={c.priority === 1 ? "primary" : ""} onClick={() => nav(c.link)}>{c.action}</Btn>
              </div>
            ))}
            {list.length > 8 && <div className="list-row small muted">+{list.length - 8} more</div>}
          </div>
        ))}
      </div>
    </>
  );
}
