// ops.js — resources (measured, never estimated) and settings (the honest knobs).
import { api } from "../api.js";
import { h, icon, fmtDate, ago, toast } from "../util.js";
import { emptyState, sectionTitle, kvList, linkOut } from "./common.js";

const MB = (kb) => `${(kb / 1024).toFixed(1)} MB`;

export const resources = {
  id: "resources",
  title: "Resources",
  icon: "resources",
  size: [820, 620],
  mount(body, { signal, sub, onClose }) {
    const stage = h("div", { class: "pane-scroll" });
    body.append(stage);
    let alive = true;
    onClose(() => { alive = false; });

    async function render() {
      if (!alive || !body.isConnected) return;
      let r;
      try { r = await api.resources(); } catch (err) { stage.replaceChildren(emptyState("No measurements", err.message)); return; }
      const mem = r.memory || {};
      const fp = r.agencyos || { rss_mb: 0, processes: [] };
      const budget = 300;
      sub(`${fp.rss_mb} MB agencyd · host ${mem.used_pct}% used`);

      const topProcs = [...(fp.processes || [])].sort((a, b) => b.rss_kb - a.rss_kb);
      stage.replaceChildren(
        h("div", { class: "section" },
          h("div", { class: "res-grid" },
            h("div", { class: "res-card" },
              h("div", { class: "label" }, "Agency OS footprint"),
              h("div", { class: "res-big" }, h("span", { text: String(fp.rss_mb) }), h("small", {}, " MB")),
              h("div", { class: "label", style: { marginTop: "6px" } }, `${fp.count} process(es) · ${r.share_of_ram_pct}% of RAM`),
              h("div", { class: "bar", style: { marginTop: "8px" } },
                h("i", { style: { width: `${Math.min(100, (fp.rss_mb / budget) * 100)}%`, background: "var(--signal)" } })),
              h("div", { class: "faint", style: { fontSize: "10px", marginTop: "4px" } },
                `Budget line: ${budget} MB for the whole environment including a browser.`)),
            h("div", { class: "res-card" },
              h("div", { class: "label" }, "Host memory"),
              h("div", { class: "res-big" }, h("span", { text: String(mem.used_pct ?? "—") }), h("small", {}, " %")),
              h("div", { class: "label", style: { marginTop: "6px" } },
                `${MB(mem.used_kb || 0)} used of ${MB(mem.total_kb || 0)}`),
              h("div", { class: "bar", style: { marginTop: "8px" } },
                h("i", { style: { width: `${mem.used_pct || 0}%`, background: (mem.used_pct || 0) > 80 ? "var(--red)" : "var(--blue)" } })),
              h("div", { class: "faint", style: { fontSize: "10px", marginTop: "4px" } },
                `${MB(mem.available_kb || 0)} available · swap ${MB(mem.swap_total_kb || 0)}`)),
            h("div", { class: "res-card" },
              h("div", { class: "label" }, "Machine"),
              h("div", { class: "res-big" }, h("span", { text: String(r.load?.["1m"] ?? "—") }), h("small", {}, " load")),
              h("div", { class: "label", style: { marginTop: "6px" } }, `${r.load?.cpus || "?"} CPUs · 5m ${r.load?.["5m"]}`),
              h("div", { class: "bar", style: { marginTop: "8px" } },
                h("i", { style: { width: `${Math.min(100, ((r.load?.["1m"] || 0) / (r.load?.cpus || 1)) * 100)}%`, background: "var(--green)" } })),
              h("div", { class: "faint", style: { fontSize: "10px", marginTop: "4px" } },
                `disk ${r.disk?.used_pct ?? "?"}% used · uptime ${Math.round((r.uptime_s || 0) / 3600)}h`)),
          ),
          h("div", { class: "faint", style: { fontSize: "10.5px", marginTop: "10px" } },
            "Every number above is read from /proc at request time. Nothing is sampled, interpolated or drawn from a model."),
        ),
        h("div", { class: "section" },
          sectionTitle("Agency OS process tree"),
          h("table", { class: "grid" },
            h("thead", {}, h("tr", {},
              ...["pid", "rss", "state", "command"].map((c) => h("th", { class: c === "rss" ? "num" : "" }, c)))),
            h("tbody", {}, ...topProcs.map((p) => h("tr", {},
              h("td", { class: "mono" }, String(p.pid)),
              h("td", { class: "mono num" }, MB(p.rss_kb)),
              h("td", { class: "mono dim" }, p.state),
              h("td", { class: "mono truncate", style: { maxWidth: "360px" }, text: p.cmd })))))),
        h("div", { class: "section" },
          sectionTitle("What the budget contains"),
          h("div", { class: "dim", style: { fontSize: "11.5px", lineHeight: 1.6 } },
            "The 300 MB target covers this daemon plus an ordinary browser rendering the deck. ",
            "The daemon holds no framework, no database and no build step: one Python process that reads git checkouts and serves static files. ",
            "The browser is measured separately with ", h("code", {}, "agencyos measure --browser"),
            " because its RSS belongs to the browser, not to the agency.")),
      );
    }

    render();
    const t = setInterval(render, 4000);
    onClose(() => clearInterval(t));
    document.addEventListener("agency:change", render, { signal });
  },
};

export const settings = {
  id: "settings",
  title: "Settings",
  icon: "settings",
  size: [760, 620],
  mount(body, { signal, sub }) {
    const stage = h("div", { class: "pane-scroll" });
    body.append(stage);

    async function render() {
      if (!body.isConnected) return;
      let cfg = {}, sources = { sources: [] };
      try { cfg = await api.config(); } catch { /* shown as unknown */ }
      try { sources = await api.sources(); } catch { /* ignore */ }
      sub(`v${cfg.version || "?"}`);

      stage.replaceChildren(
        h("div", { class: "section" },
          sectionTitle("Deck"),
          kvList([
            ["version", `agency-os ${cfg.version || "?"}`],
            ["listen", `${cfg.host}:${cfg.port}`],
            ["operator", cfg.operator],
            ["agent identity", cfg.agent_name || "—"],
            ["data dir", h("span", { class: "mono", text: cfg.data_dir })],
            ["sync interval", `${cfg.sync_interval}s`],
          ]),
          h("div", { class: "row-actions" },
            h("button", { class: "btn", onclick: () => {
              const cur = document.documentElement.dataset.theme === "paper" ? "graphite" : "paper";
              document.documentElement.dataset.theme = cur;
              localStorage.setItem("agencyos.theme", cur);
              toast("Theme", cur, "ok", 1600);
            } }, "Toggle theme"),
            h("button", { class: "btn", onclick: () => {
              window.dispatchEvent(new CustomEvent("agency:reset-layout"));
              toast("Layout reset", "Windows return to their default positions.", "ok", 2400);
            } }, "Reset layout"),
          )),
        h("div", { class: "section" },
          sectionTitle("Write access"),
          h("div", { class: "card", dataset: { ok: String(cfg.actions_enabled) } },
            h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
              icon(cfg.authenticated ? "lock" : "alert", 13),
              h("b", { text: cfg.actions_enabled ? "Authorized" : "Read-only" })),
            h("div", { class: "dim", style: { fontSize: "11.5px", marginTop: "6px" } },
              cfg.actions_enabled
                ? `Actions run through the agency's own CLIs as ${cfg.agent_name}. The token is injected through the environment and scrubbed from output.`
                : "The deck can claim, ballot and post only through the real CLIs, with your token. Without one it stays read-only rather than faking agency."),
            h("div", { style: { marginTop: "8px", display: "grid", gap: "4px" } },
              h("code", { class: "code-block", text: "export GITHUB_PAT=<fine-grained PAT, Contents: read/write>" }),
              h("code", { class: "code-block", text: "agencyos run --allow-actions" }),
              h("div", { class: "faint", style: { fontSize: "10px" } },
                "Token: ", cfg.authenticated ? "present in the daemon environment (never displayed)" : "absent"))),
        ),
        h("div", { class: "section" },
          sectionTitle("Sources"),
          h("table", { class: "grid" },
            h("thead", {}, h("tr", {}, ...["source", "repo", "head", "committed", "state"].map((c) => h("th", {}, c)))),
            h("tbody", {}, ...(sources.sources || []).map((s) => h("tr", {},
              h("td", {}, h("b", { text: s.name })),
              h("td", { class: "mono dim" }, s.repo),
              h("td", { class: "mono" }, s.head || "—"),
              h("td", { class: "mono faint" }, fmtDate(s.head_date, { time: true })),
              h("td", {}, h("span", { class: `chip ${s.present ? "st-done" : "st-blocked"}` }, s.present ? "PRESENT" : "MISSING")))))),
        ),
        h("div", { class: "section" },
          sectionTitle("Keyboard"),
          h("div", { class: "keys" },
            ...([["Ctrl K", "command palette"], ["Alt 1…9", "open a panel"], ["Alt W", "close window"],
              ["Alt M", "minimise"], ["Alt Enter", "maximise"], ["Esc", "close palette"]])
              .map(([k, v]) => h("div", { class: "key-row" }, h("kbd", { text: k }), h("span", { text: v }))))),
        h("div", { class: "section" },
          sectionTitle("Project"),
          h("div", { class: "dim", style: { fontSize: "11.5px" } },
            "Agency OS is a thin environment over the agency's own repositories. ",
            linkOut("https://github.com/dreamer2664/agency-os", "github.com/dreamer2664/agency-os"),
            h("div", { style: { marginTop: "6px" } },
              "Install: ", h("code", {}, "scripts/install.sh"), " · Update: ", h("code", {}, "git pull && scripts/install.sh"),
              " · Uninstall: ", h("code", {}, "scripts/uninstall.sh"))),
        ),
      );
    }

    render();
    document.addEventListener("agency:change", render, { signal });
  },
};
