"""Generate a local interactive snapshot from persisted requirement/evidence records."""
import json
from pathlib import Path

import yaml

from .core import atomic_plan


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def render_view(flow_dir, output):
    flow_dir, output = Path(flow_dir), Path(output)
    requirement_file = flow_dir / "requirements.yaml"
    tree = yaml.safe_load(requirement_file.read_text(encoding="utf-8")) if requirement_file.exists() else None
    payload = {
        "requirements": tree,
        "plan": atomic_plan(tree) if tree else [],
        "readiness": read_json(flow_dir / "readiness.json", {"approved": False}),
        "traceability": read_json(flow_dir / "traceability.json", {}).get("requirements", {}),
        "baseline": yaml.safe_load((flow_dir / "import-baseline.yaml").read_text(encoding="utf-8"))
        if (flow_dir / "import-baseline.yaml").exists() else None,
        "goals": yaml.safe_load((flow_dir / "goals.yaml").read_text(encoding="utf-8"))
        if (flow_dir / "goals.yaml").exists() else None,
        "gaps": read_json(flow_dir / "gaps.json", None),
        "analysis": yaml.safe_load((flow_dir / "analysis.yaml").read_text(encoding="utf-8"))
        if (flow_dir / "analysis.yaml").exists() else None,
        "tdd": {path.stem: yaml.safe_load(path.read_text(encoding='utf-8')).get('tdd', {})
                for path in sorted((flow_dir / 'reqs').glob('*.yaml'))},
        "rerun": read_json(flow_dir / "rerun.json", {}),
        "scheduler": read_json(flow_dir / 'scheduler.json', None),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    document = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>REQFlow · 需求与证据</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#172439;font:15px/1.6 system-ui,sans-serif;overflow-wrap:anywhere}
header{background:#172439;color:white;padding:26px 5vw}h1{font-size:25px;margin:0}header p{color:#c6d3e4;margin:6px 0}
main{max-width:1280px;margin:24px auto;padding:0 24px}.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;align-items:start}
section{background:white;border:1px solid #dce2eb;border-radius:12px;padding:22px;margin-bottom:20px;min-width:0}
h2{font-size:18px;margin:0 0 16px}input{padding:10px;border:1px solid #bdcadd;border-radius:6px;width:100%;margin-bottom:14px}
summary{cursor:pointer;padding:9px;border-radius:5px;background:#f0f4fa}details{margin:8px 0 8px 14px}button{border:0;color:#145cad;background:transparent;cursor:pointer;text-align:left}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:12px;font:12px/1.6 ui-monospace,monospace;max-height:420px;overflow:auto}
.tag{font-size:12px;background:#e4ebf5;border-radius:5px;padding:3px 7px;margin-left:8px}.hint{color:#5d6c80}.blocked{color:#b23f24}
@media(max-width:800px){.grid{grid-template-columns:1fr}main{padding:0 12px}}
</style><header><h1>REQFlow / 需求与证据</h1><p>持久化记录快照 · 重新运行 view 更新 · 点击需求查看依赖、场景和验收证据</p></header>
<main><section><h2>执行就绪状态</h2><div id="ready"></div></section>
<section><h2>执行依赖图</h2><div id="dag" style="overflow:auto;max-width:100%"></div></section>
<div class="grid"><section><h2>需求树</h2><input id="filter" aria-label="筛选需求" placeholder="输入 REQ ID 或名称"><div id="tree"></div></section>
<section><h2 id="selected">需求详情</h2><div id="detail" class="hint">请选择需求节点。</div></section></div>
<section><h2>目标与澄清</h2><pre id="goals"></pre></section>
<section><h2>增量差异与待决问题</h2><pre id="gaps"></pre></section>
<section><h2>项目基线与历史失败</h2><pre id="baseline"></pre></section></main>
<script id="data" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
const pretty=x=>JSON.stringify(x,null,2);
document.getElementById('ready').textContent=data.readiness.approved?
`已批准 · ${data.readiness.goal_id||'目标'} · 版本 ${data.readiness.goal_version||1} · 无待决问题`:
`尚未批准 · ${(data.readiness.unresolved||[]).join('；')||'请完成澄清、差异确认和发布'}`;
document.getElementById('ready').className=data.readiness.approved?'':'blocked';
document.getElementById('goals').textContent=pretty(data.goals||{status:'尚未建立目标'});
document.getElementById('gaps').textContent=pretty(data.gaps||{status:'尚未比较候选需求'});
document.getElementById('baseline').textContent=pretty(data.baseline||{status:'未导入既有项目'});
function select(node){document.getElementById('selected').textContent=node.id+' · '+node.name;
const detail=document.getElementById('detail');detail.replaceChildren();
const evidence=data.traceability[node.id]||null;
const pre=document.createElement('pre');pre.textContent=pretty({requirement:node,evidence});detail.append(pre);
for(const filename of [...(evidence?.tests||[]),...(evidence?.code||[]),...(evidence?.logs||[])]){
let path=filename.split(String.fromCharCode(92)).join('/');
if(navigator.platform.toLowerCase().includes('win'))path=path.replace(/^\/mnt\/([a-z])\//,(_,drive)=>drive.toUpperCase()+':/');
else path=path.replace(/^([A-Za-z]):\//,(_,drive)=>'/mnt/'+drive.toLowerCase()+'/');
if(!path.startsWith('/')&&!/^[A-Za-z]:\//.test(path))continue;
const link=document.createElement('a');link.href='file:///'+path.replace(/^\//,'');link.textContent=filename;
link.style.display='block';link.style.overflowWrap='anywhere';detail.append(link);}}
function build(node,parent,filter){if(!node)return false;const childContainer=document.createElement('div');
let childMatch=false;for(const child of node.children||[])childMatch=build(child,childContainer,filter)||childMatch;
if(filter&&!childMatch&&!((node.id+' '+node.name).toLowerCase().includes(filter)))return false;
const details=document.createElement('details');details.open=true;const summary=document.createElement('summary');
const btn=document.createElement('button');btn.textContent=node.id+' · '+node.name;btn.onclick=e=>{e.preventDefault();select(node)};
summary.append(btn);const badge=document.createElement('span');badge.className='tag';
badge.textContent=(data.traceability[node.id]||{}).status||node.type;summary.append(badge);details.append(summary,childContainer);parent.append(details);return true;}
function draw(){const target=document.getElementById('tree');target.replaceChildren();if(!data.requirements){target.textContent='暂无正式需求。未完成澄清的目标不会生成正式需求。';return;}build(data.requirements,target,document.getElementById('filter').value.toLowerCase());}
document.getElementById('filter').addEventListener('input',draw);draw();
const ns='http://www.w3.org/2000/svg',positions={},depths={};
for(const [index,node] of data.plan.entries()){depths[node.id]=Math.max(0,...node.dependencies.map(id=>(depths[id]||0)+1));positions[node.id]={x:20+220*depths[node.id],y:20+index*60};}
const svg=document.createElementNS(ns,'svg');svg.setAttribute('width',Math.max(400,...Object.values(positions).map(p=>p.x+200)));svg.setAttribute('height',Math.max(50,data.plan.length*60+20));
svg.setAttribute('aria-label','需求执行依赖图');svg.setAttribute('role','img');
for(const node of data.plan){const p=positions[node.id];for(const id of node.dependencies){const dep=positions[id];if(!dep)continue;const edge=document.createElementNS(ns,'path');edge.setAttribute('d',`M ${dep.x+180} ${dep.y+18} L ${p.x} ${p.y+18}`);edge.setAttribute('stroke','#7b94b5');edge.setAttribute('fill','none');svg.append(edge);}}
for(const node of data.plan){const p=positions[node.id],g=document.createElementNS(ns,'g'),box=document.createElementNS(ns,'rect'),label=document.createElementNS(ns,'text');
box.setAttribute('x',p.x);box.setAttribute('y',p.y);box.setAttribute('width',180);box.setAttribute('height',36);box.setAttribute('rx',6);box.setAttribute('fill','#e4ebf5');
label.setAttribute('x',p.x+10);label.setAttribute('y',p.y+24);label.textContent=node.id;g.append(box,label);g.style.cursor='pointer';g.onclick=()=>select(node);svg.append(g);}
document.getElementById('dag').append(svg);
</script></html>'''.replace("PAYLOAD", data)
    output.parent.mkdir(parents=True, exist_ok=True)
    from .canvas import enhance
    document = enhance(document)
    output.write_text(document, encoding="utf-8")
    return output


def render_markdown(tree):
    lines = ["# 需求树", ""]

    def walk(node, depth=0):
        lines.append(f"{'  ' * depth}- **{node['id']}** {node['name']} ({node['type']})")
        for child in node.get("children", []):
            walk(child, depth + 1)

    walk(tree)
    lines.extend(["", "## 需求详情", ""])

    def describe(node):
        lines.extend([f"### {node['id']} · {node['name']}", "", node.get("description", ""), "",
                      "依赖：" + ", ".join(node.get("dependencies", [])), ""])
        for scenario in node.get("scenarios", []):
            lines.append("- " + scenario["name"])
            for step in scenario["steps"]:
                lines.append(f"  - {step['keyword']}: {step['content']}")
        for child in node.get("children", []):
            describe(child)

    describe(tree)
    return "\n".join(lines) + "\n"
