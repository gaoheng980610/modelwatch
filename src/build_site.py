#!/usr/bin/env python3
"""ModelWatch static site generator.

Reads data/models.json and writes a fully static site into site/. Stdlib only.

Presentation is a small design system (tokens -> components -> pages):
  * light + dark, both selected from one validated palette (see CSS tokens);
  * the data table is fully server-rendered (crawlers see every row) and JS
    only filters/re-sorts what is already in the DOM;
  * charts are single-series horizontal bars with direct value labels, and every
    chart is backed by the equivalent table.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import monitor  # noqa: E402
from config import BASE_PATH, BASE_URL, CNAME  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "models.json"
SITE = ROOT / "site"
HISTORY_DIR = ROOT / "data" / "history"
CHANGE_LOG = ROOT / "data" / "changes" / "log.json"

# The public origin lives in src/config.py, shared with the link checker so the
# two can never disagree about where the site is served from.
_INTERNAL_URL = re.compile(r'((?:href|src)=")/')


def _prefixed(document: str) -> str:
    return _INTERNAL_URL.sub(r"\1" + BASE_PATH + "/", document) if BASE_PATH else document

BUILD_DATE = date.today().isoformat()

PROVIDER_NAMES = {
    "anthropic": "Anthropic", "openai": "OpenAI", "google": "Google", "meta": "Meta",
    "meta-llama": "Meta (Llama)", "mistralai": "Mistral AI", "deepseek": "DeepSeek",
    "x-ai": "xAI", "xai": "xAI", "qwen": "Qwen", "z-ai": "Z.ai", "minimax": "MiniMax",
    "tencent": "Tencent", "moonshotai": "Moonshot AI", "aion-labs": "Aion Labs",
    "nvidia": "NVIDIA", "bytedance-seed": "ByteDance Seed", "bytedance": "ByteDance",
    "cohere": "Cohere", "xiaomi": "Xiaomi", "amazon": "Amazon", "perplexity": "Perplexity",
    "sakana": "Sakana AI", "inclusionai": "InclusionAI", "nousresearch": "Nous Research",
    "upstage": "Upstage", "ibm-granite": "IBM Granite", "thinkingmachines": "Thinking Machines",
    "poolside": "Poolside", "inception": "Inception", "microsoft": "Microsoft",
    "rekaai": "Reka AI", "stepfun": "StepFun", "baidu": "Baidu", "meituan": "Meituan",
    "writer": "Writer", "arcee-ai": "Arcee AI", "fireworks": "Fireworks", "morph": "Morph",
    "mancer": "Mancer", "gryphe": "Gryphe", "undi95": "Undi95", "thedrummer": "TheDrummer",
    "sao10k": "Sao10K", "cognitivecomputations": "Cognitive Computations",
    "anthracite-org": "Anthracite Org", "typesafe": "TypeSafe", "prism-ml": "Prism ML",
    "inference-net": "Inference.net", "relace": "Relace", "perceptron": "Perceptron",
    "unbiased": "Unbiased", "nex-agi": "Nex AGI", "liquid": "Liquid AI", "ai21": "AI21",
}

FAVICON = ("data:image/svg+xml,"
           "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='7' fill='%232a78d6'/%3E"
           "%3Cpath d='M9 22V10l7 8 7-8v12' fill='none' stroke='white' stroke-width='3'"
           " stroke-linejoin='round' stroke-linecap='round'/%3E%3C/svg%3E")


# ---------------------------------------------------------------- helpers

def esc(value) -> str:
    return "" if value is None else html.escape(str(value))


def money(value) -> str:
    return "—" if value is None else f"${value:,.2f}"


def price_cell(pricing: dict, key: str = "input") -> str:
    """A list-table price. Prefixed with "from" when the model charges more above
    a prompt-size threshold — a bare number would understate long-context cost."""
    value = pricing.get(key)
    if value is None:
        return "—"
    return f"from {money(value)}" if pricing.get("tiers") else money(value)


def tokens(value) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if value >= 1_000:
        return f"{value / 1_000:g}K"
    return str(value)


def answer(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def slug(model_id: str) -> str:
    return model_id.replace("/", "--").replace(":", "-")


CAP_LABELS = {
    "thinking": "Thinking", "effort_levels": "Reasoning efforts",
    "modalities_in": "Input modalities", "modalities_out": "Output modalities",
    "vision": "Vision", "tool_use": "Tool use", "structured_outputs": "Structured outputs",
    "streaming": "Streaming", "prompt_caching": "Prompt caching", "batch": "Batch API",
    "web_search": "Web search", "web_fetch": "Web fetch", "code_execution": "Code execution",
    "compaction": "Compaction", "task_budgets": "Task budgets", "fast_mode": "Fast mode",
    "sampling": "Sampling (temperature)", "prefill": "Assistant prefill",
}
CAP_ORDER = ["thinking", "effort_levels", "modalities_in", "modalities_out", "vision", "tool_use",
             "structured_outputs", "streaming", "prompt_caching", "batch", "web_search", "web_fetch",
             "code_execution", "compaction", "task_budgets", "fast_mode", "sampling", "prefill"]


def cap_label(key: str) -> str:
    return CAP_LABELS.get(key, key.replace("_", " ").capitalize())


BENCH_LABELS = {"intelligence_index": "Intelligence index", "coding_index": "Coding index",
                "agentic_index": "Agentic index", "math_index": "Math index",
                "reasoning_index": "Reasoning index"}


def bench_label(key: str) -> str:
    return BENCH_LABELS.get(key, key.replace("_", " ").capitalize())


def ordered_caps(caps: dict) -> list[tuple[str, object]]:
    """Capabilities in a stable, human-meaningful order (known keys first)."""
    known = [k for k in CAP_ORDER if k in caps]
    rest = sorted(k for k in caps if k not in known)
    return [(k, caps[k]) for k in known + rest]


def provider_name(provider: str) -> str:
    return PROVIDER_NAMES.get(provider, provider.replace("-", " ").title())


def provider_link(provider: str) -> str:
    return f'<a href="/providers/{esc(provider)}.html">{esc(provider_name(provider))}</a>'


def model_link(model: dict) -> str:
    return f'<a href="/models/{esc(slug(model["id"]))}.html">{esc(model["display_name"])}</a>'


# ---------------------------------------------------------------- design system

CSS = """\
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --plane:#f9f9f7; --surface:#fcfcfb; --raised:#ffffff;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --series-1:#2a78d6; --link:#1c5cab;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --r:12px; --r-sm:8px;
  --shadow:0 1px 2px rgba(11,11,11,.05), 0 10px 26px -14px rgba(11,11,11,.22);
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --plane:#0d0d0d; --surface:#1a1a19; --raised:#202020;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --series-1:#3987e5; --link:#5598e7;
    --shadow:0 1px 2px rgba(0,0,0,.45), 0 10px 26px -14px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19; --raised:#202020;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --series-1:#3987e5; --link:#5598e7;
  --shadow:0 1px 2px rgba(0,0,0,.45), 0 10px 26px -14px rgba(0,0,0,.7);
}
body{margin:0;background:var(--plane);color:var(--ink);
  font:16px/1.6 var(--sans);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline}
/* A link inside a block of text must not rely on colour alone (WCAG 1.4.1).
   Table/nav links are the whole cell or control, so they stay un-underlined. */
main p a,main li a{text-decoration:underline;text-underline-offset:2px;text-decoration-thickness:1px}
:focus-visible{outline:2px solid var(--series-1);outline-offset:2px;border-radius:4px}
.skip{position:absolute;left:-9999px}
.skip:focus{left:12px;top:12px;z-index:50;background:var(--raised);padding:8px 12px;border-radius:8px}

/* header */
.site-header{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--plane) 82%,transparent);
  backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid var(--border)}
.header-inner{max-width:1180px;margin:0 auto;padding:0 24px;height:60px;display:flex;align-items:center;gap:20px}
.brand{font-weight:660;font-size:16px;letter-spacing:-.015em;color:var(--ink);display:flex;
  align-items:center;gap:8px;white-space:nowrap}
.brand:hover{text-decoration:none}
.brand .dot{width:9px;height:9px;border-radius:50%;background:var(--series-1)}
.brand em{font-style:normal;color:var(--ink-2);font-weight:500}
.nav{display:flex;gap:2px;margin-left:auto}
.nav a{color:var(--ink-2);font-size:14px;padding:7px 11px;border-radius:var(--r-sm);white-space:nowrap}
.nav a:hover{background:var(--surface);color:var(--ink);text-decoration:none}
.nav a[aria-current="page"]{color:var(--ink);background:var(--surface)}
.theme-btn{margin-left:6px;background:var(--surface);border:1px solid var(--border);color:var(--ink-2);
  width:32px;height:32px;border-radius:var(--r-sm);cursor:pointer;font-size:14px;line-height:1;
  display:grid;place-items:center}
.theme-btn:hover{color:var(--ink)}

main{max-width:1180px;margin:0 auto;padding:44px 24px 84px}
h1{font-size:clamp(28px,4vw,40px);line-height:1.12;letter-spacing:-.022em;margin:0 0 14px;font-weight:680}
h2{font-size:20px;letter-spacing:-.012em;margin:36px 0 12px;font-weight:640}
h3{font-size:15px;margin:0 0 8px;font-weight:640}
.lead{color:var(--ink-2);font-size:17px;margin:0 0 10px;max-width:74ch}
.eyebrow{color:var(--ink-2);font-size:12.5px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;margin:0 0 10px}
p{margin:0 0 12px}
code{font-family:var(--mono);font-size:.88em;background:var(--surface);border:1px solid var(--border);
  padding:1.5px 6px;border-radius:6px}
pre{margin:0;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:14px 16px;overflow-x:auto;font-family:var(--mono);font-size:12.5px;line-height:1.6;
  color:var(--ink-2)}
pre code{background:none;border:0;padding:0;font-size:inherit}

/* stat tiles */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:12px;margin:26px 0 8px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:15px 17px}
.k-label{color:var(--ink-2);font-size:12.5px;margin-bottom:5px}
.k-value{font-size:25px;font-weight:660;letter-spacing:-.015em;line-height:1.2}
.k-sub{color:var(--ink-2);font-size:13px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* panels */
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:20px 22px;margin:18px 0}
.panel.tight{padding:6px 0}
.rows{display:grid}
.row{display:flex;justify-content:space-between;gap:20px;padding:11px 22px;border-bottom:1px solid var(--border)}
.rows .row:last-child{border-bottom:0}
.row .k{color:var(--ink-2)}
.row .v{font-weight:550;text-align:right}

/* badges */
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:550;color:var(--ink-2);
  background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:3px 10px;white-space:nowrap}
.badge::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--muted);flex:none}
.badge.ga::before{background:var(--good)}
.badge.preview::before,.badge.beta::before{background:var(--warning)}
.badge.deprecated::before{background:var(--serious)}
.badge.retired::before{background:var(--critical)}
.badges{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 6px}
.badge.mut::before{display:none}

/* tables */
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:var(--r);background:var(--surface)}
table{width:100%;border-collapse:collapse;font-size:14.5px}
thead th{background:var(--surface);color:var(--ink-2);
  font-size:11.5px;letter-spacing:.055em;text-transform:uppercase;font-weight:650;text-align:left;
  padding:12px 16px;border-bottom:1px solid var(--border);white-space:nowrap}
tbody td{padding:11px 16px;border-bottom:1px solid var(--border);vertical-align:middle}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:color-mix(in srgb,var(--series-1) 6%,transparent)}
.num{text-align:right;font-variant-numeric:tabular-nums}
th.num{text-align:right}
td.win{font-weight:660}
td.dim{color:var(--ink-2)}
.muted{color:var(--ink-2)}

/* controls */
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:20px 0 14px}
.controls input,.controls select{appearance:none;background:var(--surface);color:var(--ink);
  border:1px solid var(--border);border-radius:var(--r-sm);padding:9px 12px;font:inherit;font-size:14px}
.controls input{min-width:250px}
.controls select{cursor:pointer}
.controls label.chk{display:inline-flex;align-items:center;gap:7px;color:var(--ink-2);
  font-size:14px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r-sm);padding:9px 12px;cursor:pointer;user-select:none}
.controls label.chk input{min-width:0;width:15px;height:15px;accent-color:var(--series-1)}
#count{color:var(--ink-2);font-size:13px;margin-left:auto;font-variant-numeric:tabular-nums}
.controls select{max-width:280px}
.btn{background:var(--ink);color:var(--plane);border:0;border-radius:var(--r-sm);
  padding:9px 16px;font:inherit;font-size:14px;font-weight:560;cursor:pointer}
.btn:hover{opacity:.88}
.vs{color:var(--ink-2);font-size:13px}

/* chart: single-series horizontal bars, value at the tip */
.chart{display:grid;gap:2px;margin:10px 0 4px}
.bar-row{display:grid;grid-template-columns:minmax(150px,230px) 1fr;gap:16px;align-items:center;
  padding:7px 0;border-bottom:1px solid var(--grid)}
.bar-row:last-child{border-bottom:0}
.bar-label{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-label .sub{color:var(--ink-2);font-size:12px;margin-left:7px}
.bar-track{display:flex;align-items:center;gap:10px;min-width:0}
.bar-fill{height:18px;background:var(--series-1);border-radius:0 4px 4px 0;flex:0 0 auto;min-width:2px}
.bar-fill.none{background:var(--axis)}
.bar-value{font-size:13px;color:var(--ink-2);font-variant-numeric:tabular-nums;white-space:nowrap}

/* chart: single-series column chart (change over time) */
.cchart{margin:14px 0 4px}
.cchart-body{max-width:100%}
.cchart.few .cchart-body{max-width:560px}   /* don't scatter a 4-point series */
.plot{display:flex;align-items:flex-end;gap:2px;height:170px;border-bottom:1px solid var(--axis)}
.col{flex:1;display:flex;align-items:flex-end;justify-content:center;height:100%}
.col i{display:block;width:min(24px,100%);background:var(--series-1);
  border-radius:4px 4px 0 0;min-height:2px}
.col:hover i{opacity:.82}
.col-labels{display:flex;gap:2px;margin-top:6px;font-size:11px;color:var(--ink-2)}
.col-labels span{flex:1;text-align:center;white-space:nowrap}
.cchart figcaption{margin-top:9px;font-size:13px;color:var(--ink-2)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* misc */
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.empty{text-align:center;padding:44px 20px;color:var(--ink-2)}
.src{display:flex;justify-content:space-between;gap:16px;padding:11px 22px;border-bottom:1px solid var(--border);font-size:13.5px}
.rows .src:last-child{border-bottom:0}
.crumbs{color:var(--ink-2);font-size:13px;margin:0 0 14px}

.site-footer{border-top:1px solid var(--border);margin-top:72px;background:var(--surface)}
.footer-inner{max-width:1180px;margin:0 auto;padding:30px 24px;color:var(--ink-2);font-size:13.5px;
  display:flex;flex-wrap:wrap;gap:18px 40px;justify-content:space-between;align-items:flex-start}
.footer-inner a{color:var(--ink-2)}
.footer-links{display:flex;gap:18px;flex-wrap:wrap}

@media (max-width:760px){
  main{padding:26px 16px 60px}
  .header-inner{padding:0 16px;gap:12px}
  .nav{overflow-x:auto;scrollbar-width:none}
  .nav::-webkit-scrollbar{display:none}
  .nav a{padding:7px 8px;font-size:13px;flex:none}
  .brand em{display:none}
  .bar-row{grid-template-columns:1fr;gap:5px}
  .controls #count{margin-left:0;width:100%}
  .hide-sm{display:none}
}
"""

INDEX_SCRIPT = """(function(){
  var q=document.getElementById('q'),prov=document.getElementById('prov'),sort=document.getElementById('sort'),
      maxp=document.getElementById('maxp'),minctx=document.getElementById('minctx'),
      vision=document.getElementById('vision'),
      openw=document.getElementById('openw'),
      tb=document.getElementById('t').tBodies[0],count=document.getElementById('count'),
      rows=Array.prototype.slice.call(tb.rows);
  // honour ?q= so a search from the 404 page lands on a filtered index
  var mq=/[?&]q=([^&]*)/.exec(location.search);
  if(mq){q.value=decodeURIComponent(mq[1].replace(/\\+/g,' '));}
  function num(r,k){var v=r.getAttribute('data-'+k);return (v===''||v===null)?null:parseFloat(v);}
  function apply(){
    var term=q.value.toLowerCase(),p=prov.value,
        mp=maxp.value?parseFloat(maxp.value):null,mc=minctx.value?parseFloat(minctx.value):null,
        vv=vision.checked,ow=openw.checked,n=0;
    rows.forEach(function(r){
      var ok=(!term||r.getAttribute('data-name').indexOf(term)>-1)&&(!p||r.getAttribute('data-provider')===p);
      if(ok&&mp!==null){var i=num(r,'input'); ok=(i!==null&&i<=mp);}
      if(ok&&mc!==null){var c=num(r,'context'); ok=(c!==null&&c>=mc);}
      if(ok&&vv){ok=(r.getAttribute('data-vision')==='yes');}
      if(ok&&ow){ok=(r.getAttribute('data-openweights')==='yes');}
      r.style.display=ok?'':'none'; if(ok)n++;
    });
    var visible=rows.filter(function(r){return r.style.display!=='none';}),mode=sort.value;
    visible.sort(function(a,b){
      if(mode==='name'){return a.getAttribute('data-name')<b.getAttribute('data-name')?-1:1;}
      // the sort key IS the mode: data-input / data-context / data-bench
      var x=num(a,mode),y=num(b,mode);
      if(x===null)return 1; if(y===null)return -1;   // unscored models sort last
      return mode==='input'?x-y:y-x;                 // price ascending, the rest descending
    });
    visible.forEach(function(r){tb.appendChild(r);});
    count.textContent=n?n+' of '+rows.length+' models':'No models match these filters';
  }
  [q,prov,sort,maxp,minctx].forEach(function(el){
    el.addEventListener('change',apply); el.addEventListener('input',apply);
  });
  vision.addEventListener('change',apply);
  openw.addEventListener('change',apply);
  apply();
})();"""

COMPARE_SCRIPT = """(function(){
  var CAPS=__CAPS__,P="__PREFIX__";
  var a=document.getElementById('ca'),b=document.getElementById('cb'),
      go=document.getElementById('cgo'),out=document.getElementById('out'),cache=null;
  function fmt(v){
    if(v===null||v===undefined)return '\\u2014';
    if(typeof v==='boolean')return v?'Yes':'No';
    if(Array.isArray(v))return v.join(', ');
    return String(v);
  }
  function money(v){return v==null?'\\u2014':'$'+Number(v).toFixed(2);}
  function toks(v){
    if(v==null)return '\\u2014';
    if(v>=1e6)return (v/1e6)+'M';
    if(v>=1e3)return Math.round(v/1e3)+'K';
    return String(v);
  }
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function row(label,x,y,opts){
    opts=opts||{};
    var f=opts.fmt||fmt, comparable=opts.num&&typeof x==='number'&&typeof y==='number'&&x!==y;
    var xw=comparable&&(opts.lower?x<y:x>y), yw=comparable&&(opts.lower?y<x:y>x);
    return '<tr><th style="text-align:left;color:var(--ink-2);font-weight:500">'+esc(label)+'</th>'+
      '<td class="num'+(xw?' win':(comparable?' dim':''))+'">'+esc(f(x))+'</td>'+
      '<td class="num'+(yw?' win':(comparable?' dim':''))+'">'+esc(f(y))+'</td></tr>';
  }
  function load(){
    return cache?Promise.resolve(cache):fetch(P+'/api/v1/models.json')
      .then(function(r){return r.json();}).then(function(d){cache=d.models;return cache;});
  }
  function byId(ms,id){for(var i=0;i<ms.length;i++){if(ms[i].id===id)return ms[i];}return null;}
  function run(){
    if(!a.value||!b.value){out.innerHTML='<div class="panel">Pick two models.</div>';return;}
    if(a.value===b.value){out.innerHTML='<div class="panel">Pick two different models.</div>';return;}
    out.innerHTML='<div class="panel">Loading\\u2026</div>';
    load().then(function(ms){
      var ma=byId(ms,a.value), mb=byId(ms,b.value);
      if(!ma||!mb){out.innerHTML='<div class="panel">Could not load those records.</div>';return;}
      var rows=[
        row('Provider', ma.provider, mb.provider),
        row('Context window', ma.context.max_input_tokens, mb.context.max_input_tokens, {num:1,fmt:toks}),
        row('Max output', ma.context.max_output_tokens, mb.context.max_output_tokens, {num:1,fmt:toks}),
        row('Input $/MTok', ma.pricing.input, mb.pricing.input, {num:1,lower:1,fmt:money}),
        row('Output $/MTok', ma.pricing.output, mb.pricing.output, {num:1,lower:1,fmt:money}),
        row('Status', ma.lifecycle.status, mb.lifecycle.status)
      ];
      var keys={},k;
      for(k in (ma.capabilities||{}))keys[k]=1;
      for(k in (mb.capabilities||{}))keys[k]=1;
      Object.keys(keys).sort().forEach(function(key){
        var av=(ma.capabilities||{})[key], bv=(mb.capabilities||{})[key];
        if(JSON.stringify(av)===JSON.stringify(bv))return;
        rows.push(row(CAPS[key]||key, av, bv));
      });
      out.innerHTML='<div class="table-wrap"><table><thead><tr><th></th>'+
        '<th class="num">'+esc(ma.display_name)+'</th><th class="num">'+esc(mb.display_name)+
        '</th></tr></thead><tbody>'+rows.join('')+'</tbody></table></div>'+
        '<p class="lead" style="margin-top:14px">Data as of '+esc(ma.as_of)+' / '+esc(mb.as_of)+
        '. Sources: <a href="/models/'+esc(ma.id)+'.html">'+esc(ma.display_name)+'</a>, '+
        '<a href="/models/'+esc(mb.id)+'.html">'+esc(mb.display_name)+'</a>.</p>';
    }).catch(function(){
      out.innerHTML='<div class="panel">Could not load the dataset.</div>';
    });
  }
  // /compare/?a=<id> (and optionally &b=<id>) link straight into a comparison,
  // which is how every model page offers a way in.
  var qa=/[?&]a=([^&]*)/.exec(location.search), qb=/[?&]b=([^&]*)/.exec(location.search);
  if(qa)a.value=decodeURIComponent(qa[1]);
  if(qb)b.value=decodeURIComponent(qb[1]);
  if(a.value===b.value&&b.options.length>1)b.selectedIndex=1;
  go.addEventListener('click',run);
  if(qa&&qb&&a.value&&b.value)run();
})();"""

THEME_SCRIPT = """(function(){
  var root=document.documentElement,btn=document.getElementById('theme');
  try{var s=localStorage.getItem('mw-theme'); if(s) root.setAttribute('data-theme',s);}catch(e){}
  function current(){return root.getAttribute('data-theme')||
    (window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');}
  function paint(){var t=current();btn.textContent=t==='dark'?'\\u2600':'\\u263E';
    btn.setAttribute('aria-label','Switch to '+(t==='dark'?'light':'dark')+' theme');}
  btn.addEventListener('click',function(){
    var next=current()==='dark'?'light':'dark';
    root.setAttribute('data-theme',next);
    try{localStorage.setItem('mw-theme',next);}catch(e){}
    paint();
  });
  paint();
})();"""


def _meta_description(text: str, limit: int = 155) -> str:
    """Trim to what a search result actually displays (~155 characters).

    Measured: 179 of 751 pages had descriptions longer than that, so the part
    that carried the point was being cut mid-sentence. Trimming on a word
    boundary at least keeps the sentence whole.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.—-") + "…"


def page(title: str, description: str, body: str, path: str, *, noindex: bool = False) -> str:
    description = _meta_description(description)
    canonical = f"{BASE_URL}/{path}"
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    here = path.split("/")[0] or "index"
    section = {"index": "models", "new.html": "new", "providers.html": "providers",
               "pricing.html": "pricing", "leaderboard.html": "leaderboard",
               "trends.html": "trends", "report.html": "report",
               "docs.html": "docs", "404.html": "404", "compare": "compare"}.get(here, "models")
    def nav_item(href: str, label: str, key: str) -> str:
        cur = ' aria-current="page"' if here == key else ""
        return f'<a href="{href}"{cur}>{label}</a>'
    nav = "".join([
        nav_item("/", "Models", "index"),
        nav_item("/new.html", "New", "new.html"),
        nav_item("/providers.html", "Providers", "providers.html"),
        nav_item("/pricing.html", "Pricing", "pricing.html"),
        nav_item("/leaderboard.html", "Leaderboard", "leaderboard.html"),
        nav_item("/trends.html", "Trends", "trends.html"),
        nav_item("/report.html", "Report", "report.html"),
        nav_item("/docs.html", "Docs", "docs.html"),
    ])
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{robots}<link rel="canonical" href="{esc(canonical)}">
<link rel="alternate" type="application/atom+xml" title="ModelWatch — new AI models" href="/feed.xml">
<meta name="theme-color" content="#f9f9f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="/"><span class="dot"></span>ModelWatch<em>&nbsp;/ {esc(section)}</em></a>
    <nav class="nav">{nav}<button id="theme" class="theme-btn" type="button" aria-label="Toggle theme"></button></nav>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="footer-inner">
    <div>
      <strong style="color:var(--ink)">ModelWatch</strong> — an independent, provenance-tracked index of
      AI model capabilities, context windows and pricing.<br>
      Built {esc(BUILD_DATE)}. Every figure carries its source and an <code>as_of</code> date.
    </div>
    <div class="footer-links">
      <a href="/">Models</a><a href="/new.html">New</a><a href="/providers.html">Providers</a>
      <a href="/pricing.html">Pricing</a><a href="/trends.html">Trends</a>
      <a href="/docs.html">Docs</a><a href="/api/v1/models.json">JSON API</a>
      <a href="/feed.xml">Feed</a>
    </div>
  </div>
</footer>
<script>{THEME_SCRIPT}</script>
</body>
</html>
"""
    return _prefixed(document)


# ---------------------------------------------------------------- components

def stat_tiles(items: list[tuple[str, str, str]]) -> str:
    out = ['<div class="kpis">']
    for label, value, sub in items:
        out.append('<div class="kpi">')
        out.append(f'<div class="k-label">{esc(label)}</div>')
        out.append(f'<div class="k-value">{value}</div>')
        if sub:
            out.append(f'<div class="k-sub">{esc(sub)}</div>')
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


def status_badge(status: str) -> str:
    return f'<span class="badge {esc(status)}">{esc(status)}</span>'


def bar_chart(rows: list[tuple[str, float | None, str]], fmt=money) -> str:
    """Single-series horizontal bars with the value at each bar's tip.

    The bar is capped at 86% of the track so the tip label always fits; the cap
    is uniform, so the encoding stays proportional. Rows with no value render as
    a zero-length mark plus an em dash.
    """
    values = [v for _, v, _ in rows if v is not None]
    vmax = max(values) if values else 0
    out = ['<div class="chart">']
    for label, value, sub in rows:
        pct = round(value / vmax * 86, 2) if (value is not None and vmax) else 0
        cls = "bar-fill" if pct else "bar-fill none"
        tip = fmt(value) if value is not None else "—"
        out.append(
            f'<div class="bar-row">'
            f'<div class="bar-label">{label}<span class="sub">{esc(sub)}</span></div>'
            f'<div class="bar-track"><div class="{cls}" style="width:{pct}%"></div>'
            f'<span class="bar-value">{esc(tip)}</span></div>'
            f"</div>"
        )
    out.append("</div>")
    return "".join(out)


def monthly_releases(models: list[dict]) -> list[tuple[str, int]]:
    """Models released per month, as a CONTINUOUS month range (gaps filled with 0).

    Filling the gaps matters: an index that skips empty months would compress time
    and make the release cadence look smoother than it is.
    """
    counts = Counter(m["released"][:7] for m in models if m.get("released"))
    if not counts:
        return []
    lo, hi = min(counts), max(counts)
    year, month = int(lo[:4]), int(lo[5:7])
    out: list[tuple[str, int]] = []
    while f"{year:04d}-{month:02d}" <= hi:
        key = f"{year:04d}-{month:02d}"
        out.append((key, counts.get(key, 0)))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def column_chart(points: list[tuple[str, int]], *, every: int = 6, note: str = "",
                 fmt=None) -> str:
    """Single-series column chart of values over time.

    Single series, so no legend box — the heading names it. Columns are capped at
    24px with a 2px surface gap and a 4px rounded cap on the baseline's opposite
    end. The peak is named in the caption rather than labelled on every column.
    """
    if not points:
        return '<div class="empty">Nothing to chart yet.</div>'
    fmt = fmt or (lambda v: f"{v} model{'' if v == 1 else 's'}")
    vmax = max(v for _, v in points) or 1
    peak = max(range(len(points)), key=lambda i: points[i][1])
    cols = "".join(
        f'<div class="col" title="{esc(lab)} — {esc(fmt(v))}">'
        f'<i style="height:{round(v / vmax * 100, 2)}%"></i></div>'
        for lab, v in points
    )
    labels = "".join(
        f"<span>{esc(lab) if (i % every == 0 or i == len(points) - 1) else ''}</span>"
        for i, (lab, _) in enumerate(points)
    )
    caption = ((note + " ") if note else "") + \
        f"Peak: {fmt(points[peak][1])} in {points[peak][0]}."
    # The chart carries its own table for assistive tech, so nothing is gated
    # behind a hover tooltip.
    table = ("<table class=\"sr-only\"><caption>Chart data</caption>"
             "<thead><tr><th>Period</th><th>Value</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{esc(lab)}</td><td>{esc(fmt(v))}</td></tr>" for lab, v in points)
             + "</tbody></table>")
    return (f'<figure class="cchart{" few" if len(points) <= 8 else ""}">'
            f'<div class="cchart-body">'
            f'<div class="plot" aria-hidden="true">{cols}</div>'
            f'<div class="col-labels" aria-hidden="true">{labels}</div>'
            f"</div>"
            f"<figcaption>{esc(caption)}</figcaption>{table}</figure>")


def median(values: list) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def context_by_year(models: list[dict]) -> list[tuple[str, int]]:
    """Median context window per release year (models that have both a date and a window)."""
    by_year: dict[str, list[int]] = {}
    for m in models:
        window = m["context"].get("max_input_tokens")
        if m.get("released") and window:
            by_year.setdefault(m["released"][:4], []).append(window)
    return [(year, int(median(vals))) for year, vals in sorted(by_year.items())]


def modality_adoption(models: list[dict], modality: str = "image") -> list[tuple[str, int]]:
    """Share of each year's models that accept `modality`, as a percentage."""
    by_year: dict[str, list[dict]] = {}
    for m in models:
        if m.get("released"):
            by_year.setdefault(m["released"][:4], []).append(m)
    out = []
    for year, group in sorted(by_year.items()):
        accepts = sum(1 for m in group
                      if modality in ((m["capabilities"] or {}).get("modalities_in") or []))
        out.append((year, round(100 * accepts / len(group))))
    return out


PRICE_BUCKETS = (("Free", lambda p: p == 0),
                 ("≤ $0.50", lambda p: 0 < p <= 0.5),
                 ("$0.50 – $1", lambda p: 0.5 < p <= 1),
                 ("$1 – $5", lambda p: 1 < p <= 5),
                 ("$5 – $15", lambda p: 5 < p <= 15),
                 ("over $15", lambda p: p > 15))


def price_distribution(models: list[dict]) -> list[tuple[str, int]]:
    priced = [m["pricing"]["input"] for m in models if m["pricing"].get("input") is not None]
    return [(label, sum(1 for p in priced if pred(p))) for label, pred in PRICE_BUCKETS]


def provider_link_cell(m: dict) -> str:
    return provider_link(m["provider"])


# ---------------------------------------------------------------- pages

def build_index(models: list[dict], meta: dict) -> str:
    providers = sorted({m["provider"] for m in models})
    options = "".join(f'<option value="{esc(p)}">{esc(provider_name(p))}</option>' for p in providers)

    priced = [m for m in models if m["pricing"].get("input") is not None]
    cheapest = min(priced, key=lambda m: m["pricing"]["input"]) if priced else None
    with_ctx = [m for m in models if m["context"].get("max_input_tokens")]
    biggest = max(with_ctx, key=lambda m: m["context"]["max_input_tokens"]) if with_ctx else None

    rows = []
    for m in sorted(models, key=lambda x: (x["provider"], x["pricing"].get("input") or 0)):
        c, p = m["context"], m["pricing"]
        vis = "yes" if (m.get("capabilities") or {}).get("vision") else "no"
        ow = "yes" if m.get("hugging_face_id") else "no"
        idx = intelligence_index(m)
        rows.append(
            f'<tr data-name="{esc(m["display_name"].lower())}" data-provider="{esc(m["provider"])}"'
            f' data-status="{esc(m["lifecycle"]["status"])}" data-vision="{vis}" data-openweights="{ow}"'
            f' data-input="{p.get("input") if p.get("input") is not None else ""}"'
            f' data-context="{c.get("max_input_tokens") or ""}"'
            f' data-bench="{idx if idx is not None else ""}">'
            f"<td>{model_link(m)}</td>"
            f'<td class="hide-sm">{provider_link_cell(m)}</td>'
            f"<td>{status_badge(m['lifecycle']['status'])}</td>"
            f'<td class="num">{tokens(c.get("max_input_tokens"))}</td>'
            f'<td class="num">{price_cell(p)}</td>'
            f'<td class="num hide-sm">{price_cell(p, "output")}</td>'
            f'<td class="num hide-sm">{idx if idx is not None else "—"}</td></tr>'
        )

    body = f"""<p class="eyebrow">Model index</p>
<h1>Every AI model, with its price and its source</h1>
<p class="lead">Capabilities, context windows, list pricing and third-party benchmark scores for
{len(models)} models across {len(providers)} providers. No number on this site is estimated — each
carries a source link and the date it was true.</p>
{stat_tiles([
  ("Models", f"{len(models):,}", "tracked"),
  ("Providers", f"{len(providers):,}", "vendors"),
  ("Cheapest input", money(cheapest["pricing"]["input"]) if cheapest else "—",
   f'per MTok · {cheapest["display_name"]}' if cheapest else ""),
  ("Largest context", tokens(biggest["context"]["max_input_tokens"]) if biggest else "—",
   biggest["display_name"] if biggest else ""),
])}
<div class="controls">
  <input id="q" type="search" placeholder="Filter by name…" autocomplete="off" aria-label="Filter models by name">
  <select id="prov" aria-label="Filter by provider"><option value="">All providers</option>{options}</select>
  <select id="maxp" aria-label="Maximum input price">
    <option value="">Any price</option>
    <option value="0.1">Input ≤ $0.10</option>
    <option value="0.5">Input ≤ $0.50</option>
    <option value="1">Input ≤ $1</option>
    <option value="5">Input ≤ $5</option>
    <option value="20">Input ≤ $20</option>
  </select>
  <select id="minctx" aria-label="Minimum context window">
    <option value="">Any context</option>
    <option value="32768">Context ≥ 32K</option>
    <option value="131072">Context ≥ 128K</option>
    <option value="200000">Context ≥ 200K</option>
    <option value="1000000">Context ≥ 1M</option>
  </select>
  <label class="chk"><input type="checkbox" id="vision"> Vision</label>
  <label class="chk"><input type="checkbox" id="openw"> Open weights</label>
  <select id="sort" aria-label="Sort models">
    <option value="name">Sort: name</option>
    <option value="input">Sort: input price (low → high)</option>
    <option value="context">Sort: context window (high → low)</option>
    <option value="bench">Sort: intelligence index (high → low)</option>
  </select>
  <span id="count"></span>
</div>
<div class="table-wrap">
<table id="t">
<thead><tr><th>Model</th><th class="hide-sm">Provider</th><th>Status</th>
<th class="num">Context</th><th class="num">Input /MTok</th><th class="num hide-sm">Output /MTok</th>
<th class="num hide-sm">Intelligence</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
<p class="lead" style="margin-top:16px">Machine-readable: <a href="/api/v1/models.json">/api/v1/models.json</a>
· changes feed: <a href="/api/v1/changes.json">/api/v1/changes.json</a></p>
<script>{INDEX_SCRIPT}</script>"""
    desc = (f"Capabilities, context windows and pricing for {len(models)} AI models across "
            f"{len(providers)} providers, each with a source and an as-of date.")
    return page("ModelWatch — AI model capabilities, context windows & pricing", desc, body, "")


RECENT_DAYS = 90


def recent_models(models: list[dict], days: int = RECENT_DAYS) -> list[dict]:
    """Models released within the last `days`, newest first.

    Only dated models qualify; an undated model is never assumed to be new.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return sorted((m for m in models if m.get("released") and m["released"] >= cutoff),
                  key=lambda m: m["released"], reverse=True)


def build_new(models: list[dict]) -> str:
    recent = recent_models(models)
    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    providers = len({m["provider"] for m in recent})
    priced = [m for m in recent if m["pricing"].get("input") is not None]
    cheapest = min(priced, key=lambda m: m["pricing"]["input"]) if priced else None
    newest = recent[0] if recent else None

    rows = "".join(
        f"<tr><td>{model_link(m)}</td>"
        f'<td class="hide-sm">{provider_link(m["provider"])}</td>'
        f'<td class="num">{esc(m["released"])}</td>'
        f'<td class="num">{tokens(m["context"].get("max_input_tokens"))}</td>'
        f'<td class="num">{price_cell(m["pricing"])}</td>'
        f'<td class="num hide-sm">{price_cell(m["pricing"], "output")}</td></tr>'
        for m in recent
    ) or f'<tr><td colspan="6" class="muted">No dated releases in the last {RECENT_DAYS} days.</td></tr>'

    body = f"""<p class="eyebrow">New</p>
<h1>Models released in the last {RECENT_DAYS} days</h1>
<p class="lead">Newest first. Only models with a release date on file appear here — this is what the
sources state, not an inference.</p>
{stat_tiles([
  ("New models", f"{len(recent):,}", f"since {cutoff}"),
  ("Providers", f"{providers:,}", "represented"),
  ("Newest", esc(newest["released"]) if newest else "—",
   newest["display_name"] if newest else ""),
  ("Cheapest input", money(cheapest["pricing"]["input"]) if cheapest else "—",
   cheapest["display_name"] if cheapest else ""),
])}
<div class="table-wrap">
<table><thead><tr><th>Model</th><th class="hide-sm">Provider</th><th class="num">Released</th>
<th class="num">Context</th><th class="num">Input /MTok</th><th class="num hide-sm">Output /MTok</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>
<p class="lead" style="margin-top:16px">See also the <a href="/trends.html">release cadence over time</a>.</p>"""
    return page(f"New AI models — released in the last {RECENT_DAYS} days | ModelWatch",
                f"{len(recent)} AI models released since {cutoff}, with pricing, context windows and sources.",
                body, "new.html")


def build_providers_index(models: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for m in models:
        groups.setdefault(m["provider"], []).append(m)

    def cheapest_input(group: list[dict]):
        prices = [g["pricing"].get("input") for g in group if g["pricing"].get("input") is not None]
        return min(prices) if prices else None

    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    chart_rows = []
    for provider, group in ranked[:20]:
        chart_rows.append((
            f'<a href="/providers/{esc(provider)}.html">{esc(provider_name(provider))}</a>',
            len(group), "",
        ))
    rows = []
    for provider, group in ranked:
        largest = max((g["context"].get("max_input_tokens") or 0 for g in group), default=0)
        rows.append(
            f"<tr><td><a href='/providers/{esc(provider)}.html'>{esc(provider_name(provider))}</a></td>"
            f"<td class='num'>{len(group)}</td>"
            f"<td class='num'>{money(cheapest_input(group))}</td>"
            f"<td class='num'>{tokens(largest) if largest else '—'}</td></tr>"
        )
    body = f"""<p class="eyebrow">Providers</p>
<h1>{len(groups)} providers</h1>
<p class="lead">Model counts, cheapest input price and largest context window per vendor.</p>
{stat_tiles([
  ("Providers", f"{len(groups):,}", "vendors"),
  ("Models", f"{len(models):,}", "total"),
])}
<h2>Models per provider</h2>
<p class="lead">The twenty largest vendors by number of tracked models.</p>
{bar_chart([(label, float(value), "") for label, value, _ in chart_rows], fmt=lambda v: f"{int(v):,}")}
<h2>All providers</h2>
<div class="table-wrap">
<table><thead><tr><th>Provider</th><th class="num">Models</th>
<th class="num">Cheapest input</th><th class="num">Largest context</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div>"""
    return page("AI model providers — ModelWatch",
                f"All {len(groups)} indexed AI model providers with model counts and price ranges.",
                body, "providers.html")


def build_pricing(models: list[dict]) -> str:
    priced = sorted((m for m in models if m["pricing"].get("input") is not None),
                    key=lambda m: m["pricing"]["input"])
    top = priced[:20]
    chart = bar_chart([
        (model_link(m), float(m["pricing"]["input"]), provider_name(m["provider"]))
        for m in top
    ])
    rows = "".join(
        f"<tr><td>{model_link(m)}</td><td class='hide-sm'>{provider_link_cell(m)}</td>"
        f"<td class='num'>{price_cell(m['pricing'])}</td>"
        f"<td class='num'>{price_cell(m['pricing'], 'output')}</td>"
        f"<td class='num'>{money(m['pricing'].get('cached_input'))}</td></tr>"
        for m in priced
    )
    body = f"""<p class="eyebrow">Pricing</p>
<h1>List price, per million tokens</h1>
<p class="lead">USD per MTok across {len(priced)} models with a published price. Cache prices are shown
where the source states them.</p>
<h2>Cheapest models by input price</h2>
<p class="lead">The twenty lowest input prices in the index.</p>
{chart}
<h2>All prices</h2>
<div class="table-wrap">
<table><thead><tr><th>Model</th><th class="hide-sm">Provider</th>
<th class="num">Input</th><th class="num">Output</th><th class="num">Cached input</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>"""
    return page("AI model pricing comparison — ModelWatch",
                "Side-by-side AI model pricing in USD per million tokens, with sources.", body, "pricing.html")


def build_model_page(m: dict, pairs: list[tuple[dict, dict]] | None = None) -> tuple[str, str]:
    c, p, caps = m["context"], m["pricing"], m.get("capabilities", {})

    tiles = [
        ("Context window", tokens(c.get("max_input_tokens")), "tokens"),
        ("Max output", tokens(c.get("max_output_tokens")), "tokens"),
        ("Input", money(p.get("input")), "per MTok · tiered" if p.get("tiers") else "per MTok"),
        ("Output", money(p.get("output")), "per MTok · tiered" if p.get("tiers") else "per MTok"),
    ]
    if p.get("cached_input") is not None:
        tiles.append(("Cached input", money(p.get("cached_input")), "per MTok"))

    cap_rows = "".join(
        f'<div class="row"><span class="k">{esc(cap_label(k))}</span><span class="v">{esc(answer(v))}</span></div>'
        for k, v in ordered_caps(caps)
    )
    facts = []
    if m.get("released"):
        facts.append(("Released", esc(m["released"])))
    if m.get("knowledge_cutoff"):
        facts.append(("Knowledge cutoff", esc(m["knowledge_cutoff"])))
    if m.get("hugging_face_id"):
        hf = m["hugging_face_id"]
        facts.append(("Open weights",
                      f'<a href="https://huggingface.co/{esc(hf)}" rel="nofollow noopener">{esc(hf)}</a>'))
    facts_html = ""
    if facts:
        fact_rows = "".join(f'<div class="row"><span class="k">{l}</span><span class="v">{v}</span></div>'
                            for l, v in facts)
        facts_html = f'<h2>Model facts</h2><div class="panel tight"><div class="rows">{fact_rows}</div></div>'
    src_rows = "".join(
        f'<div class="src"><span>{esc(e["source_type"])} · {esc(e["retrieved_at"])}</span>'
        f'<a href="{esc(e["source_url"])}" rel="nofollow noopener">{esc(e["source_url"])}</a></div>'
        for e in m["provenance"]
    )
    conflict_html = ""
    if m.get("conflicts"):
        items = "".join(
            f'<div class="row"><span class="k">{esc(cf["field"])}</span>'
            f'<span class="v">{esc(cf["disagreement"])}</span></div>' for cf in m["conflicts"]
        )
        conflict_html = f'<h2>Source disagreements</h2><div class="panel tight"><div class="rows">{items}</div></div>'

    bench = m.get("benchmarks") or {}
    aa = bench.get("artificial_analysis") or {}
    arena = bench.get("design_arena") or []
    bench_html = ""
    if aa or arena:
        blocks = []
        if aa:
            aa_rows = "".join(
                f'<div class="row"><span class="k">{esc(bench_label(k))}</span>'
                f'<span class="v">{v}</span></div>' for k, v in aa.items())
            blocks.append(f'<div class="panel tight"><div class="rows">{aa_rows}</div></div>')
        if arena:
            top = sorted(arena, key=lambda r: (r.get("rank") if r.get("rank") is not None else 10**6))[:8]
            arena_rows = "".join(
                f"<tr><td>{esc(r.get('category'))}</td><td class='num'>{esc(r.get('elo'))}</td>"
                f"<td class='num'>{esc(r.get('rank'))}</td></tr>" for r in top)
            blocks.append('<div class="table-wrap"><table><thead><tr><th>Category</th>'
                          '<th class="num">ELO</th><th class="num">Rank</th></tr></thead>'
                          f"<tbody>{arena_rows}</tbody></table></div>")
        bench_html = ('<h2>Benchmarks</h2><p class="lead">Third-party scores, as published by the '
                      "source — not vendor claims.</p>" + "".join(blocks))

    # Tiered pricing must be stated, not flattened: for these models a single
    # number understates what a long-context call actually costs.
    tiers = p.get("tiers") or []
    tier_html = ""
    if tiers:
        band = (f'<div class="row"><span class="k">up to {tokens(tiers[0]["above_input_tokens"])} tokens</span>'
                f'<span class="v">{money(p.get("input"))} in · {money(p.get("output"))} out</span></div>')
        more = "".join(
            f'<div class="row"><span class="k">above {tokens(t["above_input_tokens"])} tokens</span>'
            f'<span class="v">{money(t.get("input"))} in · {money(t.get("output"))} out</span></div>'
            for t in tiers)
        tier_html = ('<h2>Tiered pricing</h2><p class="lead">This model charges more once the prompt '
                     "passes a size threshold, so one flat price would understate long-context cost.</p>"
                     f'<div class="panel tight"><div class="rows">{band}{more}</div></div>')

    # Every model page gets a linkable way into the comparison picker (works for
    # any pair), plus the pre-built pages where this model happens to appear.
    items = []
    for a, b in (pairs or [])[:8]:
        other = b if a["id"] == m["id"] else a
        items.append(f'<li><a href="/compare/{esc(slug(a["id"]))}-vs-{esc(slug(b["id"]))}.html">'
                     f'vs {esc(other["display_name"])}</a></li>')
    listing = (f'<div class="panel"><ul style="margin:0;columns:2;column-gap:32px">{"".join(items)}</ul></div>'
               if items else "")
    compare_html = (f'<h2>Compare</h2>\n<p class="lead"><a href="/compare/?a={esc(m["id"])}">'
                    f"Compare {esc(m['display_name'])} with any other model →</a></p>\n{listing}")

    ld = {
        "@context": "https://schema.org", "@type": "Product",
        "name": m["display_name"],
        "brand": {"@type": "Brand", "name": provider_name(m["provider"])},
        "offers": {"@type": "Offer", "priceCurrency": p["currency"], "price": p.get("input"),
                   "description": "USD per million input tokens"},
    }

    body = f"""<p class="crumbs"><a href="/">Models</a> › {provider_link(m['provider'])} › {esc(m['display_name'])}</p>
<h1>{esc(m['display_name'])}</h1>
<div class="badges">{status_badge(m['lifecycle']['status'])}
<span class="badge mut">{esc(m['confidence'])}</span>
<span class="badge mut">as of {esc(m['as_of'])}</span></div>
<p class="lead">Model id <code>{esc(m['id'])}</code> · provider {provider_link(m['provider'])}</p>
{f'<div class="panel">{esc(m["lifecycle"]["notice"])}</div>' if m["lifecycle"].get("notice") else ""}
{stat_tiles(tiles)}
{tier_html}
{facts_html}
<h2>Capabilities</h2>
<div class="panel tight"><div class="rows">{cap_rows or '<div class="row"><span class="k">Not recorded</span><span class="v">—</span></div>'}</div></div>
{bench_html}
{compare_html}
{conflict_html}
<h2>Sources</h2>
<div class="panel tight"><div class="rows">{src_rows}</div></div>
<script type="application/ld+json">{json.dumps(ld)}</script>"""
    title = f"{m['display_name']} — pricing, context window & capabilities | ModelWatch"
    desc = (f"{m['display_name']} by {provider_name(m['provider'])}: "
            f"{tokens(c.get('max_input_tokens'))} context, {money(p.get('input'))}/{money(p.get('output'))} per MTok. "
            f"Verified {m['as_of']}.")
    return page(title, desc, body, f"models/{slug(m['id'])}.html"), title


def build_provider_page(provider: str, models: list[dict]) -> str:
    name = provider_name(provider)
    priced = sorted((m for m in models if m["pricing"].get("input") is not None),
                    key=lambda m: m["pricing"]["input"])
    chart = bar_chart([(model_link(m), float(m["pricing"]["input"]), "") for m in priced[:15]])
    rows = "".join(
        f"<tr><td>{model_link(m)}</td>"
        f"<td>{status_badge(m['lifecycle']['status'])}</td>"
        f"<td class='num'>{tokens(m['context'].get('max_input_tokens'))}</td>"
        f"<td class='num'>{money(m['pricing'].get('input'))}</td>"
        f"<td class='num'>{money(m['pricing'].get('output'))}</td></tr>"
        for m in sorted(models, key=lambda m: m["display_name"].lower())
    )
    body = f"""<p class="crumbs"><a href="/">Models</a> › <a href="/providers.html">Providers</a> › {esc(name)}</p>
<h1>{esc(name)}</h1>
<p class="lead">{len(models)} model(s) indexed.</p>
{f'<h2>Input price</h2>' + chart if priced else ''}
<h2>All models</h2>
<div class="table-wrap">
<table><thead><tr><th>Model</th><th>Status</th><th class="num">Context</th>
<th class="num">Input</th><th class="num">Output</th></tr></thead><tbody>{rows}</tbody></table>
</div>"""
    return page(f"{name} models — ModelWatch",
                f"Indexed {name} models with pricing and context windows.", body,
                f"providers/{provider}.html")


def comparison_pairs(models: list[dict]) -> list[tuple[dict, dict]]:
    by_provider: dict[str, list[dict]] = {}
    for m in models:
        by_provider.setdefault(m["provider"], []).append(m)
    pairs: list[tuple[dict, dict]] = []
    for group in by_provider.values():
        group = sorted(group,
                       key=lambda x: (-(x["context"].get("max_input_tokens") or 0), x["id"]))[:6]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pairs.append((a, b))
    return pairs


def comparisons_by_model(models: list[dict]) -> dict[str, list[tuple[dict, dict]]]:
    """model id -> the (a, b) pairs it appears in, so a model page can link onward."""
    out: dict[str, list[tuple[dict, dict]]] = {}
    for a, b in comparison_pairs(models):
        out.setdefault(a["id"], []).append((a, b))
        out.setdefault(b["id"], []).append((a, b))
    return out


def build_compare_index(models: list[dict]) -> str:
    # Inject the capability label map so the browser prints "Code execution",
    # not "code_execution" — the same labels the server-rendered pages use.
    script = (COMPARE_SCRIPT.replace("__CAPS__", json.dumps(CAP_LABELS))
                           .replace("__PREFIX__", BASE_PATH))
    options = "".join(
        f'<option value="{esc(m["id"])}">{esc(m["display_name"])} — {esc(provider_name(m["provider"]))}</option>'
        for m in sorted(models, key=lambda x: x["display_name"].lower()))
    items = "".join(
        f'<li><a href="/compare/{esc(slug(a["id"]))}-vs-{esc(slug(b["id"]))}.html">'
        f'{esc(a["display_name"])} vs {esc(b["display_name"])}</a></li>'
        for a, b in comparison_pairs(models)
    )
    body = f"""<p class="eyebrow">Comparisons</p>
<h1>Compare any two models</h1>
<p class="lead">Pick any pair from the {len(models)} models in the index. The comparison is computed in
your browser from the same public data the rest of the site uses.</p>
<div class="controls">
  <select id="ca" aria-label="First model">{options}</select>
  <span class="vs">vs</span>
  <select id="cb" aria-label="Second model">{options}</select>
  <button id="cgo" class="btn" type="button">Compare</button>
</div>
<div id="out" aria-live="polite"></div>
<h2>{len(comparison_pairs(models))} pre-built comparisons</h2>
<p class="lead">These are static pages — indexable and linkable — covering each vendor's top models by
context window.</p>
<ul>{items}</ul>
<script>{script}</script>"""
    return page("Compare AI models — ModelWatch",
                "Compare any two AI models side by side: pricing, context windows, capabilities.",
                body, "compare/")


def build_compare_page(a: dict, b: dict) -> str:
    rows = []

    def row(label: str, va, vb, direction: int = 0, fmt=answer) -> None:
        """direction: 1 = higher wins, -1 = lower wins, 0 = no winner."""
        sa, sb = fmt(va), fmt(vb)
        ca = cb = "num"
        if direction and isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va != vb:
            if (direction > 0 and va > vb) or (direction < 0 and va < vb):
                ca += " win"; cb += " dim"
            else:
                cb += " win"; ca += " dim"
        rows.append(f"<tr><th style='text-align:left;color:var(--ink-2);font-weight:500'>{esc(label)}</th>"
                    f"<td class='{ca}'>{esc(sa)}</td><td class='{cb}'>{esc(sb)}</td></tr>")

    row("Provider", provider_name(a["provider"]), provider_name(b["provider"]))
    row("Context window", a["context"].get("max_input_tokens"), b["context"].get("max_input_tokens"),
        direction=1, fmt=tokens)
    row("Max output", a["context"].get("max_output_tokens"), b["context"].get("max_output_tokens"),
        direction=1, fmt=tokens)
    row("Input", a["pricing"].get("input"), b["pricing"].get("input"), direction=-1, fmt=money)
    row("Output", a["pricing"].get("output"), b["pricing"].get("output"), direction=-1, fmt=money)
    row("Status", a["lifecycle"].get("status"), b["lifecycle"].get("status"))

    caps_a, caps_b = a.get("capabilities") or {}, b.get("capabilities") or {}
    for key in sorted(set(caps_a) | set(caps_b)):
        if caps_a.get(key) != caps_b.get(key):
            row(cap_label(key), caps_a.get(key), caps_b.get(key))

    verdict = []
    ai, bi = a["pricing"].get("input"), b["pricing"].get("input")
    if ai is not None and bi is not None and ai != bi:
        cheaper = a if ai < bi else b
        verdict.append(f"{cheaper['display_name']} is cheaper on input tokens "
                       f"(${min(ai, bi):g} vs ${max(ai, bi):g} per MTok).")
    ac, bc = a["context"].get("max_input_tokens"), b["context"].get("max_input_tokens")
    if ac and bc and ac != bc:
        bigger = a if ac > bc else b
        verdict.append(f"{bigger['display_name']} has the larger context window "
                       f"({tokens(max(ac, bc))} vs {tokens(min(ac, bc))}).")
    if not verdict:
        verdict.append("The two models match on the fields tracked here.")

    body = f"""<p class="crumbs"><a href="/">Models</a> › <a href="/compare/">Compare</a> › {esc(a['display_name'])} vs {esc(b['display_name'])}</p>
<h1>{esc(a['display_name'])} <span class="muted" style="font-weight:400">vs</span> {esc(b['display_name'])}</h1>
<p class="lead">{esc(' '.join(verdict))}</p>
<div class="table-wrap">
<table><thead><tr><th></th>
<th class="num">{esc(a['display_name'])}</th><th class="num">{esc(b['display_name'])}</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div>
<p class="lead" style="margin-top:16px">Data as of {esc(a.get('as_of'))} / {esc(b.get('as_of'))}.
See <a href="/models/{esc(slug(a['id']))}.html">{esc(a['display_name'])}</a> and
<a href="/models/{esc(slug(b['id']))}.html">{esc(b['display_name'])}</a> for sources.</p>"""
    title = f"{a['display_name']} vs {b['display_name']} — pricing & specs compared | ModelWatch"
    desc = (f"{a['display_name']} vs {b['display_name']}: compare pricing, context window and capabilities. "
            + " ".join(verdict))
    return page(title, desc, body, f"compare/{slug(a['id'])}-vs-{slug(b['id'])}.html")


def build_changes(history_dir: Path) -> dict:
    snaps = sorted(history_dir.glob("*.json")) if history_dir.exists() else []
    if len(snaps) < 2:
        return {"meta": {"snapshots": len(snaps), "latest": snaps[-1].stem if snaps else None,
                         "count": 0, "since": snaps[0].stem if snaps else None}, "changes": []}
    prev = json.loads(snaps[-2].read_text(encoding="utf-8"))
    curr = json.loads(snaps[-1].read_text(encoding="utf-8"))
    changes = monitor.diff(prev, curr)
    return {"meta": {"from": snaps[-2].stem, "to": snaps[-1].stem,
                     "snapshots": len(snaps), "count": len(changes),
                     "since": snaps[0].stem}, "changes": changes}


def build_trends(history_dir: Path, models: list[dict]) -> str:
    feed = build_changes(history_dir)
    log = build_history_api()
    # A change can name a model that has since been removed, so only link to a
    # model page that actually exists - otherwise render the id as plain text.
    known = {slug(m["id"]) for m in models}
    n = feed["meta"]["snapshots"]
    providers = len({m["provider"] for m in models})
    dated = sum(1 for m in models if m.get("released"))

    points = monthly_releases(models)
    last_month = points[-1][0] if points else ""
    note = (f"{last_month} is a partial month (data through {BUILD_DATE})."
            if last_month == BUILD_DATE[:7] else "")
    chart = column_chart(points, every=6, note=note)

    if n < 2:
        changes_html = f"""<div class="panel"><div class="empty">
  <p style="margin:0 0 6px;color:var(--ink)">Change history begins {esc(feed['meta']['since'] or '—')}</p>
  <p style="margin:0">The first snapshot is stored; the feed fills in from the second collection run
  onward. Each run adds one dated snapshot to the record.</p>
</div></div>"""
    else:
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td class='num'>{}</td><td class='num'>{}</td></tr>".format(
                (f"<a href='/models/{esc(slug(c['model']))}.html'>{esc(c['model'])}</a>"
                 if slug(c["model"]) in known else esc(c["model"])),
                esc(c["type"]), esc(c.get("from")), esc(c.get("to")))
            for c in feed["changes"]
        ) or '<tr><td colspan="4" class="muted">No changes between the two most recent snapshots.</td></tr>'
        changes_html = f"""<p class="lead">{feed['meta']['count']} change(s) between snapshots
{esc(feed['meta']['from'])} and {esc(feed['meta']['to'])}.</p>
<div class="table-wrap">
<table><thead><tr><th>Model</th><th>Change</th><th class="num">From</th><th class="num">To</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>"""

    body = f"""<p class="eyebrow">Trends</p>
<h1>Releases &amp; changes</h1>
<p class="lead">Two clock-based views of the index: when models appear, and what moves after they do.
The change feed accrues one dated snapshot per collection run — it is the part a competitor cannot
copy retroactively.</p>
{stat_tiles([
  ("Models", f"{len(models):,}", "tracked"),
  ("With a release date", f"{dated:,}", f"of {len(models):,}"),
  ("Providers", f"{providers:,}", "vendors"),
  ("Snapshots", str(n), "collected"),
  ("Changes logged", f"{log['meta'].get('total_changes', 0):,}",
   f"across {log['meta'].get('entries', 0)} diff(s)"),
])}
<h2>Models released per month</h2>
<p class="lead">Every dated model in the index, by release month, across all {providers} providers.</p>
{chart}
<h2>Price, limit &amp; lifecycle changes</h2>
{changes_html}
<p class="lead" style="margin-top:16px">Machine-readable:
<a href="/api/v1/changes.json">/api/v1/changes.json</a> (latest diff) ·
<a href="/api/v1/history.json">/api/v1/history.json</a> (full log)</p>"""
    return page("Model releases & changes — ModelWatch",
                "When AI models are released, and how their price, limits and lifecycle change over time.",
                body, "trends.html")


API_EXAMPLE = """curl -s https://modelwatch.example/api/v1/models.json   | jq '.models[] | select(.id=="claude-opus-5")'
curl -s https://modelwatch.example/api/v1/changes.json  | jq '.changes'"""

RECORD_EXAMPLE = """{
  "id": "claude-opus-5",
  "provider": "anthropic",
  "display_name": "Claude Opus 5",
  "lifecycle": { "status": "ga", "retired_at": null, "notice": "Excluded from Priority Tier." },
  "context": { "max_input_tokens": 1000000, "max_output_tokens": 128000 },
  "pricing": { "currency": "USD", "unit": "per_mtok",
               "input": 5.0, "output": 25.0, "cached_input": null },
  "capabilities": { "vision": true, "tool_use": true, "thinking": "adaptive",
                    "modalities_in": ["text", "image", "file"] },
  "as_of": "2026-10-08",
  "confidence": "verified",
  "benchmarks": { "artificial_analysis": { "intelligence_index": 50.8, "coding_index": 78 } },
  "provenance": [
    { "source_url": "https://docs.anthropic.com/en/docs/about-claude/models/overview",
      "source_type": "vendor_docs", "retrieved_at": "2026-06-24", "note": "..." }
  ]
}"""


def build_docs(models: list[dict], meta: dict) -> str:
    body = f"""<p class="eyebrow">Docs</p>
<h1>Using the data</h1>
<p class="lead">Everything on this site comes from one JSON API. Every figure carries its source and
the date it was true — the point of the dataset is that you can check it.</p>

<h2>Endpoints</h2>
<div class="panel tight"><div class="rows">
  <div class="row"><span class="k"><a href="/api/v1/models.json">/api/v1/models.json</a></span>
    <span class="v">every model record ({len(models)})</span></div>
  <div class="row"><span class="k"><a href="/api/v1/changes.json">/api/v1/changes.json</a></span>
    <span class="v">change feed between the two latest snapshots</span></div>
  <div class="row"><span class="k"><a href="/api/v1/history.json">/api/v1/history.json</a></span>
    <span class="v">the full append-only change log</span></div>
</div></div>
<pre><code>{esc(API_EXAMPLE)}</code></pre>

<h2>Record shape</h2>
<pre><code>{esc(RECORD_EXAMPLE)}</code></pre>

<h2>Confidence — read this before trusting a number</h2>
<div class="table-wrap"><table>
<thead><tr><th>Level</th><th>What it means</th></tr></thead><tbody>
<tr><td><code>verified</code></td><td>Transcribed from the vendor's own documentation or API.</td></tr>
<tr><td><code>partly_verified</code></td><td>Machine-read from a live source, but not every field was stated — the missing ones stay <code>null</code>.</td></tr>
<tr><td><code>unverified</code></td><td>From a third-party source that has not been cross-checked.</td></tr>
<tr><td><code>estimated</code></td><td>Derived rather than stated. Nothing in the current dataset uses this.</td></tr>
</tbody></table></div>

<h2>Provenance</h2>
<p class="lead">Every record carries the sources that produced it. <code>benchmarks</code> is always
third-party data and is kept under its own key — it is never presented as something the vendor
stated, and never merged into a first-party field.</p>
<div class="table-wrap"><table>
<thead><tr><th><code>source_type</code></th><th>Meaning</th></tr></thead><tbody>
<tr><td><code>vendor_docs</code></td><td>the provider's documentation</td></tr>
<tr><td><code>vendor_api</code></td><td>the provider's own API (e.g. its model list endpoint)</td></tr>
<tr><td><code>vendor_pricing_page</code></td><td>the provider's published price list</td></tr>
<tr><td><code>third_party</code></td><td>an aggregator; never treated as authoritative</td></tr>
<tr><td><code>manual</code></td><td>hand-curated by a maintainer</td></tr>
</tbody></table></div>

<h2>How records are merged</h2>
<p class="lead">Sources disagree. These rules decide what you get, and they are enforced in code and
covered by tests:</p>
<div class="panel"><ol style="margin:0;padding-left:20px">
<li>A <code>null</code> never erases a known fact — an unknown value can fill a gap, never blank it.</li>
<li>A third-party source can never overwrite a first-party <code>verified</code> figure.</li>
<li>A price object comes from <em>exactly one</em> source; prices are never mixed across sources.</li>
<li>When sources disagree on a price, ours is kept and the disagreement is recorded in
    <code>conflicts[]</code> rather than silently resolved.</li>
<li><code>as_of</code> is the most recent date any fact in the record was confirmed.</li>
</ol></div>

<h2>License &amp; citation</h2>
<div class="panel tight"><div class="rows">
  <div class="row"><span class="k">Data</span><span class="v">CC BY 4.0 — use it, credit it</span></div>
  <div class="row"><span class="k">Code</span><span class="v">MIT</span></div>
</div></div>
<p class="lead">Cite as: <code>ModelWatch, AI model capabilities &amp; pricing index, retrieved
{esc(BUILD_DATE)}</code>.</p>"""
    return page("Docs — using the ModelWatch data API",
                "How to use the ModelWatch JSON API: endpoints, record shape, the confidence model, "
                "and the rules used to merge conflicting sources.", body, "docs.html")


def build_history_api() -> dict:
    """The append-only change log - every diff ever recorded, not just the latest."""
    if CHANGE_LOG.exists():
        return json.loads(CHANGE_LOG.read_text(encoding="utf-8"))
    return {"meta": {"entries": 0, "total_changes": 0}, "entries": []}


def first_party_share(models: list[dict]) -> tuple[int, int]:
    """(#records backed by first-party vendor documentation, total records).

    Counts RECORDS, not provenance entries: after a merge, almost every record
    carries a third-party entry alongside a vendor one, so "has a third-party
    source" is true of ~everything and says nothing. The question worth asking is
    which records a vendor's own documentation backs.
    """
    fp = sum(1 for m in models if any(
        p["source_type"].startswith("vendor_") or p["source_type"] == "manual"
        for p in m["provenance"]))
    return fp, len(models)


def price_by_year(models: list[dict]) -> list[tuple[str, float]]:
    by_year: dict[str, list[float]] = {}
    for m in models:
        price = m["pricing"].get("input")
        if m.get("released") and price is not None:
            by_year.setdefault(m["released"][:4], []).append(price)
    return [(year, median(vals)) for year, vals in sorted(by_year.items())]


def build_report(models: list[dict], meta: dict) -> str:
    ctx = context_by_year(models)
    adopt = modality_adoption(models)
    dist = price_distribution(models)
    py = price_by_year(models)
    priced = [m["pricing"]["input"] for m in models if m["pricing"].get("input") is not None]
    med_price = median(priced)
    providers = len({m["provider"] for m in models})
    year_counts = Counter(m["released"][:4] for m in models if m.get("released"))
    first_year, first_n = sorted(year_counts.items())[0]
    first_party, total_records = first_party_share(models)
    third_party = total_records - first_party
    growth = (ctx[-1][1] / ctx[0][1]) if len(ctx) >= 2 and ctx[0][1] else None
    growth_txt = f"{growth:.0f}×" if growth else "—"

    price_rows = "".join(
        f'<tr><td>{esc(y)}</td><td class="num">{money(v)}</td></tr>' for y, v in py)

    body = f"""<p class="eyebrow">Report</p>
<h1>What the model market looks like</h1>
<p class="lead">Computed from the {len(models)} models in this index — each with a source and an
<code>as_of</code> date. Every figure below is derived from that dataset; the aggregation lives in
<code>src/build_site.py</code> and the raw data is at
<a href="/api/v1/models.json">/api/v1/models.json</a>, so you can check the arithmetic.</p>
{stat_tiles([
  ("Models", f"{len(models):,}", "in the index"),
  ("Providers", f"{providers:,}", "vendors"),
  ("Median input price", money(med_price), "per MTok"),
  ("Context growth", growth_txt, f"{ctx[0][0]} → {ctx[-1][0]}" if ctx else ""),
])}

<h2>1. Context windows grew {growth_txt} in three years</h2>
<p class="lead">Median context window by release year: {tokens(ctx[0][1])} to {tokens(ctx[-1][1])}.
The maximum in the index is {tokens(max((m["context"].get("max_input_tokens") or 0) for m in models))}.</p>
{column_chart(ctx, every=1, fmt=lambda v: f"{tokens(v)} tokens")}

<h2>2. Multimodal stopped being a feature</h2>
<p class="lead">Share of each year's models that accept image input. What was an edge case in 2024 is
close to the default now.</p>
{column_chart(adopt, every=1, fmt=lambda v: f"{v}%")}

<h2>3. Prices did not fall — the floor moved</h2>
<p class="lead">The median input price is <strong>{money(med_price)}</strong> per million tokens, and it
has stayed within a narrow band year over year. What changed is what that price buys: {growth_txt} the
context window, at roughly the same unit cost.</p>
<div class="grid2">
  <div>
    <h3>Input price distribution</h3>
    {bar_chart([(esc(label), float(count), "") for label, count in dist], fmt=lambda v: f"{int(v):,}")}
  </div>
  <div>
    <h3>Median input price by release year</h3>
    <div class="table-wrap"><table><thead><tr><th>Year</th><th class="num">Median $/MTok</th></tr></thead>
    <tbody>{price_rows}</tbody></table></div>
  </div>
</div>

<h2>How to read this</h2>
<div class="panel"><ul style="margin:0;padding-left:20px">
<li><strong>This is a catalogue sample, not the universe.</strong> {first_party} of {total_records}
records are backed by first-party vendor documentation; the other {third_party} come from third-party
aggregation and are labelled <code>partly_verified</code>. Read this as "what the catalogues show",
not "every model that exists".</li>
<li><strong>Early years are thin.</strong> {first_year} has {first_n} models; a median over {first_n}
is noisy. The trend is only meaningful because the later years are large.</li>
<li><strong>Prices are published list prices</strong> in USD per million tokens — not effective or
negotiated cost, and not adjusted for caching or batch discounts.</li>
<li><strong>Every claim here is recomputable.</strong> Fetch <a href="/api/v1/models.json">the JSON</a>
and repeat the arithmetic.</li>
</ul></div>"""
    return page("What the model market looks like — ModelWatch",
                f"Original analysis of {len(models)} AI models: context growth, multimodal adoption "
                f"and price distribution, computed from sourced data.", body, "report.html")


FEED_LIMIT = 50


def build_feed(models: list[dict]) -> str:
    """Atom feed of the most recently released models.

    Discovery, not monitoring: this announces *new* models. The paid Monitor is
    about changes to models you already depend on, which is a different question.
    """
    recent = sorted((m for m in models if m.get("released")),
                    key=lambda m: (m["released"], m["id"]), reverse=True)[:FEED_LIMIT]
    updated = f"{recent[0]['released']}T00:00:00Z" if recent else f"{BUILD_DATE}T00:00:00Z"
    entries = []
    for m in recent:
        url = f"{BASE_URL}/models/{slug(m['id'])}.html"
        bits = [provider_name(m["provider"])]
        if m["context"].get("max_input_tokens"):
            bits.append(f"{tokens(m['context']['max_input_tokens'])} context")
        if m["pricing"].get("input") is not None:
            bits.append(f"{money(m['pricing']['input'])} per MTok input")
        entries.append(
            f"<entry><title>{esc(m['display_name'])} — {esc(provider_name(m['provider']))}</title>"
            f'<link href="{esc(url)}"/><id>{esc(url)}</id>'
            f"<updated>{esc(m['released'])}T00:00:00Z</updated>"
            f"<summary>{esc(m['display_name'])} — {esc(', '.join(bits))}.</summary></entry>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>ModelWatch — new AI models</title>"
        f'<link href="{esc(BASE_URL)}/feed.xml" rel="self"/>'
        f'<link href="{esc(BASE_URL)}/"/>'
        f"<id>{esc(BASE_URL)}/</id>"
        f"<updated>{esc(updated)}</updated>"
        "<author><name>ModelWatch</name></author>"
        + "".join(entries) + "</feed>\n"
    )


def intelligence_index(m: dict):
    return ((m.get("benchmarks") or {}).get("artificial_analysis") or {}).get("intelligence_index")


def build_leaderboard(models: list[dict]) -> str:
    ranked = [m for m in models if isinstance(intelligence_index(m), (int, float))]
    ranked.sort(key=lambda m: intelligence_index(m), reverse=True)

    rows = []
    best = None                      # (model, price per index point)
    for rank, m in enumerate(ranked, start=1):
        idx = intelligence_index(m)
        price = m["pricing"].get("input")
        per_point = (price / idx) if (price is not None and idx) else None
        # A free model wins any price ratio trivially, which makes the headline
        # useless — so the "best value" pick requires a positive price.
        if per_point is not None and per_point > 0 and (best is None or per_point < best[1]):
            best = (m, per_point)
        rows.append(
            f'<tr><td class="num">{rank}</td><td>{model_link(m)}</td>'
            f'<td class="hide-sm">{provider_link(m["provider"])}</td>'
            f'<td class="num">{idx}</td><td class="num">{price_cell(m["pricing"])}</td>'
            f'<td class="num">{f"${per_point:.4f}" if per_point is not None else "—"}</td></tr>')

    body = f"""<p class="eyebrow">Leaderboard</p>
<h1>Ranked by intelligence index</h1>
<p class="lead">{len(ranked)} of {len(models)} models carry an Artificial Analysis intelligence index.
These are third-party scores — we do not run the benchmarks.</p>
{stat_tiles([
  ("Ranked", f"{len(ranked):,}", f"of {len(models):,} models"),
  ("Top score", str(intelligence_index(ranked[0])) if ranked else "—",
   ranked[0]["display_name"] if ranked else ""),
  ("Best value", f"${best[1]:.4f}" if best else "—",
   f"{best[0]['display_name']} per index point" if best else ""),
])}
<p class="lead">The right-hand column is a ratio we compute — input price divided by index point. A
crude measure: it ignores output price, throughput and reliability. It is simply the fastest way to
see what capability costs.</p>
<div class="table-wrap">
<table><thead><tr><th class="num">#</th><th>Model</th><th class="hide-sm">Provider</th>
<th class="num">Intelligence</th><th class="num">Input /MTok</th><th class="num">$ per point</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div>"""
    return page("AI model leaderboard — ranked by intelligence index | ModelWatch",
                f"{len(ranked)} AI models ranked by Artificial Analysis intelligence index, with the "
                "input price per index point computed from the dataset.",
                body, "leaderboard.html")


def build_404(models: list[dict]) -> str:
    """A stale link is a real case here: models get retired and their pages
    disappear. Make the miss useful instead of a dead end — and let the search
    box hand off to the index's own filter via ?q=."""
    body = f"""<p class="eyebrow">404</p>
<h1>That page isn't here</h1>
<p class="lead">The link may be stale — or the model may have been retired and dropped out of the
index. Either way, searching is faster than going back.</p>
<form class="controls" action="/" method="get" role="search">
  <input id="q" name="q" type="search" placeholder="Search models by name…"
         aria-label="Search models by name">
  <button class="btn" type="submit">Search</button>
</form>
<h2>Common destinations</h2>
<div class="grid2">
  <div class="panel"><h3><a href="/">Model index</a></h3>
    <p class="lead" style="margin:0">{len(models)} models, with a source and an as-of date on every figure.</p></div>
  <div class="panel"><h3><a href="/new.html">New models</a></h3>
    <p class="lead" style="margin:0">Everything released in the last 90 days.</p></div>
  <div class="panel"><h3><a href="/leaderboard.html">Leaderboard</a></h3>
    <p class="lead" style="margin:0">Ranked by benchmark score, with price per index point.</p></div>
  <div class="panel"><h3><a href="/docs.html">Docs</a></h3>
    <p class="lead" style="margin:0">The JSON API, the record shape, and the confidence model.</p></div>
</div>"""
    return page("Page not found — ModelWatch",
                "That page isn't here. Search the model index instead.",
                body, "404.html", noindex=True)


def build_api(models: list[dict], meta: dict) -> str:
    payload = {
        "meta": {"dataset": "modelwatch", "schema_version": meta.get("schema_version"),
                 "as_of": meta.get("as_of"), "generated_at": meta.get("generated_at"),
                 "collected_at": meta.get("collected_at"), "license": "CC-BY-4.0",
                 "count": len(models)},
        "models": models,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_sitemap(models: list[dict], extra: list[str] | None = None) -> str:
    urls = ["", "new.html", "pricing.html", "leaderboard.html", "providers.html", "trends.html",
            "report.html", "docs.html", "compare/"]
    urls += [f"models/{slug(m['id'])}.html" for m in models]
    urls += [f"providers/{p}.html" for p in sorted({m["provider"] for m in models})]
    urls += extra or []
    items = "".join(
        f"<url><loc>{esc(BASE_URL)}/{esc(u)}</loc><lastmod>{esc(BUILD_DATE)}</lastmod></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{items}</urlset>\n")


# ---------------------------------------------------------------- driver

def main() -> None:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    models, meta = data["models"], data["meta"]

    if SITE.exists():
        try:
            shutil.rmtree(SITE)
        except PermissionError:
            print("warn: could not clear site/ (in use); overwriting in place")
    for sub in ("models", "providers", "compare", "api/v1", "assets"):
        (SITE / sub).mkdir(parents=True, exist_ok=True)

    def write(rel: str, text: str) -> None:
        (SITE / rel).write_text(text, encoding="utf-8")

    write("assets/style.css", CSS)
    write("index.html", build_index(models, meta))
    write("new.html", build_new(models))
    write("providers.html", build_providers_index(models))
    write("pricing.html", build_pricing(models))
    write("compare/index.html", build_compare_index(models))
    write("api/v1/models.json", build_api(models, meta))
    write("api/v1/changes.json", json.dumps(build_changes(HISTORY_DIR), indent=2, ensure_ascii=False))
    write("api/v1/history.json", json.dumps(build_history_api(), indent=2, ensure_ascii=False))
    write("trends.html", build_trends(HISTORY_DIR, models))
    write("docs.html", build_docs(models, meta))
    write("report.html", build_report(models, meta))
    write("leaderboard.html", build_leaderboard(models))
    write("404.html", build_404(models))
    write("feed.xml", build_feed(models))

    compare_urls = []
    for a, b in comparison_pairs(models):
        name = f"compare/{slug(a['id'])}-vs-{slug(b['id'])}.html"
        write(name, build_compare_page(a, b))
        compare_urls.append(name)

    write("sitemap.xml", build_sitemap(models, compare_urls))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")
    if CNAME:
        # GitHub Pages reads this from the published root to bind the domain.
        write("CNAME", CNAME + "\n")
    # Cache/security headers for hosts that read a `_headers` file
    # (Cloudflare Pages, Netlify). The performance trace flagged both missing
    # caching and uncompressed documents on a plain file server.
    write("_headers", (
        "/assets/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n"
        "\n"
        "/api/v1/*\n"
        "  Cache-Control: public, max-age=3600\n"
        "\n"
        "/*\n"
        "  Cache-Control: public, max-age=300\n"
        "  X-Content-Type-Options: nosniff\n"
        "  Referrer-Policy: strict-origin-when-cross-origin\n"
    ))

    pairs_by_model = comparisons_by_model(models)
    for m in models:
        write(f"models/{slug(m['id'])}.html",
              build_model_page(m, pairs_by_model.get(m["id"]))[0])

    by_provider: dict[str, list[dict]] = {}
    for m in models:
        by_provider.setdefault(m["provider"], []).append(m)
    for provider, group in by_provider.items():
        write(f"providers/{provider}.html", build_provider_page(provider, group))

    pages = len(list(SITE.rglob("*.html")))
    print(f"Built {pages} page(s), 2 API payloads, sitemap for {len(models)} model(s) -> {SITE}")


if __name__ == "__main__":
    main()
