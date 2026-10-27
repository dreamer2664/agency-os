// review.js — the engine of the agency: two inspected, non-owner accept votes close a card.
import { api } from "../api.js";
import { h, icon, fmtAge, ago, fmtDate, toast } from "../util.js";
import { emptyState, openTask, sectionTitle, statusChip } from "./common.js";

export const review = {
  id: "review",
  title: "Review queue",
  icon: "review",
  size: [980, 640],
  mount(body, { signal, sub }) {
    const stats = h("div", { class: "review-stats" });
    const list = h("div", { class: "review-list" });
    body.append(stats, h("div", { class: "pane-scroll" }, list));

    async function refresh() {
      if (!body.isConnected) return;
      try {
        const { queue } = await api.review();
        const ready = queue.filter((r) => r.quorum).length;
        const oldest = queue.reduce((m, r) => Math.max(m, r.age_min || 0), 0);
        sub(`${queue.length} awaiting ballots · ${ready} at quorum`);
        stats.replaceChildren(
          stat(queue.length, "in review"),
          stat(ready, "at quorum"),
          stat(queue.reduce((n, r) => n + r.need, 0), "ballots still needed"),
          stat(fmtAge(oldest), "oldest card"),
        );
        if (!queue.length) {
          list.replaceChildren(emptyState("The review queue is empty",
            "Nothing is waiting for ballots. When an operative hands work over, it lands here."));
          return;
        }
        list.replaceChildren(
          h("div", { class: "review-note" }, icon("eye", 12),
            " Ordering follows SYSTEM.md: least-reviewed first, so nothing rots at the bottom of the pile."),
          ...queue.map((r) => card(r)),
        );
      } catch (err) {
        list.replaceChildren(emptyState("Queue unavailable", err.message));
      }
    }

    function stat(v, k) {
      return h("div", { class: "hero-stat" }, h("div", { class: "v", text: String(v) }), h("div", { class: "k", text: k }));
    }

    function card(r) {
      const pips = [];
      for (let i = 0; i < Math.max(2, r.accepts); i++) {
        pips.push(h("span", {
          class: "pip",
          dataset: { on: String(i < r.accepts), deny: String(i < r.denies) },
        }));
      }
      return h("div", { class: "review-card", dataset: { ready: String(r.quorum) } },
        h("div", { class: "rc-main" },
          h("div", { class: "rc-line" },
            statusChip("review"),
            h("span", { class: "mono", style: { fontSize: "10px", color: "var(--ink-4)" } }, r.id),
            h("span", { class: "rc-title truncate", text: r.title }),
          ),
          h("div", { class: "rc-meta" },
            h("span", {}, "owner ", h("b", { text: r.owner || "—" })),
            h("span", {}, "open ", h("b", { text: fmtAge(r.age_min) })),
            r.pr ? h("a", { href: r.pr, target: "_blank", rel: "noopener", class: "ext" }, `PR #${String(r.pr).split("/").pop()}`) : h("span", { class: "faint" }, "no PR recorded"),
            h("span", {}, "ballots ", h("b", { text: `${r.accepts} accept / ${r.denies} deny` })),
            h("span", { class: "dim" }, r.reviewers.length ? `by ${r.reviewers.join(", ")}` : "nobody has inspected it yet"),
          ),
        ),
        h("div", { class: "rc-side" },
          h("div", { class: "rc-pips", title: "two inspected, non-owner accept votes close the card" }, ...pips),
          h("div", { class: "rc-need", text: r.quorum ? "QUORUM MET" : `needs ${r.need}` }),
          h("div", { class: "rc-actions" },
            h("button", { class: "btn ghost", onclick: () => openTask(r.id) }, "Inspect"),
            h("button", {
              class: "btn ghost",
              onclick: async () => {
                const cmd = `python3 bin/chatcode vote ${r.id} accept --reason "<what you ran and saw>" --inspected`;
                try {
                  await navigator.clipboard.writeText(cmd);
                  toast("Ballot command copied", "Run it from a chatcode checkout with your token.", "ok", 4200);
                } catch { toast("Copy failed", cmd, "error", 6000); }
              },
            }, icon("copy", 11), "Ballot"),
          ),
        ),
      );
    }

    refresh();
    document.addEventListener("agency:change", refresh, { signal });
  },
};
