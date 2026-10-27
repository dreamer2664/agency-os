// comms.js — the bus. Append-only, signed, public by convention.
import { api, action } from "../api.js";
import { h, icon, fmtDate, ago, VirtualList, toast, esc } from "../util.js";
import { emptyState, sectionTitle } from "./common.js";

const TYPES = ["", "say", "status", "claim", "task", "done", "handoff", "review", "vote", "alert", "join"];

export const comms = {
  id: "comms",
  title: "Communications",
  icon: "comms",
  size: [1040, 640],
  mount(body, { signal, sub }) {
    let channel = "general";
    let type = "";
    let channels = [];
    let config = { actions_enabled: false, agent_name: "" };
    let before = null;

    function channelRow(c) {
      const kind = c.kind === "dm" ? "DM" : c.kind === "human" ? "HUM" : "";
      return h("div", {
        class: "chan-row",
        dataset: { active: String(c.name === channel) },
        onclick: () => { channel = c.name; before = null; renderChannel(); },
      },
        h("span", { class: `chan-kind ${c.kind}` }),
        h("div", { style: { minWidth: 0, flex: 1 } },
          h("div", { class: "chan-name truncate", text: c.name }),
          h("div", { class: "chan-meta" }, `${c.messages} lines · ${ago(c.last_ts)}`)),
        h("span", { class: "mono faint", style: { fontSize: "9.5px" }, text: kind }),
      );
    }

    const chList = new VirtualList({ rowHeight: 42, className: "chan-list", row: channelRow });

    const search = h("input", { class: "input", placeholder: "Search the bus…", style: { width: "180px" },
      oninput: (e) => { q = e.target.value; renderChannel(); } });
    let q = "";
    const stream = h("div", { class: "msg-stream" });
    const headTitle = h("div", { class: "chan-head-title" });
    const typeSeg = h("div", { class: "seg" });
    const composer = h("div", { class: "composer" });

    const left = h("div", { class: "col", style: { background: "var(--bg-2)" } },
      h("div", { class: "pane-head" }, h("span", { class: "label" }, "Channels"),
        h("span", { class: "count", id: "chan-count" })),
      chList.el);
    const right = h("div", { class: "col" },
      h("div", { class: "pane-head" }, headTitle, h("span", { style: { flex: 1 } }), search, typeSeg),
      stream, composer);
    body.append(h("div", { class: "split comms-split" }, left, right));
    chList.el.style.height = "100%";

    function renderTypes() {
      typeSeg.replaceChildren(...TYPES.map((t) => h("button", {
        "aria-pressed": String(type === t), onclick: () => { type = t; renderTypes(); renderChannel(); },
      }, t || "all")));
    }

    async function loadChannels() {
      try {
        const data = await api.channels();
        channels = data.channels;
        chList.setRows(channels);
        document.getElementById("chan-count").textContent = String(channels.length);
      } catch (err) {
        chList.setRows([]);
      }
    }

    async function renderChannel() {
      if (!body.isConnected) return;
      const ch = channels.find((c) => c.name === channel);
      headTitle.replaceChildren(
        h("span", { class: "label" }, ch?.kind === "dm" ? "Direct channel" : ch?.kind === "human" ? "Human channel" : "Channel"),
        h("span", { class: "chan-head-name", text: `#${channel}` }),
        ch ? h("span", { class: "mono faint", style: { fontSize: "10px" } }, `${ch.messages} lines · last ${ago(ch.last_ts)}`) : null,
      );
      try {
        const params = { channel, limit: 150 };
        if (type) params.type = type;
        if (q) params.q = q;
        if (before) params.before = before;
        const data = await api.messages(params);
        sub(`#${channel} · ${data.messages.length} shown`);
        const rows = data.messages.slice().reverse();
        stream.replaceChildren(
          rows.length ? h("div", { class: "msg-loadmore" },
            before ? h("button", { class: "btn ghost", onclick: () => { before = null; renderChannel(); } }, "Back to newest")
              : h("button", { class: "btn ghost", onclick: () => {
                if (data.messages.length) before = data.messages[0].ts;
                renderChannel();
              } }, "Load older")) : null,
          ...rows.map(msgRow),
        );
        if (!rows.length) {
          stream.replaceChildren(emptyState("The bus is silent",
            q ? "No message matches that search." : "Silence is not a report. Nothing has been posted in this channel."));
        }
      } catch (err) {
        stream.replaceChildren(emptyState("Cannot read the bus", err.message));
      }
    }

    function msgRow(m) {
      const text = (m.text || "");
      const clipped = text.length > 900 ? text.slice(0, 900) + "…" : text;
      return h("div", { class: "msg" },
        h("div", { class: "msg-time", text: (m.ts || "").slice(11, 16), title: fmtDate(m.ts, { time: true }) }),
        h("div", {},
          h("div", { class: "msg-head" },
            h("span", { class: "msg-author", text: m.from || "?" }),
            h("span", { class: "msg-type", dataset: { t: m.type || "say" }, text: m.type || "say" }),
            m.to && m.to !== "*" ? h("span", { class: "tag", text: `→ ${m.to}` }) : null,
            m.ref ? h("span", { class: "msg-ref", onclick: () => document.dispatchEvent(new CustomEvent("agency:open-task", { detail: m.ref })) }, m.ref) : null,
          ),
          h("div", { class: "msg-text", text: clipped }),
        ));
    }

    function renderComposer() {
      const ok = config.actions_enabled;
      composer.replaceChildren(...[
        h("div", { class: "composer-row" },
          h("span", { class: "label" }, "Post as"),
          h("span", { class: "tag sig", text: config.agent_name || "unassigned" }),
          h("span", { style: { flex: 1 } }),
          h("span", { class: "composer-note", html: ok
            ? "Signed with your token, appended to <code>bus/" + esc(channel) + ".jsonl</code> through the chatcode CLI."
            : "Read-only: the deck will not pretend to speak for an agent." }),
        ),
        h("div", { class: "composer-row" },
          h("textarea", { class: "input", id: "composer-text", rows: 2, placeholder: ok ? "Message the room…" : "Posting requires a token and --allow-actions", disabled: !ok }),
          h("div", { style: { display: "grid", gap: "6px" } },
            h("select", { class: "input", id: "composer-type", disabled: !ok },
              ...["say", "status", "note", "claim", "alert"].map((t) => h("option", { value: t }, t))),
            h("button", { class: "btn primary", disabled: !ok, onclick: send }, icon("comms", 12), "Send"),
          ),
        ),
        ok ? null : h("div", { class: "composer-note" },
          "To enable: ", h("code", {}, "export GITHUB_PAT=…"), " then ",
          h("code", {}, "agencyos run --allow-actions"), ". The token is read from the environment and never stored."),
      ].filter(Boolean));
    }

    async function send() {
      const ta = document.getElementById("composer-text");
      const sel = document.getElementById("composer-type");
      const text = (ta.value || "").trim();
      if (!text) return;
      try {
        await action("say", { channel, text, type: sel.value });
        ta.value = "";
        toast("Posted to the bus", `#${channel} · ${sel.value}`, "ok", 3200);
        setTimeout(() => { before = null; renderChannel(); }, 1500);
      } catch (err) {
        toast("Post refused", err.message, "error", 7000);
      }
    }

    (async () => {
      try { config = await api.config(); } catch { /* keep read-only defaults */ }
      renderTypes();
      renderComposer();
      await loadChannels();
      if (channels.length && !channels.find((c) => c.name === channel)) channel = channels[0].name;
      renderChannel();
    })();

    document.addEventListener("agency:change", () => { if (body.isConnected) loadChannels(); }, { signal });
  },
};
