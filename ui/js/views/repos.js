// repos.js — the estate: local mirrors (the truth) and GitHub (the public face).
import { api } from "../api.js";
import { h, icon, fmtDate, ago, VirtualList, toast } from "../util.js";
import { emptyState, sectionTitle, linkOut } from "./common.js";

export const repos = {
  id: "repos",
  title: "Repositories",
  icon: "repos",
  size: [1000, 660],
  mount(body, { signal, sub }) {
    const stage = h("div", { class: "pane-scroll" });
    body.append(stage);

    async function render() {
      if (!body.isConnected) return;
      let sources = { sources: [], sync: [] };
      let gh = null;
      try { sources = await api.sources(); } catch (err) { /* shown below */ }
      try { gh = await api.github(); } catch (err) { gh = { error: err.message }; }

      stage.replaceChildren(
        mirrorsBlock(sources),
        githubBlock(gh),
      );
    }

    function mirrorsBlock(data) {
      const dirty = data.sources.filter((s) => s.dirty);
      sub(`${data.sources.length} mirrors · ${data.sources.filter((s) => s.present).length} present`);
      return h("div", { class: "section" },
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } },
          sectionTitle("Local mirrors"),
          h("span", { style: { flex: 1 } }),
          h("button", { class: "btn", onclick: syncNow }, icon("sync", 12), "Sync mirrors")),
        h("div", { class: "source-grid" }, ...data.sources.map((s) =>
          h("div", { class: "source-card", dataset: { ok: String(s.present) } },
            h("div", { class: "source-name" }, icon("repos", 12), s.name,
              s.dirty ? h("span", { class: "tag", style: { color: "var(--signal)" } }, "DIRTY") : null),
            h("div", { class: "mono faint", style: { fontSize: "9.5px" } }, s.repo),
            h("div", { class: "source-meta" },
              h("span", { class: "mono" }, s.head || "no head"),
              h("span", { class: "faint", text: s.head_date ? ago(s.head_date) + " ago" : "—" })),
            h("div", { class: "source-path mono", text: s.path, title: s.path }),
            s.present ? null : h("div", { class: "acc-warn" }, "mirror missing — run `agencyos sync`"))),
        ),
        dirty.length ? h("div", { class: "acc-warn", style: { marginTop: "8px" } },
          `${dirty.length} mirror(s) have uncommitted changes; sync leaves them untouched rather than discarding work.`) : null,
        data.sync?.length ? h("div", { class: "sync-report" },
          ...data.sync.map((r) => h("div", { class: "sync-row" },
            h("span", { class: "tag", text: r.name }),
            h("span", { class: r.ok ? "dim" : "sig", text: r.action }),
            h("span", { class: "faint truncate", text: r.detail })))) : null,
      );
    }

    function githubBlock(gh) {
      if (!gh || gh.error) {
        return h("div", { class: "section" },
          sectionTitle("GitHub"),
          emptyState("GitHub is unreachable", gh?.error || "no response"));
      }
      const reposRows = gh.repos || [];
      const list = new VirtualList({
        rowHeight: 40, className: "repo-list",
        row: (r) => h("div", { class: "repo-row" },
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("div", { class: "repo-name" }, r.name, r.archived ? h("span", { class: "tag", style: { marginLeft: "6px" } }, "ARCHIVED") : null),
            h("div", { class: "faint truncate", style: { fontSize: "10.5px" }, text: r.description || "—" })),
          h("div", { style: { width: "86px" } }, r.language ? h("span", { class: "tag", text: r.language }) : h("span", { class: "faint" }, "—")),
          h("div", { class: "mono faint", style: { width: "74px", fontSize: "10px", textAlign: "right" } }, `${r.size_kb} KB`),
          h("div", { class: "mono faint", style: { width: "76px", fontSize: "10px", textAlign: "right" } }, ago(r.pushed_at))),
        empty: "No public repositories returned.",
      });
      list.setRows(reposRows);

      const coreTabs = h("div", { class: "seg" });
      const coreBody = h("div", { class: "core-body" });
      const slugs = Object.keys(gh.commits || {});
      let active = slugs[0];
      const paint = () => {
        coreTabs.replaceChildren(...slugs.map((slug) => h("button", {
          "aria-pressed": String(slug === active), onclick: () => { active = slug; paint(); },
        }, slug.split("/")[1])));
        const commits = gh.commits[active] || { rows: [] };
        const pulls = gh.pulls[active] || { rows: [] };
        const commitList = h("div", {},
          h("div", { class: "label", style: { marginBottom: "6px" } }, "Recent commits"),
          ...(commits.rows || []).map((c) => h("a", { class: "commit", href: c.url, target: "_blank", rel: "noopener" },
            h("span", { class: "mono", style: { color: "var(--signal)", fontSize: "10px" } }, c.sha),
            h("span", { class: "truncate", style: { flex: 1 }, text: c.message }),
            h("span", { class: "mono faint", style: { fontSize: "9.5px" } }, ago(c.date)))),
          (commits.rows || []).length
            ? null
            : h("div", { class: "dim" }, commits.meta?.error || "No commits returned."));
        const pullList = h("div", {},
          h("div", { class: "label", style: { marginBottom: "6px" } },
            `Open pull requests · ${(pulls.rows || []).length}`),
          ...(pulls.rows || []).map((p) => h("a", { class: "commit", href: p.url, target: "_blank", rel: "noopener" },
            h("span", { class: "mono", style: { fontSize: "10px" } }, `#${p.number}`),
            h("span", { class: "truncate", style: { flex: 1 }, text: p.title }),
            h("span", { class: "mono faint", style: { fontSize: "9.5px" } }, ago(p.updated_at)))),
          (pulls.rows || []).length
            ? null
            : h("div", { class: "dim", style: { fontSize: "11px" } },
                pulls.meta?.error || "No open pull requests."));
        const stale = commits.meta?.stale || pulls.meta?.stale;
        coreBody.replaceChildren(...[
          h("div", { class: "core-cols" }, commitList, pullList),
          stale ? h("div", { class: "acc-warn", style: { marginTop: "8px" } },
            "Showing a cached copy — the GitHub API did not answer.") : null,
        ].filter(Boolean));
      };
      paint();

      const rate = gh.rate || {};
      return h("div", { class: "section" },
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } },
          sectionTitle("GitHub estate"),
          h("span", { class: "tag", text: gh.authenticated ? "TOKEN" : "ANONYMOUS" }),
          h("span", { class: "mono faint", style: { fontSize: "9.5px" } },
            rate.limit ? `${rate.remaining}/${rate.limit} calls left` : ""),
          h("span", { style: { flex: 1 } }),
          h("button", { class: "btn ghost", onclick: async () => { await api.github(true); render(); toast("GitHub refreshed", "Cache cleared", "ok", 2200); } },
            icon("sync", 12), "Refresh")),
        gh.meta?.stale ? h("div", { class: "acc-warn", style: { marginBottom: "8px" } },
          `Cached data: ${gh.meta.error || "the API did not answer"}`) : null,
        h("div", { class: "core-tabs" }, coreTabs),
        coreBody,
        h("div", { style: { marginTop: "14px" } },
          sectionTitle("All public repositories", h("span", { class: "label" }, `${reposRows.length}`))),
        list.el,
        h("div", { class: "faint", style: { fontSize: "10px", marginTop: "6px" } },
          "Anonymous GitHub allows 60 requests per hour; results are cached on disk and every panel says when it is stale. ",
          "A token raises that to 5,000 and unlocks private repositories."),
      );
    }

    async function syncNow() {
      const btnLabel = "Syncing…";
      toast("Sync started", "git fetch --ff-only on every mirror", "", 2200);
      try {
        const res = await fetch("/api/sync", { method: "POST", headers: { "X-AgencyOS": "1" } });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        toast("Mirrors synced", (data.report || []).map((r) => `${r.name}:${r.action}`).join(" · "), "ok", 4200);
      } catch (err) {
        toast("Sync failed", err.message, "error", 7000);
      }
      render();
    }

    render();
    document.addEventListener("agency:change", () => { if (body.isConnected) render(); }, { signal });
  },
};
