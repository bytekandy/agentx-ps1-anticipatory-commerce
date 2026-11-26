// Optional dev tool: end-to-end check of the page in jsdom against a running server.
// Run: cd frontend/test && npm install && APP_URL=http://127.0.0.1:8765/ node e2e.cjs
const { JSDOM } = require("jsdom");
const EventSource = require("eventsource").EventSource || require("eventsource");
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function load() {
  const dom = await JSDOM.fromURL((process.env.APP_URL || "http://127.0.0.1:8765/"), {runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(w) { w.EventSource = EventSource; w.fetch = (u, o) => fetch(new URL(u, w.location.href), o); }});
  await sleep(900); return dom.window;
}
const type = (w, text) => { const t = w.document.getElementById("text"); t.value = text; t.dispatchEvent(new w.Event("input")); };
let failed = 0; const check = (name, ok, detail = "") => { console.log((ok ? "PASS " : "FAIL ") + name + (ok ? "" : "  " + detail)); if (!ok) failed++; };
(async () => {
  let w = await load(), $ = id => w.document.getElementById(id);
  check("page loads, slots drawn", $("slots").children.length === 5);
  check("dev examples listed", $("example").querySelectorAll("option").length > 10, String($("example").querySelectorAll("option").length));
  // live typing: words go out on each space; the commit shows before the last words
  let text = "";
  for (const word of "beige Loomsy sneakers size 10 under 3000 please do hurry".split(" ")) { text += word + " "; type(w, text); await sleep(120); }
  check("one chip per sent word", $("chips").children.length === 10, String($("chips").children.length));
  check("reading shows the slots", $("slot-brand").textContent.includes("Loomsy") && $("slot-size").textContent.includes("10") && $("slot-max_price").textContent.includes("3,000"), $("slots").textContent);
  check("commit card appears before Finish", $("commit").textContent.includes("Loomsy Street Sneakers") && $("commit").textContent.includes("committed after word 8"), $("commit").textContent);
  check("a commit chip is marked", w.document.querySelectorAll(".chip.commit").length === 1);
  $("act").click(); await sleep(500);
  const newQuery = () => { $("text").disabled = true; $("act").click(); };
  check("final answer shown", $("final").textContent.includes("same as the early commit"), $("final").textContent);
  check("input locked after finish", $("text").disabled === true);
  // editing a sent word is refused
  newQuery(); type(w, "black cap "); await sleep(150); type(w, "red cap "); 
  check("a sent word cannot be changed", $("text").value === "black cap " && /already sent/.test($("status").textContent), $("text").value + " | " + $("status").textContent);
  // unresolved constraint is flagged and nothing commits
  newQuery(); type(w, "navy Nike hoodies size M "); await sleep(300);
  check("unknown brand flagged", /not understood: brand: nike/.test($("flags").textContent), $("flags").textContent);
  check("no commit for it", $("commit").classList.contains("empty"));
  // a dev request with a correction, replayed
  w = await load(); $ = id => w.document.getElementById(id);
  const sel = $("example"); const opt = [...sel.querySelectorAll("optgroup[label='with a correction'] option")][0];
  sel.value = opt.value; sel.dispatchEvent(new w.Event("change")); $("delay").value = 0; $("act").click(); await sleep(1800);
  check("replay reaches the end", $("final").textContent.length > 20 && !$("final").classList.contains("empty"), $("final").textContent);
  check("replay is scored", /Right answer/.test($("evaluation").textContent), $("evaluation").textContent);
  check("replay filled the text box", $("text").value.length > 10);
  // results tab
  w.HTMLDialogElement.prototype.showModal = w.HTMLDialogElement.prototype.showModal || function () { this.setAttribute("open", ""); };   // jsdom lacks it
  $("resultsbtn").click(); await sleep(1200);
  check("results table with the baseline", /our agent/.test($("results").textContent) && /43\.5/.test($("results").textContent), $("results").textContent.slice(0, 160));
  console.log(failed ? `${failed} FAILED` : "ALL PASSED"); process.exit(failed ? 1 : 0);
})().catch(e => { console.log("ERROR", e); process.exit(2); });
